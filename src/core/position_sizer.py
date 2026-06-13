"""
Position Sizer — ATR/SL-based position sizing engine.

Formula (Risk-based sizing):
    risk_amount_usdt = equity × risk_pct / 100
    position_usdt    = risk_amount_usdt / (sl_pct / 100)
    quantity         = position_usdt / entry_price
    effective_lev    = position_usdt / equity

Tier-aware:
  - Tier A (≥8 pts): use configured risk_pct as-is
  - Tier B (6-7 pts): risk_pct auto-halved to protect capital on weaker setups

Safety caps:
  - position_usdt capped at 80% of equity (never over-expose)
  - Warnings emitted if effective leverage > 5x or > 10x
"""
from dataclasses import dataclass, field


@dataclass
class PositionSizeResult:
    """Full position sizing output ready for display."""
    # Inputs
    equity: float
    raw_risk_pct: float           # User-configured risk %
    effective_risk_pct: float     # After tier adjustment
    tier: str
    entry_price: float
    sl_pct: float

    # Outputs
    risk_amount_usdt: float       # Max loss in USDT
    position_usdt: float          # Total position value in USDT
    quantity: float               # Number of coins/contracts
    effective_leverage: float     # position_usdt / equity

    warnings: list[str] = field(default_factory=list)
    capped: bool = False          # True if position was capped at 80% equity


def calculate_position_size(
    equity: float,
    risk_pct: float,
    entry_price: float,
    sl_pct: float,
    tier: str = "A",
) -> PositionSizeResult:
    """
    Calculate position size based on equity, risk tolerance, and SL distance.

    Args:
        equity:     Total account equity in USDT
        risk_pct:   Max % of equity to risk per trade (e.g. 1.0 for 1%)
        entry_price: Coin/contract entry price
        sl_pct:     Stop loss distance from entry in % (e.g. 2.5 for 2.5%)
        tier:       Signal tier — 'A' (full risk) or 'B' (half risk)

    Returns:
        PositionSizeResult with all calculated fields
    """
    raw_risk_pct = risk_pct
    # Tier B: auto-halve risk to protect capital on weaker setups
    effective_risk_pct = risk_pct if tier == "A" else risk_pct / 2.0

    # Guard: prevent division by zero
    if sl_pct <= 0:
        sl_pct = 2.0  # safe fallback

    risk_amount_usdt = equity * effective_risk_pct / 100.0
    position_usdt    = risk_amount_usdt / (sl_pct / 100.0)

    # Safety cap: never expose more than 80% of equity in one trade
    capped = False
    max_position = equity * 0.80
    if position_usdt > max_position:
        position_usdt = max_position
        capped = True

    quantity = position_usdt / entry_price
    effective_leverage = position_usdt / equity

    warnings: list[str] = []
    if tier == "B":
        warnings.append(f"ℹ️ Tier B: Risk% tự động giảm 50% ({raw_risk_pct}% → {effective_risk_pct}%)")
    if capped:
        warnings.append("⚠️ Vị thế đã bị giới hạn ở 80% vốn — SL quá rộng")
    if effective_leverage > 10:
        warnings.append("🚨 Đòn bẩy hiệu quả > 10x — rủi ro RẤT CAO")
    elif effective_leverage > 5:
        warnings.append("⚠️ Đòn bẩy hiệu quả > 5x — kiểm tra lại SL")

    return PositionSizeResult(
        equity=equity,
        raw_risk_pct=raw_risk_pct,
        effective_risk_pct=effective_risk_pct,
        tier=tier,
        entry_price=entry_price,
        sl_pct=sl_pct,
        risk_amount_usdt=round(risk_amount_usdt, 2),
        position_usdt=round(position_usdt, 2),
        quantity=round(quantity, 6),
        effective_leverage=round(effective_leverage, 2),
        warnings=warnings,
        capped=capped,
    )


def format_position_block(ps: PositionSizeResult) -> str:
    """
    Format a PositionSizeResult into a Telegram-ready multi-line string.
    Used directly in signal_handler output.
    """
    lev_emoji = "🚨" if ps.effective_leverage > 10 else (
                "⚠️" if ps.effective_leverage > 5 else "✅")

    lines = [
        f"💼 *Position Size (tự động):*",
        f"   Vốn: `${ps.equity:,.0f}` | Rủi ro: `{ps.effective_risk_pct}%` "
        f"(`${ps.risk_amount_usdt:,.2f}` USDT)",
        f"   📊 Vào lệnh: `${ps.position_usdt:,.2f}` USDT "
        f"_({ps.position_usdt / ps.equity * 100:.1f}% vốn)_",
        f"   🪙 Số lượng: `{ps.quantity:,.6f}` coins",
        f"   {lev_emoji} Đòn bẩy hiệu quả: `~{ps.effective_leverage:.1f}x`",
    ]
    for w in ps.warnings:
        lines.append(f"   {w}")

    return "\n".join(lines)
