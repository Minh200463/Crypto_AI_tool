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


async def job_auto_scan_watchlist(bot_data: dict) -> None:
    """
    [NEW] Auto-scan Watchlist — runs every 4H.

    For each user who has /autoscan enabled:
      1. Fetch their watchlist symbols
      2. Run scoring (same engine as /signal) for each symbol
      3. If any symbol scores >= user's min_score threshold → send Telegram alert
      4. Does NOT call AI (no token cost), does NOT log to signal_logs DB
         — user still needs to type /signal <coin> to get full analysis + log

    This converts the bot from reactive (user asks) to proactive (bot alerts).
    """
    from src.data.database import AsyncSessionLocal
    from src.data.repositories.watchlist_repo import WatchlistRepository
    from src.data.repositories.user_repo import UserRepository
    from src.core.ta_service import TAService, SCORE_TIER_A
    from src.database.settings_repository import get_all_autoscan_users
    import asyncio

    binance = bot_data.get("binance")
    bot     = bot_data.get("bot_instance")
    if not binance or not bot:
        return

    # Get all users who enabled autoscan
    autoscan_users = get_all_autoscan_users()
    if not autoscan_users:
        return  # Nobody has autoscan on — skip entirely

    logger.info("Auto-scan: checking %d users", len(autoscan_users))
    ta_svc = TAService()

    async with AsyncSessionLocal() as db:
        watchlist_repo = WatchlistRepository(db)
        user_repo      = UserRepository(db)

        for user_cfg in autoscan_users:
            user_id       = user_cfg["user_id"]
            min_score     = user_cfg["autoscan_min_score"]

            try:
                # Get telegram_id from user table
                user = await user_repo.get_by_telegram_id(user_id)
                if not user:
                    continue

                # Get this user's watchlist symbols
                symbols = await watchlist_repo.get_symbols(user.id)
                if not symbols:
                    continue

                # Scan each symbol — use asyncio.gather for speed
                async def _scan_one(symbol: str) -> dict | None:
                    """Score one symbol, return result if above threshold."""
                    try:
                        coin = symbol.replace("USDT", "")
                        # Fetch 4H, 1D, 1W candles in parallel
                        candles_4h, candles_1d, candles_1w, oi_data = await asyncio.gather(
                            binance.get_klines(coin, interval="4h", limit=200),
                            binance.get_klines(coin, interval="1d", limit=60),
                            binance.get_klines(coin, interval="1w", limit=52),
                            binance.get_open_interest(coin),
                            return_exceptions=True,
                        )
                        if isinstance(candles_4h, Exception) or len(candles_4h) < 50:
                            return None

                        ind = ta_svc.compute_indicators(symbol, "4h", candles_4h)
                        if isinstance(oi_data, dict):
                            ind.oi_change_pct = oi_data.get("oi_change_pct")

                        daily_trend  = ta_svc.get_daily_trend(candles_1d) if not isinstance(candles_1d, Exception) else "UNKNOWN"
                        weekly_trend = ta_svc.get_weekly_trend(candles_1w) if not isinstance(candles_1w, Exception) else "UNKNOWN"

                        long_score,  long_reasons  = ta_svc.score_long_setup(ind, daily_trend, weekly_trend)
                        short_score, short_reasons = ta_svc.score_short_setup(ind, daily_trend, weekly_trend)

                        best_score = max(long_score, short_score)
                        if best_score < min_score:
                            return None  # Below user's threshold

                        side        = "LONG" if long_score >= short_score else "SHORT"
                        score       = long_score if side == "LONG" else short_score
                        tier_label  = "⭐⭐⭐ Tier A" if score >= SCORE_TIER_A else "⭐⭐ Tier B"
                        side_emoji  = "🟢" if side == "LONG" else "🔴"
                        session     = ta_svc.get_current_session()

                        return {
                            "symbol":       symbol,
                            "coin":         coin,
                            "side":         side,
                            "side_emoji":   side_emoji,
                            "score":        score,
                            "tier_label":   tier_label,
                            "price":        ind.current_price,
                            "daily_trend":  daily_trend,
                            "weekly_trend": weekly_trend,
                            "session":      session,
                        }
                    except Exception as e:
                        logger.warning("Auto-scan error for %s: %s", symbol, e)
                        return None

                # Run all symbols in parallel for this user
                results = await asyncio.gather(*[_scan_one(sym) for sym in symbols])
                hits    = [r for r in results if r is not None]

                if not hits:
                    logger.debug("Auto-scan user %d: no signals above %d/10", user_id, min_score)
                    continue

                # Build and send alert message for each hit
                for hit in hits:
                    sess = hit["session"]
                    msg = (
                        f"🚨 *AUTO-SCAN ALERT*\n"
                        f"━━━━━━━━━━━━━━━━━━━━━━\n"
                        f"{hit['side_emoji']} *{hit['coin']}* — {hit['tier_label']} `({hit['score']}/10)`\n"
                        f"Lệnh: *{hit['side']}* | Giá: `${hit['price']:,.2f}`\n"
                        f"📅 1W: `{hit['weekly_trend']}` | 1D: `{hit['daily_trend']}`\n"
                        f"{sess['emoji']} Phiên: `{sess['label']}`\n\n"
                        f"👉 Gõ `/signal {hit['coin']}` để xem phân tích đầy đủ\n"
                        f"_Bot không ghi log cho đến khi bạn gõ /signal_"
                    )
                    try:
                        await bot.send_message(
                            chat_id=user.telegram_id,
                            text=msg,
                            parse_mode="Markdown",
                        )
                        logger.info(
                            "Auto-scan alert sent: user=%d symbol=%s score=%d side=%s",
                            user_id, hit["symbol"], hit["score"], hit["side"],
                        )
                    except Exception as tg_err:
                        logger.warning("Failed to send auto-scan alert: %s", tg_err)

            except Exception as e:
                logger.error("Auto-scan failed for user %d: %s", user_id, e)


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

    # Every 4H — Auto-scan watchlist for all users who enabled /autoscan
    # [NEW] Proactive signal hunting: bot alerts user instead of user having to ask
    scheduler.add_job(
        job_auto_scan_watchlist,
        trigger="interval",
        hours=4,
        kwargs={"bot_data": bot_data},
        id="auto_scan_watchlist",
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
