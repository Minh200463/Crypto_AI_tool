"""
Settings Repository — persists per-user Position Sizing configuration.
Uses the same signals.db file as signal_repository.

Table: user_settings
  Keyed by telegram_user_id (integer).
  Stores equity and risk_pct for position sizing calculations.
"""
import logging
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Optional

from src.database.signal_repository import DB_PATH

logger = logging.getLogger(__name__)

# Default settings when user hasn't configured anything
DEFAULT_EQUITY   = 1000.0   # USDT
DEFAULT_RISK_PCT = 1.0      # 1% per trade (Tier A); Tier B auto-halved to 0.5%


def init_settings_table(db_path: Path = DB_PATH) -> None:
    """Create user_settings table if it doesn't exist."""
    with sqlite3.connect(db_path) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS user_settings (
                user_id    INTEGER PRIMARY KEY,   -- Telegram user ID
                equity     REAL    NOT NULL DEFAULT 1000.0,
                risk_pct   REAL    NOT NULL DEFAULT 1.0,
                updated_at TEXT
            )
        """)
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
    """Return equity and risk_pct for a user. Falls back to defaults."""
    with _conn(db_path) as conn:
        row = conn.execute(
            "SELECT equity, risk_pct FROM user_settings WHERE user_id = ?",
            (user_id,)
        ).fetchone()
    if row:
        return {"equity": row["equity"], "risk_pct": row["risk_pct"]}
    return {"equity": DEFAULT_EQUITY, "risk_pct": DEFAULT_RISK_PCT}


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
