"""
Risk Service — Position sizing and fee calculation.
Pure math, no AI needed.
"""


class RiskService:
    """Calculates position sizing and risk management metrics."""

    def calculate_position_size(
        self,
        capital: float,
        entry_price: float,
        stop_loss: float,
        risk_pct: float = 0.02,
        leverage: int = 1,
    ) -> dict:
        """
        Calculate safe position size based on account capital and risk percentage.
        Returns: {quantity, position_usd, margin_required, risk_amount, liq_price}
        """
        raise NotImplementedError

    def calculate_fees(self, price: float, quantity: float, side: str) -> dict:
        """
        Calculate trading fees (using Binance standard 0.1%).
        Returns: {fee_usd, breakeven_price}
        """
        raise NotImplementedError
