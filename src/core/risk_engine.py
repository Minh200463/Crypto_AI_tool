"""
Risk Engine — Portfolio and Correlation Risk Management.
Phase 5 of the Trader-Driven Update Roadmap.
"""
import logging
from datetime import datetime, timedelta, timezone
from src.database.db_adapter import get_conn, adapt_sql

logger = logging.getLogger(__name__)

# Basic correlation groups for major coins
CORRELATION_GROUPS = [
    {"BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT"},
    {"DOGEUSDT", "SHIBUSDT", "PEPEUSDT", "FLOKIUSDT"},
]

def is_correlated(symbol1: str, symbol2: str) -> bool:
    if symbol1 == symbol2:
        return True
    for group in CORRELATION_GROUPS:
        if symbol1 in group and symbol2 in group:
            return True
    return False

def check_portfolio_risk(
    new_signal_symbol: str,
    new_signal_side: str,
    open_signals: list,
    equity: float,
    user_risk_pct: float,
    max_total_risk_pct: float = 4.0
) -> tuple[bool, str]:
    """
    Check if a new signal would exceed the portfolio risk limits.
    Since we don't have exact position sizing in SignalRecord, we assume each trade risks `user_risk_pct` of equity.
    Returns (True, "") if allowed, (False, reason) if blocked.
    """
    if not open_signals:
        return True, ""
        
    risk_per_trade = equity * (user_risk_pct / 100.0)
    
    correlated_direction_risk = 0.0
    total_open_risk = 0.0
    
    for s in open_signals:
        # Assuming s is a SignalRecord
        total_open_risk += risk_per_trade
        if s.side == new_signal_side and is_correlated(s.symbol, new_signal_symbol):
            correlated_direction_risk += risk_per_trade
            
    # Add the new signal's risk
    total_open_risk += risk_per_trade
    correlated_direction_risk += risk_per_trade
    
    # 1. Total Portfolio Risk Check
    max_allowed_total = equity * (max_total_risk_pct / 100.0)
    if total_open_risk > max_allowed_total:
        return False, f"Vượt ngưỡng tổng rủi ro ({max_total_risk_pct}% tài khoản)"
        
    # 2. Correlation Risk Check (Max 70% of max_total_risk_pct on highly correlated assets in same direction)
    max_allowed_correlated = max_allowed_total * 0.7
    if correlated_direction_risk > max_allowed_correlated:
        return False, "Rủi ro tương quan quá cao (cược cùng 1 chiều trên các coin chạy giống nhau)"
        
    return True, ""


def check_drawdown_circuit_breaker(equity: float, user_risk_pct: float, max_drawdown_pct: float = 8.0, days: int = 7) -> tuple[bool, str]:
    """
    Check if the simulated equity drawdown over the last `days` exceeds `max_drawdown_pct`.
    Simulated equity is calculated based on closed signals (pnl_pct relative to entry, sized by user_risk_pct / sl_pct).
    Returns (True, "") if allowed (or no severe drawdown), (False, warning) if circuit breaker tripped.
    """
    try:
        cutoff_date = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        
        with get_conn() as conn:
            cursor = conn.cursor()
            # We get all closed signals (status not 'open' and not 'waiting_trigger')
            cursor.execute(adapt_sql("""
                SELECT pnl_pct, sl_pct 
                FROM signal_logs 
                WHERE status NOT IN ('open', 'waiting_trigger') 
                AND outcome_at >= ?
                ORDER BY outcome_at ASC
            """), (cutoff_date,))
            rows = cursor.fetchall()
            
        if not rows:
            return True, ""
            
        simulated_equity = equity
        peak_equity = equity
        
        for row in rows:
            pnl_pct, sl_pct = row[0], row[1]
            if pnl_pct is None or sl_pct is None or sl_pct <= 0:
                continue
                
            # If user risks X% at SL, then position size = (X% * equity) / SL%
            # PNL = position size * PNL%
            trade_pnl = (simulated_equity * (user_risk_pct / 100.0) / (sl_pct / 100.0)) * (pnl_pct / 100.0)
            simulated_equity += trade_pnl
            
            if simulated_equity > peak_equity:
                peak_equity = simulated_equity
                
        current_drawdown = (peak_equity - simulated_equity) / peak_equity * 100.0
        
        if current_drawdown > max_drawdown_pct:
            return False, f"Drawdown 7 ngày qua đạt {current_drawdown:.1f}% (> {max_drawdown_pct}%). Hệ thống tạm ngưng để bảo vệ vốn."
            
        return True, ""
        
    except Exception as e:
        logger.error("Drawdown circuit breaker error: %s", e)
        return True, ""
