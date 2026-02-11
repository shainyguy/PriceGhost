import asyncio
import logging
from aiohttp import web

from aiogram import Bot, Dispatcher, Router
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application

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


async def on_startup(bot: Bot):
    global _scheduler_task

    db = await get_db()
    logger.info("Database initialized")

    if config.webhook.url:
        full = config.webhook.full_url
        await bot.set_webhook(full)
        logger.info(f"Webhook set: {full}")

    try:
        from bot.services.monitor_scheduler import run_scheduler
        _scheduler_task = asyncio.create_task(run_scheduler(bot, interval_hours=3))
        logger.info("Monitor scheduler started")
    except Exception as e:
        logger.error(f"Scheduler failed: {e}")

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

    if config.webhook.url:
        await bot.delete_webhook()

    logger.info("PriceGhost Bot stopped!")


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

    return dp


async def start_polling():
    bot = create_bot()
    dp = create_dispatcher()
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)


def start_webhook():
    bot = create_bot()
    dp = create_dispatcher()

    app = web.Application()

    # Регистрируем хендлер на ЧИСТЫЙ путь
    webhook_path = config.webhook.path
    logger.info(f"Registering webhook handler on path: {webhook_path}")

    webhook_handler = SimpleRequestHandler(dispatcher=dp, bot=bot)
    webhook_handler.register(app, path=webhook_path)
    setup_application(app, dp, bot=bot)

    web.run_app(app, host=config.webhook.host, port=config.webhook.port)
