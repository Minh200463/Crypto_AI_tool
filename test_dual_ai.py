import asyncio
from src.ai.context_builder import MarketContext, build_signal_context, build_adversarial_context

ctx = MarketContext(
    symbol="BTCUSDT",
    timeframe="4h",
    price=50000,
    change_pct_24h=1.5,
    volume_24h=1000000000,
    rsi=60,
    macd_line=100,
    macd_signal=90,
    macd_histogram=10,
    macd_crossover="bullish",
    bb_upper=52000,
    bb_mid=50000,
    bb_lower=48000,
    ma20=49000,
    ma50=48000,
    ma200=45000,
    atr=1000,
    adx=30,
    market_regime="trending",
    volume_vs_avg=1.2,
    volume_trend="rising",
    daily_trend="uptrend",
    support_levels=[48000, 45000],
    resistance_levels=[52000, 55000],
)

levels = {
    "entry": 50000,
    "limit_entry": 49000,
    "entry_type": "LIMIT",
    "sl": 48000,
    "sl_pct": 4.0,
    "tp1": 52000,
    "rr1": 1.5,
    "tp2": 55000,
    "rr2": 2.5,
    "tp3": 60000
}

prompt_trader = build_signal_context(ctx, 8, 10, ["RSI > 50"], "long", levels)
prompt_risk = build_adversarial_context(ctx, "long", levels)

print("--- TRADER PROMPT ---")
print(prompt_trader)
print("\n--- RISK PROMPT ---")
print(prompt_risk)
