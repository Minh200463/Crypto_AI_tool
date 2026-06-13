"""
Signal Tracker — auto-checks open signal outcomes against live prices.

Called by:
  - Background scheduler (every 4H)
  - On-demand via /checkoutcomes Telegram command

Outcome check logic (priority order — SL first, then TP2, then TP1):
  - LONG: SL hit if price <= sl | TP2 hit if price >= tp2 | TP1 hit if price >= tp1
  - SHORT: SL hit if price >= sl | TP2 hit if price <= tp2 | TP1 hit if price <= tp1

Expiry policy (tier-based):
  - Tier A (8+ pts): 7 days — strong setups may need time on sideways market
  - Tier B (6-7 pts): 5 days — weaker setups, exit faster if not triggered

Known limitations:
  - outcome_at records the polling job execution time, NOT the exact candle
    when TP/SL was hit. Acceptable for statistical use; not for timing analysis.
  - Win is defined as first outcome = tp1_hit or tp2_hit. Partial close + reversal
    to SL still counts as win. No partial_close field in v1 schema.
"""
import logging
from datetime import datetime, timezone

from src.database.signal_repository import (
    SignalRecord,
    expire_old_signals,
    get_open_signals,
    get_stats,
    log_signal,
    update_outcome,
)

logger = logging.getLogger(__name__)


def build_signal_record(
    symbol: str,
    side: str,
    score: int,
    tier: str,
    daily_trend: str,
    market_regime: str,
    adx: float,
    levels: dict,
) -> SignalRecord:
    """Helper to create a SignalRecord from signal_handler data."""
    now = datetime.now(timezone.utc).isoformat()
    return SignalRecord(
        id=None,
        symbol=symbol.upper(),
        side=side,
        score=score,
        tier=tier,
        daily_trend=daily_trend,
        market_regime=market_regime,
        adx=round(adx, 2),
        entry_price=levels["entry"],
        limit_entry=levels.get("limit_entry"),
        sl=levels["sl"],
        tp1=levels["tp1"],
        tp2=levels.get("tp2"),
        tp3=levels.get("tp3"),
        sl_pct=levels.get("sl_pct"),
        rr1=levels.get("rr1"),
        rr2=levels.get("rr2"),
        fired_at=now,
    )


async def check_open_signals(binance_client) -> list[dict]:
    """
    Fetch live prices for all open signals and auto-update outcomes.
    Returns list of resolved signals (for notification).
    """
    open_signals = get_open_signals()
    if not open_signals:
        logger.info("No open signals to check.")
        return []

    # Expire stale signals (Tier A: 7d, Tier B: 5d) before checking outcomes
    expire_old_signals()

    resolved = []
    # Group by symbol to batch price fetches
    symbols = list({s.symbol for s in open_signals})

    prices: dict[str, float] = {}
    for sym in symbols:
        try:
            ticker = await binance_client.get_ticker(sym)
            prices[sym] = ticker["price"]
        except Exception as e:
            logger.warning("Could not fetch price for %s: %s", sym, e)

    for sig in open_signals:
        price = prices.get(sig.symbol)
        if price is None:
            continue

        status = None
        pnl_pct = None

        if sig.side == "long":
            if price <= sig.sl:
                status = "sl_hit"
                pnl_pct = round((price - sig.entry_price) / sig.entry_price * 100, 2)
            elif sig.tp2 and price >= sig.tp2:
                status = "tp2_hit"
                pnl_pct = round((price - sig.entry_price) / sig.entry_price * 100, 2)
            elif price >= sig.tp1:
                status = "tp1_hit"
                pnl_pct = round((price - sig.entry_price) / sig.entry_price * 100, 2)
        else:  # short
            if price >= sig.sl:
                status = "sl_hit"
                pnl_pct = round((sig.entry_price - price) / sig.entry_price * 100, 2)
            elif sig.tp2 and price <= sig.tp2:
                status = "tp2_hit"
                pnl_pct = round((sig.entry_price - price) / sig.entry_price * 100, 2)
            elif price <= sig.tp1:
                status = "tp1_hit"
                pnl_pct = round((sig.entry_price - price) / sig.entry_price * 100, 2)

        if status:
            update_outcome(sig.id, status, price, pnl_pct)
            resolved.append({
                "id": sig.id,
                "symbol": sig.symbol,
                "side": sig.side,
                "status": status,
                "entry": sig.entry_price,
                "outcome_price": price,
                "pnl_pct": pnl_pct,
                "fired_at": sig.fired_at,
            })
            logger.info(
                "Signal #%d %s %s resolved: %s @ $%.2f (PnL: %.2f%%)",
                sig.id, sig.symbol, sig.side, status, price, pnl_pct,
            )

    return resolved


def format_stats_message(symbol: str | None = None) -> str:
    """Build a Telegram-ready stats summary string."""
    stats = get_stats(symbol)

    if stats.get("total", 0) == 0:
        scope = f"*{symbol}*" if symbol else "toàn hệ thống"
        return (
            f"📊 *Thống kê tín hiệu — {scope}*\n\n"
            f"Chưa có signal nào được ghi nhận.\n"
            f"_Hãy dùng /signal để tạo signal đầu tiên!_"
        )

    total = stats["total"]
    wins = stats["wins"]
    losses = stats["losses"]
    expired = stats["expired"]
    win_rate = stats["win_rate_pct"]
    scope = f"*{symbol}*" if symbol else "toàn hệ thống"

    # Win rate emoji
    if win_rate >= 65:
        wr_emoji = "🟢"
    elif win_rate >= 50:
        wr_emoji = "🟡"
    else:
        wr_emoji = "🔴"

    lines = [
        f"📊 *Thống kê tín hiệu — {scope}*",
        f"────────────────────────────",
        f"",
        f"📈 Tổng signal: `{total}`",
        f"✅ Thắng: `{wins}` | ❌ Thua: `{losses}` | ⌛ Hết hạn: `{expired}`",
        f"{wr_emoji} Win rate: `{win_rate}%`",
        f"",
        f"💰 Avg lãi/lệnh thắng: `+{stats['avg_win_pnl_pct']}%`",
        f"💸 Avg lỗ/lệnh thua:   `{stats['avg_loss_pnl_pct']}%`",
        f"",
        f"📋 *Phân tích theo Tier:*",
        f"⭐⭐⭐ Tier A (7d expire): `{stats['tier_a_wins']}/{stats['tier_a_total']}` thắng "
        f"({stats['tier_a_win_rate']}%)",
        f"⭐⭐ Tier B (5d expire): `{stats['tier_b_wins']}/{stats['tier_b_total']}` thắng "
        f"({stats['tier_b_win_rate']}%)",
        f"",
        f"_\u26a0\ufe0f Win = chạm TP1 hoặc TP2 (first outcome). "
        f"Tham khảo /history để xem chi tiết._",
    ]

    return "\n".join(lines)


def format_recent_signals_message(limit: int = 8) -> str:
    """Build a summary of the last N signals for display."""
    from src.database.signal_repository import get_recent_signals
    records = get_recent_signals(limit)

    if not records:
        return "📭 Chưa có signal nào được ghi nhận."

    STATUS_ICON = {
        "open":    "⏳",
        "tp1_hit": "✅ TP1",
        "tp2_hit": "✅ TP2",
        "sl_hit":  "❌ SL",
        "expired": "⌛",
    }

    lines = ["📜 *Lịch sử Signal gần đây:*", "━━━━━━━━━━━━━━━━━━━━━━━━━━━━"]
    for r in records:
        icon = STATUS_ICON.get(r.status, r.status)
        side_icon = "🟢" if r.side == "long" else "🔴"
        date_str = r.fired_at[:10]  # YYYY-MM-DD
        pnl_str = f" | PnL: `{r.pnl_pct:+.2f}%`" if r.pnl_pct is not None else ""
        lines.append(
            f"{side_icon} `{r.symbol}` {r.side.upper()} "
            f"| Score: `{r.score}/10` "
            f"| {icon}{pnl_str} "
            f"| _{date_str}_"
        )

    return "\n".join(lines)
