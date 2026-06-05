"""
Alert Service — evaluate active alerts against current market data.
Pure code logic, no AI. AI is used only for generating the alert message.
"""
import logging
from datetime import datetime, timezone, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from src.data.models.alert import Alert
from src.data.repositories.alert_repo import AlertRepository

logger = logging.getLogger(__name__)


class AlertService:
    """
    Checks active alerts and returns triggered ones.
    Anti-spam: 30-minute cooldown per alert trigger.
    Max 3 alerts per coin per hour enforced at creation time.
    """

    def __init__(self, db: AsyncSession) -> None:
        self._db = db
        self._alert_repo = AlertRepository(db)

    async def create_alert(
        self,
        user_id: str,
        symbol: str,
        alert_type: str,
        threshold: float | None = None,
        direction: str | None = None,
    ) -> Alert:
        """Create a new alert for the user."""
        alert = Alert(
            user_id=user_id,
            symbol=symbol,
            alert_type=alert_type,
            threshold=threshold,
            direction=direction,
            is_active=True,
        )
        self._db.add(alert)
        await self._db.flush()
        await self._db.refresh(alert)
        return alert

    async def check_price_alerts(
        self,
        symbol: str,
        current_price: float,
    ) -> list[Alert]:
        """
        Compare current price against all active threshold alerts for symbol.
        Returns list of triggered Alert objects.
        """
        alerts = await self._alert_repo.get_active_alerts(symbol)
        triggered: list[Alert] = []
        now = datetime.now(timezone.utc)

        for alert in alerts:
            # Skip if in cooldown
            if alert.cooldown_until and alert.cooldown_until > now:
                continue

            fired = False
            if alert.alert_type == "price_above" and alert.threshold:
                fired = current_price >= float(alert.threshold)
            elif alert.alert_type == "price_below" and alert.threshold:
                fired = current_price <= float(alert.threshold)

            if fired:
                alert.triggered_at = now
                alert.cooldown_until = now + timedelta(minutes=30)
                alert.is_active = False  # one-shot: deactivate after trigger
                triggered.append(alert)

        if triggered:
            await self._db.flush()

        return triggered

    async def check_pct_change_alert(
        self,
        symbol: str,
        change_pct_1h: float,
    ) -> list[Alert]:
        """Trigger if coin moved > threshold% in last hour."""
        alerts = await self._alert_repo.get_active_alerts(symbol)
        triggered: list[Alert] = []
        now = datetime.now(timezone.utc)

        for alert in alerts:
            if alert.alert_type != "pct_change" or not alert.threshold:
                continue
            if alert.cooldown_until and alert.cooldown_until > now:
                continue
            if abs(change_pct_1h) >= float(alert.threshold):
                alert.triggered_at = now
                alert.cooldown_until = now + timedelta(minutes=30)
                alert.is_active = False
                triggered.append(alert)

        if triggered:
            await self._db.flush()

        return triggered

    async def check_rsi_alert(
        self,
        symbol: str,
        rsi: float,
        user_id: str | None = None,
    ) -> dict | None:
        """
        Returns alert dict if RSI is extreme (< 30 or > 70).
        Not stored as DB alert — auto-triggered by scheduler.
        """
        if rsi < 30:
            return {"symbol": symbol, "rsi": rsi, "type": "rsi_oversold"}
        if rsi > 70:
            return {"symbol": symbol, "rsi": rsi, "type": "rsi_overbought"}
        return None

    async def deactivate_all_for_symbol(self, user_id: str, symbol: str) -> int:
        """Deactivate all alerts for a user+symbol. Returns count deactivated."""
        alerts = await self._alert_repo.get_user_alerts(user_id)
        count = 0
        for alert in alerts:
            if alert.symbol == symbol and alert.is_active:
                alert.is_active = False
                count += 1
        if count:
            await self._db.flush()
        return count

    async def deactivate_all(self, user_id: str) -> int:
        """Deactivate all alerts for user. Returns count."""
        alerts = await self._alert_repo.get_user_alerts(user_id)
        count = 0
        for alert in alerts:
            if alert.is_active:
                alert.is_active = False
                count += 1
        if count:
            await self._db.flush()
        return count
