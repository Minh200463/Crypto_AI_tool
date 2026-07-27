import json

def calculate_dca_plan(side: str, entry: float, last_candles: list, atr: float, is_tier_b: bool, liquidity_context: dict = None):
    # fallback if not enough candles
    if len(last_candles) < 20:
        swing_high = entry + atr * 2
        swing_low = entry - atr * 2
    else:
        recent = last_candles[-20:]
        swing_high = max(float(c["high"]) for c in recent)
        swing_low = min(float(c["low"]) for c in recent)

    swing_range = swing_high - swing_low
    if swing_range <= 0:
        swing_range = atr * 2
        swing_high = entry + atr
        swing_low = entry - atr

    if side == "long":
        # Retrace from swing high down
        fib_0_5 = swing_high - swing_range * 0.5
        fib_0_618 = swing_high - swing_range * 0.618
        fib_0_786 = swing_high - swing_range * 0.786
        
        entry_top = min(entry, fib_0_5) if not is_tier_b else min(entry, fib_0_618)
        entry_bottom = min(entry, fib_0_786)

    else:
        # Retrace from swing low up
        fib_0_5 = swing_low + swing_range * 0.5
        fib_0_618 = swing_low + swing_range * 0.618
        fib_0_786 = swing_low + swing_range * 0.786
        
        entry_top = max(entry, fib_0_5) if not is_tier_b else max(entry, fib_0_618)
        entry_bottom = max(entry, fib_0_786)

    # Intersection with HVN (optional advanced logic, for now simple fib zone)
    # Just record the DCA plan based on tier
    dca = []
    if not is_tier_b:
        dca = [
            {"price": round(fib_0_5, 4), "weight": 40},
            {"price": round(fib_0_618, 4), "weight": 35},
            {"price": round(fib_0_786, 4), "weight": 25}
        ]
    else:
        dca = [
            {"price": round(fib_0_618, 4), "weight": 50},
            {"price": round(fib_0_786, 4), "weight": 50}
        ]

    # ensure limits don't exceed current price backwards
    for level in dca:
        if side == "long" and level["price"] > entry:
            level["price"] = round(entry, 4)
        if side == "short" and level["price"] < entry:
            level["price"] = round(entry, 4)

    return entry_top, entry_bottom, json.dumps(dca)

print(calculate_dca_plan("long", 100, [{"high": 110, "low": 90}]*20, 2, False))
