import asyncio
import logging
import os
import traceback
from aiohttp import web

from aiogram import Bot, Dispatcher, Router
from aiogram.enums import ParseMode
from aiogram.types import Update
from aiogram.client.default import DefaultBotProperties

from config import config
from database.db import get_db
from bot.middlewares.throttling import ThrottlingMiddleware

logger = logging.getLogger(__name__)

_scheduler_task = None


def setup_routers() -> Router:
    main_router = Router()

    from bot.handlers.admin import router as admin_router
    from bot.handlers.start import router as start_router
    from bot.handlers.profile import router as profile_router
    from bot.handlers.payment import router as payment_router
    from bot.handlers.price_check import router as price_check_router
    from bot.handlers.monitoring import router as monitoring_router
    from bot.handlers.ai_features import router as ai_features_router

    main_router.include_router(admin_router)
    main_router.include_router(start_router)
    main_router.include_router(profile_router)
    main_router.include_router(payment_router)
    main_router.include_router(price_check_router)
    main_router.include_router(monitoring_router)
    main_router.include_router(ai_features_router)

    return main_router


async def health_handler(request):
    return web.Response(text="OK")


async def run_health_server():
    """Мини HTTP-сервер — Railway не убьёт контейнер"""
    port = int(os.getenv("PORT", "8080"))
    app = web.Application()
    app.router.add_get("/", health_handler)
    app.router.add_get("/health", health_handler)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    logger.info(f"Health server started on port {port}")


async def on_startup(bot: Bot):
    global _scheduler_task

    db = await get_db()
    logger.info("Database initialized")

    await bot.delete_webhook(drop_pending_updates=True)
    logger.info("Webhook deleted, polling mode")

    try:
        from bot.services.monitor_scheduler import run_scheduler
        _scheduler_task = asyncio.create_task(run_scheduler(bot, interval_hours=3))
        logger.info("Scheduler started")
    except Exception as e:
        logger.error(f"Scheduler failed: {e}")

    me = await bot.get_me()
    logger.info(f"Bot: @{me.username} (id={me.id})")
    logger.info("PriceGhost Bot started!")


async def on_shutdown(bot: Bot):
    global _scheduler_task
    if _scheduler_task:
        _scheduler_task.cancel()
        try:
            await _scheduler_task
        except asyncio.CancelledError:
            pass
    try:
        db = await get_db()
        await db.close()
    except Exception:
        pass
    logger.info("Bot stopped")


def create_bot() -> Bot:
    return Bot(
        token=config.bot.token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )


def create_dispatcher() -> Dispatcher:
    dp = Dispatcher()

    dp.message.middleware(ThrottlingMiddleware(rate_limit=0.5))
    dp.callback_query.middleware(ThrottlingMiddleware(rate_limit=0.3))

    main_router = setup_routers()
    dp.include_router(main_router)

    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)

    @dp.update.outer_middleware()
    async def log_updates(handler, event: Update, data):
        logger.info(f"UPDATE {event.update_id}: {event.event_type}")
        try:
            return await handler(event, data)
        except Exception as e:
            logger.error(f"HANDLER ERROR: {e}\n{traceback.format_exc()}")
            raise

    return dp


async def start_polling():
    # Health сервер для Railway
    await run_health_server()

    bot = create_bot()
    dp = create_dispatcher()
    await bot.delete_webhook(drop_pending_updates=True)
    logger.info("Starting polling...")
    await dp.start_polling(bot)
