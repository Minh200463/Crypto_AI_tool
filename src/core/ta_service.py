"""
Technical Analysis Service — upgraded v2.
Improvements:
  1. Multi-Timeframe (MTF) trend filter
  2. Weighted confluence scoring (10-point scale, threshold 6)
  3. Entry Zone (limit vs market entry)
  4. Candle confirmation, volume trend, swing proximity checks
  5. ADX Market Regime Filter (trending vs ranging)
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
    adx: float = 0.0  # ADX(14) — trend strength indicator

    # Swing levels
    support_levels: list[float] = field(default_factory=list)
    resistance_levels: list[float] = field(default_factory=list)

    # Candle context (last 3 candles)
    last_candles: list[dict] = field(default_factory=list)  # [{o,h,l,c,v}]
    volume_trend: str = "neutral"  # "rising" | "falling" | "neutral"

    # Open Interest (P4) & Fair Value Gap (P5)
    oi_change_pct: float | None = None
    fvg_zones: list[dict] = field(default_factory=list)

    # Break of Structure (BOS) — earlier trend confirmation than MA cross
    # [NEW] 'bullish' | 'bearish' | None
    bos_signal: str | None = None

    # Liquidity Engine Output (Phase 1)
    liquidity_context: dict | None = None

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
        """
        True if the last CLOSED candle is bullish (close > open).
        Uses last_candles[-2] (index N-1, confirmed closed) to avoid
        lookahead bias from the still-forming candle at last_candles[-1].
        """
        if len(self.last_candles) < 2:
            return False
        c = self.last_candles[-2]  # closed candle, NOT the forming one
        return c["close"] > c["open"]

    @property
    def last_candle_bearish(self) -> bool:
        """
        True if the last CLOSED candle is bearish. Uses [-2] (see above).
        """
        if len(self.last_candles) < 2:
            return False
        c = self.last_candles[-2]  # closed candle
        return c["close"] < c["open"]

    @property
    def candle_body_pct(self) -> float:
        """Size of last CLOSED candle body as % of its range. 0-100."""
        if len(self.last_candles) < 2:
            return 0.0
        c = self.last_candles[-2]  # closed candle
        rng = c["high"] - c["low"]
        if rng == 0:
            return 0.0
        return abs(c["close"] - c["open"]) / rng * 100

    @property
    def is_doji(self) -> bool:
        """
        True nếu nến cuối cùng đã đóng là Doji.
        Doji: body < 10% của toàn bộ range nến.
        Biểu thị thị trường do dự, hai phấ cân bằng nhau.
        Không vào lệnh khi doji tại vùng S/R quan trọng.
        """
        if len(self.last_candles) < 2:
            return False
        c = self.last_candles[-2]  # closed candle
        rng = c["high"] - c["low"]
        if rng == 0:
            return False
        body = abs(c["close"] - c["open"])
        return (body / rng) < 0.10  # body nhỏ hơn 10% range = doji

    @property
    def pin_bar_signal(self) -> str | None:
        """
        Detect Pin Bar (rejection candle) on the last CLOSED candle.
        Bullish pin bar (hammer): lower_wick > 2x body, upper_wick < 0.5x body
        Bearish pin bar (shooting star): upper_wick > 2x body, lower_wick < 0.5x body
        Returns: 'bullish' | 'bearish' | None
        """
        if len(self.last_candles) < 2:
            return None
        c = self.last_candles[-2]  # closed candle
        body = abs(c["close"] - c["open"])
        if body == 0:
            return None
        upper_wick = c["high"] - max(c["open"], c["close"])
        lower_wick = min(c["open"], c["close"]) - c["low"]
        if lower_wick > 2 * body and upper_wick < body * 0.5:
            return "bullish"  # hammer / dragonfly doji
        if upper_wick > 2 * body and lower_wick < body * 0.5:
            return "bearish"  # shooting star / gravestone doji
        return None

    @property
    def engulfing_signal(self) -> str | None:
        """
        Detect Engulfing pattern using last 2 CLOSED candles [-2] and [-3].
        Bullish engulfing: curr body > prev body, curr bullish, prev bearish.
        Bearish engulfing: curr body > prev body, curr bearish, prev bullish.
        Returns: 'bullish' | 'bearish' | None
        """
        if len(self.last_candles) < 3:
            return None
        prev = self.last_candles[-3]  # 2 candles ago (closed)
        curr = self.last_candles[-2]  # last closed candle
        prev_body = abs(prev["close"] - prev["open"])
        curr_body = abs(curr["close"] - curr["open"])
        if curr_body == 0:
            return None
        curr_bull = curr["close"] > curr["open"]
        prev_bull = prev["close"] > prev["open"]
        if curr_body > prev_body and curr_bull and not prev_bull:
            return "bullish"
        if curr_body > prev_body and not curr_bull and prev_bull:
            return "bearish"
        return None

    @property
    def market_regime(self) -> str:
        """
        Market regime based on ADX(14):
          'trending'     — ADX > 25: strong directional move, use trend indicators
          'ranging'      — ADX < 20: consolidation, use mean-reversion indicators
          'transitional' — ADX 20-25: ambiguous, apply standard scoring
        """
        if self.adx > 25:
            return "trending"
        if self.adx < 20:
            return "ranging"
        return "transitional"


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
        # [FIX] MA20/MA50 reverted to SMA to match Binance chart default display.
        # MA200 also SMA — all three now consistent with what users see on Binance. 
        # MA200 stays SMA: used for long-term trend baseline, not entry timing
        ma20 = float(ta.trend.SMAIndicator(close=close, window=20).sma_indicator().iloc[-1])
        ma50 = float(ta.trend.SMAIndicator(close=close, window=50).sma_indicator().iloc[-1])
        ma200 = float(ta.trend.SMAIndicator(close=close, window=200).sma_indicator().iloc[-1])

        # ── ATR ───────────────────────────────────────────────────────────
        atr = float(
            ta.volatility.AverageTrueRange(
                high=high, low=low, close=close, window=14
            ).average_true_range().iloc[-1]
        )

        # ── ADX (trend strength) ──────────────────────────────────────────
        # ADX > 25 = trending, < 20 = ranging, 20-25 = transitional
        try:
            adx_ind = ta.trend.ADXIndicator(high=high, low=low, close=close, window=14)
            adx_val = float(adx_ind.adx().iloc[-1])
        except Exception:
            adx_val = 0.0  # fallback if insufficient data

        # ── Volume ───────────────────────────────────────────────────────
        avg_vol_20 = float(df["quote_volume"].iloc[-20:].mean())
        current_vol = float(df["quote_volume"].iloc[-1])

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
            adx=adx_val,
            support_levels=support_levels,
            resistance_levels=resistance_levels,
            last_candles=last_candles,
            volume_trend=vol_trend,
            fvg_zones=self._detect_fvg(df),
            bos_signal=self._detect_bos(df),  # [NEW] BOS detection
        )

    def _detect_bos(self, df: pd.DataFrame, lookback: int = 20) -> str | None:
        """
        [NEW] Break of Structure (BOS) detection.

        Identifies when price breaks a key structural level before MA cross
        confirms it — gives trend signal 5-10 candles earlier than MA cross.

        Bullish BOS:  current closed candle's HIGH > max of 3 recent swing highs
        Bearish BOS:  current closed candle's LOW  < min of 3 recent swing lows

        Uses closed candle [-2] to avoid lookahead bias.

        Returns: 'bullish' | 'bearish' | None
        """
        if len(df) < lookback + 5:
            return None

        from scipy.signal import find_peaks

        highs = df["high"].values[-lookback:]
        lows  = df["low"].values[-lookback:]

        # Find swing points in lookback window, excluding last 3 candles
        peak_idx,   _ = find_peaks(highs[:-3],  distance=3)
        trough_idx, _ = find_peaks(-lows[:-3], distance=3)

        # Closed candle = [-2] to avoid lookahead bias
        current_high = float(df["high"].iloc[-2])
        current_low  = float(df["low"].iloc[-2])

        if len(peak_idx) >= 3:
            recent_swing_highs = highs[peak_idx[-3:]]
            if current_high > float(max(recent_swing_highs)):
                return "bullish"  # Price broke above 3 recent swing highs

        if len(trough_idx) >= 3:
            recent_swing_lows = lows[trough_idx[-3:]]
            if current_low < float(min(recent_swing_lows)):
                return "bearish"  # Price broke below 3 recent swing lows

        return None

    @staticmethod
    def confirm_ltf_trigger(side: str, ltf_klines: list) -> bool:
        """
        [Phase 2] LTF Confirmation Logic (15m/1h)
        Checks if the latest LTF candles show a reversal pattern (Engulfing/Pinbar).
        """
        if len(ltf_klines) < 3:
            return False
            
        import pandas as pd
        df = pd.DataFrame(ltf_klines, columns=[
            "open_time", "open", "high", "low", "close", "volume",
            "close_time", "quote_volume", "count", "taker_buy_vol", "taker_buy_quote", "ignore"
        ])
        
        # Check last 2 closed candles (index -2 and -3 to avoid lookahead bias)
        prev_open = float(df["open"].iloc[-3])
        prev_close = float(df["close"].iloc[-3])
        curr_open = float(df["open"].iloc[-2])
        curr_close = float(df["close"].iloc[-2])
        curr_high = float(df["high"].iloc[-2])
        curr_low = float(df["low"].iloc[-2])
        
        if side == "long":
            prev_bearish = prev_close < prev_open
            curr_bullish = curr_close > curr_open
            engulfing = prev_bearish and curr_bullish and curr_close > prev_open and curr_open < prev_close
            
            candle_range = curr_high - curr_low
            body = abs(curr_close - curr_open)
            lower_wick = min(curr_open, curr_close) - curr_low
            pinbar = candle_range > 0 and lower_wick > body * 2 and curr_bullish
            
            return engulfing or pinbar
        else:
            prev_bullish = prev_close > prev_open
            curr_bearish = curr_close < curr_open
            engulfing = prev_bullish and curr_bearish and curr_close < prev_open and curr_open > prev_close
            
            candle_range = curr_high - curr_low
            body = abs(curr_close - curr_open)
            upper_wick = curr_high - max(curr_open, curr_close)
            pinbar = candle_range > 0 and upper_wick > body * 2 and curr_bearish
            
            return engulfing or pinbar

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

    def _detect_fvg(self, df: pd.DataFrame, lookback: int = 20) -> list[dict]:
        """
        Detect Fair Value Gaps in last N candles.
        Filters out FVGs that have already been filled by subsequent price action.
        Returns list of {"type": "bullish"|"bearish", "top": float, "bottom": float}
        """
        fvgs = []
        current_low  = float(df["low"].iloc[-1])
        current_high = float(df["high"].iloc[-1])
        # Use ATR-based threshold for impulse body (more robust than std)
        atr_proxy = float((df["high"] - df["low"]).rolling(14).mean().iloc[-1])
        impulse_threshold = atr_proxy * 0.5

        # Scan from [-lookback] to [-3] (need c_prev, c_curr, c_next — all closed)
        for i in range(lookback, 2, -1):
            idx = -i
            c_prev = df.iloc[idx - 1]  # candle before the impulse
            c_curr = df.iloc[idx]      # impulse candle
            c_next = df.iloc[idx + 1] # candle after (confirms gap)

            body_size = abs(float(c_curr["close"]) - float(c_curr["open"]))
            if body_size < impulse_threshold:
                continue

            # Bullish FVG: gap between c_prev.high and c_next.low
            if float(c_prev["high"]) < float(c_next["low"]):
                fvg_bottom = float(c_prev["high"])
                fvg_top    = float(c_next["low"])
                # Filter filled: check if any candle after c_curr has dipped into or below the gap
                is_filled = False
                for j in range(idx + 1, 0):
                    if float(df["low"].iloc[j]) <= fvg_bottom:
                        is_filled = True
                        break
                if not is_filled:
                    fvgs.append({"type": "bullish", "top": fvg_top, "bottom": fvg_bottom})

            # Bearish FVG: gap between c_next.high and c_prev.low
            elif float(c_prev["low"]) > float(c_next["high"]):
                fvg_top    = float(c_prev["low"])
                fvg_bottom = float(c_next["high"])
                # Filter filled: check if any candle after c_curr has risen into or above the gap
                is_filled = False
                for j in range(idx + 1, 0):
                    if float(df["high"].iloc[j]) >= fvg_top:
                        is_filled = True
                        break
                if not is_filled:
                    fvgs.append({"type": "bearish", "top": fvg_top, "bottom": fvg_bottom})

        return fvgs[:3]  # 3 most recent unfilled FVGs

    # ── MTF Trend Filter ─────────────────────────────────────────────────────

    @staticmethod
    def _trend_from_candles(raw_candles: list[list]) -> str:
        """
        Shared MA-based trend computation for any timeframe.
        Returns: 'uptrend' | 'downtrend' | 'sideways'
        Requires at least 50 candles; returns 'sideways' otherwise.
        """
        import ta
        if len(raw_candles) < 50:
            return "sideways"
        df = _parse_candles(raw_candles)
        close = df["close"]
        ma50  = float(ta.trend.SMAIndicator(close=close, window=50).sma_indicator().iloc[-1])
        ma200 = float(ta.trend.SMAIndicator(close=close, window=200).sma_indicator().iloc[-1])
        current = float(close.iloc[-1])
        if current > ma50 > ma200:
            return "uptrend"
        if current < ma50 < ma200:
            return "downtrend"
        return "sideways"

    def get_daily_trend(self, raw_candles_1d: list[list]) -> str:
        """
        Returns daily trend label: 'uptrend' | 'downtrend' | 'sideways'.
        Used as intermediate MTF filter (Layer 2).
        Needs >= 50 daily candles (~2 months).
        """
        return self._trend_from_candles(raw_candles_1d)

    def get_weekly_trend(self, raw_candles_1w: list[list]) -> str:
        """
        Returns weekly trend label: 'uptrend' | 'downtrend' | 'sideways'.
        Used as macro MTF filter (Layer 3 — strongest filter).
        Needs >= 50 weekly candles (~1 year). Binance returns 200 by default.

        Weekly trend represents the primary market structure:
          - DOWNTREND: bear market, rising counters are risky for LONG
          - UPTREND:   bull market, dips are risky for SHORT
          - SIDEWAYS:  neutral, no macro filter applied
        """
        return self._trend_from_candles(raw_candles_1w)

    @staticmethod
    def get_current_session() -> dict:
        """
        Classify current UTC time into Forex/Crypto trading sessions.

        Sessions (UTC):
          london   07:00–13:00  — High liquidity, institutional activity
          overlap  13:00–17:00  — London + NY overlap (STRONGEST, most volume)
          ny_close 17:00–21:00  — NY afternoon, fading liquidity
          asia     01:00–07:00  — Low liquidity, fakeouts more common
          off      21:00–01:00  — Dead zone, minimal volume

        Returns dict: {name, label, emoji, high_liquidity}
        """
        from datetime import datetime, timezone
        utc_hour = datetime.now(timezone.utc).hour

        if 13 <= utc_hour < 17:
            return {"name": "overlap",   "label": "London+NY Overlap", "emoji": "🟢", "high_liquidity": True}
        if 7  <= utc_hour < 13:
            return {"name": "london",    "label": "London Session",     "emoji": "🟢", "high_liquidity": True}
        if 17 <= utc_hour < 21:
            return {"name": "ny_close",  "label": "NY Close",           "emoji": "🟡", "high_liquidity": True}
        if 1  <= utc_hour < 7:
            return {"name": "asia",      "label": "Asia Session",       "emoji": "🔴", "high_liquidity": False}
        return     {"name": "off",       "label": "Off-Hours",          "emoji": "⚫", "high_liquidity": False}

    # ── Scoring (v2 — 10-point weighted system) ──────────────────────────────

    def score_long_setup(
        self,
        ind: IndicatorResult,
        daily_trend: str = "sideways",
        weekly_trend: str = "sideways",
    ) -> tuple[int, list[str], dict]:
        """
        Confluence scoring for LONG signal.
        Scale: 0–10. Threshold: 6 to fire signal.

        3-Layer MTF Filter:
          L1 — 4H indicators    (score base)
          L2 — Daily trend      (block if DOWNTREND)
          L3 — Weekly trend     (hard block if weekly+daily both DOWNTREND;
                                  soft warning + withhold daily bonus if weekly DOWNTREND alone)
        """
        score = 0
        reasons: list[str] = []
        breakdown: dict = {}

        # ── [L2] Block if daily is bearish ───────────────────────────────
        if daily_trend == "downtrend":
            return 0, ["❌ Blocked: Daily trend is DOWNTREND — no long signals"], {}

        # ── [L3] Weekly macro trend check ────────────────────────────────
        # Hard block: weekly AND daily both bearish — deep bear market, no LONG
        if weekly_trend == "downtrend" and daily_trend == "downtrend":
            return 0, ["❌ Blocked: Weekly + Daily DOWNTREND — macro bear market"], {}
        # Soft warning: weekly bearish but daily is a counter-trend relief rally
        weekly_counter = (weekly_trend == "downtrend")
        if weekly_counter:
            reasons.append(
                "⚠️ Weekly: DOWNTREND — counter-trend LONG in bear market (elevated risk)"
            )

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

        # ── 4. Candle Confirmation (0–2 pts) ────────────────────────────
        # Priority: Pin Bar > Engulfing > Strong body > Weak body
        # All checks use last_candles[-2] (closed candle — no lookahead bias)
        _pin = ind.pin_bar_signal
        _eng = ind.engulfing_signal

        # ── Doji warning tại vùng S/R quan trọng ────────────────────────────
        # Doji tại resistance/MA200 = thị trường đang do dự = KHÔNG vào ngay
        _doji_at_sr = False
        if ind.is_doji:
            _near_res = (
                ind.nearest_resistance is not None and
                abs(ind.nearest_resistance - ind.current_price) / ind.current_price < 0.01
            )
            _above_ma200_fresh = (
                ind.current_price > ind.ma200 and
                abs(ind.current_price - ind.ma200) / ind.current_price < 0.012
            )
            if _near_res or _above_ma200_fresh:
                _doji_at_sr = True
                _sr_label = (
                    f"${ind.nearest_resistance:,.0f}" if _near_res
                    else f"MA200 ${ind.ma200:,.0f}"
                )
                reasons.append(
                    f"⚠️ Doji tại kháng cự {_sr_label} — thị trường đang do dự. "
                    "Chờ nến xác nhận tiếp theo trước khi vào lệnh."
                )

        if not _doji_at_sr:
            if _pin == "bullish":
                score += 2
                reasons.append("🔨 Bullish Pin Bar (hammer/rejection) — strong reversal signal")
            elif _eng == "bullish":
                score += 2
                reasons.append("📈 Bullish Engulfing candle — momentum shift confirmed")
            elif ind.last_candle_bullish and ind.candle_body_pct >= 50:
                score += 1
                reasons.append(f"Bullish candle, strong body ({ind.candle_body_pct:.0f}%)")
            elif ind.last_candle_bullish:
                score += 0  # weak body, no signal
                reasons.append(f"Bullish candle, weak body ({ind.candle_body_pct:.0f}%) — no points")
            elif _pin == "bearish" or _eng == "bearish":
                reasons.append("⚠️ Bearish candle pattern — contradicts LONG setup")

        # ── 5. Swing Level & FVG Proximity (0–2 pts) ─────────────────────────
        ns = ind.nearest_support
        if ns and abs(ind.current_price - ns) / ind.current_price < 0.015:
            score += 1
            reasons.append(f"Price near key support (${ns:,.0f}, within 1.5%)")
            
        # P5: Check if current price is inside a bullish FVG
        for fvg in ind.fvg_zones:
            if fvg["type"] == "bullish" and fvg["bottom"] <= ind.current_price <= fvg["top"]:
                score += 1
                reasons.append(f"Price inside Bullish FVG zone (${fvg['bottom']:,.0f} - ${fvg['top']:,.0f}) 🎯")
                break

        # ── 6. Volume Trend & Open Interest (0–3 pts) ────────────────────────
        # Volume only counts if the candle is BULLISH (confirming buy pressure)
        if ind.volume_trend == "rising" and ind.volume_vs_avg > 1.5 and ind.last_candle_bullish:
            score += 2
            reasons.append(f"Strong bullish volume spike ({ind.volume_vs_avg:.1f}x avg) 🔥")
        elif ind.volume_trend == "rising" and ind.volume_vs_avg > 1.2 and ind.last_candle_bullish:
            score += 1
            reasons.append(f"Bullish rising volume ({ind.volume_vs_avg:.1f}x avg)")
        elif ind.volume_trend == "rising" and not ind.last_candle_bullish:
            reasons.append(f"⚠️ Volume spike on bearish candle — sell pressure, not counted for LONG")

        # ── 6b. Volume Breakout Confirmation (0 / -1 / +1 pt) ───────────────
        # [NEW] Breakout quality filter — price near key S/R needs volume to confirm.
        # A breakout on low volume is the #1 cause of false signals (fake breakouts).
        #
        # Rule:
        #   Price near MA200 (within 1%) → check if volume confirms:
        #     volume_vs_avg >= 1.5  → real breakout → +1 bonus
        #     volume_vs_avg <  0.8  → fake breakout → -1 penalty + warning
        #   Price NOT near MA200 → no adjustment (rule only applies to key level breaks)
        near_ma200 = abs(ind.current_price - ind.ma200) / ind.ma200 < 0.01  # within 1%

        if near_ma200:
            if ind.volume_vs_avg >= 1.5:
                score += 1
                reasons.append(
                    f"✅ Breakout MA200 xác nhận bởi volume ({ind.volume_vs_avg:.1f}x avg) — tín hiệu mạnh"
                )
            elif ind.volume_vs_avg < 0.8:
                score = max(0, score - 1)
                reasons.append(
                    f"⚠️ Breakout MA200 volume thấp ({ind.volume_vs_avg:.1f}x avg) — nguy cơ fakeout cao, score -1"
                )

        # ── P4 & Phase 1: Open Interest & Liquidity Context ──────────────────
        if ind.liquidity_context:
            l_ctx = ind.liquidity_context
            for w in l_ctx.get("warnings", []):
                reasons.append(w)
            
            # Bonus từ Liquidity Score (Phase 7: bỏ cộng điểm từ order book theo feedback của trader)
            
            # LVN check (Entry rơi vào vùng kém thanh khoản)
            vp = l_ctx.get("volume_profile", {})
            lvn_zones = vp.get("lvn_zones", [])
            for z in lvn_zones:
                if z["bottom"] <= ind.current_price <= z["top"]:
                    reasons.append("⚠️ Giá hiện tại đang nằm trong LVN (Low Volume Node) — dễ trượt giá")
                    break

            oi_pct = l_ctx.get("funding_oi", {}).get("oi_change_pct", 0)
            if oi_pct > 2.0 and ind.last_candle_bullish:
                score += 1
                reasons.append(f"OI Rising (+{oi_pct:.1f}%) + Price Rising = Strong New Longs 🟢")
            elif oi_pct < -2.0 and ind.last_candle_bullish:
                reasons.append(f"OI Falling ({oi_pct:.1f}%) + Price Rising = Short Covering (Weak Buy)")
        elif ind.oi_change_pct is not None:
            # Fallback legacy
            if ind.oi_change_pct > 2.0 and ind.last_candle_bullish:
                score += 1
                reasons.append(f"OI Rising (+{ind.oi_change_pct:.1f}%) + Price Rising = Strong New Longs 🟢")
            elif ind.oi_change_pct < -2.0 and ind.last_candle_bullish:
                reasons.append(f"OI Falling ({ind.oi_change_pct:.1f}%) + Price Rising = Short Covering (Weak Buy)")


        # ── 7. Daily + Weekly alignment bonus (0–1 pt) ──────────────────
        # Full +1 only when weekly trend ALSO confirms the direction.
        # Counter-weekly daily = relief rally = bonus withheld (risk factor).
        if daily_trend == "uptrend" and not weekly_counter:
            score += 1
            reasons.append("Daily + Weekly aligned: UPTREND ✅")
        elif daily_trend == "uptrend" and weekly_counter:
            reasons.append("Daily UPTREND (0 pts — counter-weekly bear rally, bonus withheld)")

        # ── 8. ADX Market Regime bonus (0–2 pts) ─────────────────────────
        # TRENDING (ADX > 25): Reward MACD crossover + short/medium MA momentum
        # RANGING  (ADX < 20): Reward BB extreme + RSI extreme (mean-reversion)
        # NOTE: ADX has ~5-7 candle lag — trending bonus may be absent at the
        # best entry candles (early trend) and still present near trend exhaustion.
        # This is a known trade-off; users should not rely solely on the regime label.
        regime = ind.market_regime
        if regime == "trending":  # ADX > 25
            reasons.append(f"📊 Regime: TRENDING (ADX {ind.adx:.1f}) — trend-following signals amplified")
            if ind.macd_crossover == "bullish":
                score += 1
                reasons.append("  → Trending bonus: MACD crossover +1 in strong trend")
            # Only require MA20 > MA50 (short/medium term momentum)
            # MA200 on 4H is ~800 days — too slow to reflect early bull runs
            if ind.ma20 > ind.ma50:
                score += 1
                reasons.append("  → Trending bonus: MA20 > MA50 momentum +1")
        elif regime == "ranging":  # ADX < 20
            reasons.append(f"📊 Regime: RANGING (ADX {ind.adx:.1f}) — mean-reversion signals amplified")
            if ind.current_price <= ind.bb_lower:
                score += 1
                reasons.append("  → Ranging bonus: BB lower touch +1 in sideways market")
            if ind.rsi < 30:
                score += 1
                reasons.append("  → Ranging bonus: RSI oversold +1 in sideways market")
        else:  # transitional 20–25 — high-noise zone, no bonus
            reasons.append(f"📊 Regime: TRANSITIONAL (ADX {ind.adx:.1f}) — standard scoring, no regime bonus")


        # ── 9. Session filter penalty (P3 fix) ──────────────────────────────
        # Real -1 penalty (not just label downgrade) when Asia/Off-hours.
        # Rationale: institutional liquidity is low — fakeout probability is higher.
        _session = self.get_current_session()
        if not _session["high_liquidity"]:
            score = max(0, score - 1)
            breakdown["session_penalty"] = breakdown.get("session_penalty", 0) - 1
            reasons.append(
                f"⚠️ {_session['emoji']} {_session['label']}: Low-liquidity session — score -1"
            )

        # ── 10. BOS (Break of Structure) bonus (+1 pt) ──────────────────────
        # [NEW] BOS gives earlier trend confirmation than MA cross (5-10 candles ahead).
        # Only award bonus for bullish BOS on a LONG setup.
        if ind.bos_signal == "bullish":
            score += 1
            reasons.append("📈 BOS xác nhận — phá vỡ swing high cấu trúc, trend mới hình thành 🎯")
        return score, reasons, breakdown

    def score_short_setup(
        self,
        ind: IndicatorResult,
        daily_trend: str = "sideways",
        weekly_trend: str = "sideways",
    ) -> tuple[int, list[str], dict]:
        """
        Confluence scoring for SHORT signal.
        Scale: 0–10. Threshold: 6 to fire signal.

        3-Layer MTF Filter (mirror of LONG):
          L2 — Daily: block if UPTREND
          L3 — Weekly: hard block if weekly+daily both UPTREND;
                        soft warning if weekly UPTREND alone (daily dip in bull market)
        """
        score = 0
        reasons: list[str] = []
        breakdown: dict = {}

        # ── [L2] Block if daily is bullish ───────────────────────────────
        if daily_trend == "uptrend":
            return 0, ["❌ Blocked: Daily trend is UPTREND — no short signals"], {}

        # ── [L3] Weekly macro trend check ────────────────────────────────
        # Hard block: weekly AND daily both bullish — bull market, no SHORT
        if weekly_trend == "uptrend" and daily_trend == "uptrend":
            return 0, ["❌ Blocked: Weekly + Daily UPTREND — macro bull market"], {}
        # Soft warning: weekly bullish but daily shows a counter-trend pullback
        weekly_counter = (weekly_trend == "uptrend")
        if weekly_counter:
            reasons.append(
                "⚠️ Weekly: UPTREND — counter-trend SHORT in bull market (elevated risk)"
            )

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

        # ── 4. Candle Confirmation (0–2 pts) ────────────────────────────
        # Priority: Pin Bar > Engulfing > Strong body > Weak body
        _pin = ind.pin_bar_signal
        _eng = ind.engulfing_signal
        if _pin == "bearish":
            score += 2
            reasons.append("🌠 Bearish Pin Bar (shooting star/rejection) — strong reversal signal")
        elif _eng == "bearish":
            score += 2
            reasons.append("📉 Bearish Engulfing candle — momentum shift confirmed")
        elif ind.last_candle_bearish and ind.candle_body_pct >= 50:
            score += 1
            reasons.append(f"Bearish candle, strong body ({ind.candle_body_pct:.0f}%)")
        elif ind.last_candle_bearish:
            score += 0
            reasons.append(f"Bearish candle, weak body ({ind.candle_body_pct:.0f}%) — no points")
        elif _pin == "bullish" or _eng == "bullish":
            reasons.append("⚠️ Bullish candle pattern — contradicts SHORT setup")

        # ── 5. Swing Level & FVG Proximity (0–2 pts) ─────────────────────────
        nr = ind.nearest_resistance
        if nr and abs(nr - ind.current_price) / ind.current_price < 0.015:
            score += 1
            reasons.append(f"Price near key resistance (${nr:,.0f}, within 1.5%)")

        # P5: Check if current price is inside a bearish FVG
        for fvg in ind.fvg_zones:
            if fvg["type"] == "bearish" and fvg["bottom"] <= ind.current_price <= fvg["top"]:
                score += 1
                reasons.append(f"Price inside Bearish FVG zone (${fvg['bottom']:,.0f} - ${fvg['top']:,.0f}) 🎯")
                break

        # ── 6. Volume Trend & Open Interest (0–3 pts) ────────────────────────
        # Volume only counts if the candle is BEARISH (confirming sell pressure)
        if ind.volume_trend == "rising" and ind.volume_vs_avg > 1.5 and ind.last_candle_bearish:
            score += 2
            reasons.append(f"Strong bearish volume spike ({ind.volume_vs_avg:.1f}x avg) 🔥")
        elif ind.volume_trend == "rising" and ind.volume_vs_avg > 1.2 and ind.last_candle_bearish:
            score += 1
            reasons.append(f"Bearish rising volume ({ind.volume_vs_avg:.1f}x avg)")
        elif ind.volume_trend == "rising" and not ind.last_candle_bearish:
            reasons.append(f"⚠️ Volume spike on bullish candle — buy pressure, not counted for SHORT")

        # ── 6b. Volume Breakout Confirmation (SHORT) ────────────────────────
        # Price breaking below MA200 on low volume = likely fake breakdown
        near_ma200 = abs(ind.current_price - ind.ma200) / ind.ma200 < 0.01

        if near_ma200:
            if ind.volume_vs_avg >= 1.5:
                score += 1
                reasons.append(
                    f"✅ Breakdown MA200 xác nhận bởi volume ({ind.volume_vs_avg:.1f}x avg) — tín hiệu mạnh"
                )
            elif ind.volume_vs_avg < 0.8:
                score = max(0, score - 1)
                reasons.append(
                    f"⚠️ Breakdown MA200 volume thấp ({ind.volume_vs_avg:.1f}x avg) — nguy cơ false breakdown, score -1"
                )

        # ── P4 & Phase 1: Open Interest & Liquidity Context ──────────────────
        if ind.liquidity_context:
            l_ctx = ind.liquidity_context
            for w in l_ctx.get("warnings", []):
                reasons.append(w)
            
            # LVN check
            vp = l_ctx.get("volume_profile", {})
            lvn_zones = vp.get("lvn_zones", [])
            for z in lvn_zones:
                if z["bottom"] <= ind.current_price <= z["top"]:
                    reasons.append("⚠️ Giá hiện tại đang nằm trong LVN (Low Volume Node) — dễ trượt giá")
                    break

            oi_pct = l_ctx.get("funding_oi", {}).get("oi_change_pct", 0)
            if oi_pct > 2.0 and ind.last_candle_bearish:
                score += 1
                reasons.append(f"OI Rising (+{oi_pct:.1f}%) + Price Falling = Strong New Shorts 🔴")
            elif oi_pct < -2.0 and ind.last_candle_bearish:
                reasons.append(f"OI Falling ({oi_pct:.1f}%) + Price Falling = Long Liquidation (Weak Sell)")
        elif ind.oi_change_pct is not None:
            # Fallback legacy
            if ind.oi_change_pct > 2.0 and ind.last_candle_bearish:
                score += 1
                reasons.append(f"OI Rising (+{ind.oi_change_pct:.1f}%) + Price Falling = Strong New Shorts 🔴")
            elif ind.oi_change_pct < -2.0 and ind.last_candle_bearish:
                reasons.append(f"OI Falling ({ind.oi_change_pct:.1f}%) + Price Falling = Long Liquidation (Weak Sell)")


        # ── 7. Daily + Weekly alignment bonus (0–1 pt) ──────────────────
        # Full +1 only when weekly trend ALSO confirms the bearish direction.
        if daily_trend == "downtrend" and not weekly_counter:
            score += 1
            reasons.append("Daily + Weekly aligned: DOWNTREND ✅")
        elif daily_trend == "downtrend" and weekly_counter:
            reasons.append("Daily DOWNTREND (0 pts — counter-weekly bull dip, bonus withheld)")

        # ── 8. ADX Market Regime bonus (0–2 pts) ─────────────────────────
        # NOTE: ADX has ~5-7 candle lag (same caveat as LONG scoring above).
        regime = ind.market_regime
        if regime == "trending":  # ADX > 25
            reasons.append(f"📊 Regime: TRENDING (ADX {ind.adx:.1f}) — trend-following signals amplified")
            if ind.macd_crossover == "bearish":
                score += 1
                reasons.append("  → Trending bonus: MACD crossover +1 in strong trend")
            # Only require MA20 < MA50 (short/medium term bearish momentum)
            if ind.ma20 < ind.ma50:
                score += 1
                reasons.append("  → Trending bonus: MA20 < MA50 momentum +1")
        elif regime == "ranging":  # ADX < 20
            reasons.append(f"📊 Regime: RANGING (ADX {ind.adx:.1f}) — mean-reversion signals amplified")
            if ind.current_price >= ind.bb_upper:
                score += 1
                reasons.append("  → Ranging bonus: BB upper touch +1 in sideways market")
            if ind.rsi > 70:
                score += 1
                reasons.append("  → Ranging bonus: RSI overbought +1 in sideways market")
        else:  # transitional 20–25 — high-noise zone, no bonus
            reasons.append(f"📊 Regime: TRANSITIONAL (ADX {ind.adx:.1f}) — standard scoring, no regime bonus")


        # ── 9. Session filter penalty (P3 fix) ──────────────────────────────
        # Real -1 penalty (not just label downgrade) when Asia/Off-hours.
        # Rationale: institutional liquidity is low — fakeout probability is higher.
        _session = self.get_current_session()
        if not _session["high_liquidity"]:
            score = max(0, score - 1)
            breakdown["session_penalty"] = breakdown.get("session_penalty", 0) - 1
            reasons.append(
                f"⚠️ {_session['emoji']} {_session['label']}: Low-liquidity session — score -1"
            )

        # ── 10. BOS (Break of Structure) bonus (+1 pt) ──────────────────────
        # [NEW] BOS gives earlier trend confirmation than MA cross (5-10 candles ahead).
        # Only award bonus for bearish BOS on a SHORT setup.
        if ind.bos_signal == "bearish":
            score += 1
            reasons.append("📉 BOS xác nhận — phá vỡ swing low cấu trúc, downtrend mới hình thành 🎯")

        return score, reasons, breakdown

    # ── Entry Zone (v2) ──────────────────────────────────────────────────────

    def calculate_trade_levels(
        self,
        side: str,
        entry: float,
        ind: IndicatorResult,
        use_limit_entry: bool = True,
        is_tier_b: bool = False,
    ) -> dict:
        """
        Calculate TP1/TP2/TP3, SL, and DCA Plan based on ATR + swing + liquidity levels.
        v2 (Phase 2): Adds DCA multi-tier entry (Fib 0.5 - 0.786) and HVN/LVN intersection.
        Returns dict with entry zones, sl, tp1, tp2, tp3, R:R, and dca_plan.
        """
        atr = ind.atr
        # Tier B (score 6–7) uses tighter SL to limit risk on weaker setups
        sl_atr_mult = 1.0 if is_tier_b else 1.5

        if side == "long":
            import json

            # ── 1. Swing High/Low (Phase 2 & 3) ─────────────────────────────
            if len(ind.last_candles) >= 20:
                recent = ind.last_candles[-20:]
                swing_high = max(float(c["high"]) for c in recent)
                swing_low = min(float(c["low"]) for c in recent)
            else:
                swing_high = entry + atr * 2
                swing_low = entry - atr * 2
                
            swing_range = swing_high - swing_low
            if swing_range <= 0:
                swing_range = atr * 2
                swing_high = entry + atr
            
            # ── 2. Structural SL (Phase 3) ─────────────────────────────
            sl_warning = None
            pools = ind.liquidity_context.get("liquidity_pools", {}) if ind.liquidity_context else {}
            support_pools = pools.get("support_pools", [])
            pools_below = [p["price"] for p in support_pools if p["price"] < swing_low]
            nearest_pool = max(pools_below) if pools_below else swing_low
            
            sl = min(swing_low, nearest_pool) - (atr * 0.25)
            
            sl_distance_atr = abs(entry - sl) / atr
            if sl_distance_atr > 2.5:
                sl_warning = "⚠️ SL cấu trúc khá xa (>2.5 ATR), cân nhắc rủi ro."
            elif sl_distance_atr < 0.5:
                sl_warning = "⚠️ SL cấu trúc quá hẹp (<0.5 ATR), dễ bị quét (Stop Hunt)."

            import json


            # Retrace from swing high down
            fib_0_5 = swing_high - swing_range * 0.5
            fib_0_618 = swing_high - swing_range * 0.618
            fib_0_786 = swing_high - swing_range * 0.786
            
            entry_zone_top = min(entry, fib_0_5) if not is_tier_b else min(entry, fib_0_618)
            entry_zone_bottom = min(entry, fib_0_786)

            if not is_tier_b:
                dca = [
                    {"price": fib_0_5, "weight": 40},
                    {"price": fib_0_618, "weight": 35},
                    {"price": fib_0_786, "weight": 25}
                ]
            else:
                dca = [
                    {"price": fib_0_618, "weight": 50},
                    {"price": fib_0_786, "weight": 50}
                ]

            # Adjust if in LVN (Phase 2 intersection)
            if ind.liquidity_context and "volume_profile" in ind.liquidity_context:
                lvn_zones = ind.liquidity_context["volume_profile"].get("lvn_zones", [])
                for d in dca:
                    p = d["price"]
                    for lvn in lvn_zones:
                        if lvn["bottom"] <= p <= lvn["top"]:
                            # Move price down to nearest better price (for LONG, move down)
                            d["price"] = lvn["bottom"] - atr * 0.1
                            break

            # Sanity guards
            for d in dca:
                if d["price"] > entry:
                    d["price"] = entry
            
            limit_entry = dca[0]["price"] # For legacy compatibility
            entry_type = "LIMIT" if use_limit_entry else "MARKET"

            # ── 3. Liquidity-Aware TP (Phase 3) ──────────────────────────
            sl_dist_long = abs(entry - sl)
            tp1 = entry + sl_dist_long * 1.5

            resistance_pools = pools.get("resistance_pools", [])
            pools_above = [p["price"] for p in resistance_pools if p["price"] > entry]
            next_pool = min(pools_above) if pools_above else None

            if next_pool:
                buffer = sl_dist_long * 0.1
                tp_before_pool = next_pool - buffer
                tp2 = max(tp1, tp_before_pool)
            else:
                tp2 = entry + sl_dist_long * 3

            tp3 = entry + sl_dist_long * 5

            entry_type = "LIMIT" if abs(limit_entry - entry) > atr * 0.1 else "MARKET"

        else:  # short
            import json

            # ── 1. Swing High/Low (Phase 2 & 3) ─────────────────────────────
            if len(ind.last_candles) >= 20:
                recent = ind.last_candles[-20:]
                swing_high = max(float(c["high"]) for c in recent)
                swing_low = min(float(c["low"]) for c in recent)
            else:
                swing_high = entry + atr * 2
                swing_low = entry - atr * 2
                
            swing_range = swing_high - swing_low
            if swing_range <= 0:
                swing_range = atr * 2
                swing_low = entry - atr

            # ── 2. Structural SL (Phase 3) ─────────────────────────────
            sl_warning = None
            pools = ind.liquidity_context.get("liquidity_pools", {}) if ind.liquidity_context else {}
            resistance_pools = pools.get("resistance_pools", [])
            pools_above = [p["price"] for p in resistance_pools if p["price"] > swing_high]
            nearest_pool = min(pools_above) if pools_above else swing_high
            
            sl = max(swing_high, nearest_pool) + (atr * 0.25)

            sl_distance_atr = abs(entry - sl) / atr
            if sl_distance_atr > 2.5:
                sl_warning = "⚠️ SL cấu trúc khá xa (>2.5 ATR), cân nhắc rủi ro."
            elif sl_distance_atr < 0.5:
                sl_warning = "⚠️ SL cấu trúc quá hẹp (<0.5 ATR), dễ bị quét (Stop Hunt)."



            # Retrace from swing low up
            fib_0_5 = swing_low + swing_range * 0.5
            fib_0_618 = swing_low + swing_range * 0.618
            fib_0_786 = swing_low + swing_range * 0.786

            entry_zone_top = max(entry, fib_0_5) if not is_tier_b else max(entry, fib_0_618)
            entry_zone_bottom = max(entry, fib_0_786)

            if not is_tier_b:
                dca = [
                    {"price": fib_0_5, "weight": 40},
                    {"price": fib_0_618, "weight": 35},
                    {"price": fib_0_786, "weight": 25}
                ]
            else:
                dca = [
                    {"price": fib_0_618, "weight": 50},
                    {"price": fib_0_786, "weight": 50}
                ]

            if ind.liquidity_context and "volume_profile" in ind.liquidity_context:
                lvn_zones = ind.liquidity_context["volume_profile"].get("lvn_zones", [])
                for d in dca:
                    p = d["price"]
                    for lvn in lvn_zones:
                        if lvn["bottom"] <= p <= lvn["top"]:
                            # Move price up to nearest better price (for SHORT, move up)
                            d["price"] = lvn["top"] + atr * 0.1
                            break

            for d in dca:
                if d["price"] < entry:
                    d["price"] = entry

            limit_entry = dca[0]["price"]
            entry_type = "LIMIT" if use_limit_entry else "MARKET"

            # ── 3. Liquidity-Aware TP (Phase 3) ──────────────────────────
            sl_dist_short = abs(sl - entry)
            tp1 = entry - sl_dist_short * 1.5

            support_pools = pools.get("support_pools", [])
            pools_below = [p["price"] for p in support_pools if p["price"] < entry]
            next_pool = max(pools_below) if pools_below else None

            if next_pool:
                buffer = sl_dist_short * 0.1
                tp_before_pool = next_pool + buffer
                tp2 = min(tp1, tp_before_pool)
            else:
                tp2 = entry - sl_dist_short * 3

            tp3 = entry - sl_dist_short * 5

            entry_type = "LIMIT" if abs(limit_entry - entry) > atr * 0.1 else "MARKET"

        sl_dist = abs(entry - sl)
        rr1 = abs(tp1 - entry) / sl_dist if sl_dist > 0 else 0
        rr2 = abs(tp2 - entry) / sl_dist if sl_dist > 0 else 0

        # Price-adaptive rounding: low-price coins need more decimals
        if entry < 1:
            dp = 6
        elif entry < 10:
            dp = 4
        elif entry < 100:
            dp = 3
        else:
            dp = 2

        return {
            "entry": round(entry, dp),
            "limit_entry": round(limit_entry, dp),
            "entry_type": entry_type,
            "entry_zone_top": round(entry_zone_top, dp),
            "entry_zone_bottom": round(entry_zone_bottom, dp),
            "dca_plan": json.dumps([{ "price": round(d["price"], dp), "weight": d["weight"] } for d in dca]),
            "sl": round(sl, dp),
            "sl_warning": sl_warning,
            "tp1": round(tp1, dp),
            "tp2": round(tp2, dp),
            "tp3": round(tp3, dp),
            "sl_pct": round(sl_dist / entry * 100, 2),
            "tp1_pct": round(abs(tp1 - entry) / entry * 100, 2),
            "tp2_pct": round(abs(tp2 - entry) / entry * 100, 2),
            "rr1": round(rr1, 2),
            "rr2": round(rr2, 2),
        }
