"""
Walk-Forward Backtesting Engine for Crypto AI Tool (Phase 6).
Simulates trading over historical data to evaluate performance metrics.
"""

import pandas as pd
import sys
import os

# Add parent directory to path so we can import src
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from src.core.ta_service import TAService
import logging

logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger(__name__)

class BacktestEngine:
    def __init__(self, data_dir: str = 'data'):
        self.data_dir = data_dir
        self.ta_svc = TAService()
        
    def load_data(self, symbol: str) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
        df_4h = pd.read_csv(f"{self.data_dir}/{symbol}_4h.csv")
        df_1d = pd.read_csv(f"{self.data_dir}/{symbol}_1d.csv")
        df_1w = pd.read_csv(f"{self.data_dir}/{symbol}_1w.csv")
        
        # Sort just in case
        df_4h = df_4h.sort_values('open_time').reset_index(drop=True)
        df_1d = df_1d.sort_values('open_time').reset_index(drop=True)
        df_1w = df_1w.sort_values('open_time').reset_index(drop=True)
        return df_4h, df_1d, df_1w
        
    def run(self, symbol: str, initial_equity: float = 10000.0, risk_per_trade_pct: float = 1.0):
        try:
            df_4h, df_1d, df_1w = self.load_data(symbol)
        except Exception as e:
            logger.error(f"Failed to load data for {symbol}: {e}")
            return
            
        logger.info(f"Loaded {len(df_4h)} 4H candles, {len(df_1d)} 1D candles, {len(df_1w)} 1W candles for {symbol}")
        
        # Convert DataFrames to list of lists for ta_service
        raw_1d = df_1d.values.tolist()
        raw_1w = df_1w.values.tolist()
        
        # We need at least 200 candles to compute indicators
        if len(df_4h) < 200:
            logger.error("Not enough 4H data.")
            return
            
        equity = initial_equity
        trades = []
        
        # We will iterate through 4H candles from index 200 to the end
        # We also need to map the current 4H time to the correct 1D and 1W candles
        
        for i in range(200, len(df_4h)):
            # Simulated current time is the close_time of the (i-1)th candle 
            # We are making a decision at the open of the i-th candle.
            # Actually, `ta_service` expects up to the CURRENT candle.
            
            # Extract 200 candles up to index i (inclusive)
            chunk_4h = df_4h.iloc[i-199:i+1].values.tolist()
            current_time = chunk_4h[-1][0] # open_time
            
            # Find the most recent 1D and 1W candles up to current_time
            # For backtesting simplicity, we just filter by open_time <= current_time
            # and take the last 60 for 1D, 52 for 1W
            chunk_1d = [row for row in raw_1d if row[0] <= current_time][-60:]
            chunk_1w = [row for row in raw_1w if row[0] <= current_time][-52:]
            
            if not chunk_1d or not chunk_1w:
                logger.error(f"Error: {e}")
                continue
                
            try:
                ind = self.ta_svc.compute_indicators(symbol, "4h", chunk_4h)
                daily_trend = self.ta_svc.get_daily_trend(chunk_1d)
                weekly_trend = self.ta_svc.get_weekly_trend(chunk_1w)
                
                long_score, long_reasons = self.ta_svc.score_long_setup(ind, daily_trend, weekly_trend)
                short_score, short_reasons = self.ta_svc.score_short_setup(ind, daily_trend, weekly_trend)
                
                best_score = max(long_score, short_score)
                
                if best_score >= 6: # Tier B or A
                    side = "LONG" if long_score >= short_score else "SHORT"
                    
                    # We have a signal. Let's record it and evaluate outcome
                    # To evaluate outcome, we need to look ahead in df_4h
                    
                    is_tier_b = best_score < 8
                    levels = self.ta_svc.calculate_trade_levels(side, ind.current_price, ind, is_tier_b=is_tier_b)
                    
                    outcome = self._simulate_trade(df_4h, i+1, side, levels, is_tier_b)
                    
                    if outcome:
                        pnl_pct = outcome['pnl_pct']
                        # Position sizing: risk_usd = equity * risk_per_trade_pct
                        # If SL hit, we lose risk_usd. 
                        # Trade PNL = (risk_usd / sl_distance_pct) * pnl_pct
                        sl_dist_pct = abs(entry - sl) / entry * 100
                        if sl_dist_pct > 0:
                            trade_pnl = (equity * (risk_per_trade_pct/100) / (sl_dist_pct/100)) * (pnl_pct/100)
                            equity += trade_pnl
                            
                            trades.append({
                                'time': pd.to_datetime(current_time, unit='ms'),
                                'side': side,
                                'score': best_score,
                                'regime': ind.market_regime,
                                'outcome': outcome['type'],
                                'pnl_pct': pnl_pct,
                                'equity': equity
                            })
                            
                            # Skip ahead a few candles if we entered a trade to avoid overlapping signals
                            # Not skipping for now, let's just log them all (might overlap)
                            
            except Exception as e:
                # Some candles might cause math errors
                logger.error(f"Error: {e}")
                continue
                
        self._print_report(trades, initial_equity, equity)
        
    def _simulate_trade(self, df_4h: pd.DataFrame, start_idx: int, side: str, levels: dict, is_tier_b: bool) -> dict | None:
        import json
        dca_plan = json.loads(levels.get("dca_plan", "[]"))
        
        sl = levels['sl']
        tp1 = levels['tp1']
        tp2 = levels.get('tp2')
        tp3 = levels.get('tp3')
        
        # State tracking
        current_sl = sl
        dca_hits = []
        hit_tp1 = False
        hit_tp2 = False
        
        # Look ahead up to 42 candles (7 days * 6 4H candles)
        for j in range(start_idx, min(start_idx + 42, len(df_4h))):
            candle = df_4h.iloc[j]
            high = candle['high']
            low = candle['low']
            
            # Fill DCA
            for tranche in dca_plan:
                p = tranche["price"]
                if tranche not in dca_hits:
                    if (side == "LONG" and low <= p) or (side == "SHORT" and high >= p):
                        dca_hits.append(tranche)
            
            if not dca_hits:
                # If price hasn't hit any entry level yet, continue looking
                # But if price goes to SL/TP1 before any entry is hit, the trade never triggers.
                # Simplified: if it hits SL before entry, trade is invalidated.
                if (side == "LONG" and low <= current_sl) or (side == "SHORT" and high >= current_sl):
                    return None # Never entered
                continue
                
            # Calculate current weighted entry
            weighted_entry = sum(t["price"] * (t["weight"]/100) for t in dca_hits) / sum(t["weight"]/100 for t in dca_hits)
            
            if side == "LONG":
                if low <= current_sl:
                    if hit_tp1:
                        # Stopped out at breakeven after TP1
                        return {'type': 'Partial Win (BE)', 'pnl_pct': (current_sl - weighted_entry) / weighted_entry * 100}
                    return {'type': 'SL', 'pnl_pct': (current_sl - weighted_entry) / weighted_entry * 100}
                    
                if high >= tp1 and not hit_tp1:
                    if is_tier_b or not tp2:
                        return {'type': 'TP1', 'pnl_pct': (tp1 - weighted_entry) / weighted_entry * 100}
                    # Hit TP1, move SL to breakeven
                    hit_tp1 = True
                    current_sl = weighted_entry
                
                if hit_tp1 and tp2 and high >= tp2 and not hit_tp2:
                    if not tp3:
                        return {'type': 'TP2', 'pnl_pct': (tp2 - weighted_entry) / weighted_entry * 100}
                    hit_tp2 = True
                    
                if hit_tp2 and tp3 and high >= tp3:
                    return {'type': 'TP3', 'pnl_pct': (tp3 - weighted_entry) / weighted_entry * 100}
            else:
                if high >= current_sl:
                    if hit_tp1:
                        return {'type': 'Partial Win (BE)', 'pnl_pct': (weighted_entry - current_sl) / weighted_entry * 100}
                    return {'type': 'SL', 'pnl_pct': (weighted_entry - current_sl) / weighted_entry * 100}
                    
                if low <= tp1 and not hit_tp1:
                    if is_tier_b or not tp2:
                        return {'type': 'TP1', 'pnl_pct': (weighted_entry - tp1) / weighted_entry * 100}
                    hit_tp1 = True
                    current_sl = weighted_entry
                    
                if hit_tp1 and tp2 and low <= tp2 and not hit_tp2:
                    if not tp3:
                        return {'type': 'TP2', 'pnl_pct': (weighted_entry - tp2) / weighted_entry * 100}
                    hit_tp2 = True
                    
                if hit_tp2 and tp3 and low <= tp3:
                    return {'type': 'TP3', 'pnl_pct': (weighted_entry - tp3) / weighted_entry * 100}
        
        # Expired
        if not dca_hits:
            return None
            
        weighted_entry = sum(t["price"] * (t["weight"]/100) for t in dca_hits) / sum(t["weight"]/100 for t in dca_hits)
        close_price = df_4h.iloc[start_idx + 41]['close']
        pnl_pct = (close_price - weighted_entry) / weighted_entry * 100 if side == "LONG" else (weighted_entry - close_price) / weighted_entry * 100
        return {'type': 'EXPIRED', 'pnl_pct': pnl_pct}
        
    def _print_report(self, trades: list, initial_equity: float, final_equity: float):
        logger.warning("⚠️ Backtest này KHÔNG bao gồm order book/funding — chỉ test phần dựa trên OHLCV (MTF, scoring, structural SL/TP, DCA).")
        
        if not trades:
            logger.info("No trades executed.")
            return
            
        wins = [t for t in trades if t['pnl_pct'] > 0]
        losses = [t for t in trades if t['pnl_pct'] < 0]
        
        win_rate = len(wins) / len(trades) * 100
        
        gross_profit = sum(t['pnl_pct'] for t in wins)
        gross_loss = abs(sum(t['pnl_pct'] for t in losses))
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else float('inf')
        
        logger.info("\n" + "="*50)
        logger.info(f"BACKTEST RESULTS (Phase 6)")
        logger.info("="*50)
        logger.info(f"Total Trades : {len(trades)}")
        logger.info(f"Win Rate     : {win_rate:.1f}% ({len(wins)}W / {len(losses)}L)")
        logger.info(f"Profit Factor: {profit_factor:.2f}")
        logger.info(f"Start Equity : ${initial_equity:,.2f}")
        logger.info(f"Final Equity : ${final_equity:,.2f}")
        logger.info(f"Net Profit   : {((final_equity - initial_equity)/initial_equity)*100:.1f}%")
        
        # By regime
        for regime in ["trending", "ranging", "transitional"]:
            regime_trades = [t for t in trades if t['regime'] == regime]
            if regime_trades:
                r_wins = len([t for t in regime_trades if t['pnl_pct'] > 0])
                r_wr = r_wins / len(regime_trades) * 100
                logger.info(f" - {regime.capitalize():12} : {len(regime_trades)} trades, {r_wr:.1f}% WR")
                
        logger.info("="*50)


if __name__ == "__main__":
    engine = BacktestEngine()
    engine.run("BTCUSDT")
