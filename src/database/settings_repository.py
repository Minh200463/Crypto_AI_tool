"""
Settings Repository — persists per-user Position Sizing configuration.
Uses the same signals.db file as signal_repository.

Table: user_settings
  Keyed by telegram_user_id (integer).
  Stores equity, risk_pct, and autoscan preferences.
"""
import logging
from typing import Optional

from src.database.db_adapter import get_conn, adapt_sql

logger = logging.getLogger(__name__)

# Default settings when user hasn't configured anything
DEFAULT_EQUITY             = 1000.0  # USDT
DEFAULT_RISK_PCT           = 1.0     # 1% per trade (Tier A); Tier B auto-halved to 0.5%
# [NEW] Auto-scan defaults
DEFAULT_AUTOSCAN_ENABLED   = 0       # Off by default — user must explicitly enable
DEFAULT_AUTOSCAN_MIN_SCORE = 7       # Alert when score >= 7 (lowest Tier A)


def init_settings_table() -> None:
    """Create user_settings table and run safe migrations."""
    with get_conn() as conn:
        conn.execute(adapt_sql("""
            CREATE TABLE IF NOT EXISTS user_settings (
                user_id              INTEGER PRIMARY KEY,
                equity               REAL    NOT NULL DEFAULT 1000.0,
                risk_pct             REAL    NOT NULL DEFAULT 1.0,
                autoscan_enabled     INTEGER NOT NULL DEFAULT 0,
                autoscan_min_score   INTEGER NOT NULL DEFAULT 7,
                updated_at           TEXT
            )
        """))
        # [NEW] Safe migration for existing DBs without autoscan columns
        for col, defval in [
            ("autoscan_enabled",   "0"),
            ("autoscan_min_score", "7"),
        ]:
            try:
                conn.execute(adapt_sql(
                    f"ALTER TABLE user_settings ADD COLUMN {col} INTEGER NOT NULL DEFAULT {defval}"
                ))
            except Exception:
                pass  # Column already exists — safe to ignore
    logger.debug("user_settings table ready")





def get_user_settings(user_id: int) -> dict:
    """Return all settings for a user. Falls back to defaults."""
    with get_conn() as conn:
        row = conn.execute(
            adapt_sql("SELECT equity, risk_pct, autoscan_enabled, autoscan_min_score FROM user_settings WHERE user_id = ?"),
            (user_id,)
        ).fetchone()
    if row:
        return {
            "equity":             row["equity"],
            "risk_pct":           row["risk_pct"],
            # [NEW] autoscan fields
            "autoscan_enabled":   bool(row["autoscan_enabled"]),
            "autoscan_min_score": int(row["autoscan_min_score"]),
        }
    return {
        "equity":             DEFAULT_EQUITY,
        "risk_pct":           DEFAULT_RISK_PCT,
        "autoscan_enabled":   bool(DEFAULT_AUTOSCAN_ENABLED),
        "autoscan_min_score": DEFAULT_AUTOSCAN_MIN_SCORE,
    }


def get_all_autoscan_users() -> list[dict]:
    """
    [NEW] Return all users who have autoscan enabled.
    Used by the 4H auto-scan cron job to know who to notify.
    Returns list of {user_id, autoscan_min_score}.
    """
    with get_conn() as conn:
        rows = conn.execute(
            adapt_sql("SELECT user_id, autoscan_min_score FROM user_settings WHERE autoscan_enabled = 1")
        ).fetchall()
    return [{"user_id": row["user_id"], "autoscan_min_score": row["autoscan_min_score"]} for row in rows]


def set_autoscan(
    user_id: int,
    enabled: bool,
    min_score: int = DEFAULT_AUTOSCAN_MIN_SCORE,
) -> None:
    """
    [NEW] Enable or disable auto-scan for a user, and set minimum score threshold.
    min_score: 6 = Tier B+, 7 = Tier A minimum (default), 8 = strong Tier A only
    """
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()
    with get_conn() as conn:
        conn.execute(adapt_sql("""
            INSERT INTO user_settings (user_id, equity, risk_pct, autoscan_enabled, autoscan_min_score, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                autoscan_enabled   = excluded.autoscan_enabled,
                autoscan_min_score = excluded.autoscan_min_score,
                updated_at         = excluded.updated_at
        """), (user_id, DEFAULT_EQUITY, DEFAULT_RISK_PCT, int(enabled), min_score, now))
    logger.info("User %d autoscan=%s min_score=%d", user_id, enabled, min_score)


def set_equity(user_id: int, equity: float) -> None:
    """Update or insert user equity."""
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()
    with get_conn() as conn:
        conn.execute(adapt_sql("""
            INSERT INTO user_settings (user_id, equity, risk_pct, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET equity=excluded.equity, updated_at=excluded.updated_at
        """), (user_id, equity, DEFAULT_RISK_PCT, now))
    logger.info("User %d equity set to $%.2f", user_id, equity)


def set_risk_pct(user_id: int, risk_pct: float) -> None:
    """Update or insert user risk % per trade."""
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()
    with get_conn() as conn:
        conn.execute(adapt_sql("""
            INSERT INTO user_settings (user_id, equity, risk_pct, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET risk_pct=excluded.risk_pct, updated_at=excluded.updated_at
        """), (user_id, DEFAULT_EQUITY, risk_pct, now))
    logger.info("User %d risk_pct set to %.2f%%", user_id, risk_pct)
