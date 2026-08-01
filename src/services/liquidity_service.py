import logging
import numpy as np
from typing import Any

logger = logging.getLogger(__name__)

async def analyze_order_book_depth(binance_client, symbol: str, current_price: float, range_pct: float = 0.5) -> dict[str, Any]:
    """
    Phân tích độ dày sổ lệnh trong khoảng ±range_pct% quanh giá hiện tại.
    Trả về: liquidity walls (vùng có volume gom lớn bất thường), bid/ask imbalance ratio.
    """
    try:
        depth = await binance_client.get_order_book(symbol=symbol, limit=500)
    except Exception as e:
        logger.warning("Could not fetch order book for %s: %s", symbol, e)
        return {"bid_ask_imbalance": 0.5, "liquidity_walls": [], "raw_bids": [], "raw_asks": []}

    bids = [(float(p), float(q)) for p, q in depth.get("bids", [])]
    asks = [(float(p), float(q)) for p, q in depth.get("asks", [])]

    price_range = current_price * (range_pct / 100)
    bids_in_range = [(p, q) for p, q in bids if current_price - p <= price_range]
    asks_in_range = [(p, q) for p, q in asks if p - current_price <= price_range]

    bid_volume = sum(q for _, q in bids_in_range)
    ask_volume = sum(q for _, q in asks_in_range)
    total_volume = bid_volume + ask_volume
    imbalance = bid_volume / total_volume if total_volume > 0 else 0.5

    # Phát hiện "wall": 1 mức giá có volume > 3x trung bình các mức lân cận
    avg_bid_size = bid_volume / max(len(bids_in_range), 1)
    avg_ask_size = ask_volume / max(len(asks_in_range), 1)
    
    bid_walls = [{"price": p, "vol": q, "type": "bid"} for p, q in bids_in_range if q > avg_bid_size * 3]
    ask_walls = [{"price": p, "vol": q, "type": "ask"} for p, q in asks_in_range if q > avg_ask_size * 3]

    return {
        "bid_ask_imbalance": round(imbalance, 3),  # >0.6 = áp lực mua chiếm ưu thế gần giá
        "liquidity_walls": bid_walls + ask_walls,
        "raw_bids": bids,
        "raw_asks": asks
    }

def calculate_slippage(depth_data: dict, position_usdt: float, side: str, current_price: float) -> float:
    """
    Tính ước lượng slippage (%) khi khớp lệnh market dựa vào Order Book.
    """
    if not position_usdt or position_usdt <= 0:
        return 0.0
        
    orders = depth_data.get("raw_asks", []) if side.lower() == "long" else depth_data.get("raw_bids", [])
    if not orders:
        return 0.0
        
    remaining_usdt = position_usdt
    total_cost_usdt = 0.0
    total_qty = 0.0
    
    for p, q in orders:
        level_usdt = p * q
        if remaining_usdt <= level_usdt:
            # Khớp hết phần còn lại ở mức giá này
            qty = remaining_usdt / p
            total_qty += qty
            total_cost_usdt += remaining_usdt
            remaining_usdt = 0
            break
        else:
            # Khớp toàn bộ mức giá này và đi tiếp
            total_qty += q
            total_cost_usdt += level_usdt
            remaining_usdt -= level_usdt
            
    if total_qty == 0:
        return 0.0
        
    avg_price = total_cost_usdt / total_qty
    slippage_pct = abs(avg_price - current_price) / current_price * 100.0
    return round(slippage_pct, 4)

def compute_volume_profile(klines: list[list], num_bins: int = 50) -> dict[str, Any]:
    """
    Tính Volume Profile từ N nến gần nhất (khuyến nghị: 200 nến 4H ~ 33 ngày).
    HVN (High Volume Node) = vùng giá có volume tích lũy cao -> support/resistance mạnh, đủ thanh khoản để đặt limit order.
    LVN (Low Volume Node) = vùng giá bị "nhảy qua" nhanh -> KHÔNG nên đặt entry ở đây vì dễ trượt giá.
    """
    if not klines:
        return {"poc": 0, "hvn_zones": [], "lvn_zones": []}
        
    # kline format: [open_time, open, high, low, close, volume, ...]
    prices = np.array([(float(k[2]) + float(k[3])) / 2 for k in klines])  # (high+low)/2
    volumes = np.array([float(k[5]) for k in klines])

    price_min, price_max = prices.min(), prices.max()
    if price_min == price_max:
        return {"poc": price_min, "hvn_zones": [], "lvn_zones": []}
        
    bins = np.linspace(price_min, price_max, num_bins + 1)
    bin_volumes = np.zeros(num_bins)

    for p, v in zip(prices, volumes):
        idx = min(int((p - price_min) / (price_max - price_min) * num_bins), num_bins - 1)
        bin_volumes[idx] += v

    poc_idx = int(np.argmax(bin_volumes))  # Point of Control - mức giá có volume cao nhất
    poc_price = float((bins[poc_idx] + bins[poc_idx + 1]) / 2)

    threshold_hvn = np.percentile(bin_volumes, 70)
    threshold_lvn = np.percentile(bin_volumes, 20)

    hvn_zones = [{"bottom": float(bins[i]), "top": float(bins[i+1])} for i in range(num_bins) if bin_volumes[i] >= threshold_hvn]
    lvn_zones = [{"bottom": float(bins[i]), "top": float(bins[i+1])} for i in range(num_bins) if bin_volumes[i] <= threshold_lvn]

    return {"poc": poc_price, "hvn_zones": hvn_zones, "lvn_zones": lvn_zones}

async def analyze_funding_and_oi(binance_client, symbol: str) -> dict[str, Any]:
    funding = await binance_client.get_funding_rate(symbol)
    oi_data = await binance_client.get_open_interest(symbol)
    
    funding_rate = (funding * 100) if funding is not None else 0.0
    oi_change_pct = oi_data["oi_change_pct"] if oi_data else 0.0
    
    warnings = []
    if abs(funding_rate) > 0.05:  # >0.05%/8h là khá cực đoan
        warnings.append(f"⚠️ Funding rate cực đoan ({funding_rate:.3f}%) — rủi ro squeeze")

    # Phân loại regime theo OI và giá: Tạm thời lấy trend giá từ outside logic hoặc 
    # mặc định oi_change_pct lớn là có trend mới.
    regime = "neutral"
    if oi_change_pct > 5.0:
        regime = "high_participation"
    elif oi_change_pct < -5.0:
        regime = "liquidation"

    return {
        "funding_rate_pct": round(funding_rate, 4),
        "oi_change_pct": round(oi_change_pct, 2),
        "regime": regime,
        "warnings": warnings,
    }

def cluster_equal_levels(levels: list[float], tolerance_pct: float) -> list[float]:
    if not levels:
        return []
    sorted_levels = sorted(levels)
    pools = []
    current_pool = [sorted_levels[0]]
    for level in sorted_levels[1:]:
        if (level - current_pool[0]) / current_pool[0] * 100 <= tolerance_pct:
            current_pool.append(level)
        else:
            if len(current_pool) >= 3:  # Cần ít nhất 3 điểm chạm để coi là pool thanh khoản lớn
                pools.append(sum(current_pool)/len(current_pool))
            current_pool = [level]
    if len(current_pool) >= 3:
        pools.append(sum(current_pool)/len(current_pool))
    return [float(p) for p in pools]

def detect_liquidity_pools(klines: list[list], lookback: int = 100, k: float = 0.3) -> dict[str, list[float]]:
    """
    Tìm các vùng equal highs/lows - nơi nhiều trader đặt SL cùng 1 chỗ.
    """
    if len(klines) < lookback:
        lookback = len(klines)
    if lookback == 0:
        return {"resistance_pools": [], "support_pools": []}
        
    recent_klines = klines[-lookback:]
    highs = [float(candle[2]) for candle in recent_klines]
    lows = [float(candle[3]) for candle in recent_klines]
    
    # Calculate ATR proxy for tolerance
    import pandas as pd
    df = pd.DataFrame(recent_klines, columns=["open_time", "open", "high", "low", "close", "volume", "close_time", "quote_volume", "count", "taker_buy_vol", "taker_buy_quote", "ignore"])
    for col in ["high", "low", "close"]:
        df[col] = df[col].astype(float)
    df["tr0"] = abs(df["high"] - df["low"])
    df["tr1"] = abs(df["high"] - df["close"].shift())
    df["tr2"] = abs(df["low"] - df["close"].shift())
    tr = df[["tr0", "tr1", "tr2"]].max(axis=1)
    atr = tr.rolling(14).mean().iloc[-1]
    current_price = float(df["close"].iloc[-1])
    atr_pct = (atr / current_price) * 100 if current_price > 0 else 0.15
    tolerance_pct = k * atr_pct

    pools_high = cluster_equal_levels(highs, tolerance_pct)
    pools_low = cluster_equal_levels(lows, tolerance_pct)

    return {"resistance_pools": pools_high, "support_pools": pools_low}

async def get_liquidity_context(binance_client, symbol: str, klines: list[list], current_price: float) -> dict[str, Any]:
    """
    Tổng hợp toàn bộ bối cảnh thanh khoản cho một symbol.
    """
    depth = await analyze_order_book_depth(binance_client, symbol, current_price)
    vp = compute_volume_profile(klines)
    funding_oi = await analyze_funding_and_oi(binance_client, symbol)
    pools = detect_liquidity_pools(klines)
    
    warnings = []
    warnings.extend(funding_oi.get("warnings", []))
    
    # Tính điểm liquidity_score (0-10)
    score = 5.0
    if depth["bid_ask_imbalance"] > 0.6:
        score += 1
    elif depth["bid_ask_imbalance"] < 0.4:
        score -= 1
        
    if funding_oi["oi_change_pct"] > 3.0:
        score += 1
    
    score = max(0.0, min(10.0, score))

    return {
        "score": score,
        "warnings": warnings,
        "depth": depth,
        "volume_profile": vp,
        "funding_oi": funding_oi,
        "liquidity_pools": pools
    }
