"""
Telegram Bot handlers — all commands for Milestone 2+3.
Thin layer: parse command → call service → format → reply.
"""
import asyncio
import logging
from telegram import Update
from telegram.ext import ContextTypes

logger = logging.getLogger(__name__)

DISCLAIMER = "\n\n⚠️ _Tham khảo kỹ thuật — không phải tư vấn tài chính\\._"


def _get_binance(ctx: ContextTypes.DEFAULT_TYPE):
    return ctx.application.bot_data["binance"]

def _get_db_session(ctx: ContextTypes.DEFAULT_TYPE):
    return ctx.application.bot_data["db_session"]

def _normalize_symbol(s: str) -> str:
    s = s.upper().strip()
    return s if s.endswith("USDT") else f"{s}USDT"


# ─── /start ──────────────────────────────────────────────────────────────────

async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_user or not update.effective_message:
        return
    tg_user = update.effective_user
    AsyncSessionLocal = _get_db_session(context)

    async with AsyncSessionLocal() as db:
        from src.data.repositories.user_repo import UserRepository
        user, created = await UserRepository(db).upsert_user(
            telegram_id=tg_user.id,
            username=tg_user.username,
            first_name=tg_user.first_name,
        )

    name = tg_user.first_name or "Trader"
    if created:
        msg = (
            f"👋 Xin chào *{name}*\\!\n\n"
            "🤖 *CryptoAI Trading Assistant* đã sẵn sàng\\.\n\n"
            "📋 *Lệnh cơ bản:*\n"
            "`/price BTC` — Xem giá\n"
            "`/analyze BTC` — Phân tích kỹ thuật\n"
            "`/watch BTC ETH` — Theo dõi coin\n"
            "`/setalert BTC 70000` — Đặt cảnh báo giá\n"
            "`/help` — Xem tất cả lệnh\n\n"
            "Chúc trading hiệu quả\\! 🚀"
        )
    else:
        msg = f"👋 Chào mừng trở lại *{name}*\\! Gõ `/help` để xem lệnh\\."

    await update.effective_message.reply_text(msg, parse_mode="MarkdownV2")


# ─── /help ───────────────────────────────────────────────────────────────────

async def help_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_message:
        return
    msg = (
        "📖 *Danh sách lệnh*\n\n"
        "*💰 Giá & Thị trường*\n"
        "`/price BTC` — Giá \\+ 24h stats\n"
        "`/market` — Top coins \\+ Fear \\& Greed\n"
        "`/watchlist` — Danh sách theo dõi\n"
        "`/watch BTC ETH SOL` — Thêm coin\n"
        "`/unwatch BTC` — Xóa coin\n\n"
        "*📊 Phân tích & Tín hiệu*\n"
        "`/analyze BTC` — TA đầy đủ \\(4H\\) kết hợp AI\n"
        "`/analyze ETH 1h` — TA theo timeframe\n"
        "`/signal BTC` — Setup giao dịch & AI nhận định\n\n"
        "*🔔 Cảnh báo*\n"
        "`/setalert BTC 70000` — Giá vượt ngưỡng\n"
        "`/setalert BTC 60000 below` — Giá xuống ngưỡng\n"
        "`/alerts` — Xem alerts đang active\n"
        "`/clear BTC` — Xóa alerts của BTC\n"
        "`/clearall` — Xóa tất cả alerts\n\n"
        "*🛠 Sắp ra mắt \\(Quản lý rủi ro\\)*\n"
        "`/risk 1000 BTC 67000 63850` — Quản lý rủi ro\n"
        "`/log BTC buy 67000 0\\.01` — Nhật ký lệnh"
    )
    await update.effective_message.reply_text(msg, parse_mode="MarkdownV2")


# ─── /price ──────────────────────────────────────────────────────────────────

async def price_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_message:
        return
    args = context.args or []
    symbol = args[0].upper() if args else "BTC"
    msg = await update.effective_message.reply_text(f"⏳ Đang lấy giá {symbol}...")

    try:
        ticker = await _get_binance(context).get_ticker(symbol)
        pct = ticker["change_pct"]
        emoji = "🟢" if pct >= 0 else "🔴"
        text = (
            f"💰 *{ticker['symbol']}*\n"
            f"━━━━━━━━━━━━━━\n"
            f"Giá: `${ticker['price']:,.2f}`\n"
            f"24h: {emoji} `{pct:+.2f}%`\n"
            f"Volume: `${ticker['volume_usdt']:,.0f}`\n"
            f"High: `${ticker['high_24h']:,.2f}`\n"
            f"Low:  `${ticker['low_24h']:,.2f}`"
        )
        await msg.edit_text(text, parse_mode="Markdown")
    except Exception as e:
        logger.error("Price error %s: %s", symbol, e)
        await msg.edit_text(f"❌ Không thể lấy giá `{symbol}`. Kiểm tra lại tên coin.")


# ─── /market ─────────────────────────────────────────────────────────────────

async def market_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_message:
        return
    msg = await update.effective_message.reply_text("⏳ Đang tải dữ liệu thị trường...")

    try:
        binance = _get_binance(context)
        coins = ["BTC", "ETH", "BNB", "SOL", "XRP"]
        lines = ["📊 *Tổng quan thị trường*\n━━━━━━━━━━━━━━━━━━━━"]

        for coin in coins:
            try:
                t = await binance.get_ticker(coin)
                pct = t["change_pct"]
                arrow = "▲" if pct >= 0 else "▼"
                lines.append(f"`{coin:<4}` ${t['price']:>12,.2f}  {arrow} `{pct:+.2f}%`")
            except Exception:
                lines.append(f"`{coin}` — N/A")

        try:
            fg = await binance.get_fear_greed_index()
            lines.append(f"\n😱 *Fear & Greed:* `{fg['value']}` — {fg['label']}")
        except Exception:
            pass

        await msg.edit_text("\n".join(lines), parse_mode="Markdown")
    except Exception as e:
        logger.error("Market error: %s", e)
        await msg.edit_text("❌ Lỗi tải dữ liệu thị trường.")


# ─── /analyze ────────────────────────────────────────────────────────────────

async def analyze_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_message:
        return
    args = context.args or []
    symbol = args[0].upper() if args else "BTC"
    timeframe = args[1].lower() if len(args) > 1 else "4h"

    valid_tf = ["1m", "5m", "15m", "1h", "4h", "1d"]
    if timeframe not in valid_tf:
        await update.effective_message.reply_text(
            f"❌ Timeframe không hợp lệ. Dùng: {', '.join(valid_tf)}"
        )
        return

    msg = await update.effective_message.reply_text(
        f"⏳ Đang phân tích *{symbol}* trên *{timeframe.upper()}*...",
        parse_mode="Markdown",
    )

    try:
        from src.core.ta_service import TAService
        binance = _get_binance(context)
        ta_svc = TAService()

        candles = await binance.get_klines(symbol, interval=timeframe, limit=200)
        if len(candles) < 50:
            await msg.edit_text("❌ Không đủ dữ liệu để phân tích.")
            return

        ind = ta_svc.compute_indicators(_normalize_symbol(symbol), timeframe, candles)
        ticker = await binance.get_ticker(symbol)

        # Funding rate (optional)
        funding = await binance.get_funding_rate(symbol)
        funding_str = f"`{funding*100:+.4f}%`" if funding is not None else "N/A"

        # Formatting technical text
        vol_ratio = ind.volume_vs_avg
        vol_emoji = "🔥" if vol_ratio > 1.5 else "📊"

        text = (
            f"📊 *{ind.symbol} — {timeframe.upper()} Analysis*\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"💰 Price: `${ind.current_price:,.2f}` | 24h: `{ticker['change_pct']:+.2f}%`\n\n"
            f"📈 *Trend*\n"
            f"  MA20:  `${ind.ma20:,.2f}` {'✅' if ind.current_price > ind.ma20 else '❌'}\n"
            f"  MA50:  `${ind.ma50:,.2f}` {'✅' if ind.current_price > ind.ma50 else '❌'}\n"
            f"  MA200: `${ind.ma200:,.2f}` {'✅' if ind.current_price > ind.ma200 else '❌'}\n"
            f"  → {ind.trend_label}\n\n"
            f"⚡ *Momentum*\n"
            f"  RSI(14): `{ind.rsi:.1f}` — {ind.rsi_label}\n"
            f"  MACD: `{ind.macd_histogram:+.4f}` "
            f"{'🔼 Bullish' if ind.macd_crossover == 'bullish' else '🔽 Bearish' if ind.macd_crossover == 'bearish' else '—'}\n\n"
            f"📉 *Bollinger Bands*\n"
            f"  Upper: `${ind.bb_upper:,.2f}`\n"
            f"  Mid:   `${ind.bb_mid:,.2f}`\n"
            f"  Lower: `${ind.bb_lower:,.2f}`\n"
            f"  → {ind.bb_position}\n\n"
            f"{vol_emoji} *Volume:* `${ind.volume:,.0f}` ({vol_ratio:.1f}x avg)\n"
            f"📏 *ATR(14):* `${ind.atr:,.2f}`\n"
            f"💱 *Funding:* {funding_str}"
        )

        if ind.support_levels:
            supports = " | ".join(f"`${s:,.0f}`" for s in ind.support_levels[:3])
            text += f"\n\n🛡 *Support:* {supports}"
        if ind.resistance_levels:
            resistances = " | ".join(f"`${r:,.0f}`" for r in ind.resistance_levels[:3])
            text += f"\n🚧 *Resistance:* {resistances}"

        await msg.edit_text(text + "\n\n⏳ _Đang chờ AI nhận định..._", parse_mode="Markdown")

        # ── Call AI for natural language interpretation (Claude) ──
        from src.ai.context_builder import MarketContext, build_analysis_context
        from src.ai.factory import complete_with_fallback

        ctx = MarketContext(
            symbol=ind.symbol,
            timeframe=timeframe,
            price=ind.current_price,
            change_pct_24h=ticker["change_pct"],
            volume_24h=ticker["volume_usdt"],
            rsi=ind.rsi,
            macd_line=ind.macd_line,
            macd_signal=ind.macd_signal,
            macd_histogram=ind.macd_histogram,
            macd_crossover=ind.macd_crossover,
            bb_upper=ind.bb_upper,
            bb_mid=ind.bb_mid,
            bb_lower=ind.bb_lower,
            ma20=ind.ma20,
            ma50=ind.ma50,
            ma200=ind.ma200,
            atr=ind.atr,
            funding_rate=funding,
            support_levels=ind.support_levels,
            resistance_levels=ind.resistance_levels,
        )

        prompt = build_analysis_context(ctx) + (
            "\n\nPlease provide a concise 3-4 sentence interpretation of this data. "
            "Focus on the most important signals and overall market structure. "
            "Reply in Vietnamese."
        )

        try:
            # fast=False -> uses Primary Provider (Claude)
            ai_response = await complete_with_fallback(prompt, max_tokens=300, fast=False)
            final_text = text + f"\n\n🤖 *AI Nhận Định:*\n_{ai_response}_"
            final_text += DISCLAIMER
            await msg.edit_text(final_text, parse_mode="Markdown")
        except Exception as ai_err:
            logger.warning("AI analyze failed: %s", ai_err)
            await msg.edit_text(text + "\n\n❌ _Lỗi kết nối AI._" + DISCLAIMER, parse_mode="Markdown")

    except Exception as e:
        logger.error("Analyze error %s %s: %s", symbol, timeframe, e)
        await msg.edit_text(f"❌ Lỗi phân tích `{symbol}`. Thử lại sau.")


# ─── /signal ─────────────────────────────────────────────────────────────────

async def signal_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_message:
        return
    args = context.args or []
    symbol = args[0].upper() if args else "BTC"

    msg = await update.effective_message.reply_text(
        f"⏳ Đang phân tích đa khung thời gian cho *{symbol}*...",
        parse_mode="Markdown"
    )

    try:
        from src.core.ta_service import TAService
        from src.ai.context_builder import MarketContext, build_signal_context
        from src.ai.factory import complete_with_fallback

        binance = _get_binance(context)
        ta_svc = TAService()

        # ── Fetch 4H + 1D candles for MTF filter ──────────────────────
        candles_4h, candles_1d = await asyncio.gather(
            binance.get_klines(symbol, interval="4h", limit=200),
            binance.get_klines(symbol, interval="1d", limit=200),
        )

        if len(candles_4h) < 50:
            await msg.edit_text("❌ Không đủ dữ liệu 4H.")
            return

        ind = ta_svc.compute_indicators(_normalize_symbol(symbol), "4h", candles_4h)

        # ── MTF: Get daily trend ───────────────────────────────────────
        daily_trend = "sideways"
        if len(candles_1d) >= 50:
            daily_trend = ta_svc.get_daily_trend(candles_1d)

        await msg.edit_text(
            f"⏳ *{symbol}* — 1D Trend: `{daily_trend.upper()}` | Đang chấm điểm setup...",
            parse_mode="Markdown"
        )

        # ── Confluence Scoring (v2: 10-point, 2-tier) ─────────────────
        from src.core.ta_service import SCORE_TIER_A, SCORE_TIER_B, SCORE_THRESHOLD
        long_score, long_reasons = ta_svc.score_long_setup(ind, daily_trend)
        short_score, short_reasons = ta_svc.score_short_setup(ind, daily_trend)

        if long_score >= SCORE_THRESHOLD:
            side, score, reasons, emoji = "long", long_score, long_reasons, "🟢 LONG"
        elif short_score >= SCORE_THRESHOLD:
            side, score, reasons, emoji = "short", short_score, short_reasons, "🔴 SHORT"
        else:
            await msg.edit_text(
                f"⚖️ *{symbol}* — Không có setup chất lượng cao\n"
                f"Long: `{long_score}/10` | Short: `{short_score}/10`\n"
                f"📊 Xu hướng 1D: `{daily_trend.upper()}`\n\n"
                f"_Cần tối thiểu {SCORE_THRESHOLD}/10 điểm để kích hoạt signal._\n"
                f"Hãy kiên nhẫn chờ setup tốt hơn. 🎯",
                parse_mode="Markdown"
            )
            return

        # ── 2-tier position size guidance ─────────────────────────────
        if score >= SCORE_TIER_A:
            signal_grade = "⭐⭐⭐ MẠNH"
            size_advice = "Full size (1–2% vốn)"
        else:
            signal_grade = "⭐⭐ KHÁ"
            size_advice = "Half size (0.5–1% vốn) — thận trọng"

        text = (
            f"🎯 *Signal: {symbol} — 4H*\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"Lệnh: {emoji} | Chất lượng: {signal_grade}\n"
            f"Điểm hợp lưu: `{score}/10` | Xu hướng 1D: `{daily_trend.upper()}`\n"
            f"💼 *Position size gợi ý:* _{size_advice}_\n\n"
            f"📍 *Entry {levels['entry_type']}:*\n"
            f"   Market: `${levels['entry']:,.2f}`\n"
            f"   Limit tối ưu: `${levels['limit_entry']:,.2f}` _(Fib 0.618)_\n\n"
            f"🛡 *Stop Loss:*  `${levels['sl']:,.2f}` `(-{levels['sl_pct']}%)`\n"
            f"🎯 *TP1:* `${levels['tp1']:,.2f}` `(R:R 1:{levels['rr1']})`\n"
            f"🎯 *TP2:* `${levels['tp2']:,.2f}` `(R:R 1:{levels['rr2']})`\n"
            f"🎯 *TP3:* `${levels['tp3']:,.2f}` _(1:3 target)_\n\n"
            f"🔍 *Tín hiệu kỹ thuật ({score}/10):*\n" +
            "\n".join([f"• {r}" for r in reasons])
        )

        await msg.edit_text(text + "\n\n⏳ _Đang chờ AI phản biện setup..._", parse_mode="Markdown")

        # ── AI validation (Claude = Primary provider) ──────────────────
        ticker = await binance.get_ticker(symbol)
        ctx = MarketContext(
            symbol=ind.symbol,
            timeframe="4h",
            price=ind.current_price,
            change_pct_24h=ticker["change_pct"],
            volume_24h=ticker["volume_usdt"],
            rsi=ind.rsi,
            macd_line=ind.macd_line,
            macd_signal=ind.macd_signal,
            macd_histogram=ind.macd_histogram,
            macd_crossover=ind.macd_crossover,
            bb_upper=ind.bb_upper,
            bb_mid=ind.bb_mid,
            bb_lower=ind.bb_lower,
            ma20=ind.ma20,
            ma50=ind.ma50,
            ma200=ind.ma200,
            atr=ind.atr,
            volume_vs_avg=ind.volume_vs_avg,
            volume_trend=ind.volume_trend,
            daily_trend=daily_trend,
            last_candles=ind.last_candles,
            support_levels=ind.support_levels,
            resistance_levels=ind.resistance_levels,
        )

        prompt = build_signal_context(ctx, score, MAX_SCORE, reasons, side, levels)
        prompt += "\nReply in Vietnamese in 4-5 sentences."

        try:
            ai_response = await complete_with_fallback(prompt, max_tokens=350, fast=False)
            final_text = text + f"\n\n🤖 *AI Nhận Định:*\n_{ai_response}_" + DISCLAIMER
            await msg.edit_text(final_text, parse_mode="Markdown")
        except Exception as ai_err:
            logger.warning("AI signal failed: %s", ai_err)
            await msg.edit_text(text + "\n\n❌ _Lỗi kết nối AI._" + DISCLAIMER, parse_mode="Markdown")

    except Exception as e:
        logger.error("Signal error %s: %s", symbol, e)
        await msg.edit_text(f"❌ Lỗi xử lý tín hiệu `{symbol}`. Thử lại sau.")

        logger.error("Signal error %s: %s", symbol, e)
        await msg.edit_text(f"❌ Lỗi xử lý tín hiệu `{symbol}`. Thử lại sau.")


# ─── /watchlist, /watch, /unwatch ───────────────────────────────────────────

async def watchlist_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_message or not update.effective_user:
        return
    AsyncSessionLocal = _get_db_session(context)
    binance = _get_binance(context)

    async with AsyncSessionLocal() as db:
        from src.data.repositories.user_repo import UserRepository
        from src.data.repositories.watchlist_repo import WatchlistRepository
        user, _ = await UserRepository(db).upsert_user(update.effective_user.id)
        symbols = await WatchlistRepository(db).get_symbols(user.id)

    if not symbols:
        await update.effective_message.reply_text(
            "📋 Watchlist trống.\nDùng `/watch BTC ETH` để thêm coin.", parse_mode="Markdown"
        )
        return

    msg = await update.effective_message.reply_text("⏳ Đang tải watchlist...")
    lines = ["📋 *Watchlist của bạn*\n━━━━━━━━━━━━━━━━━━━━"]

    for sym in symbols:
        try:
            t = await binance.get_ticker(sym.replace("USDT", ""))
            pct = t["change_pct"]
            arrow = "▲" if pct >= 0 else "▼"
            lines.append(f"`{sym.replace('USDT',''):<5}` ${t['price']:>12,.2f}  {arrow}`{pct:+.2f}%`")
        except Exception:
            lines.append(f"`{sym}` — lỗi")

    await msg.edit_text("\n".join(lines), parse_mode="Markdown")


async def watch_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_message or not update.effective_user:
        return
    if not context.args:
        await update.effective_message.reply_text("❌ Dùng: `/watch BTC ETH SOL`", parse_mode="Markdown")
        return

    AsyncSessionLocal = _get_db_session(context)
    added, already = [], []

    async with AsyncSessionLocal() as db:
        from src.data.repositories.user_repo import UserRepository
        from src.data.repositories.watchlist_repo import WatchlistRepository
        user, _ = await UserRepository(db).upsert_user(update.effective_user.id)
        wl_repo = WatchlistRepository(db)
        for arg in context.args:
            sym = _normalize_symbol(arg)
            _, created = await wl_repo.add(user.id, sym)
            (added if created else already).append(sym.replace("USDT", ""))

    parts = []
    if added:
        parts.append(f"✅ Đã thêm: *{', '.join(added)}*")
    if already:
        parts.append(f"ℹ️ Đã có: {', '.join(already)}")
    await update.effective_message.reply_text("\n".join(parts), parse_mode="Markdown")


async def unwatch_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_message or not update.effective_user:
        return
    if not context.args:
        await update.effective_message.reply_text("❌ Dùng: `/unwatch BTC`", parse_mode="Markdown")
        return

    AsyncSessionLocal = _get_db_session(context)
    removed, not_found = [], []

    async with AsyncSessionLocal() as db:
        from src.data.repositories.user_repo import UserRepository
        from src.data.repositories.watchlist_repo import WatchlistRepository
        user, _ = await UserRepository(db).upsert_user(update.effective_user.id)
        wl_repo = WatchlistRepository(db)
        for arg in context.args:
            sym = _normalize_symbol(arg)
            ok = await wl_repo.remove(user.id, sym)
            (removed if ok else not_found).append(sym.replace("USDT", ""))

    parts = []
    if removed:
        parts.append(f"✅ Đã xóa: *{', '.join(removed)}*")
    if not_found:
        parts.append(f"ℹ️ Không tìm thấy: {', '.join(not_found)}")
    await update.effective_message.reply_text("\n".join(parts), parse_mode="Markdown")


# ─── /setalert, /alerts, /clear, /clearall ──────────────────────────────────

async def setalert_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /setalert BTC 70000          → price_above
    /setalert BTC 60000 below    → price_below
    /setalert ETH 5pct           → pct_change (not yet implemented in checker)
    """
    if not update.effective_message or not update.effective_user:
        return
    args = context.args or []

    if len(args) < 2:
        await update.effective_message.reply_text(
            "❌ Cú pháp:\n"
            "`/setalert BTC 70000` — giá vượt\n"
            "`/setalert BTC 60000 below` — giá xuống",
            parse_mode="Markdown",
        )
        return

    symbol = _normalize_symbol(args[0])
    threshold_str = args[1]
    direction = args[2].lower() if len(args) > 2 else "above"

    try:
        threshold = float(threshold_str)
    except ValueError:
        await update.effective_message.reply_text("❌ Giá không hợp lệ.")
        return

    alert_type = "price_above" if direction == "above" else "price_below"
    emoji = "📈" if direction == "above" else "📉"

    AsyncSessionLocal = _get_db_session(context)
    async with AsyncSessionLocal() as db:
        from src.data.repositories.user_repo import UserRepository
        from src.core.alert_service import AlertService
        user, _ = await UserRepository(db).upsert_user(update.effective_user.id)
        alert_svc = AlertService(db)
        await alert_svc.create_alert(
            user_id=user.id,
            symbol=symbol,
            alert_type=alert_type,
            threshold=threshold,
            direction=direction,
        )

    await update.effective_message.reply_text(
        f"🔔 Alert đã đặt!\n"
        f"{emoji} *{symbol.replace('USDT','')}* {'vượt' if direction == 'above' else 'xuống'} "
        f"`${threshold:,.2f}`\n\n"
        f"Bot sẽ thông báo ngay khi giá chạm ngưỡng này.",
        parse_mode="Markdown",
    )


async def alerts_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_message or not update.effective_user:
        return
    AsyncSessionLocal = _get_db_session(context)

    async with AsyncSessionLocal() as db:
        from src.data.repositories.user_repo import UserRepository
        from src.data.repositories.alert_repo import AlertRepository
        user, _ = await UserRepository(db).upsert_user(update.effective_user.id)
        alerts = await AlertRepository(db).get_user_alerts(user.id)

    if not alerts:
        await update.effective_message.reply_text("📭 Không có alert nào đang active.")
        return

    lines = ["🔔 *Alerts đang active*\n━━━━━━━━━━━━━━━━━━"]
    for a in alerts:
        sym = a.symbol.replace("USDT", "")
        t_str = f"${float(a.threshold):,.2f}" if a.threshold else "—"
        dir_str = "▲ Above" if a.alert_type == "price_above" else "▼ Below"
        lines.append(f"• *{sym}* {dir_str} `{t_str}`")

    await update.effective_message.reply_text("\n".join(lines), parse_mode="Markdown")


async def clear_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_message or not update.effective_user:
        return
    if not context.args:
        await update.effective_message.reply_text("❌ Dùng: `/clear BTC`", parse_mode="Markdown")
        return

    symbol = _normalize_symbol(context.args[0])
    AsyncSessionLocal = _get_db_session(context)

    async with AsyncSessionLocal() as db:
        from src.data.repositories.user_repo import UserRepository
        from src.core.alert_service import AlertService
        user, _ = await UserRepository(db).upsert_user(update.effective_user.id)
        count = await AlertService(db).deactivate_all_for_symbol(user.id, symbol)

    sym = symbol.replace("USDT", "")
    if count:
        await update.effective_message.reply_text(f"✅ Đã xóa *{count}* alert của *{sym}*.", parse_mode="Markdown")
    else:
        await update.effective_message.reply_text(f"ℹ️ Không có alert nào cho *{sym}*.", parse_mode="Markdown")


async def clearall_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_message or not update.effective_user:
        return
    AsyncSessionLocal = _get_db_session(context)

    async with AsyncSessionLocal() as db:
        from src.data.repositories.user_repo import UserRepository
        from src.core.alert_service import AlertService
        user, _ = await UserRepository(db).upsert_user(update.effective_user.id)
        count = await AlertService(db).deactivate_all(user.id)

    if count:
        await update.effective_message.reply_text(f"✅ Đã xóa *{count}* alerts.", parse_mode="Markdown")
    else:
        await update.effective_message.reply_text("ℹ️ Không có alert nào để xóa.")
