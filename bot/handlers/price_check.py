import logging

from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, BufferedInputFile

from database.db import get_db
from config import PlanLimits
from bot.utils.url_parser import (
    parse_marketplace_url, is_valid_url,
    get_marketplace_emoji, get_marketplace_name
)
from bot.utils.helpers import format_price, format_percent, plan_badge
from bot.keyboards.inline import (
    product_actions_kb, upgrade_kb, back_to_menu_kb
)
from bot.services.price_history import fetch_and_save_price, get_price_stats
from bot.services.chart import generate_price_chart
from bot.services.fake_discount import analyze_fake_discount
from bot.services.search_cheaper import find_cheaper, format_cheaper_results
from bot.services.seller_check import check_seller, format_seller_check

logger = logging.getLogger(__name__)
router = Router()


@router.message(F.text.regexp(r"https?://"))
async def handle_url(message: Message):
    """Обработка ссылки на товар"""
    url = message.text.strip()

    # Парсим URL
    marketplace, product_id = parse_marketplace_url(url)

    if not marketplace:
        await message.answer(
            "❌ Не удалось распознать ссылку.\n\n"
            "Поддерживаемые площадки:\n"
            "🟣 Wildberries\n"
            "🔵 Ozon\n"
            "🟠 AliExpress\n"
            "🟡 Amazon\n\n"
            "Отправь прямую ссылку на товар.",
        )
        return

    db = await get_db()
    user = await db.get_user(message.from_user.id)

    if not user:
        user = await db.get_or_create_user(
            telegram_id=message.from_user.id,
            username=message.from_user.username,
            first_name=message.from_user.first_name,
        )

    # Проверяем лимит
    allowed, used, limit = await db.check_and_increment_usage(message.from_user.id)

    if not allowed:
        plan = user.active_plan
        await message.answer(
            f"⛔ <b>Лимит исчерпан!</b>\n\n"
            f"Тариф: {plan_badge(plan)}\n"
            f"Проверок сегодня: {used}/{limit}\n\n"
            f"💎 Улучши план для большего количества проверок!",
            reply_markup=upgrade_kb(),
        )
        return

    # Начинаем проверку
    mp_emoji = get_marketplace_emoji(marketplace)
    mp_name = get_marketplace_name(marketplace)

    loading_msg = await message.answer(
        f"⏳ Анализирую товар...\n\n"
        f"{mp_emoji} {mp_name} | ID: {product_id}\n"
        f"📊 Проверка {used}/{limit}",
    )

    # Скрапим и сохраняем
    product_data = await fetch_and_save_price(marketplace, product_id, url)

    if not product_data:
        await loading_msg.edit_text(
            f"❌ Не удалось получить данные о товаре.\n\n"
            f"Возможные причины:\n"
            f"• Товар удалён или недоступен\n"
            f"• Площадка временно не отвечает\n"
            f"• Некорректная ссылка\n\n"
            f"Попробуйте позже.",
            reply_markup=back_to_menu_kb(),
        )
        return

    # Формируем ответ
    db_id = product_data.get("db_id", 0)
    title = product_data.get("title", "Без названия")
    current_price = product_data.get("current_price", 0)
    original_price = product_data.get("original_price", 0)
    discount = product_data.get("discount_percent", 0)
    rating = product_data.get("rating", 0)
    reviews = product_data.get("reviews_count", 0)
    brand = product_data.get("brand", "")
    seller = product_data.get("seller_name", "")

    # Получаем статистику по истории
    stats = await get_price_stats(db_id, days=365)

    text = f"👻 <b>PriceGhost</b> — Результат\n\n"
    text += f"{mp_emoji} <b>{mp_name}</b>\n"
    text += f"📦 <b>{title}</b>\n\n"

    if brand:
        text += f"🏷 Бренд: {brand}\n"
    if seller:
        text += f"🏪 Продавец: {seller}\n"

    text += f"\n💰 <b>Цена: {format_price(current_price)}</b>\n"

    if discount > 0 and original_price > current_price:
        text += f"🏷 До скидки: <s>{format_price(original_price)}</s>\n"
        text += f"📉 Скидка: <b>-{discount:.0f}%</b>\n"

    if rating > 0:
        stars = "⭐" * int(rating) + "☆" * (5 - int(rating))
        text += f"\n{stars} {rating}/5"
        if reviews > 0:
            text += f" ({reviews:,} отзывов)"
        text += "\n"

    # Статистика из истории
    if stats.get("has_data"):
        text += f"\n📊 <b>Статистика:</b>\n"
        text += f"├ 📉 Минимум: {format_price(stats['min_price'])}\n"
        text += f"├ 📈 Максимум: {format_price(stats['max_price'])}\n"
        text += f"├ 📊 Средняя: {format_price(stats['avg_price'])}\n"

        trend_emoji = {"up": "📈", "down": "📉", "stable": "➡️"}
        trend_text = {"up": "Растёт", "down": "Падает", "stable": "Стабильна"}
        trend = stats["trend"]
        text += (
            f"└ {trend_emoji[trend]} Тренд: <b>{trend_text[trend]}</b>"
            f" ({format_percent(stats['trend_percent'])})\n"
        )

        # Быстрый вердикт по скидке
        if current_price <= stats["min_price"] * 1.05:
            text += "\n🎉 <b>Отличная цена! Близко к историческому минимуму.</b>"
        elif current_price >= stats["max_price"] * 0.95:
            text += "\n⚠️ <b>Цена близка к максимуму. Лучше подождать.</b>"
    else:
        text += "\n📊 Отслеживание начато! При следующей проверке будет больше данных."

    # Определяем план для показа кнопок
    active_plan = user.active_plan

    await loading_msg.edit_text(
        text,
        reply_markup=product_actions_kb(db_id, active_plan),
    )


# ==================== ДЕЙСТВИЯ С ТОВАРОМ ====================

@router.callback_query(F.data.startswith("product_"))
async def cb_product_info(callback: CallbackQuery):
    """Показать инфо о товаре повторно"""
    product_id = int(callback.data.replace("product_", ""))
    db = await get_db()
    product = await db.get_product(product_id)
    user = await db.get_user(callback.from_user.id)

    if not product:
        await callback.answer("Товар не найден", show_alert=True)
        return

    mp_emoji = get_marketplace_emoji(product.marketplace)
    mp_name = get_marketplace_name(product.marketplace)

    text = (
        f"👻 <b>PriceGhost</b>\n\n"
        f"{mp_emoji} <b>{mp_name}</b>\n"
        f"📦 {product.title or 'Без названия'}\n\n"
        f"💰 Цена: <b>{format_price(product.current_price)}</b>\n"
    )

    if product.original_price and product.original_price > product.current_price:
        text += f"🏷 До скидки: <s>{format_price(product.original_price)}</s>\n"

    active_plan = user.active_plan if user else "FREE"
    await callback.message.edit_text(
        text,
        reply_markup=product_actions_kb(product_id, active_plan),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("history_"))
async def cb_price_history(callback: CallbackQuery):
    """Показать график истории цен"""
    product_id = int(callback.data.replace("history_", ""))
    db = await get_db()
    user = await db.get_user(callback.from_user.id)
    product = await db.get_product(product_id)

    if not product:
        await callback.answer("Товар не найден", show_alert=True)
        return

    active_plan = user.active_plan if user else "FREE"
    limits = PlanLimits.get(active_plan)
    days = limits["history_days"]

    await callback.answer("📊 Генерирую график...")

    stats = await get_price_stats(product_id, days=days)

    if not stats.get("has_data") or stats["records_count"] < 2:
        text = (
            f"📊 <b>История цен</b>\n\n"
            f"📦 {product.title or 'Товар'}\n\n"
            f"Пока недостаточно данных для графика.\n"
            f"Записей: {stats.get('records_count', 0)}\n\n"
            f"Отслеживание начато! Данные накопятся за несколько дней."
        )
        await callback.message.edit_text(
            text, reply_markup=product_actions_kb(product_id, active_plan)
        )
        return

    title = product.title[:50] if product.title else "Товар"

    # Проверяем доступ к графику
    if not limits.get("chart") and active_plan == "FREE":
        # Для бесплатного плана — текстовая история
        text = (
            f"📊 <b>История цен (последние {days} дней)</b>\n\n"
            f"📦 {title}\n\n"
            f"💰 Сейчас: <b>{format_price(stats['current_price'])}</b>\n"
            f"📉 Минимум: {format_price(stats['min_price'])}\n"
            f"📈 Максимум: {format_price(stats['max_price'])}\n"
            f"📊 Средняя: {format_price(stats['avg_price'])}\n"
            f"📝 Записей: {stats['records_count']}\n\n"
            f"💎 Для графика нужен PRO план"
        )
        await callback.message.edit_text(
            text, reply_markup=product_actions_kb(product_id, active_plan)
        )
        return

    # Генерируем график
    chart = await generate_price_chart(
        records=stats["records"],
        title=title,
        current_price=stats["current_price"],
        min_price=stats["min_price"],
        max_price=stats["max_price"],
    )

    caption = (
        f"📊 <b>История цен ({days} дн.)</b>\n\n"
        f"📦 {title}\n"
        f"💰 Сейчас: <b>{format_price(stats['current_price'])}</b>\n"
        f"📉 Мин: {format_price(stats['min_price'])}\n"
        f"📈 Макс: {format_price(stats['max_price'])}\n"
        f"📊 Средняя: {format_price(stats['avg_price'])}\n"
        f"📝 Записей: {stats['records_count']}"
    )

    photo = BufferedInputFile(chart.read(), filename="price_chart.png")

    # Удаляем старое сообщение и отправляем фото
    try:
        await callback.message.delete()
    except Exception:
        pass

    await callback.message.answer_photo(
        photo=photo,
        caption=caption,
        reply_markup=product_actions_kb(product_id, active_plan),
    )


@router.callback_query(F.data.startswith("fake_"))
async def cb_fake_discount(callback: CallbackQuery):
    """Проверка фейковой скидки"""
    product_id = int(callback.data.replace("fake_", ""))
    db = await get_db()
    product = await db.get_product(product_id)
    user = await db.get_user(callback.from_user.id)

    if not product:
        await callback.answer("Товар не найден", show_alert=True)
        return

    await callback.answer("🔍 Анализирую скидку...")

    result = await analyze_fake_discount(
        product_id=product_id,
        current_price=product.current_price or 0,
        original_price=product.original_price or 0,
    )

    # Формируем ответ
    confidence_bar = "█" * int(result["confidence"] / 10) + "░" * (10 - int(result["confidence"] / 10))

    text = f"🚨 <b>Детектор фейковых скидок</b>\n\n"
    text += f"📦 {product.title[:60] if product.title else 'Товар'}\n\n"

    if result["is_fake"]:
        text += f"🔴 <b>ФЕЙКОВАЯ СКИДКА</b> (уверенность: {result['confidence']}%)\n"
    else:
        text += f"🟢 <b>Скидка выглядит честной</b> (уверенность: {result['confidence']}%)\n"

    text += f"[{confidence_bar}]\n\n"
    text += result["verdict"] + "\n"

    if result["details"]:
        text += "\n<b>Детали:</b>\n"
        for detail in result["details"]:
            text += f"  {detail}\n"

    active_plan = user.active_plan if user else "FREE"
    await callback.message.edit_text(
        text,
        reply_markup=product_actions_kb(product_id, active_plan),
    )


@router.callback_query(F.data.startswith("cheaper_"))
async def cb_find_cheaper(callback: CallbackQuery):
    """Поиск дешевле на других площадках"""
    product_id = int(callback.data.replace("cheaper_", ""))
    db = await get_db()
    user = await db.get_user(callback.from_user.id)
    product = await db.get_product(product_id)

    if not product:
        await callback.answer("Товар не найден", show_alert=True)
        return

    active_plan = user.active_plan if user else "FREE"
    limits = PlanLimits.get(active_plan)

    if not limits.get("search_cheaper"):
        await callback.message.edit_text(
            "🔍 <b>Поиск дешевле</b>\n\n"
            "Эта функция доступна в тарифах PRO и PREMIUM.\n\n"
            "💎 Улучшите план для доступа!",
            reply_markup=upgrade_kb(),
        )
        await callback.answer()
        return

    await callback.answer("🔍 Ищу на других площадках...")

    results = await find_cheaper(
        title=product.title or "",
        current_price=product.current_price or 0,
        current_marketplace=product.marketplace,
        brand=product.brand or "",
    )

    text = format_cheaper_results(results, product.current_price or 0)

    await callback.message.edit_text(
        text,
        reply_markup=product_actions_kb(product_id, active_plan),
        disable_web_page_preview=True,
    )


@router.callback_query(F.data.startswith("seller_"))
async def cb_seller_check(callback: CallbackQuery):
    """Проверка продавца"""
    product_id = int(callback.data.replace("seller_", ""))
    db = await get_db()
    user = await db.get_user(callback.from_user.id)
    product = await db.get_product(product_id)

    if not product:
        await callback.answer("Товар не найден", show_alert=True)
        return

    active_plan = user.active_plan if user else "FREE"
    limits = PlanLimits.get(active_plan)

    if not limits.get("seller_check"):
        await callback.message.edit_text(
            "🛡 <b>Проверка продавца</b>\n\n"
            "Эта функция доступна в тарифах PRO и PREMIUM.\n\n"
            "💎 Улучшите план для доступа!",
            reply_markup=upgrade_kb(),
        )
        await callback.answer()
        return

    await callback.answer("🛡 Проверяю продавца...")

    result = await check_seller(
        marketplace=product.marketplace,
        seller_id=product.seller_id or "",
        seller_name=product.seller_name or "",
        product_data={
            "rating": product.rating,
            "reviews_count": product.reviews_count,
        },
    )

    text = format_seller_check(result)

    await callback.message.edit_text(
        text,
        reply_markup=product_actions_kb(product_id, active_plan),
    )