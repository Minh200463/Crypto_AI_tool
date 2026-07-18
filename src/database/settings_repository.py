"""
Settings Repository — persists per-user Position Sizing configuration.
Uses the same signals.db file as signal_repository.

Table: user_settings
  Keyed by telegram_user_id (integer).
  Stores equity, risk_pct, and autoscan preferences.
"""
import logging
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Optional

from src.database.signal_repository import DB_PATH

logger = logging.getLogger(__name__)

# Default settings when user hasn't configured anything
DEFAULT_EQUITY             = 1000.0  # USDT
DEFAULT_RISK_PCT           = 1.0     # 1% per trade (Tier A); Tier B auto-halved to 0.5%
# [NEW] Auto-scan defaults
DEFAULT_AUTOSCAN_ENABLED   = 0       # Off by default — user must explicitly enable
DEFAULT_AUTOSCAN_MIN_SCORE = 7       # Alert when score >= 7 (lowest Tier A)


def init_settings_table(db_path: Path = DB_PATH) -> None:
    """Create user_settings table and run safe migrations."""
    with sqlite3.connect(db_path) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS user_settings (
                user_id              INTEGER PRIMARY KEY,
                equity               REAL    NOT NULL DEFAULT 1000.0,
                risk_pct             REAL    NOT NULL DEFAULT 1.0,
                autoscan_enabled     INTEGER NOT NULL DEFAULT 0,
                autoscan_min_score   INTEGER NOT NULL DEFAULT 7,
                updated_at           TEXT
            )
        """)
        # [NEW] Safe migration for existing DBs without autoscan columns
        for col, defval in [
            ("autoscan_enabled",   "0"),
            ("autoscan_min_score", "7"),
        ]:
            try:
                conn.execute(
                    f"ALTER TABLE user_settings ADD COLUMN {col} INTEGER NOT NULL DEFAULT {defval}"
                )
            except Exception:
                pass  # Column already exists — safe to ignore
        conn.commit()
    logger.debug("user_settings table ready")


@contextmanager
def _conn(db_path: Path = DB_PATH):
    c = sqlite3.connect(db_path)
    c.row_factory = sqlite3.Row
    try:
        yield c
        c.commit()
    except Exception:
        c.rollback()
        raise
    finally:
        c.close()


def get_user_settings(user_id: int, db_path: Path = DB_PATH) -> dict:
    """Return all settings for a user. Falls back to defaults."""
    with _conn(db_path) as conn:
        row = conn.execute(
            "SELECT equity, risk_pct, autoscan_enabled, autoscan_min_score FROM user_settings WHERE user_id = ?",
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


def get_all_autoscan_users(db_path: Path = DB_PATH) -> list[dict]:
    """
    [NEW] Return all users who have autoscan enabled.
    Used by the 4H auto-scan cron job to know who to notify.
    Returns list of {user_id, autoscan_min_score}.
    """
    with _conn(db_path) as conn:
        rows = conn.execute(
            "SELECT user_id, autoscan_min_score FROM user_settings WHERE autoscan_enabled = 1"
        ).fetchall()
    return [{"user_id": row["user_id"], "autoscan_min_score": row["autoscan_min_score"]} for row in rows]


def set_autoscan(
    user_id: int,
    enabled: bool,
    min_score: int = DEFAULT_AUTOSCAN_MIN_SCORE,
    db_path: Path = DB_PATH,
) -> None:
    """
    [NEW] Enable or disable auto-scan for a user, and set minimum score threshold.
    min_score: 6 = Tier B+, 7 = Tier A minimum (default), 8 = strong Tier A only
    """
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()
    with _conn(db_path) as conn:
        conn.execute("""
            INSERT INTO user_settings (user_id, equity, risk_pct, autoscan_enabled, autoscan_min_score, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                autoscan_enabled   = excluded.autoscan_enabled,
                autoscan_min_score = excluded.autoscan_min_score,
                updated_at         = excluded.updated_at
        """, (user_id, DEFAULT_EQUITY, DEFAULT_RISK_PCT, int(enabled), min_score, now))
    logger.info("User %d autoscan=%s min_score=%d", user_id, enabled, min_score)


def set_equity(user_id: int, equity: float, db_path: Path = DB_PATH) -> None:
    """Update or insert user equity."""
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()
    with _conn(db_path) as conn:
        conn.execute("""
            INSERT INTO user_settings (user_id, equity, risk_pct, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET equity=excluded.equity, updated_at=excluded.updated_at
        """, (user_id, equity, DEFAULT_RISK_PCT, now))
    logger.info("User %d equity set to $%.2f", user_id, equity)


def set_risk_pct(user_id: int, risk_pct: float, db_path: Path = DB_PATH) -> None:
    """Update or insert user risk % per trade."""
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()
    with _conn(db_path) as conn:
        conn.execute("""
            INSERT INTO user_settings (user_id, equity, risk_pct, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET risk_pct=excluded.risk_pct, updated_at=excluded.updated_at
        """, (user_id, DEFAULT_EQUITY, risk_pct, now))
    logger.info("User %d risk_pct set to %.2f%%", user_id, risk_pct)
