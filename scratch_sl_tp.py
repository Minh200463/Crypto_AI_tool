def calculate_structure_sl(direction: str, entry: float, atr: float, swing_low: float, swing_high: float, liquidity_context: dict):
    structural_sl_warn = None
    if not liquidity_context:
        return None, structural_sl_warn

    pools = liquidity_context.get("liquidity_pools", {})
    if direction == "long":
        support_pools = pools.get("support_pools", [])
        # Find nearest pool below swing_low (or entry if swing_low is too close)
        pools_below = [p["price"] for p in support_pools if p["price"] < swing_low]
        nearest_pool = max(pools_below) if pools_below else swing_low
        structural_sl = min(swing_low, nearest_pool) - (atr * 0.25)
        
        sl_distance_atr = abs(entry - structural_sl) / atr
        if sl_distance_atr > 2.5:
            structural_sl_warn = "⚠️ SL cấu trúc xa (>2.5 ATR), rủi ro cao"
        elif sl_distance_atr < 0.5:
            structural_sl_warn = "⚠️ SL cấu trúc quá hẹp (<0.5 ATR), dễ bị Stop Hunt"
        return structural_sl, structural_sl_warn

    else:
        resistance_pools = pools.get("resistance_pools", [])
        pools_above = [p["price"] for p in resistance_pools if p["price"] > swing_high]
        nearest_pool = min(pools_above) if pools_above else swing_high
        structural_sl = max(swing_high, nearest_pool) + (atr * 0.25)

        sl_distance_atr = abs(entry - structural_sl) / atr
        if sl_distance_atr > 2.5:
            structural_sl_warn = "⚠️ SL cấu trúc xa (>2.5 ATR), rủi ro cao"
        elif sl_distance_atr < 0.5:
            structural_sl_warn = "⚠️ SL cấu trúc quá hẹp (<0.5 ATR), dễ bị Stop Hunt"
        return structural_sl, structural_sl_warn

def calculate_liquidity_aware_tp(direction: str, entry: float, sl: float, liquidity_context: dict):
    risk = abs(entry - sl)
    pools = liquidity_context.get("liquidity_pools", {}) if liquidity_context else {}
    
    tp1 = entry + risk * 1.5 if direction == "long" else entry - risk * 1.5

    if direction == "long":
        resistance_pools = pools.get("resistance_pools", [])
        pools_above = [p["price"] for p in resistance_pools if p["price"] > entry]
        next_pool = min(pools_above) if pools_above else None
        
        if next_pool:
            buffer = risk * 0.1
            tp_before_pool = next_pool - buffer
            tp2 = max(tp1, tp_before_pool)
        else:
            tp2 = entry + risk * 3
            
        tp3 = entry + risk * 5
    else:
        support_pools = pools.get("support_pools", [])
        pools_below = [p["price"] for p in support_pools if p["price"] < entry]
        next_pool = max(pools_below) if pools_below else None
        
        if next_pool:
            buffer = risk * 0.1
            tp_before_pool = next_pool + buffer
            tp2 = min(tp1, tp_before_pool)
        else:
            tp2 = entry - risk * 3
            
        tp3 = entry - risk * 5

    return tp1, tp2, tp3

print("OK")
