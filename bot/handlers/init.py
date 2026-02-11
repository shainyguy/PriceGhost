from aiogram import Router
from bot.handlers.start import router as start_router
from bot.handlers.profile import router as profile_router
from bot.handlers.payment import router as payment_router
from bot.handlers.price_check import router as price_check_router
from bot.handlers.monitoring import router as monitoring_router
from bot.handlers.ai_features import router as ai_features_router
from bot.handlers.admin import router as admin_router


def setup_routers() -> Router:
    main_router = Router()
    main_router.include_router(admin_router)       # Первый — чтобы /admin не конфликтовал
    main_router.include_router(start_router)
    main_router.include_router(profile_router)
    main_router.include_router(payment_router)
    main_router.include_router(price_check_router)
    main_router.include_router(monitoring_router)
    main_router.include_router(ai_features_router)
    return main_router