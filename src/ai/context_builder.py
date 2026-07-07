"""
Context Builder v2 — richer AI prompts with candle context, MTF trend, and volume analysis.
"""
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class MarketContext:
    """Structured market data ready to be inserted into a prompt."""
    symbol: str
    timeframe: str
    price: float
    change_pct_24h: float
    volume_24h: float
    # Technical indicators
    rsi: Optional[float] = None
    macd_line: Optional[float] = None
    macd_signal: Optional[float] = None
    macd_histogram: Optional[float] = None
    macd_crossover: Optional[str] = None
    bb_upper: Optional[float] = None
    bb_mid: Optional[float] = None
    bb_lower: Optional[float] = None
    ma20: Optional[float] = None
    ma50: Optional[float] = None
    ma200: Optional[float] = None
    atr: Optional[float] = None
    adx: Optional[float] = None                  # ADX(14) — trend strength
    market_regime: Optional[str] = None          # "trending" | "ranging" | "transitional"
    funding_rate: Optional[float] = None
    fear_greed_index: Optional[int] = None
    fear_greed_label: Optional[str] = None
    avg_volume_20: Optional[float] = None
    volume_vs_avg: Optional[float] = None
    volume_trend: Optional[str] = None          # "rising" | "falling" | "neutral"
    daily_trend: Optional[str] = None           # "uptrend" | "downtrend" | "sideways"
    last_candles: list[dict] = field(default_factory=list)  # [{o,h,l,c,v}]
    news_headlines: list[str] = field(default_factory=list)
    support_levels: list[float] = field(default_factory=list)
    resistance_levels: list[float] = field(default_factory=list)


def _candle_description(candle: dict) -> str:
    body_size = abs(candle["close"] - candle["open"])
    candle_range = candle["high"] - candle["low"]
    body_pct = body_size / candle_range * 100 if candle_range > 0 else 0
    direction = "🟢 Bullish" if candle["close"] > candle["open"] else "🔴 Bearish"
    strength = "strong" if body_pct >= 60 else "moderate" if body_pct >= 35 else "indecisive (doji)"
    return f"{direction} {strength} ({body_pct:.0f}% body)"


def build_analysis_context(ctx: MarketContext) -> str:
    """Format market data for /analyze command prompt — v2 with richer context."""
    lines = [
        f"=== {ctx.symbol} Technical Analysis ({ctx.timeframe}) ===",
        f"Price: ${ctx.price:,.2f} | 24h Change: {ctx.change_pct_24h:+.2f}%",
        f"Volume 24h: ${ctx.volume_24h:,.0f}",
    ]

    if ctx.daily_trend:
        lines.append(f"Daily (1D) Macro Trend: {ctx.daily_trend.upper()}")

    if ctx.adx is not None:
        regime_str = ctx.market_regime.upper() if ctx.market_regime else "UNKNOWN"
        lines.append(
            f"Market Regime: {regime_str} (ADX={ctx.adx:.1f}) — "
            + ("use trend-following indicators (MACD/MA)" if regime_str == "TRENDING" else
               "use mean-reversion indicators (BB/RSI)" if regime_str == "RANGING" else
               "mixed signals, apply standard scoring")
        )

    if ctx.rsi is not None:
        lines.append(f"RSI(14): {ctx.rsi:.1f}")

    if ctx.macd_line is not None:
        lines.append(
            f"MACD: line={ctx.macd_line:.4f}, signal={ctx.macd_signal:.4f}, "
            f"histogram={ctx.macd_histogram:.4f}, crossover={ctx.macd_crossover}"
        )

    if ctx.bb_upper is not None:
        bb_pos = "ABOVE upper" if ctx.price >= ctx.bb_upper else (
            "AT/BELOW lower" if ctx.price <= ctx.bb_lower else "inside bands"
        )
        lines.append(
            f"Bollinger Bands: upper={ctx.bb_upper:,.2f}, mid={ctx.bb_mid:,.2f}, "
            f"lower={ctx.bb_lower:,.2f} → Price is {bb_pos}"
        )

    if ctx.ma20 is not None:
        trend_vs_ma = (
            f"price {'above' if ctx.price > ctx.ma20 else 'below'} MA20, "
            f"{'above' if ctx.price > ctx.ma50 else 'below'} MA50, "
            f"{'above' if ctx.price > ctx.ma200 else 'below'} MA200"
        )
        lines.append(f"MA20={ctx.ma20:,.2f} | MA50={ctx.ma50:,.2f} | MA200={ctx.ma200:,.2f} ({trend_vs_ma})")

    if ctx.atr is not None:
        lines.append(f"ATR(14): {ctx.atr:.2f} (expected move per candle)")

    if ctx.volume_vs_avg is not None:
        lines.append(f"Volume: {ctx.volume_vs_avg:.1f}x 20-period avg | Trend: {ctx.volume_trend or 'n/a'}")

    if ctx.funding_rate is not None:
        lines.append(f"Funding Rate: {ctx.funding_rate:.4f}%")

    if ctx.fear_greed_index is not None:
        lines.append(f"Fear & Greed: {ctx.fear_greed_index} ({ctx.fear_greed_label})")

    if ctx.support_levels:
        levels = ", ".join(f"${v:,.2f}" for v in ctx.support_levels[:3])
        lines.append(f"Key Support levels: {levels}")

    if ctx.resistance_levels:
        levels = ", ".join(f"${v:,.2f}" for v in ctx.resistance_levels[:3])
        lines.append(f"Key Resistance levels: {levels}")

    # Last 3 candles narrative
    if ctx.last_candles:
        lines.append("\nRecent price action (last 3 candles):")
        for i, c in enumerate(ctx.last_candles, 1):
            lines.append(f"  [{i}] {_candle_description(c)} — close=${c['close']:,.2f}")

    return "\n".join(lines)


def build_signal_context(
    ctx: MarketContext,
    score: int,
    max_score: int,
    reasons: list[str],
    side: str,
    levels: dict,
) -> str:
    """Format data for /signal interpretation prompt — v2 with entry zone + scenario planning."""
    signal_strength = "STRONG" if score >= 8 else "MODERATE" if score >= 6 else "WEAK"

    lines = [
        f"=== Trade Signal Analysis: {ctx.symbol} ({ctx.timeframe}) ===",
        f"Signal: {side.upper()} | Confluence: {score}/{max_score} ({signal_strength})",
        f"Daily Macro Trend: {(ctx.daily_trend or 'unknown').upper()}",
        "",
        "Technical reasons triggered:",
        *[f"  • {r}" for r in reasons],
        "",
        f"Entry Zone: Market=${levels['entry']:,.2f} | Optimal Limit=${levels['limit_entry']:,.2f} ({levels['entry_type']})",
        f"Stop Loss: ${levels['sl']:,.2f} ({levels['sl_pct']}% from entry)",
        f"Take Profit 1: ${levels['tp1']:,.2f} | R:R = 1:{levels['rr1']}",
        f"Take Profit 2: ${levels['tp2']:,.2f} | R:R = 1:{levels['rr2']}",
        f"Take Profit 3 (1:3 target): ${levels['tp3']:,.2f}",
        "",
        build_analysis_context(ctx),
        "",
        "As a professional trader with 20+ years experience, provide a structured analysis:",
        "1. SCENARIO XÁC NHẬN: Điều kiện cụ thể nào (price level + volume) để setup này được xác nhận?",
        "   Ví dụ: 'Vào lệnh nếu giá đóng nến trên/dưới $X với volume > Y lần avg'",
        "2. SCENARIO VÔ HIỆU: Level nào khiến setup này hoàn toàn mất giá trị?",
        "   Ví dụ: 'Setup vô hiệu nếu giá phá $X'",
        "3. ENTRY TỐI ƯU: Entry hiện tại có phải đang chase giá không? Gợi ý entry tốt hơn nếu cần pullback.",
        "4. RỦI RO CHÍNH: Một câu về rủi ro lớn nhất của setup này ngay lúc này.",
        "",
        "Use precise price levels. Reply in Vietnamese. Keep under 6 sentences total.",
    ]
    return "\n".join(lines)



def build_morning_brief_context(
    market_data: list[MarketContext],
    top_news: list[str],
    watchlist_performance: dict[str, float],
) -> str:
    """Format data for daily morning brief prompt."""
    lines = ["=== Morning Market Brief ==="]
    for ctx in market_data[:5]:
        lines.append(f"{ctx.symbol}: ${ctx.price:,.2f} ({ctx.change_pct_24h:+.2f}%)")

    if market_data and market_data[0].fear_greed_index is not None:
        fg = market_data[0]
        lines.append(f"\nFear & Greed: {fg.fear_greed_index} ({fg.fear_greed_label})")

    if watchlist_performance:
        lines.append("\nYour watchlist performance:")
        for sym, pct in watchlist_performance.items():
            lines.append(f"  {sym}: {pct:+.2f}%")

    if top_news:
        lines.append("\nTop news (last 12h):")
        for i, headline in enumerate(top_news[:5], 1):
            lines.append(f"  {i}. {headline}")

    lines.append(
        "\nWrite a concise 150-200 word market brief based on this data. "
        "Highlight key trends, risks, and what to watch today."
    )
    return "\n".join(lines)
