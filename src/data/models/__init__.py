"""
Models package — export all models so Alembic can auto-detect them.
Import this in alembic/env.py: from src.data.models import Base, *
"""
from src.data.models.base import Base
from src.data.models.user import User
from src.data.models.watchlist import Watchlist
from src.data.models.alert import Alert
from src.data.models.trade import Trade
from src.data.models.signal import Signal

__all__ = ["Base", "User", "Watchlist", "Alert", "Trade", "Signal"]
