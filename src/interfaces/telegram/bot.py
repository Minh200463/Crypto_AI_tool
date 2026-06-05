"""
Telegram Bot setup — registers all command handlers and injects dependencies.
"""
import logging
from telegram.ext import Application, CommandHandler

from config.settings import settings
from src.interfaces.telegram import handlers

logger = logging.getLogger(__name__)


def setup_bot(cache, db_session_factory) -> Application | None:
    if not settings.TELEGRAM_BOT_TOKEN:
        logger.warning("TELEGRAM_BOT_TOKEN not set. Telegram bot will not start.")
        return None

    app = Application.builder().token(settings.TELEGRAM_BOT_TOKEN).build()

    # Inject shared services into bot_data
    app.bot_data["cache"] = cache
    app.bot_data["db_session"] = db_session_factory

    from src.data.binance_client import BinanceClient
    binance = BinanceClient(cache=cache, testnet=settings.BINANCE_TESTNET)
    app.bot_data["binance"] = binance
    # Expose bot instance for scheduler to send messages
    app.bot_data["bot_instance"] = app.bot

    # ── Register all command handlers ─────────────────────────────────────
    commands = [
        ("start",       handlers.start_handler),
        ("help",        handlers.help_handler),
        # Price & Market
        ("price",       handlers.price_handler),
        ("market",      handlers.market_handler),
        # Watchlist
        ("watchlist",   handlers.watchlist_handler),
        ("watch",       handlers.watch_handler),
        ("unwatch",     handlers.unwatch_handler),
        # Analysis & Signals
        ("analyze",     handlers.analyze_handler),
        ("signal",      handlers.signal_handler),
        # Alerts
        ("setalert",    handlers.setalert_handler),
        ("alerts",      handlers.alerts_handler),
        ("clear",       handlers.clear_handler),
        ("clearall",    handlers.clearall_handler),
    ]

    for cmd, handler in commands:
        app.add_handler(CommandHandler(cmd, handler))

    logger.info("Telegram bot ready — %d commands registered.", len(commands))
    return app
