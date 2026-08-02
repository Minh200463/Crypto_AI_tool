import pytest
from src.core.position_sizer import calculate_position_size, format_position_block

def test_calculate_position_size_tier_a():
    ps = calculate_position_size(equity=10000, risk_pct=1.0, entry_price=50000, sl_pct=2.0, tier="A")
    assert ps.effective_risk_pct == 1.0
    assert ps.risk_amount_usdt == 100.0
    assert ps.position_usdt == 5000.0
    assert ps.quantity == 0.1
    assert ps.capital_utilization == 0.5
    assert not ps.capped

def test_calculate_position_size_tier_b():
    ps = calculate_position_size(equity=10000, risk_pct=1.0, entry_price=50000, sl_pct=2.0, tier="B")
    assert ps.effective_risk_pct == 0.5
    assert ps.risk_amount_usdt == 50.0
    assert ps.position_usdt == 2500.0
    assert ps.quantity == 0.05
    assert ps.capital_utilization == 0.25
    assert not ps.capped
    assert "Tier B: Risk% tự động giảm 50%" in ps.warnings[0]

def test_calculate_position_size_capped():
    # sl_pct is very tight, so position size would exceed 80% equity
    ps = calculate_position_size(equity=10000, risk_pct=1.0, entry_price=50000, sl_pct=0.5, tier="A")
    # risk_amount = 100
    # ideal position = 100 / (0.5/100) = 20000
    # capped at 80% equity = 8000
    assert ps.position_usdt == 8000.0
    assert ps.capped
    assert "Vị thế đã bị giới hạn ở 80% vốn" in ps.warnings[0]

def test_calculate_position_size_zero_sl():
    ps = calculate_position_size(equity=10000, risk_pct=1.0, entry_price=50000, sl_pct=0.0, tier="A")
    # fallback to 2.0%
    assert ps.sl_pct == 2.0 
    # risk_amount_usdt = equity * effective_risk_pct / 100.0 = 100
    # position_usdt = 100 / (2.0/100) = 5000
    assert ps.position_usdt == 5000.0

def test_format_position_block():
    ps = calculate_position_size(equity=10000, risk_pct=1.0, entry_price=50000, sl_pct=2.0, tier="A")
    text = format_position_block(ps)
    assert "Vốn: `$10,000`" in text
    assert "Rủi ro: `1.0%`" in text
    assert "Vào lệnh: `$5,000.00` USDT" in text
