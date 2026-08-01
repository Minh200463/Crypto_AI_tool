"""
Signal Engine — logic lõi tạo trade signal (dùng chung cho /signal thủ công
và Auto-scan tự động).

Tách từ handlers.signal_handler ra để không bị trùng lặp code giữa 2 nơi gọi:
  1. Telegram command /signal  (user chủ động gõ)
  2. job_auto_scan_watchlist   (scheduler tự động, mode "full")

Trả về (text, was_logged) — text để gửi qua Telegram, was_logged để caller biết
có cần thông báo thêm gì không.
"""
import asyncio
import logging

from src.core.ta_service import TAService, SCORE_TIER_A, SCORE_THRESHOLD
from src.services.liquidity_service import get_liquidity_context
from src.core.position_sizer import calculate_position_size, format_position_block
from src.core.signal_tracker import build_signal_record, log_signal
from src.database.settings_repository import get_user_settings, DEFAULT_EQUITY, DEFAULT_RISK_PCT
from src.ai.context_builder import MarketContext, build_signal_context, build_adversarial_context
import asyncio
from src.ai.factory import complete_with_fallback

logger = logging.getLogger(__name__)

DISCLAIMER = "\n\n⚠️ _Tham khảo kỹ thuật — không phải tư vấn tài chính\\._"


def _normalize_symbol(s: str) -> str:
    s = s.upper().strip()
    return s if s.endswith("USDT") else f"{s}USDT"


class NoSignalResult:
    """Trả về khi không đủ điểm — caller tự quyết định có báo user hay im lặng."""
    def __init__(self, symbol: str, long_score: int, short_score: int,
                 daily_trend: str, weekly_trend: str):
        self.symbol = symbol
        self.long_score = long_score
        self.short_score = short_score
        self.daily_trend = daily_trend
        self.weekly_trend = weekly_trend


async def generate_full_signal(
    symbol: str,
    telegram_user_id: int,
    binance,
    call_ai: bool = True,
    log_to_db: bool = True,
) -> str | NoSignalResult:
    """
    Chạy toàn bộ pipeline: fetch candles → MTF trend → scoring → levels →
    position sizing → (optional) AI interpretation → (optional) log DB.

    call_ai / log_to_db: cho phép caller tắt AI hoặc tắt log DB nếu cần
    (VD: auto-scan mode "alert" muốn tiết kiệm chi phí AI nhưng vẫn muốn
    thấy format đầy đủ — dù hiện tại "alert" mode không dùng hàm này).

    Returns:
      - str: Markdown text sẵn sàng gửi Telegram, nếu có signal đạt ngưỡng.
      - NoSignalResult: nếu điểm không đạt SCORE_THRESHOLD — caller tự quyết
        định có gửi thông báo "không có setup" hay im lặng.

    Raises: Exception nếu fetch data lỗi — caller tự try/except.
    """
    symbol = symbol.upper().strip()
    ta_svc = TAService()

    candles_4h, candles_1d, candles_1w, oi_data = await asyncio.gather(
        binance.get_klines(symbol, interval="4h", limit=200),
        binance.get_klines(symbol, interval="1d", limit=200),
        binance.get_klines(symbol, interval="1w", limit=100),
        binance.get_open_interest(symbol),
        return_exceptions=True,
    )

    if isinstance(candles_4h, Exception) or len(candles_4h) < 50:
        raise ValueError(f"Không đủ dữ liệu 4H cho {symbol}")

    ind = ta_svc.compute_indicators(_normalize_symbol(symbol), "4h", candles_4h)
    if oi_data and not isinstance(oi_data, Exception):
        ind.oi_change_pct = oi_data.get("oi_change_pct")

    # Fetch Liquidity Context
    try:
        current_price = float(candles_4h[-1][4])  # close price of last 4h candle
        liquidity_ctx = await get_liquidity_context(binance, _normalize_symbol(symbol), candles_4h, current_price)
        ind.liquidity_context = liquidity_ctx
    except Exception as e:
        logger.error("Failed to fetch liquidity context for %s: %s", symbol, e)
        ind.liquidity_context = None

    daily_trend = (
        ta_svc.get_daily_trend(candles_1d)
        if not isinstance(candles_1d, Exception) and len(candles_1d) >= 50
        else "sideways"
    )
    weekly_trend = (
        ta_svc.get_weekly_trend(candles_1w)
        if not isinstance(candles_1w, Exception) and len(candles_1w) >= 50
        else "sideways"
    )

    long_score, long_reasons, long_breakdown = ta_svc.score_long_setup(ind, daily_trend, weekly_trend)
    short_score, short_reasons, short_breakdown = ta_svc.score_short_setup(ind, daily_trend, weekly_trend)

    if long_score >= SCORE_THRESHOLD:
        side, score, reasons, breakdown, emoji = "long", long_score, long_reasons, long_breakdown, "🟢 LONG"
    elif short_score >= SCORE_THRESHOLD:
        side, score, reasons, breakdown, emoji = "short", short_score, short_reasons, short_breakdown, "🔴 SHORT"
    else:
        return NoSignalResult(symbol, long_score, short_score, daily_trend, weekly_trend)

    is_tier_b = score < SCORE_TIER_A
    tier_label = "B" if is_tier_b else "A"
    signal_grade = "⭐⭐⭐ MẠNH" if not is_tier_b else "⭐⭐ KHÁ"

    levels = ta_svc.calculate_trade_levels(side, ind.current_price, ind, is_tier_b=is_tier_b)

    user_cfg = get_user_settings(telegram_user_id)
    equity, risk_pct = user_cfg["equity"], user_cfg["risk_pct"]
    sl_pct = levels.get("sl_pct") or 2.0

    import json
    dca_plan = json.loads(levels.get("dca_plan", "[]"))
    if dca_plan:
        weighted_avg_entry = sum(d["price"] * (d["weight"] / 100.0) for d in dca_plan)
    else:
        weighted_avg_entry = ind.current_price

    ps = calculate_position_size(
        equity=equity, risk_pct=risk_pct,
        entry_price=weighted_avg_entry, sl_pct=sl_pct, tier=tier_label,
    )
    
    from src.services.liquidity_service import calculate_slippage
    depth_data = ind.liquidity_context.get("depth", {}) if ind.liquidity_context else {}
    slippage_pct = calculate_slippage(depth_data, ps.position_size_usd, side, ind.current_price)
    
    if slippage_pct > 0.5:
        slip_warning = f"\n   ⚠️ *Cảnh báo trượt giá:* Ước tính trượt ~{slippage_pct}% (Volume quá lớn so với Order Book)"
    elif slippage_pct > 0:
        slip_warning = f"\n   ℹ️ *Trượt giá dự kiến:* ~{slippage_pct}%"
    else:
        slip_warning = ""

    user_has_config = not (equity == DEFAULT_EQUITY and risk_pct == DEFAULT_RISK_PCT)
    if user_has_config:
        sizing_block = format_position_block(ps) + slip_warning + "\n"
    else:
        static = "Full size (1–2% vốn)" if not is_tier_b else "Half size (0.5–1% vốn) — thận trọng"
        sizing_block = (
            f"💼 *Position size gợi ý:* _{static}_\n"
            f"   💡 _Dùng /setequity 10000 để tính chính xác theo vốn của bạn_\n"
        )

    dca_str = "\n".join([f"   Lệnh {i+1} ({d['weight']}%): `${d['price']:,.2f}`" for i, d in enumerate(dca_plan)])
    
    entry_block = (
        f"📍 *Vùng Entry {levels['entry_type']}:* `${levels['entry_zone_top']:,.2f}` - `${levels['entry_zone_bottom']:,.2f}`\n"
        f"   (Giá Market hiện tại: `${levels['entry']:,.2f}`)\n"
        f"📉 *Chiến lược DCA (Rải lệnh):*\n{dca_str}\n\n"
        f"⏳ *Trạng thái:* Đang chờ xác nhận LTF (1H) tại vùng Entry...\n\n"
    )
    sl_warning_str = f"\n   {levels['sl_warning']}" if levels.get("sl_warning") else ""
    sl_block = f"🛡 *Stop Loss (Structural):*  `${levels['sl']:,.2f}` `(-{levels['sl_pct']}%)`{sl_warning_str}\n"

    if is_tier_b:
        tp_block = (
            f"🎯 *TP1 (chốt 100%):* `${levels['tp1']:,.2f}` `(R:R 1:{levels['rr1']})`\n"
            f"⚠️ _Setup Tier B: Chốt 100% vị thế tại TP1. Không giữ lệnh chờ TP2._\n"
        )
    else:
        tp_block = (
            f"🎯 *TP1 (Thanh khoản gần nhất):* `${levels['tp1']:,.2f}` `(R:R 1:{levels['rr1']})`\n"
            f"   → _Sau TP1: dời SL về `${levels['entry']:,.2f}` (breakeven) — risk\\-free_\n"
            f"🎯 *TP2 (Trước Liquidity Pool):* `${levels['tp2']:,.2f}` `(R:R 1:{levels['rr2']})`\n"
            f"🎯 *TP3 (Gồng lời tối đa):* `${levels['tp3']:,.2f}` _(1:5 target)_\n"
        )

    regime = ind.market_regime
    regime_labels = {
        "trending":     f"📈 TRENDING  (ADX {ind.adx:.1f})",
        "ranging":      f"↔️ RANGING   (ADX {ind.adx:.1f})",
        "transitional": f"⚡ NEUTRAL   (ADX {ind.adx:.1f})",
    }
    regime_label = regime_labels.get(regime, f"ADX {ind.adx:.1f}")

    session = ta_svc.get_current_session()
    if score >= 9:
        confidence_label = f"Rất cao ({score}/10)"
    elif score >= 7:
        confidence_label = f"Cao ({score}/10)"
    else:
        confidence_label = f"Trung bình ({score}/10)"

    session_warning = ""
    if not session["high_liquidity"]:
        session_warning = (
            f"\n⚠️ {session['emoji']} *{session['label']}* "
            f"— thanh khoản thấp, tăng nguy cơ fakeout\n"
        )

    tier_a_warning = (
        "\n⚠️ _Tier A không miễn trừ rủi ro — luôn tôn trọng SL._\n"
        if not is_tier_b else ""
    )

    weekly_icons = {"uptrend": "📈", "downtrend": "📉", "sideways": "↔️"}
    weekly_icon = weekly_icons.get(weekly_trend, "↔️")

    from src.database.signal_repository import get_open_signals
    from src.core.risk_engine import check_portfolio_risk
    
    open_signals = get_open_signals()
    risk_ok, risk_msg = check_portfolio_risk(
        new_signal_symbol=symbol,
        new_signal_side=side,
        open_signals=open_signals,
        equity=equity,
        user_risk_pct=risk_pct
    )
    
    risk_block = ""
    if not risk_ok:
        risk_block = f"\n\n🛑 *[BLOCKED BY RISK MANAGER]*\n⚠️ {risk_msg}\n_Bạn nên cân nhắc KHÔNG vào thêm lệnh này để bảo vệ vốn._"
        
    text = (
        f"🎯 *Signal: {symbol} — 4H*\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"Lệnh: {emoji} | Chất lượng: {signal_grade}\n"
        f"Độ tin cậy: `{confidence_label}`\n"
        f"📅 1W: {weekly_icon}`{weekly_trend.upper()}` | 1D: `{daily_trend.upper()}`\n"
        f"📊 Regime: `{regime_label}` | Phiên: {session['emoji']}`{session['label']}`\n"
        + session_warning
        + tier_a_warning
        + sizing_block + "\n"
        + entry_block + sl_block + tp_block + "\n"
        f"🔍 *Tín hiệu kỹ thuật ({score}/10):*\n" +
        "\n".join([f"• {r}" for r in reasons])
        + risk_block
    )

    if call_ai:
        try:
            ticker = await binance.get_ticker(symbol)
            ctx = MarketContext(
                symbol=ind.symbol, timeframe="4h", price=ind.current_price,
                change_pct_24h=ticker["change_pct"], volume_24h=ticker["volume_usdt"],
                rsi=ind.rsi, macd_line=ind.macd_line, macd_signal=ind.macd_signal,
                macd_histogram=ind.macd_histogram, macd_crossover=ind.macd_crossover,
                bb_upper=ind.bb_upper, bb_mid=ind.bb_mid, bb_lower=ind.bb_lower,
                ma20=ind.ma20, ma50=ind.ma50, ma200=ind.ma200, atr=ind.atr,
                adx=ind.adx, market_regime=ind.market_regime,
                volume_vs_avg=ind.volume_vs_avg, volume_trend=ind.volume_trend,
                daily_trend=daily_trend, last_candles=ind.last_candles,
                support_levels=ind.support_levels, resistance_levels=ind.resistance_levels,
            )
            prompt_trader = build_signal_context(ctx, score, 10, reasons, side, levels)
            prompt_risk = build_adversarial_context(ctx, side, levels)
            
            # Execute both AI prompts concurrently
            trader_resp, risk_resp = await asyncio.gather(
                complete_with_fallback(prompt_trader, max_tokens=600, fast=False),
                complete_with_fallback(prompt_risk, max_tokens=600, fast=False)
            )
            
            text += f"\n\n🤖 *Góc nhìn Trader (Setup):*\n_{trader_resp}_"
            text += f"\n\n🛡 *Góc nhìn Risk Manager (Phản biện):*\n_{risk_resp}_" + DISCLAIMER
        except Exception as ai_err:
            logger.warning("AI signal failed for %s: %s", symbol, ai_err)
            text += "\n\n❌ _Lỗi kết nối AI._" + DISCLAIMER
    else:
        text += DISCLAIMER

    if log_to_db:
        try:
            l_score = ind.liquidity_context["score"] if ind.liquidity_context else 0.0
            rec = build_signal_record(
                symbol=symbol, side=side, score=score,
                tier="B" if is_tier_b else "A",
                daily_trend=daily_trend, market_regime=ind.market_regime,
                adx=ind.adx, levels=levels,
                liquidity_score=l_score,
                score_breakdown=breakdown,
            )
            log_signal(rec)
        except Exception as db_err:
            logger.warning("Signal DB log failed (non-critical) for %s: %s", symbol, db_err)

    return text
