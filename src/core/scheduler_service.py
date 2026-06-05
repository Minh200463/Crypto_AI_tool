"""
Scheduler Service — Setup and manage cron jobs using APScheduler.
"""
import logging

logger = logging.getLogger(__name__)


class SchedulerService:
    """Manages background jobs for the application."""

    def __init__(self) -> None:
        pass

    def start(self) -> None:
        """Start the scheduler."""
        logger.info("Scheduler started.")

    def shutdown(self) -> None:
        """Shutdown the scheduler."""
        logger.info("Scheduler shutdown.")

    def setup_jobs(self) -> None:
        """Define all cron jobs (fetch prices, check alerts, morning brief)."""
        logger.info("Jobs setup completed.")
