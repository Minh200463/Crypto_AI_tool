import pytest
from src.core.risk_engine import check_portfolio_risk, is_correlated
from dataclasses import dataclass

@dataclass
class MockSignal:
    symbol: str
    side: str

def test_check_portfolio_risk_allow():
    open_signals = [MockSignal("BTCUSDT", "long")]
    # Max risk is 4.0%, user risk is 1.0%, currently 1 trade open.
    # Adding a 2nd trade takes total risk to 2.0% < 4.0%.
    # Adding ETHUSDT long (correlated) -> correlated risk = 2.0%
    # max_allowed_correlated = 4.0 * 0.7 = 2.8%
    # So 2.0% < 2.8%, should allow.
    ok, msg = check_portfolio_risk(
        new_signal_symbol="ETHUSDT",
        new_signal_side="long",
        open_signals=open_signals,
        equity=10000,
        user_risk_pct=1.0,
        max_total_risk_pct=4.0
    )
    assert ok
    assert msg == ""

def test_check_portfolio_risk_total_blocked():
    # 3 trades open at 1.0% risk each -> 3.0%
    # New trade adds 1.0% -> 4.0%. 
    # Let's say we have 4 trades open, adding 5th -> 5.0% > 4.0%
    open_signals = [
        MockSignal("XRPUSDT", "long"),
        MockSignal("ADAUSDT", "long"),
        MockSignal("DOTUSDT", "short"),
        MockSignal("LINKUSDT", "short")
    ]
    ok, msg = check_portfolio_risk(
        new_signal_symbol="LTCUSDT",
        new_signal_side="long",
        open_signals=open_signals,
        equity=10000,
        user_risk_pct=1.0,
        max_total_risk_pct=4.0
    )
    assert not ok
    assert "Vượt ngưỡng tổng rủi ro" in msg

def test_check_portfolio_risk_correlation_blocked():
    # 2 correlated trades open: BTC, ETH (both long)
    # Adding 3rd correlated: SOL (long)
    # Total correlated = 3.0% > 2.8% (which is 4.0 * 0.7)
    open_signals = [
        MockSignal("BTCUSDT", "long"),
        MockSignal("ETHUSDT", "long"),
    ]
    ok, msg = check_portfolio_risk(
        new_signal_symbol="SOLUSDT",
        new_signal_side="long",
        open_signals=open_signals,
        equity=10000,
        user_risk_pct=1.0,
        max_total_risk_pct=4.0
    )
    assert not ok
    assert "Rủi ro tương quan quá cao" in msg

def test_check_portfolio_risk_correlation_opposite_side_allowed():
    # 2 correlated trades open: BTC (long), ETH (long)
    # Adding SOL (short). Correlation only counts if same direction.
    open_signals = [
        MockSignal("BTCUSDT", "long"),
        MockSignal("ETHUSDT", "long"),
    ]
    ok, msg = check_portfolio_risk(
        new_signal_symbol="SOLUSDT",
        new_signal_side="short",
        open_signals=open_signals,
        equity=10000,
        user_risk_pct=1.0,
        max_total_risk_pct=4.0
    )
    assert ok
