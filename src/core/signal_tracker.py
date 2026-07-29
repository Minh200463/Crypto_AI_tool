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
import json
from datetime import datetime, timezone

from src.database.signal_repository import (
    SignalRecord,
    expire_old_signals,
    get_open_signals,
    get_stats,
    log_signal,
    update_outcome,
    update_partial_close,
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
    liquidity_score: float = 0.0,
    score_breakdown: dict = None,
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
        status="waiting_trigger",
        liquidity_score=liquidity_score,
        entry_zone_top=levels.get("entry_zone_top"),
        entry_zone_bottom=levels.get("entry_zone_bottom"),
        dca_plan=levels.get("dca_plan"),
        score_breakdown=json.dumps(score_breakdown) if score_breakdown else None,
        notes=None,
    )


async def check_open_signals(binance_client) -> list[dict]:
    """
    Fetch historical 15m/1h klines for all open signals since they were fired
    and auto-update outcomes chronologically.
    Returns list of resolved signals (for notification).
    """
    await check_waiting_signals(binance_client)

    open_signals = get_open_signals()
    if not open_signals:
        logger.info("No open signals to check.")
        return []

    # Expire stale signals (Tier A: 7d, Tier B: 5d) before checking outcomes
    expire_old_signals()
    # Re-fetch open signals in case some were expired
    open_signals = get_open_signals()

    resolved = []
    # Group by symbol to batch klines fetches
    symbols = list({s.symbol for s in open_signals})

    klines_dict: dict[str, list[list]] = {}
    for sym in symbols:
        try:
            # Fetch last 200 1h klines (~8 days of data, covers Tier A 7-day expiry)
            # which is enough to find outcomes since fired_at
            klines = await binance_client.get_klines(sym, interval="1h", limit=200)
            klines_dict[sym] = klines
        except Exception as e:
            logger.warning("Could not fetch klines for %s: %s", sym, e)

    for sig in open_signals:
        klines = klines_dict.get(sig.symbol)
        if not klines:
            continue

        try:
            fired_dt = datetime.fromisoformat(sig.fired_at).replace(tzinfo=timezone.utc)
            fired_timestamp = int(fired_dt.timestamp() * 1000)
        except Exception:
            # fallback if fired_at isn't parseable ISO
            fired_timestamp = 0

        status = None
        pnl_pct = None
        outcome_price = None
        partially_closed = sig.partial_close_pct == 50.0

        for k in klines:
            # kline format: [open_time, open, high, low, close, volume, ...]
            open_time = int(k[0])
            if open_time < fired_timestamp:
                continue
            
            high = float(k[2])
            low = float(k[3])

            if sig.side == "long":
                # Check SL first
                if low <= sig.sl:
                    status = "sl_hit"
                    outcome_price = sig.sl
                    pnl_pct = round((outcome_price - sig.entry_price) / sig.entry_price * 100, 2)
                    break
                
                # Check TP2
                if sig.tp2 and high >= sig.tp2:
                    status = "tp2_hit"
                    outcome_price = sig.tp2
                    pnl_pct = round((outcome_price - sig.entry_price) / sig.entry_price * 100, 2)
                    break
                
                # Check TP1
                if not partially_closed and high >= sig.tp1:
                    partially_closed = True
                    update_partial_close(sig.id, 50.0, sig.entry_price)
                    sig.partial_close_pct = 50.0
                    sig.sl = sig.entry_price  # Move SL to breakeven in memory
                    resolved.append({
                        "id": sig.id,
                        "symbol": sig.symbol,
                        "side": sig.side,
                        "status": "tp1_partial",
                        "entry": sig.entry_price,
                        "outcome_price": sig.tp1,
                        "pnl_pct": round((sig.tp1 - sig.entry_price) / sig.entry_price * 100, 2),
                        "fired_at": sig.fired_at,
                    })

            else:  # short
                # Check SL first
                if high >= sig.sl:
                    status = "sl_hit"
                    outcome_price = sig.sl
                    pnl_pct = round((sig.entry_price - outcome_price) / sig.entry_price * 100, 2)
                    break
                
                # Check TP2
                if sig.tp2 and low <= sig.tp2:
                    status = "tp2_hit"
                    outcome_price = sig.tp2
                    pnl_pct = round((sig.entry_price - outcome_price) / sig.entry_price * 100, 2)
                    break
                
                # Check TP1
                if not partially_closed and low <= sig.tp1:
                    partially_closed = True
                    update_partial_close(sig.id, 50.0, sig.entry_price)
                    sig.partial_close_pct = 50.0
                    sig.sl = sig.entry_price
                    resolved.append({
                        "id": sig.id,
                        "symbol": sig.symbol,
                        "side": sig.side,
                        "status": "tp1_partial",
                        "entry": sig.entry_price,
                        "outcome_price": sig.tp1,
                        "pnl_pct": round((sig.entry_price - sig.tp1) / sig.entry_price * 100, 2),
                        "fired_at": sig.fired_at,
                    })

        if status:
            update_outcome(sig.id, status, outcome_price, pnl_pct)
            resolved.append({
                "id": sig.id,
                "symbol": sig.symbol,
                "side": sig.side,
                "status": status,
                "entry": sig.entry_price,
                "outcome_price": outcome_price,
                "pnl_pct": pnl_pct,
                "fired_at": sig.fired_at,
            })
            logger.info(
                "Signal #%d %s %s resolved: %s @ $%.2f (PnL: %.2f%%)",
                sig.id, sig.symbol, sig.side, status, outcome_price, pnl_pct,
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

    total    = stats["total"]
    full_wins = stats.get("full_wins", 0)
    tp1_wins  = stats.get("tp1_wins", 0)
    losses   = stats["losses"]
    expired  = stats["expired"]
    win_rate = stats["win_rate_pct"]
    scope    = f"*{symbol}*" if symbol else "toàn hệ thống"

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
        f"✅ Hit TP2 (full win): `{full_wins}` | ✅ Hit TP1: `{tp1_wins}` | ❌ SL: `{losses}` | ⌛ Hết hạn: `{expired}`",
        f"{wr_emoji} Win rate (weighted): `{win_rate}%`",
        f"   _TP2=1pt, TP1=0.5pt — phản ánh đúng chất lượng lệnh_",
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
        f"_Dùng /history để xem chi tiết từng lệnh._",
    ]

    return "\n".join(lines)


def format_performance_message() -> str:
    """Build a Telegram-ready performance report."""
    stats = get_stats()
    if stats.get("total", 0) == 0:
        return "Chưa có đủ dữ liệu để phân tích Performance."

    regime = stats.get("regime_breakdown", {})
    t = regime.get("trending", {"total": 0, "wins": 0})
    r = regime.get("ranging", {"total": 0, "wins": 0})
    tr = regime.get("transitional", {"total": 0, "wins": 0})
    
    t_wr = round(t["wins"] / t["total"] * 100, 1) if t["total"] else 0
    r_wr = round(r["wins"] / r["total"] * 100, 1) if r["total"] else 0
    tr_wr = round(tr["wins"] / tr["total"] * 100, 1) if tr["total"] else 0
    
    def bar(pct):
        filled = int(pct / 10)
        return "█" * filled + "░" * (10 - filled)
        
    lines = [
        "📊 *Performance Dashboard (Phase 7)*",
        "━━━━━━━━━━━━━━━━━━━━━━━━",
        "",
        "🌍 *Tổng quan Win Rate:*",
        f"`{stats.get('win_rate_pct', 0)}%` {bar(stats.get('win_rate_pct', 0))} `({stats.get('wins', 0)}/{stats.get('total', 0)})`",
        "",
        "📈 *Win Rate Theo Regime (Điều kiện thị trường):*",
        f"• *Trending* (ADX > 25):",
        f"  `{t_wr}%` {bar(t_wr)} `({t['wins']}/{t['total']})`",
        f"• *Ranging* (ADX < 20):",
        f"  `{r_wr}%` {bar(r_wr)} `({r['wins']}/{r['total']})`",
        f"• *Transitional*:",
        f"  `{tr_wr}%` {bar(tr_wr)} `({tr['wins']}/{tr['total']})`",
        "",
        "💡 _Nếu Win Rate ở giai đoạn Ranging suy giảm, hãy tăng điểm phạt ADX hoặc tạm ngưng trade._"
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

async def check_waiting_signals(binance_client):
    """
    [Phase 2] Scan signals in 'waiting_trigger' status.
    Check 1H candles:
    - If price touches entry_zone and confirms LTF trigger -> switch to 'open'.
    - If 4H candle closes beyond entry zone (invalidation) -> switch to 'invalidated'.
    """
    from src.database.signal_repository import get_waiting_signals
    from src.core.ta_service import TAService
    from src.database.db_adapter import get_conn, adapt_sql
    
    waiting_signals = get_waiting_signals()
    if not waiting_signals:
        return

    symbols = list({s.symbol for s in waiting_signals})
    klines_dict = {}
    for sym in symbols:
        try:
            klines = await binance_client.get_klines(sym, interval="1h", limit=50)
            klines_dict[sym] = klines
        except Exception as e:
            logger.warning("Could not fetch klines for waiting signal %s: %s", sym, e)

    for sig in waiting_signals:
        klines = klines_dict.get(sig.symbol)
        if not klines:
            continue
            
        try:
            fired_dt = datetime.fromisoformat(sig.fired_at).replace(tzinfo=timezone.utc)
            fired_timestamp = int(fired_dt.timestamp() * 1000)
        except Exception:
            fired_timestamp = 0

        # filter klines after signal was fired
        valid_klines = [k for k in klines if int(k[0]) >= fired_timestamp]
        if not valid_klines:
            continue
            
        # check if it touched entry zone
        touched = False
        invalidated = False
        for k in valid_klines:
            high = float(k[2])
            low = float(k[3])
            close = float(k[4])
            
            if sig.side == "long":
                if low <= sig.entry_zone_top:
                    touched = True
                if close < sig.entry_zone_bottom:
                    invalidated = True
            else:
                if high >= sig.entry_zone_bottom:
                    touched = True
                if close > sig.entry_zone_top:
                    invalidated = True
                    
        with get_conn() as conn:
            if invalidated:
                conn.execute(adapt_sql("UPDATE signal_logs SET status = 'invalidated' WHERE id = ?"), (sig.id,))
                logger.info("Signal %d INVALIDATED (Price closed beyond entry zone)", sig.id)
            elif touched:
                # check LTF confirmation on the most recent candles
                if TAService.confirm_ltf_trigger(sig.side, valid_klines):
                    conn.execute(adapt_sql("UPDATE signal_logs SET status = 'open' WHERE id = ?"), (sig.id,))
                    logger.info("Signal %d CONFIRMED and OPENED", sig.id)

def check_rolling_performance(limit: int = 20, threshold_pct: float = 40.0) -> str | None:
    """
    Check the win rate of the last N resolved signals.
    If it drops below the threshold, return an alert message string.
    Otherwise return None.
    """
    from src.database.db_adapter import get_conn, adapt_sql
    with get_conn() as conn:
        rows = conn.execute(
            adapt_sql("SELECT status FROM signal_logs WHERE status != 'open' AND status != 'waiting_trigger' ORDER BY fired_at DESC LIMIT ?"), (limit,)
        ).fetchall()
        
    if len(rows) < limit:
        return None  # Not enough data for a rolling window yet
        
    wins = 0.0
    for r in rows:
        status = r["status"]
        if status == "tp2_hit":
            wins += 1.0
        elif status == "tp1_hit":
            wins += 0.5
            
    win_rate = (wins / limit) * 100
    if win_rate < threshold_pct:
        return (
            f"⚠️ *CẢNH BÁO HIỆU SUẤT (Phase 7)* ⚠️\n"
            f"Win rate {limit} lệnh gần nhất đã giảm xuống `{win_rate:.1f}%` "
            f"(Dưới ngưỡng `{threshold_pct}%`).\n\n"
            f"Hệ thống có thể đang lệch Regime. Cần review lại các thông số hoặc tạm ngưng giao dịch."
        )
    return None
