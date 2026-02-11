import logging

from aiogram import Router, F
from aiogram.types import CallbackQuery, BufferedInputFile

from database.db import get_db
from config import PlanLimits
from bot.keyboards.inline import (
    product_actions_kb, upgrade_kb, back_to_menu_kb
)
from bot.utils.helpers import format_price
from bot.services.review_analyzer import analyze_reviews, format_review_analysis
from bot.services.analogs_finder import find_analogs, format_analogs_result
from bot.services.price_predictor import predict_price, format_prediction
from bot.services.cashback import get_cashback_info, format_cashback_info

logger = logging.getLogger(__name__)
router = Router()


# ==================== AI-АНАЛИЗ ОТЗЫВОВ ====================

@router.callback_query(F.data.startswith("reviews_"))
async def cb_ai_reviews(callback: CallbackQuery):
    """AI-анализ отзывов (PREMIUM)"""
    product_id = int(callback.data.replace("reviews_", ""))
    db = await get_db()
    user = await db.get_user(callback.from_user.id)
    product = await db.get_product(product_id)

    if not product:
        await callback.answer("Товар не найден", show_alert=True)
        return

    active_plan = user.active_plan if user else "FREE"
    limits = PlanLimits.get(active_plan)

    if not limits.get("ai_reviews"):
        await callback.message.edit_text(
            "🤖 <b>AI-анализ отзывов</b>\n\n"
            "Эта функция доступна только в тарифе PREMIUM.\n\n"
            "Что вы получите:\n"
            "• Выявление фейковых отзывов\n"
            "• Реальный рейтинг товара\n"
            "• Выжимка плюсов и минусов\n"
            "• Рекомендация от AI\n\n"
            "💎 Улучшите план для доступа!",
            reply_markup=upgrade_kb(),
        )
        await callback.answer()
        return

    await callback.answer("🤖 Анализирую отзывы... (может занять 15-30 сек)")

    # Обновляем сообщение чтобы показать прогресс
    await callback.message.edit_text(
        "🤖 <b>AI-анализ отзывов</b>\n\n"
        "⏳ Скачиваю отзывы...\n"
        "⏳ Анализирую паттерны...\n"
        "⏳ Запрашиваю AI...\n\n"
        "Это может занять 15-30 секунд.",
    )

    try:
        result = await analyze_reviews(
            marketplace=product.marketplace,
            product_id=product.external_id or str(product.id),
            product_title=product.title or "",
        )

        text = format_review_analysis(result)

        # Обрезаем если слишком длинный
        if len(text) > 4000:
            text = text[:3950] + "\n\n... (обрезано)"

        await callback.message.edit_text(
            text,
            reply_markup=product_actions_kb(product_id, active_plan),
        )

    except Exception as e:
        logger.error(f"Review analysis error: {e}")
        await callback.message.edit_text(
            "❌ Ошибка при анализе отзывов.\n"
            "Возможно, отзывы недоступны для этого товара.\n\n"
            "Попробуйте позже.",
            reply_markup=product_actions_kb(product_id, active_plan),
        )


# ==================== ПОИСК АНАЛОГОВ ====================

@router.callback_query(F.data.startswith("analogs_"))
async def cb_find_analogs(callback: CallbackQuery):
    """Поиск аналогов дешевле (PREMIUM)"""
    product_id = int(callback.data.replace("analogs_", ""))
    db = await get_db()
    user = await db.get_user(callback.from_user.id)
    product = await db.get_product(product_id)

    if not product:
        await callback.answer("Товар не найден", show_alert=True)
        return

    active_plan = user.active_plan if user else "FREE"
    limits = PlanLimits.get(active_plan)

    if not limits.get("analogs"):
        await callback.message.edit_text(
            "📦 <b>Поиск аналогов</b>\n\n"
            "Эта функция доступна только в тарифе PREMIUM.\n\n"
            "Что вы получите:\n"
            "• Тот же товар у других продавцов\n"
            "• Похожие товары других брендов дешевле\n"
            "• AI-рекомендация по соотношению цена/качество\n\n"
            "💎 Улучшите план для доступа!",
            reply_markup=upgrade_kb(),
        )
        await callback.answer()
        return

    await callback.answer("📦 Ищу аналоги...")

    await callback.message.edit_text(
        "📦 <b>Поиск аналогов</b>\n\n"
        "⏳ Ищу на маркетплейсах...\n"
        "⏳ Сравниваю цены...\n"
        "⏳ Готовлю рекомендации...",
    )

    try:
        result = await find_analogs(
            title=product.title or "",
            brand=product.brand or "",
            category=product.category or "",
            current_price=product.current_price or 0,
            marketplace=product.marketplace,
        )

        text = format_analogs_result(result, product.current_price or 0)

        if len(text) > 4000:
            text = text[:3950] + "\n\n... (обрезано)"

        await callback.message.edit_text(
            text,
            reply_markup=product_actions_kb(product_id, active_plan),
            disable_web_page_preview=True,
        )

    except Exception as e:
        logger.error(f"Analogs search error: {e}")
        await callback.message.edit_text(
            "❌ Ошибка при поиске аналогов. Попробуйте позже.",
            reply_markup=product_actions_kb(product_id, active_plan),
        )


# ==================== ПРОГНОЗ ЦЕН ====================

@router.callback_query(F.data.startswith("predict_"))
async def cb_price_predict(callback: CallbackQuery):
    """Прогноз цен + календарь (PREMIUM)"""
    product_id = int(callback.data.replace("predict_", ""))
    db = await get_db()
    user = await db.get_user(callback.from_user.id)
    product = await db.get_product(product_id)

    if not product:
        await callback.answer("Товар не найден", show_alert=True)
        return

    active_plan = user.active_plan if user else "FREE"
    limits = PlanLimits.get(active_plan)

    if not limits.get("price_predict"):
        await callback.message.edit_text(
            "📅 <b>Прогноз цен</b>\n\n"
            "Эта функция доступна только в тарифе PREMIUM.\n\n"
            "Что вы получите:\n"
            "• Когда лучше покупать эту категорию\n"
            "• Календарь цен по месяцам\n"
            "• AI-прогноз ценовых трендов\n"
            "• Персональные рекомендации\n\n"
            "💎 Улучшите план для доступа!",
            reply_markup=upgrade_kb(),
        )
        await callback.answer()
        return

    await callback.answer("📅 Анализирую тренды...")

    await callback.message.edit_text(
        "📅 <b>Прогноз цен</b>\n\n"
        "⏳ Анализирую историю...\n"
        "⏳ Строю прогноз...\n"
        "⏳ Запрашиваю AI...",
    )

    try:
        result = await predict_price(
            product_id=product_id,
            title=product.title or "",
            category=product.category or "",
            current_price=product.current_price or 0,
        )

        text = format_prediction(result, title=product.title or "")

        if len(text) > 4000:
            text = text[:3950] + "\n\n... (обрезано)"

        # Если есть график — отправляем с фото
        chart = result.get("monthly_chart")
        if chart:
            try:
                await callback.message.delete()
            except Exception:
                pass

            photo = BufferedInputFile(chart.read(), filename="prediction.png")
            await callback.message.answer_photo(
                photo=photo,
                caption=text[:1024],  # Лимит caption
                reply_markup=product_actions_kb(product_id, active_plan),
            )

            # Если текст длиннее caption, доотправляем
            if len(text) > 1024:
                await callback.message.answer(
                    text[1024:],
                    reply_markup=product_actions_kb(product_id, active_plan),
                )
        else:
            await callback.message.edit_text(
                text,
                reply_markup=product_actions_kb(product_id, active_plan),
            )

    except Exception as e:
        logger.error(f"Price prediction error: {e}")
        await callback.message.edit_text(
            "❌ Ошибка при построении прогноза. Попробуйте позже.",
            reply_markup=product_actions_kb(product_id, active_plan),
        )


# ==================== КЕШБЭК И ПРОМОКОДЫ ====================

@router.callback_query(F.data.startswith("cashback_"))
async def cb_cashback(callback: CallbackQuery):
    """Кешбэк и промокоды (PREMIUM)"""
    product_id = int(callback.data.replace("cashback_", ""))
    db = await get_db()
    user = await db.get_user(callback.from_user.id)
    product = await db.get_product(product_id)

    if not product:
        await callback.answer("Товар не найден", show_alert=True)
        return

    active_plan = user.active_plan if user else "FREE"
    limits = PlanLimits.get(active_plan)

    if not limits.get("cashback"):
        await callback.message.edit_text(
            "💸 <b>Кешбэк и промокоды</b>\n\n"
            "Эта функция доступна только в тарифе PREMIUM.\n\n"
            "Что вы получите:\n"
            "• Все доступные кешбэки на товар\n"
            "• Советы по промокодам\n"
            "• Расчёт финальной цены\n"
            "• AI-советы по экономии\n\n"
            "💎 Улучшите план для доступа!",
            reply_markup=upgrade_kb(),
        )
        await callback.answer()
        return

    await callback.answer("💸 Собираю информацию о кешбэках...")

    try:
        result = await get_cashback_info(
            marketplace=product.marketplace,
            current_price=product.current_price or 0,
            title=product.title or "",
            category=product.category or "",
        )

        text = format_cashback_info(result, product.current_price or 0)

        if len(text) > 4000:
            text = text[:3950] + "\n\n... (обрезано)"

        await callback.message.edit_text(
            text,
            reply_markup=product_actions_kb(product_id, active_plan),
        )

    except Exception as e:
        logger.error(f"Cashback info error: {e}")
        await callback.message.edit_text(
            "❌ Ошибка при получении информации о кешбэках.",
            reply_markup=product_actions_kb(product_id, active_plan),
        )