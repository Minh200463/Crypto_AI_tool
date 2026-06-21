"""
Telegram Bot handlers — all commands for Milestone 2+3.
Thin layer: parse command → call service → format → reply.
"""
import asyncio
import httpx
import logging
from telegram import Update
from telegram.ext import ContextTypes

from src.database.signal_repository import init_db, SignalRecord
from src.database.settings_repository import (
    init_settings_table,
    get_user_settings,
    DEFAULT_EQUITY,
    DEFAULT_RISK_PCT,
)
from src.core.position_sizer import calculate_position_size, format_position_block
from src.core.signal_tracker import (
    build_signal_record,
    check_open_signals,
    format_stats_message,
    format_recent_signals_message,
    log_signal,
)

logger = logging.getLogger(__name__)

# Ensure DB tables are ready on first import
try:
    init_db()
    init_settings_table()
except Exception as _e:
    logger.warning("DB init failed: %s", _e)

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
        "*📅 Spot vs Futures*\n"
        "Bot tự detect thị trường khi bạn gọi lệnh\.\n"
        "• 📊 *SPOT* — BTC, ETH, BNB, SOL\.\.\. \\(lờị thường\\)\n"
        "• ⚡ *FUTURES* — XAGUSDT, XAU, các coin Futures\-only\n"
        "Signal hiển thị badge rõ `\\[SPOT\\]` hoặc `\\[FUTURES\\]`\.\n\n"
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

        # ── Fetch 4H + 1D + 1W candles + OI (P4) ──────────
        candles_4h, candles_1d, candles_1w, oi_data = await asyncio.gather(
            binance.get_klines(symbol, interval="4h", limit=200),
            binance.get_klines(symbol, interval="1d", limit=200),
            binance.get_klines(symbol, interval="1w", limit=100),  # ~2 years
            binance.get_open_interest(symbol),
            return_exceptions=True
        )

        if isinstance(candles_4h, Exception) or len(candles_4h) < 50:
            await msg.edit_text("❌ Không đủ dữ liệu 4H.")
            return

        ind = ta_svc.compute_indicators(_normalize_symbol(symbol), "4h", candles_4h)
        
        # Attach OI data to indicator result
        if oi_data and not isinstance(oi_data, Exception):
            ind.oi_change_pct = oi_data.get("oi_change_pct")

        # ── MTF: 3-layer trend filter (1W → 1D → 4H) ─────────────────
        daily_trend  = ta_svc.get_daily_trend(candles_1d)  if not isinstance(candles_1d, Exception) and len(candles_1d)  >= 50 else "sideways"
        weekly_trend = ta_svc.get_weekly_trend(candles_1w) if not isinstance(candles_1w, Exception) and len(candles_1w) >= 50 else "sideways"

        # Weekly trend icon
        weekly_icons = {"uptrend": "📈", "downtrend": "📉", "sideways": "↔️"}
        weekly_icon  = weekly_icons.get(weekly_trend, "↔️")

        await msg.edit_text(
            f"⏳ *{symbol}* — 1W: {weekly_icon}`{weekly_trend.upper()}` | "
            f"1D: `{daily_trend.upper()}` | Đang chấm điểm setup...",
            parse_mode="Markdown"
        )

        # ── Confluence Scoring (v2: 10-point, 3-layer MTF) ───────────
        from src.core.ta_service import SCORE_TIER_A, SCORE_TIER_B, SCORE_THRESHOLD
        long_score,  long_reasons  = ta_svc.score_long_setup(ind,  daily_trend, weekly_trend)
        short_score, short_reasons = ta_svc.score_short_setup(ind, daily_trend, weekly_trend)

        if long_score >= SCORE_THRESHOLD:
            side, score, reasons, emoji = "long", long_score, long_reasons, "🟢 LONG"
        elif short_score >= SCORE_THRESHOLD:
            side, score, reasons, emoji = "short", short_score, short_reasons, "🔴 SHORT"
        else:
            await msg.edit_text(
                f"⚖️ *{symbol}* `{mtype_badge}` — Không có setup chất lượng cao\n"
                f"Long: `{long_score}/10` | Short: `{short_score}/10`\n"
                f"📊 Xu hướng 1W: {weekly_icon}`{weekly_trend.upper()}` | 1D: `{daily_trend.upper()}`\n\n"
                f"_Cần tối thiểu {SCORE_THRESHOLD}/10 điểm để kích hoạt signal._\n"
                f"Hãy kiên nhẫn chờ setup tốt hơn. 🎯",
                parse_mode="Markdown"
            )
            return

        # ── 2-tier: position size + SL tightness ──────────────────────
        is_tier_b = score < SCORE_TIER_A
        tier_label = "B" if is_tier_b else "A"
        signal_grade = "⭐⭐⭐ MẠNH" if not is_tier_b else "⭐⭐ KHÁ"

        levels = ta_svc.calculate_trade_levels(side, ind.current_price, ind, is_tier_b=is_tier_b)

        # ── Position Sizing (auto from user settings) ─────────────────
        user_id = update.effective_user.id if update.effective_user else 0
        user_cfg = get_user_settings(user_id)
        equity   = user_cfg["equity"]
        risk_pct = user_cfg["risk_pct"]
        sl_pct   = levels.get("sl_pct") or 2.0

        ps = calculate_position_size(
            equity=equity,
            risk_pct=risk_pct,
            entry_price=ind.current_price,
            sl_pct=sl_pct,
            tier=tier_label,
        )

        # Show auto-calculation if user configured equity; else show hint
        user_has_config = not (equity == DEFAULT_EQUITY and risk_pct == DEFAULT_RISK_PCT)
        if user_has_config:
            sizing_block = format_position_block(ps) + "\n"
        else:
            static = "Full size (1–2% vốn)" if not is_tier_b else "Half size (0.5–1% vốn) — thận trọng"
            sizing_block = (
                f"💼 *Position size gợi ý:* _{static}_\n"
                f"   💡 _Dùng /setequity 10000 để tính chính xác theo vốn của bạn_\n"
            )

        # ── Build signal text based on tier ───────────────────────────
        entry_block = (
            f"📍 *Entry {levels['entry_type']}:*\n"
            f"   Market: `${levels['entry']:,.2f}`\n"
            f"   Limit tối ưu: `${levels['limit_entry']:,.2f}` _(Fib 0.618)_\n\n"
        )
        sl_block = f"🛡 *Stop Loss:*  `${levels['sl']:,.2f}` `(-{levels['sl_pct']}%)`\n"

        if is_tier_b:
            tp_block = (
                f"🎯 *TP1 (chốt 100%):* `${levels['tp1']:,.2f}` `(R:R 1:{levels['rr1']})`\n"
                f"⚠️ _Setup Tier B: Chốt 100% vị thế tại TP1. Không giữ lệnh chờ TP2._\n"
            )
        else:
            tp_block = (
                f"🎯 *TP1:* `${levels['tp1']:,.2f}` `(R:R 1:{levels['rr1']})`\n"
                f"🎯 *TP2:* `${levels['tp2']:,.2f}` `(R:R 1:{levels['rr2']})`\n"
                f"🎯 *TP3:* `${levels['tp3']:,.2f}` _(1:3 target)_\n"
            )

        # ── Regime label for display ───────────────────────────────────
        regime = ind.market_regime
        regime_labels = {
            "trending":     f"📈 TRENDING  (ADX {ind.adx:.1f})",
            "ranging":      f"↔️ RANGING   (ADX {ind.adx:.1f})",
            "transitional": f"⚡ NEUTRAL   (ADX {ind.adx:.1f})",
        }
        regime_label = regime_labels.get(regime, f"ADX {ind.adx:.1f}")

        # ── Confidence label + Session filter (P3) ──────────────────────
        session = ta_svc.get_current_session()
        if score >= 9:
            confidence_label = f"Rất cao ({score}/10)"
        elif score >= 7:
            confidence_label = f"Cao ({score}/10)"
        else:
            confidence_label = f"Trung bình ({score}/10)"

        # Low-liquidity session → downgrade confidence label + add warning
        session_warning = ""
        if not session["high_liquidity"]:
            confidence_label = confidence_label.replace("Rất cao", "Cao").replace("Cao", "Trung bình")
            session_warning = (
                f"\n⚠️ {session['emoji']} *{session['label']}* "
                f"— thanh khoản thấp, tăng nguy cơ fakeout\n"
            )

        # ── Risk reminder block (mandatory for Tier A) ─────────────────
        tier_a_warning = (
            "\n⚠️ _Tier A không miễn trừ rủi ro — luôn tôn trọng SL._\n"
            if not is_tier_b else ""
        )

        text = (
            f"🎯 *Signal: {symbol} — 4H*\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"Lệnh: {emoji} | Chất lượng: {signal_grade}\n"
            f"Độ tin cậy: `{confidence_label}`\n"
            f"📅 1W: {weekly_icon}`{weekly_trend.upper()}` | 1D: `{daily_trend.upper()}`\n"
            f"📊 Regime: `{regime_label}` | Phên: {session['emoji']}`{session['label']}`\n"
            + session_warning
            + tier_a_warning
            + sizing_block + "\n"
            + entry_block + sl_block + tp_block + "\n"
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
            adx=ind.adx,
            market_regime=ind.market_regime,
            volume_vs_avg=ind.volume_vs_avg,
            volume_trend=ind.volume_trend,
            daily_trend=daily_trend,
            last_candles=ind.last_candles,
            support_levels=ind.support_levels,
            resistance_levels=ind.resistance_levels,
        )

        prompt = build_signal_context(ctx, score, 10, reasons, side, levels)
        prompt += "\nReply in Vietnamese in 4-5 sentences."

        try:
            ai_response = await complete_with_fallback(prompt, max_tokens=350, fast=False)
            final_text = text + f"\n\n🤖 *AI Nhận Định:*\n_{ai_response}_" + DISCLAIMER
            await msg.edit_text(final_text, parse_mode="Markdown")
        except Exception as ai_err:
            logger.warning("AI signal failed: %s", ai_err)
            await msg.edit_text(text + "\n\n❌ _Lỗi kết nối AI._" + DISCLAIMER, parse_mode="Markdown")

        # ── Log signal to DB (non-blocking — don't fail if DB has error) ──────────
        try:
            rec = build_signal_record(
                symbol=symbol,
                side=side,
                score=score,
                tier="B" if is_tier_b else "A",
                daily_trend=daily_trend,
                market_regime=ind.market_regime,
                adx=ind.adx,
                levels=levels,
            )
            log_signal(rec)
        except Exception as db_err:
            logger.warning("Signal DB log failed (non-critical): %s", db_err)

    except httpx.HTTPStatusError as e:
        if e.response.status_code == 400:
            await msg.edit_text(f"❌ Mã giao dịch `{symbol}` không tồn tại trên sàn Binance (cả Spot và Futures).")
        else:
            await msg.edit_text(f"❌ Lỗi mạng khi lấy dữ liệu `{symbol}` từ Binance. Thử lại sau.")
    except Exception as e:
        logger.error("Signal error %s: %s", symbol, e, exc_info=True)
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


# ─── /stats — Win/Loss statistics ────────────────────────────────────────────

async def stats_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /stats [SYMBOL]
    Show win/loss statistics. Optionally filter by symbol.
    Examples: /stats  |  /stats BTC
    """
    if not update.effective_message:
        return

    args = context.args or []
    symbol = args[0].upper() + "USDT" if args else None
    if args and args[0].upper().endswith("USDT"):
        symbol = args[0].upper()

    msg = await update.effective_message.reply_text("📊 _Đang tính toán thống kê..._", parse_mode="Markdown")
    try:
        text = format_stats_message(symbol)
        await msg.edit_text(text, parse_mode="Markdown")
    except Exception as e:
        logger.error("Stats error: %s", e)
        await msg.edit_text("❌ Lỗi tải thống kê.")


# ─── /history — Recent signal log ────────────────────────────────────────────

async def history_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /history
    Show the last 8 signals with their outcomes.
    """
    if not update.effective_message:
        return

    msg = await update.effective_message.reply_text("📜 _Đang tải lịch sử..._", parse_mode="Markdown")
    try:
        text = format_recent_signals_message(limit=8)
        await msg.edit_text(text, parse_mode="Markdown")
    except Exception as e:
        logger.error("History error: %s", e)
        await msg.edit_text("❌ Lỗi tải lịch sử signal.")


# ─── /checkoutcomes — Manual trigger outcome check ───────────────────────────

async def checkoutcomes_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /checkoutcomes
    Manually trigger a check of all open signals against current prices.
    """
    if not update.effective_message:
        return

    msg = await update.effective_message.reply_text(
        "🔄 _Đang kiểm tra kết quả các signal đang mở..._", parse_mode="Markdown"
    )
    try:
        binance = context.bot_data.get("binance")
        if not binance:
            await msg.edit_text("❌ Không tìm thấy Binance client.")
            return

        resolved = await check_open_signals(binance)

        if not resolved:
            await msg.edit_text("✅ Không có signal nào đạt TP/SL. Tất cả vẫn đang mở.")
            return

        STATUS_ICON = {
            "tp1_hit": "✅ TP1 chạm",
            "tp2_hit": "✅ TP2 chạm",
            "sl_hit":  "❌ SL chạm",
            "expired": "⌛ Hết hạn",
        }
        lines = [f"🔔 *{len(resolved)} signal vừa được cập nhật:*\n"]
        for r in resolved:
            icon = STATUS_ICON.get(r["status"], r["status"])
            side_icon = "🟢" if r["side"] == "long" else "🔴"
            pnl = r["pnl_pct"]
            pnl_str = f"`{pnl:+.2f}%`" if pnl is not None else "—"
            lines.append(
                f"{side_icon} *{r['symbol']}* {r['side'].upper()} | {icon} | PnL: {pnl_str}\n"
                f"  Entry: `${r['entry']:,.2f}` → Outcome: `${r['outcome_price']:,.2f}`"
            )

        await msg.edit_text("\n".join(lines), parse_mode="Markdown")

    except Exception as e:
        logger.error("Checkoutcomes error: %s", e)
        await msg.edit_text("❌ Lỗi kiểm tra kết quả.")


# ─── /setequity — Configure account equity ───────────────────────────────────

async def setequity_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /setequity <amount>
    Set your total trading account equity in USDT.
    This enables automatic position size calculation on every signal.

    Examples:
      /setequity 1000     → $1,000 USDT
      /setequity 10000    → $10,000 USDT
    """
    if not update.effective_message or not update.effective_user:
        return

    args = context.args or []
    if not args:
        # Show current setting
        cfg = get_user_settings(update.effective_user.id)
        await update.effective_message.reply_text(
            f"💰 *Vốn hiện tại:* `${cfg['equity']:,.2f}` USDT\n"
            f"📊 *Risk/lệnh:* `{cfg['risk_pct']}%`\n\n"
            f"Dùng `/setequity <số tiền>` để thay đổi.\n"
            f"Ví dụ: `/setequity 10000`",
            parse_mode="Markdown"
        )
        return

    try:
        equity = float(args[0].replace(",", ""))
        if equity <= 0:
            raise ValueError("Equity must be positive")
        if equity > 10_000_000:
            raise ValueError("Equity too large (max 10,000,000)")

        from src.database.settings_repository import set_equity
        set_equity(update.effective_user.id, equity)

        cfg = get_user_settings(update.effective_user.id)
        # Show example calculation with BTC at ~65k
        example_sl = 2.0
        example_ps = calculate_position_size(equity, cfg["risk_pct"], 65000, example_sl, "A")
        await update.effective_message.reply_text(
            f"✅ *Vốn đã cập nhật: `${equity:,.2f}` USDT*\n\n"
            f"📊 *Ví dụ với BTC @ $65,000 (SL 2%):*\n"
            f"   Rủi ro {cfg['risk_pct']}% = `${example_ps.risk_amount_usdt:,.2f}` USDT\n"
            f"   Vào lệnh: `${example_ps.position_usdt:,.2f}` USDT\n"
            f"   Số lượng: `{example_ps.quantity:.6f}` BTC\n"
            f"   Đòn bẩy hiệu quả: `~{example_ps.effective_leverage:.1f}x`\n\n"
            f"_Signal tiếp theo sẽ tính toán tự động theo vốn này._",
            parse_mode="Markdown"
        )
    except ValueError as e:
        await update.effective_message.reply_text(
            f"❌ Số tiền không hợp lệ: `{args[0]}`\n"
            f"Ví dụ đúng: `/setequity 10000`",
            parse_mode="Markdown"
        )


# ─── /setrisk — Configure risk % per trade ───────────────────────────────────

async def setrisk_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /setrisk <percent>
    Set max % of equity to risk per trade (Tier A).
    Tier B signals automatically use half this value.

    Recommended: 0.5% – 2% per trade.
    Examples:
      /setrisk 1     → risk 1% per Tier A trade, 0.5% per Tier B
      /setrisk 0.5   → risk 0.5% per Tier A trade, 0.25% per Tier B
    """
    if not update.effective_message or not update.effective_user:
        return

    args = context.args or []
    if not args:
        cfg = get_user_settings(update.effective_user.id)
        await update.effective_message.reply_text(
            f"📊 *Risk/lệnh hiện tại:*\n"
            f"   Tier A: `{cfg['risk_pct']}%`\n"
            f"   Tier B: `{cfg['risk_pct'] / 2}%` (tự động 50%)\n\n"
            f"Dùng `/setrisk <phần trăm>` để thay đổi.\n"
            f"Khuyến nghị: 0.5% – 2%\n"
            f"Ví dụ: `/setrisk 1`",
            parse_mode="Markdown"
        )
        return

    try:
        risk_pct = float(args[0].replace("%", ""))
        if risk_pct <= 0 or risk_pct > 10:
            raise ValueError("Risk must be between 0.1% and 10%")

        from src.database.settings_repository import set_risk_pct
        set_risk_pct(update.effective_user.id, risk_pct)

        await update.effective_message.reply_text(
            f"✅ *Risk/lệnh đã cập nhật:*\n"
            f"   ⭐⭐⭐ Tier A: `{risk_pct}%` của vốn\n"
            f"   ⭐⭐ Tier B: `{risk_pct / 2}%` của vốn (tự động giảm 50%)\n\n"
            f"_Signal tiếp theo sẽ tính toán tự động theo mức risk này._",
            parse_mode="Markdown"
        )
    except ValueError:
        await update.effective_message.reply_text(
            f"❌ Phần trăm không hợp lệ: `{args[0]}`\n"
            f"Nhập số từ 0.1 đến 10. Ví dụ: `/setrisk 1`",
            parse_mode="Markdown"
        )


# ─── /possize — Manual position size calculator ──────────────────────────────

async def possize_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /possize <entry> <sl_price> [tier]
    Manually calculate position size for any entry/SL combination.

    Examples:
      /possize 65000 63000        → Tier A calculation
      /possize 65000 63000 B      → Tier B calculation (half risk)
      /possize 3200 3100          → ETH example
    """
    if not update.effective_message or not update.effective_user:
        return

    args = context.args or []
    if len(args) < 2:
        await update.effective_message.reply_text(
            "📐 *Tính Position Size thủ công*\n\n"
            "Cú pháp: `/possize <entry> <sl_price> [tier]`\n"
            "Ví dụ:\n"
            "  `/possize 65000 63000`     → Tier A\n"
            "  `/possize 65000 63000 B`   → Tier B\n\n"
            "_Vốn và Risk% lấy từ cài đặt của bạn (/setequity, /setrisk)_",
            parse_mode="Markdown"
        )
        return

    try:
        entry_price = float(args[0].replace(",", ""))
        sl_price    = float(args[1].replace(",", ""))
        tier        = args[2].upper() if len(args) > 2 else "A"
        if tier not in ("A", "B"):
            tier = "A"

        if entry_price <= 0 or sl_price <= 0:
            raise ValueError("Prices must be positive")

        sl_pct = abs(entry_price - sl_price) / entry_price * 100

        cfg = get_user_settings(update.effective_user.id)
        ps = calculate_position_size(
            equity=cfg["equity"],
            risk_pct=cfg["risk_pct"],
            entry_price=entry_price,
            sl_pct=sl_pct,
            tier=tier,
        )

        tier_icon = "⭐⭐⭐" if tier == "A" else "⭐⭐"
        await update.effective_message.reply_text(
            f"📐 *Tính Position Size*\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"Tier: {tier_icon} Tier {tier}\n"
            f"Entry: `${entry_price:,.2f}` | SL: `${sl_price:,.2f}` (`{sl_pct:.2f}%`)\n\n"
            + format_position_block(ps),
            parse_mode="Markdown"
        )
    except (ValueError, ZeroDivisionError) as e:
        await update.effective_message.reply_text(
            f"❌ Dữ liệu không hợp lệ. Ví dụ đúng:\n`/possize 65000 63000`",
            parse_mode="Markdown"
        )
