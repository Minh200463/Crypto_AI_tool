"""
Signal Repository — SQLite-backed storage for all fired signals.
Uses Python's built-in sqlite3 (no ORM dependency).

Schema: signal_logs table
  - Stores every signal fired by the bot
  - Auto-tracks outcome when price hits TP1 / TP2 / SL
  - Used for win-rate stats and backtesting
"""
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from src.database.db_adapter import get_conn, adapt_sql

logger = logging.getLogger(__name__)

def init_db() -> None:
    """Create DB and tables if they don't exist. Safe to call multiple times."""
    with get_conn() as conn:
        conn.execute(adapt_sql("""
            CREATE TABLE IF NOT EXISTS signal_logs (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol         TEXT    NOT NULL,
                side           TEXT    NOT NULL,      -- 'long' | 'short'
                score          INTEGER NOT NULL,
                tier           TEXT    NOT NULL,      -- 'A' | 'B'
                daily_trend    TEXT,
                market_regime  TEXT,
                adx            REAL,
                entry_price    REAL    NOT NULL,
                limit_entry    REAL,
                sl             REAL    NOT NULL,
                tp1            REAL    NOT NULL,
                tp2            REAL,
                tp3            REAL,
                sl_pct         REAL,
                rr1            REAL,
                rr2            REAL,
                fired_at       TEXT    NOT NULL,      -- ISO-8601 UTC
                status         TEXT    DEFAULT 'open',-- 'open'|'tp1_hit'|'tp2_hit'|'sl_hit'|'expired'
                outcome_price  REAL,
                -- NOTE: outcome_at is the time the 4H polling job detected the outcome,
                -- NOT the exact candle time when TP/SL was actually hit.
                -- For statistical backtesting this is acceptable, but do not use
                -- outcome_at for precise timing analysis.
                outcome_at     TEXT,
                pnl_pct        REAL,
                -- partial_close_pct: % of position closed so far
                -- 0 = not yet closed | 50 = closed 50% at TP1 | 100 = fully closed
                partial_close_pct REAL DEFAULT 0,
                -- market_type: which engine/market generated this signal
                -- 'spot' | 'futures' | 'auto' (default — current hybrid engine)
                market_type    TEXT    DEFAULT 'auto',
                notes          TEXT
            )
        """))
        # Composite index for get_open_signals() — most frequent query
        conn.execute(adapt_sql("""
            CREATE INDEX IF NOT EXISTS idx_signal_status
            ON signal_logs (status, symbol)
        """))
        # Separate index for symbol-only filter in get_stats(symbol=...)
        conn.execute(adapt_sql("""
            CREATE INDEX IF NOT EXISTS idx_signal_symbol
            ON signal_logs (symbol)
        """))
        # Safe migration: add partial_close_pct to existing DBs
        try:
            conn.execute(adapt_sql("ALTER TABLE signal_logs ADD COLUMN partial_close_pct REAL DEFAULT 0"))
        except Exception:
            pass  # Column already exists — safe to ignore
        # [NEW] market_type column — safe migration for existing DBs
        try:
            conn.execute(adapt_sql("ALTER TABLE signal_logs ADD COLUMN market_type TEXT DEFAULT 'auto'"))
        except Exception:
            pass  # Column already exists — safe to ignore
    logger.info("Signal DB initialised")





# ── Data class for a logged signal ───────────────────────────────────────────

@dataclass
class SignalRecord:
    id: Optional[int]
    symbol: str
    side: str
    score: int
    tier: str
    daily_trend: Optional[str]
    market_regime: Optional[str]
    adx: Optional[float]
    entry_price: float
    limit_entry: Optional[float]
    sl: float
    tp1: float
    tp2: Optional[float]
    tp3: Optional[float]
    sl_pct: Optional[float]
    rr1: Optional[float]
    rr2: Optional[float]
    fired_at: str
    status: str = "open"
    outcome_price: Optional[float] = None
    outcome_at: Optional[str] = None
    pnl_pct: Optional[float] = None
    partial_close_pct: float = 0.0  # 0=open | 50=TP1 hit | 100=fully closed
    # [NEW] market_type: engine that generated this signal
    # 'auto' = current hybrid | 'spot' = /spot cmd | 'futures' = /futures cmd
    market_type: str = "auto"
    notes: Optional[str] = None


# ── CRUD operations ───────────────────────────────────────────────────────────

def log_signal(rec: SignalRecord) -> int:
    """Insert a new signal. Returns the new row ID."""
    with get_conn() as conn:
        cursor = conn.execute(adapt_sql("""
            INSERT INTO signal_logs
                (symbol, side, score, tier, daily_trend, market_regime, adx,
                 entry_price, limit_entry, sl, tp1, tp2, tp3,
                 sl_pct, rr1, rr2, fired_at, status, market_type, notes)
            VALUES
                (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """), (
            rec.symbol, rec.side, rec.score, rec.tier,
            rec.daily_trend, rec.market_regime, rec.adx,
            rec.entry_price, rec.limit_entry,
            rec.sl, rec.tp1, rec.tp2, rec.tp3,
            rec.sl_pct, rec.rr1, rec.rr2,
            rec.fired_at, rec.status, rec.market_type, rec.notes,
        ))
        row_id = cursor.lastrowid
    logger.info("Signal logged: id=%d %s %s score=%d", row_id, rec.symbol, rec.side.upper(), rec.score)
    return row_id


def get_open_signals() -> list[SignalRecord]:
    """Return all signals with status='open'."""
    with get_conn() as conn:
        rows = conn.execute(
            adapt_sql("SELECT * FROM signal_logs WHERE status = 'open' ORDER BY fired_at ASC")
        ).fetchall()
    return [_row_to_record(r) for r in rows]


def update_outcome(
    signal_id: int,
    status: str,
    outcome_price: float,
    pnl_pct: float,
) -> None:
    """Mark a signal as resolved with its outcome."""
    now = datetime.now(timezone.utc).isoformat()
    with get_conn() as conn:
        conn.execute(adapt_sql("""
            UPDATE signal_logs
            SET status=?, outcome_price=?, outcome_at=?, pnl_pct=?
            WHERE id=?
        """), (status, outcome_price, now, pnl_pct, signal_id))
    logger.info("Signal #%d outcome updated: %s pnl=%.2f%%", signal_id, status, pnl_pct)


# Tier-based expiry windows:
#   Tier A (strong signal, 8+ pts): 7 days — may need more time to reach TP on sideways market
#   Tier B (moderate signal, 6-7 pts): 5 days — tighter window, exit faster if not triggered
_TIER_EXPIRY_DAYS = {"A": 7, "B": 5}
_DEFAULT_EXPIRY_DAYS = 5


def expire_old_signals() -> int:
    """
    Expire open signals that have exceeded their tier-based max age.
    Tier A: 7 days | Tier B: 5 days
    Returns total count of newly expired signals.
    """
    from datetime import timedelta
    now = datetime.now(timezone.utc)
    total_expired = 0

    for tier, max_days in _TIER_EXPIRY_DAYS.items():
        cutoff = (now - timedelta(days=max_days)).isoformat()
        with get_conn() as conn:
            cur = conn.execute(adapt_sql("""
                UPDATE signal_logs
                SET status='expired',
                    notes=('Auto-expired: no outcome within ' || ? || ' days (Tier ' || ? || ')')
                WHERE status='open' AND tier=? AND fired_at < ?
            """), (max_days, tier, tier, cutoff))
            count = cur.rowcount
        if count:
            logger.info("Expired %d Tier %s signals (>%d days)", count, tier, max_days)
        total_expired += count

    return total_expired


# ── Stats queries ─────────────────────────────────────────────────────────────

def get_stats(symbol: Optional[str] = None) -> dict:
    """
    Compute win/loss stats across all resolved signals.
    If symbol is provided, filter to that symbol only.

    Win definitions (v2 — partial close aware):
      tp2_hit                         → Full Win (1.0)
      tp1_hit + partial_close_pct=50  → Partial Win (0.5) — held through to TP1 then reversed
      tp1_hit                         → Win (TP1 only, may have been closed before reversal)
    FIXED: No longer counts tp1_hit that later reversed to SL as a full win.
    """
    where = "WHERE status != 'open'"
    params: tuple = ()
    if symbol:
        where += " AND symbol = ?"
        params = (symbol.upper(),)

    with get_conn() as conn:
        rows = conn.execute(
            adapt_sql(f"SELECT * FROM signal_logs {where}"), params
        ).fetchall()

    if not rows:
        return {"total": 0, "message": "Chưa có signal nào được giải quyết."}

    records = [_row_to_record(r) for r in rows]
    total = len(records)
    full_wins  = [r for r in records if r.status == "tp2_hit"]
    tp1_wins   = [r for r in records if r.status == "tp1_hit"]
    losses     = [r for r in records if r.status == "sl_hit"]
    expired    = [r for r in records if r.status == "expired"]

    # Count: tp2_hit = full win, tp1_hit = partial win (0.5)
    weighted_wins = len(full_wins) + len(tp1_wins) * 0.5
    win_rate = weighted_wins / total * 100 if total else 0

    all_wins = full_wins + tp1_wins
    avg_win_pnl  = sum(r.pnl_pct for r in all_wins if r.pnl_pct) / len(all_wins) if all_wins else 0
    avg_loss_pnl = sum(r.pnl_pct for r in losses if r.pnl_pct) / len(losses) if losses else 0

    # Tier breakdown
    tier_a = [r for r in records if r.tier == "A"]
    tier_b = [r for r in records if r.tier == "B"]
    tier_a_wins = [r for r in tier_a if r.status in ("tp1_hit", "tp2_hit")]
    tier_b_wins = [r for r in tier_b if r.status in ("tp1_hit", "tp2_hit")]

    return {
        "total": total,
        "full_wins": len(full_wins),
        "tp1_wins": len(tp1_wins),
        "wins": len(all_wins),            # backward compat
        "losses": len(losses),
        "expired": len(expired),
        "win_rate_pct": round(win_rate, 1),  # weighted: TP2=1pt, TP1=0.5pt
        "avg_win_pnl_pct": round(avg_win_pnl, 2),
        "avg_loss_pnl_pct": round(avg_loss_pnl, 2),
        "tier_a_total": len(tier_a),
        "tier_a_wins": len(tier_a_wins),
        "tier_a_win_rate": round(len(tier_a_wins) / len(tier_a) * 100, 1) if tier_a else 0,
        "tier_b_total": len(tier_b),
        "tier_b_wins": len(tier_b_wins),
        "tier_b_win_rate": round(len(tier_b_wins) / len(tier_b) * 100, 1) if tier_b else 0,
    }


def get_recent_signals(limit: int = 10) -> list[SignalRecord]:
    """Return the last N signals (any status) for display."""
    with get_conn() as conn:
        rows = conn.execute(
            adapt_sql("SELECT * FROM signal_logs ORDER BY fired_at DESC LIMIT ?"), (limit,)
        ).fetchall()
    return [_row_to_record(r) for r in rows]


def _row_to_record(row: dict) -> SignalRecord:
    d = dict(row)
    return SignalRecord(
        id=d["id"],
        symbol=d["symbol"],
        side=d["side"],
        score=d["score"],
        tier=d["tier"],
        daily_trend=d.get("daily_trend"),
        market_regime=d.get("market_regime"),
        adx=d.get("adx"),
        entry_price=d["entry_price"],
        limit_entry=d.get("limit_entry"),
        sl=d["sl"],
        tp1=d["tp1"],
        tp2=d.get("tp2"),
        tp3=d.get("tp3"),
        sl_pct=d.get("sl_pct"),
        rr1=d.get("rr1"),
        rr2=d.get("rr2"),
        fired_at=d["fired_at"],
        status=d["status"],
        outcome_price=d.get("outcome_price"),
        outcome_at=d.get("outcome_at"),
        pnl_pct=d.get("pnl_pct"),
        partial_close_pct=d.get("partial_close_pct") or 0.0,
        market_type=d.get("market_type") or "auto",  # [NEW]
        notes=d.get("notes"),
    )
