import asyncio
import logging
from aiohttp import web

from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application

from config import config
from database.db import get_db
from bot.handlers import setup_routers
from bot.middlewares.throttling import ThrottlingMiddleware
from bot.services.monitor_scheduler import run_scheduler

logger = logging.getLogger(__name__)

# Хранение задач для cleanup
_scheduler_task = None


async def on_startup(bot: Bot):
    """Действия при запуске бота"""
    global _scheduler_task

    db = await get_db()
    logger.info("✅ Database initialized")

    if config.webhook.url:
        webhook_url = f"{config.webhook.url}{config.webhook.path}"
        await bot.set_webhook(webhook_url)
        logger.info(f"✅ Webhook set: {webhook_url}")

    # Запускаем планировщик мониторинга
    _scheduler_task = asyncio.create_task(run_scheduler(bot, interval_hours=3))
    logger.info("✅ Monitor scheduler started")

    logger.info("👻 PriceGhost Bot started!")


async def on_shutdown(bot: Bot):
    """Действия при остановке"""
    global _scheduler_task

    if _scheduler_task:
        _scheduler_task.cancel()
        try:
            await _scheduler_task
        except asyncio.CancelledError:
            pass

    db = await get_db()
    await db.close()

    if config.webhook.url:
        await bot.delete_webhook()

    logger.info("👻 PriceGhost Bot stopped!")


def create_bot() -> Bot:
    return Bot(
        token=config.bot.token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )


def create_dispatcher() -> Dispatcher:
    dp = Dispatcher()

    # Middlewares
    dp.message.middleware(ThrottlingMiddleware(rate_limit=0.5))
    dp.callback_query.middleware(ThrottlingMiddleware(rate_limit=0.3))

    # Routers
    main_router = setup_routers()
    dp.include_router(main_router)

    # Lifecycle
    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)

    return dp


async def start_polling():
    """Запуск в режиме long polling (для разработки)"""
    bot = create_bot()
    dp = create_dispatcher()

    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)


def start_webhook():
    """Запуск в режиме webhook (для Railway)"""
    bot = create_bot()
    dp = create_dispatcher()

    app = web.Application()

    webhook_handler = SimpleRequestHandler(dispatcher=dp, bot=bot)
    webhook_handler.register(app, path=config.webhook.path)
    setup_application(app, dp, bot=bot)

    web.run_app(app, host=config.webhook.host, port=config.webhook.port)