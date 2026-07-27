from src.core.risk_engine import check_portfolio_risk, check_drawdown_circuit_breaker
from dataclasses import dataclass

@dataclass
class DummySignal:
    symbol: str
    side: str

# Test 1: Empty open signals
ok, msg = check_portfolio_risk("BTCUSDT", "LONG", [], 10000.0, 1.0)
print(f"Empty: {ok}, {msg}")

# Test 2: Over total risk (4%)
open_signals = [DummySignal("ADAUSDT", "LONG")] * 4
ok, msg = check_portfolio_risk("XRPUSDT", "LONG", open_signals, 10000.0, 1.0)
print(f"Over total risk: {ok}, {msg}")

# Test 3: Over correlation risk (BTC, ETH, SOL)
open_signals = [
    DummySignal("BTCUSDT", "LONG"),
    DummySignal("ETHUSDT", "LONG"),
]
ok, msg = check_portfolio_risk("SOLUSDT", "LONG", open_signals, 10000.0, 1.0)
print(f"Over correlation risk: {ok}, {msg}")

# Test 4: Circuit breaker (no data in DB should pass)
ok, msg = check_drawdown_circuit_breaker(10000.0, 1.0)
print(f"Circuit breaker (no data): {ok}, {msg}")

