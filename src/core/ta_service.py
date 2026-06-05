"""
Technical Analysis Service — upgraded v2.
Improvements:
  1. Multi-Timeframe (MTF) trend filter
  2. Weighted confluence scoring (10-point scale, threshold 6)
  3. Entry Zone (limit vs market entry)
  4. Candle confirmation, volume trend, swing proximity checks
"""
import logging
from dataclasses import dataclass, field

import pandas as pd
from scipy.signal import find_peaks  # type: ignore

logger = logging.getLogger(__name__)


@dataclass
class IndicatorResult:
    """Structured result of all computed indicators."""
    symbol: str
    timeframe: str
    current_price: float
    volume: float
    avg_volume_20: float

    # Trend
    ma20: float
    ma50: float
    ma200: float

    # Momentum
    rsi: float
    macd_line: float
    macd_signal: float
    macd_histogram: float
    macd_crossover: str | None  # "bullish" | "bearish" | None

    # Volatility
    bb_upper: float
    bb_mid: float
    bb_lower: float
    atr: float

    # Swing levels
    support_levels: list[float] = field(default_factory=list)
    resistance_levels: list[float] = field(default_factory=list)

    # Candle context (last 3 candles)
    last_candles: list[dict] = field(default_factory=list)  # [{o,h,l,c,v}]
    volume_trend: str = "neutral"  # "rising" | "falling" | "neutral"

    @property
    def rsi_label(self) -> str:
        if self.rsi >= 70:
            return "Overbought 🔴"
        if self.rsi <= 30:
            return "Oversold 🟢"
        if self.rsi >= 60:
            return "Bullish"
        if self.rsi <= 40:
            return "Bearish"
        return "Neutral"

    @property
    def trend_label(self) -> str:
        if self.ma20 > self.ma50 > self.ma200:
            return "📈 Strong Uptrend"
        if self.ma20 < self.ma50 < self.ma200:
            return "📉 Strong Downtrend"
        if self.current_price > self.ma200:
            return "↗️ Above MA200"
        return "↘️ Below MA200"

    @property
    def bb_position(self) -> str:
        if self.current_price >= self.bb_upper:
            return "Above Upper 🔴"
        if self.current_price <= self.bb_lower:
            return "At Lower 🟢"
        if self.current_price >= self.bb_mid:
            return "Upper Half"
        return "Lower Half"

    @property
    def volume_vs_avg(self) -> float:
        if self.avg_volume_20 == 0:
            return 1.0
        return self.volume / self.avg_volume_20

    @property
    def nearest_support(self) -> float | None:
        supports = [s for s in self.support_levels if s < self.current_price]
        return max(supports) if supports else None

    @property
    def nearest_resistance(self) -> float | None:
        resistances = [r for r in self.resistance_levels if r > self.current_price]
        return min(resistances) if resistances else None

    @property
    def last_candle_bullish(self) -> bool:
        """True if the last closed candle is bullish (close > open)."""
        if not self.last_candles:
            return False
        c = self.last_candles[-1]
        return c["close"] > c["open"]

    @property
    def last_candle_bearish(self) -> bool:
        if not self.last_candles:
            return False
        c = self.last_candles[-1]
        return c["close"] < c["open"]

    @property
    def candle_body_pct(self) -> float:
        """Size of last candle body as % of its range. 0-100."""
        if not self.last_candles:
            return 0.0
        c = self.last_candles[-1]
        rng = c["high"] - c["low"]
        if rng == 0:
            return 0.0
        return abs(c["close"] - c["open"]) / rng * 100


def _parse_candles(raw_candles: list[list]) -> pd.DataFrame:
    """Convert raw Binance klines list to typed DataFrame."""
    df = pd.DataFrame(
        raw_candles,
        columns=[
            "timestamp", "open", "high", "low", "close", "volume",
            "close_time", "quote_volume", "trades",
            "taker_buy_base", "taker_buy_quote", "ignore",
        ],
    )
    for col in ["open", "high", "low", "close", "volume", "quote_volume"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


# ── Signal quality tiers ─────────────────────────────────────────────────────
SCORE_TIER_A = 8   # Strong signal — full position size
SCORE_TIER_B = 6   # Moderate signal — half position size
SCORE_THRESHOLD = SCORE_TIER_B  # Minimum to fire a signal


class TAService:
    """
    Computes all technical indicators from raw OHLCV candle data.
    Uses 'ta' library — compatible with numpy 2.x / Python 3.13.
    """

    def compute_indicators(
        self,
        symbol: str,
        timeframe: str,
        raw_candles: list[list],
    ) -> IndicatorResult:
        """
        Full indicator computation from 200 OHLCV candles.
        Returns IndicatorResult with all values populated.
        """
        import ta  # local import — avoid slow startup

        df = _parse_candles(raw_candles)
        close = df["close"]
        high = df["high"]
        low = df["low"]
        volume = df["volume"]

        # ── RSI ──────────────────────────────────────────────────────────
        rsi_ind = ta.momentum.RSIIndicator(close=close, window=14)
        rsi_val = float(rsi_ind.rsi().iloc[-1])

        # ── MACD ─────────────────────────────────────────────────────────
        macd_ind = ta.trend.MACD(
            close=close, window_slow=26, window_fast=12, window_sign=9
        )
        macd_line = float(macd_ind.macd().iloc[-1])
        macd_signal = float(macd_ind.macd_signal().iloc[-1])
        macd_hist = float(macd_ind.macd_diff().iloc[-1])
        prev_macd_hist = float(macd_ind.macd_diff().iloc[-2])

        if prev_macd_hist < 0 and macd_hist > 0:
            crossover = "bullish"
        elif prev_macd_hist > 0 and macd_hist < 0:
            crossover = "bearish"
        else:
            crossover = None

        # ── Bollinger Bands ───────────────────────────────────────────────
        bb = ta.volatility.BollingerBands(close=close, window=20, window_dev=2)
        bb_upper = float(bb.bollinger_hband().iloc[-1])
        bb_mid = float(bb.bollinger_mavg().iloc[-1])
        bb_lower = float(bb.bollinger_lband().iloc[-1])

        # ── Moving Averages ───────────────────────────────────────────────
        ma20 = float(ta.trend.SMAIndicator(close=close, window=20).sma_indicator().iloc[-1])
        ma50 = float(ta.trend.SMAIndicator(close=close, window=50).sma_indicator().iloc[-1])
        ma200 = float(ta.trend.SMAIndicator(close=close, window=200).sma_indicator().iloc[-1])

        # ── ATR ───────────────────────────────────────────────────────────
        atr = float(
            ta.volatility.AverageTrueRange(
                high=high, low=low, close=close, window=14
            ).average_true_range().iloc[-1]
        )

        # ── Volume ───────────────────────────────────────────────────────
        avg_vol_20 = float(volume.iloc[-20:].mean())
        current_vol = float(volume.iloc[-1])

        # ── Volume trend (last 3 vs prior 3 candles) ─────────────────────
        vol_last3 = float(volume.iloc[-4:-1].mean())
        vol_prior3 = float(volume.iloc[-7:-4].mean())
        if vol_prior3 > 0:
            vol_trend = "rising" if vol_last3 > vol_prior3 * 1.1 else (
                "falling" if vol_last3 < vol_prior3 * 0.9 else "neutral"
            )
        else:
            vol_trend = "neutral"

        # ── Last 3 candles context ─────────────────────────────────────
        last_candles = []
        for i in [-3, -2, -1]:
            last_candles.append({
                "open": float(df["open"].iloc[i]),
                "high": float(high.iloc[i]),
                "low": float(low.iloc[i]),
                "close": float(close.iloc[i]),
                "volume": float(volume.iloc[i]),
            })

        # ── Swing Levels (support / resistance) ──────────────────────────
        support_levels, resistance_levels = self._detect_swing_levels(df)

        return IndicatorResult(
            symbol=symbol,
            timeframe=timeframe,
            current_price=float(close.iloc[-1]),
            volume=current_vol,
            avg_volume_20=avg_vol_20,
            ma20=ma20,
            ma50=ma50,
            ma200=ma200,
            rsi=rsi_val,
            macd_line=macd_line,
            macd_signal=macd_signal,
            macd_histogram=macd_hist,
            macd_crossover=crossover,
            bb_upper=bb_upper,
            bb_mid=bb_mid,
            bb_lower=bb_lower,
            atr=atr,
            support_levels=support_levels,
            resistance_levels=resistance_levels,
            last_candles=last_candles,
            volume_trend=vol_trend,
        )

    def _detect_swing_levels(
        self, df: pd.DataFrame, lookback: int = 100
    ) -> tuple[list[float], list[float]]:
        """
        Detect support (swing lows) and resistance (swing highs).
        Uses last 100 candles (was 50) for more accurate structure.
        """
        highs = df["high"].values[-lookback:]
        lows = df["low"].values[-lookback:]
        current_price = float(df["close"].values[-1])

        # Resistance — peaks in high prices
        peak_idx, _ = find_peaks(highs, distance=5, prominence=current_price * 0.005)
        resistance = sorted(
            [float(highs[i]) for i in peak_idx if float(highs[i]) > current_price]
        )[:5]

        # Support — troughs in low prices
        trough_idx, _ = find_peaks(-lows, distance=5, prominence=current_price * 0.005)
        support = sorted(
            [float(lows[i]) for i in trough_idx if float(lows[i]) < current_price],
            reverse=True,
        )[:5]

        return support, resistance

    # ── MTF Trend Filter ─────────────────────────────────────────────────────

    def get_daily_trend(self, raw_candles_1d: list[list]) -> str:
        """
        Returns daily trend label: 'uptrend' | 'downtrend' | 'sideways'.
        Used as MTF filter to avoid trading against the macro trend.
        """
        import ta
        df = _parse_candles(raw_candles_1d)
        close = df["close"]
        ma50 = float(ta.trend.SMAIndicator(close=close, window=50).sma_indicator().iloc[-1])
        ma200 = float(ta.trend.SMAIndicator(close=close, window=200).sma_indicator().iloc[-1])
        current = float(close.iloc[-1])
        if current > ma50 > ma200:
            return "uptrend"
        if current < ma50 < ma200:
            return "downtrend"
        return "sideways"

    # ── Scoring (v2 — 10-point weighted system) ──────────────────────────────

    def score_long_setup(
        self,
        ind: IndicatorResult,
        daily_trend: str = "sideways",
    ) -> tuple[int, list[str]]:
        """
        Confluence scoring for LONG signal.
        Scale: 0–10. Threshold: 6 to fire signal.
        daily_trend: 'uptrend' | 'downtrend' | 'sideways' (from 1D candles)
        """
        score = 0
        reasons: list[str] = []

        # ── [FILTER] Block counter-trend signals ─────────────────────────
        if daily_trend == "downtrend":
            return 0, ["❌ Blocked: Daily trend is DOWNTREND — no long signals"]

        # ── 1. RSI Momentum (0–2 pts) ────────────────────────────────────
        if ind.rsi < 15:
            # Extreme RSI — likely crash/manipulation, NOT a safe entry
            reasons.append(f"⚠️ RSI extremely low ({ind.rsi:.1f}) — danger zone, no points awarded")
        elif ind.rsi < 30:
            score += 2
            reasons.append(f"RSI oversold ({ind.rsi:.1f}) 🟢")
        elif ind.rsi < 45:
            score += 1
            reasons.append(f"RSI approaching oversold ({ind.rsi:.1f})")

        # ── 2. MACD (0–2 pts) ────────────────────────────────────────────
        if ind.macd_crossover == "bullish":
            score += 2
            reasons.append("MACD bullish crossover ✅")
        elif ind.macd_histogram > 0:
            score += 1
            reasons.append("MACD histogram positive")

        # ── 3. Bollinger Bands (0–2 pts) ─────────────────────────────────
        if ind.current_price <= ind.bb_lower:
            score += 2
            reasons.append("Price at/below Bollinger lower band 🎯")
        elif ind.current_price <= ind.bb_mid:
            score += 1
            reasons.append("Price below Bollinger midband")

        # ── 4. Candle Confirmation (0–2 pts) — NEW ────────────────────────
        if ind.last_candle_bullish and ind.candle_body_pct >= 50:
            score += 2
            reasons.append(f"Strong bullish candle confirmation ({ind.candle_body_pct:.0f}% body)")
        elif ind.last_candle_bullish:
            score += 1
            reasons.append("Bullish candle (small body)")

        # ── 5. Swing Level Proximity (0–1 pt) — NEW ──────────────────────
        ns = ind.nearest_support
        if ns and abs(ind.current_price - ns) / ind.current_price < 0.015:
            score += 1
            reasons.append(f"Price near key support (${ns:,.0f}, within 1.5%)")

        # ── 6. Volume Trend (0–2 pts) — upgraded from +1 ─────────────────
        if ind.volume_trend == "rising" and ind.volume_vs_avg > 1.5:
            score += 2
            reasons.append(f"Strong rising volume ({ind.volume_vs_avg:.1f}x avg) 🔥")
        elif ind.volume_trend == "rising" and ind.volume_vs_avg > 1.2:
            score += 1
            reasons.append(f"Rising volume ({ind.volume_vs_avg:.1f}x avg)")

        # ── 7. Daily Uptrend bonus (0–1 pt) ──────────────────────────────
        if daily_trend == "uptrend":
            score += 1
            reasons.append("Daily trend aligned: UPTREND ✅")

        return score, reasons

    def score_short_setup(
        self,
        ind: IndicatorResult,
        daily_trend: str = "sideways",
    ) -> tuple[int, list[str]]:
        """
        Confluence scoring for SHORT signal.
        Scale: 0–10. Threshold: 6 to fire signal.
        """
        score = 0
        reasons: list[str] = []

        # ── [FILTER] Block counter-trend signals ─────────────────────────
        if daily_trend == "uptrend":
            return 0, ["❌ Blocked: Daily trend is UPTREND — no short signals"]

        # ── 1. RSI (0–2 pts) ─────────────────────────────────────────────
        if ind.rsi > 85:
            # Extreme RSI — likely short-squeeze/blow-off, NOT a safe short entry
            reasons.append(f"⚠️ RSI extremely high ({ind.rsi:.1f}) — danger zone, no points awarded")
        elif ind.rsi > 70:
            score += 2
            reasons.append(f"RSI overbought ({ind.rsi:.1f}) 🔴")
        elif ind.rsi > 55:
            score += 1
            reasons.append(f"RSI approaching overbought ({ind.rsi:.1f})")

        # ── 2. MACD (0–2 pts) ────────────────────────────────────────────
        if ind.macd_crossover == "bearish":
            score += 2
            reasons.append("MACD bearish crossover ✅")
        elif ind.macd_histogram < 0:
            score += 1
            reasons.append("MACD histogram negative")

        # ── 3. Bollinger Bands (0–2 pts) ─────────────────────────────────
        if ind.current_price >= ind.bb_upper:
            score += 2
            reasons.append("Price at/above Bollinger upper band 🎯")
        elif ind.current_price >= ind.bb_mid:
            score += 1
            reasons.append("Price above Bollinger midband")

        # ── 4. Candle Confirmation (0–2 pts) — NEW ────────────────────────
        if ind.last_candle_bearish and ind.candle_body_pct >= 50:
            score += 2
            reasons.append(f"Strong bearish candle confirmation ({ind.candle_body_pct:.0f}% body)")
        elif ind.last_candle_bearish:
            score += 1
            reasons.append("Bearish candle (small body)")

        # ── 5. Swing Level Proximity (0–1 pt) — NEW ──────────────────────
        nr = ind.nearest_resistance
        if nr and abs(nr - ind.current_price) / ind.current_price < 0.015:
            score += 1
            reasons.append(f"Price near key resistance (${nr:,.0f}, within 1.5%)")

        # ── 6. Volume Trend (0–2 pts) — upgraded from +1 ─────────────────
        if ind.volume_trend == "rising" and ind.volume_vs_avg > 1.5:
            score += 2
            reasons.append(f"Strong rising volume ({ind.volume_vs_avg:.1f}x avg) 🔥")
        elif ind.volume_trend == "rising" and ind.volume_vs_avg > 1.2:
            score += 1
            reasons.append(f"Rising volume ({ind.volume_vs_avg:.1f}x avg)")

        # ── 7. Daily Downtrend bonus (0–1 pt) ────────────────────────────
        if daily_trend == "downtrend":
            score += 1
            reasons.append("Daily trend aligned: DOWNTREND ✅")

        return score, reasons

    # ── Entry Zone (v2) ──────────────────────────────────────────────────────

    def calculate_trade_levels(
        self,
        side: str,
        entry: float,
        ind: IndicatorResult,
        use_limit_entry: bool = True,
    ) -> dict:
        """
        Calculate TP1/TP2/TP3 and SL based on ATR + swing levels.
        v2: Adds optimal limit entry (Fib 0.618 retracement) and
            classifies entry as 'limit' vs 'market'.
        Returns dict with entry zones, sl, tp1, tp2, tp3, R:R.
        """
        atr = ind.atr

        if side == "long":
            nearest_support = ind.nearest_support or (entry - atr * 2)

            # SL: below nearest support + buffer, at least 1.5×ATR from entry
            sl = min(nearest_support - atr * 0.5, entry - atr * 1.5)

            # Entry Zone: optimal limit entry at Fib 0.618 retracement of last move
            last_candle = ind.last_candles[-1] if ind.last_candles else None
            if last_candle and use_limit_entry:
                candle_range = last_candle["high"] - last_candle["low"]
                limit_entry = last_candle["high"] - candle_range * 0.618
                limit_entry = max(limit_entry, nearest_support + atr * 0.3)
            else:
                limit_entry = entry

            # TPs: use next resistance levels, fallback to ATR multiples
            resistances = [r for r in ind.resistance_levels if r > entry]
            tp1 = resistances[0] if len(resistances) > 0 else entry + atr * 2
            tp2 = resistances[1] if len(resistances) > 1 else entry + atr * 4
            tp3 = entry + abs(entry - sl) * 3  # 1:3 R:R target

            entry_type = "LIMIT" if abs(limit_entry - entry) > atr * 0.1 else "MARKET"

        else:  # short
            nearest_resistance = ind.nearest_resistance or (entry + atr * 2)

            # Cap resistance-based SL — don't use if it's too far (> 3×ATR)
            if nearest_resistance - entry > atr * 3:
                nearest_resistance = entry + atr * 2

            sl = max(nearest_resistance + atr * 0.5, entry + atr * 1.5)

            last_candle = ind.last_candles[-1] if ind.last_candles else None
            if last_candle and use_limit_entry:
                candle_range = last_candle["high"] - last_candle["low"]
                limit_entry = last_candle["low"] + candle_range * 0.618
                limit_entry = min(limit_entry, nearest_resistance - atr * 0.3)
            else:
                limit_entry = entry

            supports = [s for s in ind.support_levels if s < entry]
            tp1 = supports[0] if len(supports) > 0 else entry - atr * 2
            tp2 = supports[1] if len(supports) > 1 else entry - atr * 4
            tp3 = entry - abs(sl - entry) * 3

            entry_type = "LIMIT" if abs(limit_entry - entry) > atr * 0.1 else "MARKET"

        sl_dist = abs(entry - sl)
        rr1 = abs(tp1 - entry) / sl_dist if sl_dist > 0 else 0
        rr2 = abs(tp2 - entry) / sl_dist if sl_dist > 0 else 0

        return {
            "entry": round(entry, 2),
            "limit_entry": round(limit_entry, 2),
            "entry_type": entry_type,
            "sl": round(sl, 2),
            "tp1": round(tp1, 2),
            "tp2": round(tp2, 2),
            "tp3": round(tp3, 2),
            "sl_pct": round(sl_dist / entry * 100, 2),
            "tp1_pct": round(abs(tp1 - entry) / entry * 100, 2),
            "tp2_pct": round(abs(tp2 - entry) / entry * 100, 2),
            "rr1": round(rr1, 2),
            "rr2": round(rr2, 2),
        }
