"""
DB Adapter — unified connection helper for signal_repository and settings_repository.

Automatically detects database type from DATABASE_URL env var:
  - sqlite://...   → uses sqlite3 (local dev)
  - postgresql://... → uses psycopg2 (production / Neon / Supabase)

[NEW] This replaces the sqlite3-only connection pattern so both repos
work without modification whether running locally (SQLite) or on
Render/Fly.io (PostgreSQL).

Usage (same as before, just import from here):
    from src.database.db_adapter import get_conn, init_schema, placeholder

    with get_conn() as conn:
        conn.execute("SELECT * FROM signal_logs WHERE id = %s", (1,))
        # use placeholder() for ? vs %s difference
"""
import logging
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

logger = logging.getLogger(__name__)

# ── Detect which DB to use ─────────────────────────────────────────────────────

try:
    from config.settings import settings
    _RAW_URL: str = settings.DATABASE_URL
except ImportError:
    # Fallback if config is not loadable in script mode
    _RAW_URL: str = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./data/cryptoai.db")

# Normalise: strip async driver prefix so we can use sync drivers here
# e.g. "postgresql+asyncpg://..." → "postgresql://..."
#      "sqlite+aiosqlite://..."   → "sqlite:///..."
_SYNC_URL = (
    _RAW_URL
    .replace("postgresql+asyncpg://", "postgresql://")
    .replace("sqlite+aiosqlite:///", "sqlite:///")
)

USE_POSTGRES: bool = _SYNC_URL.startswith("postgresql")

# SQLite file path (only used when USE_POSTGRES is False)
_SQLITE_PATH = Path(__file__).parent.parent.parent / "data" / "signals.db"

# SQL placeholder: SQLite uses ?, PostgreSQL uses %s
placeholder = "%s" if USE_POSTGRES else "?"

logger.info("DB Adapter: using %s", "PostgreSQL" if USE_POSTGRES else "SQLite")


# ── Connection context manager ─────────────────────────────────────────────────

@contextmanager
def get_conn():
    """
    Yield a DB connection that works for both SQLite and PostgreSQL.
    Commits on success, rolls back on exception, always closes.

    The returned connection/cursor follows DB-API 2.0 so all existing
    code that does conn.execute(...) keeps working unchanged.
    """
    if USE_POSTGRES:
        import psycopg2
        import psycopg2.extras
        conn = psycopg2.connect(_SYNC_URL)
        conn.autocommit = True
        conn.cursor_factory = psycopg2.extras.RealDictCursor  # row["col"] syntax
        
        class PostgresConnectionWrapper:
            def __init__(self, conn):
                self._conn = conn
            def execute(self, query, vars=None):
                cur = self._conn.cursor()
                cur.execute(query, vars)
                return cur
            def __getattr__(self, name):
                return getattr(self._conn, name)

        wrapper = PostgresConnectionWrapper(conn)

        try:
            yield wrapper
            wrapper.commit()
        except Exception:
            wrapper.rollback()
            raise
        finally:
            wrapper.close()
    else:
        _SQLITE_PATH.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(_SQLITE_PATH))
        conn.row_factory = sqlite3.Row  # same row["col"] syntax
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()


def adapt_sql(sql: str) -> str:
    """
    Convert SQLite-flavoured SQL to PostgreSQL where needed.
    Handles the most common differences automatically:
      - ? → %s  (placeholder)
      - INTEGER PRIMARY KEY AUTOINCREMENT → SERIAL PRIMARY KEY
      - AUTOINCREMENT (standalone) → (removed, not needed in PG)
    """
    if not USE_POSTGRES:
        return sql
    return (
        sql
        .replace("?", "%s")
        .replace("INTEGER PRIMARY KEY AUTOINCREMENT", "SERIAL PRIMARY KEY")
        .replace(" AUTOINCREMENT", "")
    )
