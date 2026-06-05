"""
Background scheduler jobs using APScheduler.
- Every 5 min: fetch prices for watched coins + check price alerts
- Every 30 min: check RSI extreme alerts
- Daily 7 AM: morning brief (Phase 3 — after AI integration)
"""
import logging
from apscheduler.schedulers.asyncio import AsyncIOScheduler

logger = logging.getLogger(__name__)

_scheduler: AsyncIOScheduler | None = None


def get_scheduler() -> AsyncIOScheduler:
    global _scheduler
    if _scheduler is None:
        _scheduler = AsyncIOScheduler(timezone="Asia/Ho_Chi_Minh")
    return _scheduler


async def job_check_price_alerts(bot_data: dict) -> None:
    """
    Every 5 minutes:
    1. Fetch prices for all watched symbols
    2. Check against active price alerts
    3. Send Telegram notification if triggered
    """
    from src.data.database import AsyncSessionLocal
    from src.data.repositories.watchlist_repo import WatchlistRepository
    from src.data.repositories.user_repo import UserRepository
    from src.core.alert_service import AlertService

    binance = bot_data.get("binance")
    bot = bot_data.get("bot_instance")
    if not binance or not bot:
        return

    try:
        async with AsyncSessionLocal() as db:
            watchlist_repo = WatchlistRepository(db)
            symbols = await watchlist_repo.get_all_watched_symbols()

            if not symbols:
                return

            for symbol in symbols:
                try:
                    ticker = await binance.get_ticker(symbol.replace("USDT", ""))
                    current_price = ticker["price"]

                    alert_svc = AlertService(db)
                    triggered = await alert_svc.check_price_alerts(symbol, current_price)

                    for alert in triggered:
                        # Get user telegram_id
                        user_repo = UserRepository(db)
                        user = await user_repo.get(alert.user_id)
                        if not user:
                            continue

                        change_emoji = "📈" if alert.alert_type == "price_above" else "📉"
                        msg = (
                            f"🔔 *Alert Triggered!*\n"
                            f"{change_emoji} *{symbol}* reached `${current_price:,.2f}`\n"
                            f"Your target: `${float(alert.threshold):,.2f}`"
                        )
                        await bot.send_message(
                            chat_id=user.telegram_id,
                            text=msg,
                            parse_mode="Markdown",
                        )
                        logger.info("Alert triggered: %s %s", symbol, alert.alert_type)

                    await db.commit()

                except Exception as e:
                    logger.warning("Alert check failed for %s: %s", symbol, e)

    except Exception as e:
        logger.error("job_check_price_alerts error: %s", e)


async def job_check_rsi_alerts(bot_data: dict) -> None:
    """
    Every 30 minutes:
    Check RSI extremes for all watched symbols.
    """
    from src.data.database import AsyncSessionLocal
    from src.data.repositories.watchlist_repo import WatchlistRepository
    from src.data.repositories.user_repo import UserRepository
    from src.core.ta_service import TAService

    binance = bot_data.get("binance")
    bot = bot_data.get("bot_instance")
    cache = bot_data.get("cache")
    if not binance or not bot:
        return

    ta_svc = TAService()

    try:
        async with AsyncSessionLocal() as db:
            watchlist_repo = WatchlistRepository(db)
            symbols = await watchlist_repo.get_all_watched_symbols()

            for symbol in symbols:
                try:
                    candles = await binance.get_klines(
                        symbol.replace("USDT", ""), interval="4h", limit=200
                    )
                    if len(candles) < 50:
                        continue

                    ind = ta_svc.compute_indicators(symbol, "4h", candles)

                    # Alert on extreme RSI
                    if ind.rsi < 30 or ind.rsi > 70:
                        # Notify all users watching this symbol
                        user_watchlists = await watchlist_repo.get_user_watchlist_by_symbol(symbol)
                        for wl in user_watchlists:
                            user_repo = UserRepository(db)
                            user = await user_repo.get(wl.user_id)
                            if not user:
                                continue

                            label = "oversold 🟢" if ind.rsi < 30 else "overbought 🔴"
                            msg = (
                                f"⚠️ *RSI Alert — {symbol}*\n"
                                f"RSI(14) is *{label}* on 4H\n"
                                f"Current RSI: `{ind.rsi:.1f}`\n"
                                f"Price: `${ind.current_price:,.2f}`"
                            )
                            await bot.send_message(
                                chat_id=user.telegram_id,
                                text=msg,
                                parse_mode="Markdown",
                            )

                except Exception as e:
                    logger.warning("RSI check failed for %s: %s", symbol, e)

    except Exception as e:
        logger.error("job_check_rsi_alerts error: %s", e)


async def job_morning_brief(bot_data: dict) -> None:
    """
    Daily 7:00 AM:
    Fetch market data, watchlist, and news. Pass to AI to generate a morning brief.
    Send to all registered users who have morning_brief_enabled=True.
    """
    from src.data.database import AsyncSessionLocal
    from src.data.repositories.user_repo import UserRepository
    from src.data.repositories.watchlist_repo import WatchlistRepository
    from src.core.news_service import NewsService
    from src.ai.context_builder import MarketContext, build_morning_brief_context
    from src.ai.factory import complete_with_fallback

    binance = bot_data.get("binance")
    bot = bot_data.get("bot_instance")
    cache = bot_data.get("cache")
    if not binance or not bot:
        return

    logger.info("Starting Morning Brief generation...")
    news_svc = NewsService(cache=cache)

    try:
        # 1. Fetch top news
        top_news = await news_svc.fetch_top_news(limit=5)

        # 2. Process for each user
        async with AsyncSessionLocal() as db:
            user_repo = UserRepository(db)
            watchlist_repo = WatchlistRepository(db)
            users = await user_repo.get_all()

            for user in users:
                if not user.morning_brief_enabled:
                    continue

                try:
                    # Fetch watchlist
                    wl_symbols = await watchlist_repo.get_symbols(user.id)
                    wl_performance = {}
                    market_data: list[MarketContext] = []

                    # Default coins if watchlist is empty
                    symbols_to_fetch = wl_symbols if wl_symbols else ["BTCUSDT", "ETHUSDT", "SOLUSDT"]

                    for sym in symbols_to_fetch:
                        ticker = await binance.get_ticker(sym)
                        wl_performance[sym.replace("USDT", "")] = ticker["change_pct"]
                        
                        # Just need basic info for context
                        ctx = MarketContext(
                            symbol=sym.replace("USDT", ""),
                            timeframe="1d",
                            price=ticker["price"],
                            change_pct_24h=ticker["change_pct"],
                            volume_24h=ticker["volume_usdt"]
                        )
                        market_data.append(ctx)

                    # Add Fear & Greed to first context
                    try:
                        fg = await binance.get_fear_greed_index()
                        if market_data:
                            market_data[0].fear_greed_index = fg["value"]
                            market_data[0].fear_greed_label = fg["label"]
                    except Exception:
                        pass

                    # 3. Build Prompt & Call AI (Fast Provider)
                    prompt = build_morning_brief_context(market_data, top_news, wl_performance)
                    prompt += "\nReply in a professional, concise tone in Vietnamese. Format nicely with Telegram MarkdownV2."
                    
                    try:
                        # fast=True -> uses Fast Provider (DeepSeek)
                        ai_text = await complete_with_fallback(prompt, max_tokens=500, fast=True)
                    except Exception as ai_err:
                        logger.error("AI morning brief failed: %s", ai_err)
                        ai_text = "Lỗi tạo bản tin sáng từ AI."

                    header = f"🌅 *Bản Tin Sáng — {datetime.now().strftime('%d/%m/%Y')}*\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
                    
                    # MarkdownV2 requires escaping some chars if the AI didn't do it perfectly,
                    # but we trust the AI to format mostly correctly. If it fails, fallback to Markdown.
                    try:
                        await bot.send_message(
                            chat_id=user.telegram_id,
                            text=header + ai_text,
                            parse_mode="Markdown"
                        )
                    except Exception as tg_err:
                        logger.warning("Failed to send morning brief with Markdown, retrying without: %s", tg_err)
                        await bot.send_message(chat_id=user.telegram_id, text=header + ai_text)

                except Exception as e:
                    logger.error("Failed to generate brief for user %s: %s", user.telegram_id, e)

    except Exception as e:
        logger.error("job_morning_brief error: %s", e)


def setup_scheduler(bot_data: dict) -> AsyncIOScheduler:
    """Configure and return the scheduler with all jobs."""
    scheduler = get_scheduler()

    # Every 5 minutes — price alert check
    scheduler.add_job(
        job_check_price_alerts,
        trigger="interval",
        minutes=5,
        kwargs={"bot_data": bot_data},
        id="check_price_alerts",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )

    # Every 30 minutes — RSI extreme check
    scheduler.add_job(
        job_check_rsi_alerts,
        trigger="interval",
        minutes=30,
        kwargs={"bot_data": bot_data},
        id="check_rsi_alerts",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )

    # Daily 07:00 AM — Morning Brief
    from config.settings import settings
    h, m = map(int, settings.MORNING_BRIEF_TIME.split(":"))
    scheduler.add_job(
        job_morning_brief,
        trigger="cron",
        hour=h,
        minute=m,
        kwargs={"bot_data": bot_data},
        id="morning_brief",
        replace_existing=True,
        max_instances=1,
    )

    logger.info("Scheduler configured: %d jobs", len(scheduler.get_jobs()))
    return scheduler
