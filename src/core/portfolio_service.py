"""
Portfolio Service — P&L tracking and trade journal management.
"""


class PortfolioService:
    """Manages user trade history, portfolio state and calculates P&L."""

    def __init__(self, trade_repo) -> None:
        self._trade_repo = trade_repo

    async def log_trade(self, user_id: int, symbol: str, side: str, price: float, quantity: float) -> dict:
        """Log a new trade entry."""
        raise NotImplementedError

    async def close_trade(self, trade_id: str, exit_price: float) -> dict:
        """Close an open trade and calculate P&L."""
        raise NotImplementedError

    async def get_history(self, user_id: int, limit: int = 10) -> list:
        """Get recent trades."""
        raise NotImplementedError

    async def generate_weekly_report_stats(self, user_id: int) -> dict:
        """Aggregate stats for weekly report (win rate, total P&L, etc.)."""
        raise NotImplementedError
