"""
Application entrypoint.
Startup sequence: DB → Cache → Scheduler → Telegram Bot → run polling.
"""
import asyncio
import logging
import threading
import os
import uvicorn
from fastapi import FastAPI

from config.settings import settings

# Thêm vào main.py — giữ server không sleep
health_app = FastAPI()

@health_app.get("/health")
async def health():
    return {"status": "ok"}

logging.basicConfig(
    format="%(asctime)s | %(levelname)-8s | %(name)s — %(message)s",
    level=getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO),
)
logger = logging.getLogger(__name__)


async def main() -> None:
    logger.info("Starting CryptoAI Tool [%s]...", settings.APP_ENV)

    # 1. Init database
    from src.data.database import create_all_tables, AsyncSessionLocal
    await create_all_tables()

    # 2. Init cache
    from src.data.cache import get_cache
    cache = get_cache()
    logger.info("Cache backend: %s", settings.CACHE_BACKEND)

    # 3. Setup Telegram bot
    from src.interfaces.telegram.bot import setup_bot
    bot_app = setup_bot(cache=cache, db_session_factory=AsyncSessionLocal)

    if not bot_app:
        logger.error("Bot setup failed — check TELEGRAM_BOT_TOKEN in .env")
        return

    # 4. Start scheduler (after bot is set up so bot_data is available)
    from src.interfaces.scheduler.jobs import setup_scheduler
    scheduler = setup_scheduler(bot_app.bot_data)
    scheduler.start()
    logger.info("Scheduler started.")

    # Cấu hình uvicorn chạy chung event loop với bot thay vì dùng thread
    port = int(os.environ.get("PORT", 8080))
    config = uvicorn.Config(health_app, host="0.0.0.0", port=port, log_level="error")
    server = uvicorn.Server(config)

    # 5. Run bot polling
    logger.info("Bot and Health server are running. Press Ctrl+C to stop.")
    async with bot_app:
        await bot_app.start()
        await bot_app.updater.start_polling(drop_pending_updates=True)

        try:
            # Chạy web server thay vì dùng Event().wait()
            logger.info("Health check server listening on port %s", port)
            await server.serve()
        except (KeyboardInterrupt, SystemExit):
            pass
        finally:
            logger.info("Shutting down...")
            scheduler.shutdown(wait=False)
            await bot_app.updater.stop()
            await bot_app.stop()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Application stopped.")
