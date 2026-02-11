import logging

from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, BufferedInputFile

from database.db import get_db
from config import PlanLimits
from bot.utils.url_parser import (
    parse_marketplace_url, resolve_short_url,
    get_marketplace_emoji, get_marketplace_name
)
from bot.utils.helpers import format_price, format_percent, plan_badge
from bot.keyboards.inline import (
    product_actions_kb, upgrade_kb, back_to_menu_kb
)
from bot.services.price_history import fetch_and_save_price, get_price_stats
from bot.services.chart import generate_price_chart
from bot.services.fake_discount import analyze_fake_discount

logger = logging.getLogger(__name__)
router = Router()


@router.message(F.text.regexp(r"https?://"))
async def handle_url(message: Message):
    """Обработка ссылки на товар"""
    url = message.text.strip()

    # Если в тексте несколько слов — ищем URL
    if " " in url:
        import re
        urls = re.findall(r'https?://\S+', url)
        if urls:
            url = urls[0]
        else:
            return

    # Парсим URL
    marketplace, product_id, clean_url = parse_marketplace_url(url)

    # Короткая ссылка Ozon — резолвим
    if marketplace == "ozon_short":
        loading = await message.answer("⏳ Обрабатываю короткую ссылку...")
        resolved = await resolve_short_url(url)
        if resolved:
            marketplace, product_id, clean_url = parse_marketplace_url(resolved)
            if not marketplace:
                await loading.edit_text(
                    "❌ Не удалось распознать ссылку после перенаправления.\n"
                    f"Получена: {resolved}\n\n"
                    "Попробуйте скопировать полную ссылку на товар."
                )
                return
        else:
            await loading.edit_text(
                "❌ Не удалось обработать короткую ссылку.\n"
                "Попробуйте скопировать полную ссылку на товар с Ozon."
            )
            return
        try:
            await loading.delete()
        except:
            pass

    if not marketplace:
        await message.answer(
            "❌ Не удалось распознать ссылку.\n\n"
            "Поддерживаемые площадки:\n"
            "🟣 Wildberries — wildberries.ru/catalog/...\n"
            "🔵 Ozon — ozon.ru/product/...\n"
            "🟠 AliExpress — aliexpress.ru/item/...\n"
            "🟡 Amazon — amazon.com/dp/...\n\n"
            "Скопируйте прямую ссылку на товар.",
        )
        return

    db = await get_db()
    user = await db.get_or_create_user(
        telegram_id=message.from_user.id,
        username=message.from_user.username,
        first_name=message.from_user.first_name,
    )

    # Проверяем лимит
    allowed, used, limit = await db.check_and_increment_usage(message.from_user.id)

    if not allowed:
        await message.answer(
            f"⛔ <b>Лимит исчерпан!</b>\n\n"
            f"Тариф: {plan_badge(user.active_plan)}\n"
            f"Проверок сегодня: {used}/{limit}\n\n"
            f"💎 Улучши план для большего количества проверок!",
            reply_markup=upgrade_kb(),
        )
        return

    mp_emoji = get_marketplace_emoji(marketplace)
    mp_name = get_marketplace_name(marketplace)

    loading_msg = await message.answer(
        f"⏳ Анализирую товар...\n\n"
        f"{mp_emoji} {mp_name} | ID: {product_id}\n"
        f"📊 Проверка {used}/{limit}",
    )

    # Скрапим и сохраняем
    product_data = await fetch_and_save_price(
        marketplace, product_id, clean_url or url
    )

    if not product_data:
        await loading_msg.edit_text(
            f"❌ Не удалось получить данные о товаре.\n\n"
            f"{mp_emoji} {mp_name}\n\n"
            f"Возможные причины:\n"
            f"• Товар удалён или недоступен\n"
            f"• {mp_name} блокирует запросы с серверов\n"
            f"• Некорректная ссылка\n\n"
            f"💡 Попробуйте другую ссылку или площадку.",
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

    if stats.get("has_data") and stats["records_count"] > 1:
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

        if current_price <= stats["min_price"] * 1.05:
            text += "\n🎉 <b>Отличная цена! Близко к минимуму.</b>"
        elif current_price >= stats["max_price"] * 0.95:
            text += "\n⚠️ <b>Цена близка к максимуму. Лучше подождать.</b>"
    else:
        text += "\n📊 Отслеживание начато! Данные накопятся за несколько дней."

    active_plan = user.active_plan

    await loading_msg.edit_text(
        text,
        reply_markup=product_actions_kb(db_id, active_plan),
    )


# ==================== ДЕЙСТВИЯ С ТОВАРОМ ====================

@router.callback_query(F.data.startswith("product_"))
async def cb_product_info(callback: CallbackQuery):
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

    if product.original_price and product.original_price > (product.current_price or 0):
        text += f"🏷 До скидки: <s>{format_price(product.original_price)}</s>\n"

    active_plan = user.active_plan if user else "FREE"
    await callback.message.edit_text(
        text, reply_markup=product_actions_kb(product_id, active_plan)
    )
    await callback.answer()


@router.callback_query(F.data.startswith("history_"))
async def cb_price_history(callback: CallbackQuery):
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

    await callback.answer("📊 Генерирую...")

    stats = await get_price_stats(product_id, days=days)

    if not stats.get("has_data") or stats["records_count"] < 2:
        await callback.message.edit_text(
            f"📊 <b>История цен</b>\n\n"
            f"📦 {product.title or 'Товар'}\n\n"
            f"Записей: {stats.get('records_count', 1)}\n"
            f"Данные накопятся за несколько дней.\n"
            f"Каждая проверка добавляет точку на график!",
            reply_markup=product_actions_kb(product_id, active_plan),
        )
        return

    title = (product.title or "Товар")[:50]

    if not limits.get("chart") and active_plan == "FREE":
        text = (
            f"📊 <b>История цен ({days} дн.)</b>\n\n"
            f"📦 {title}\n\n"
            f"💰 Сейчас: <b>{format_price(stats['current_price'])}</b>\n"
            f"📉 Мин: {format_price(stats['min_price'])}\n"
            f"📈 Макс: {format_price(stats['max_price'])}\n"
            f"📊 Средняя: {format_price(stats['avg_price'])}\n"
            f"📝 Записей: {stats['records_count']}\n\n"
            f"💎 Для графика нужен PRO план"
        )
        await callback.message.edit_text(
            text, reply_markup=product_actions_kb(product_id, active_plan)
        )
        return

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

    try:
        await callback.message.delete()
    except:
        pass

    await callback.message.answer_photo(
        photo=photo,
        caption=caption,
        reply_markup=product_actions_kb(product_id, active_plan),
    )


@router.callback_query(F.data.startswith("fake_"))
async def cb_fake_discount(callback: CallbackQuery):
    product_id = int(callback.data.replace("fake_", ""))
    db = await get_db()
    product = await db.get_product(product_id)
    user = await db.get_user(callback.from_user.id)

    if not product:
        await callback.answer("Товар не найден", show_alert=True)
        return

    await callback.answer("🔍 Анализирую...")

    result = await analyze_fake_discount(
        product_id=product_id,
        current_price=product.current_price or 0,
        original_price=product.original_price or 0,
    )

    bar_filled = int(result["confidence"] / 10)
    bar = "█" * bar_filled + "░" * (10 - bar_filled)

    text = f"🚨 <b>Детектор фейковых скидок</b>\n\n"
    text += f"📦 {(product.title or 'Товар')[:60]}\n\n"

    if result["is_fake"]:
        text += f"🔴 <b>ФЕЙКОВАЯ СКИДКА</b> ({result['confidence']}%)\n"
    else:
        text += f"🟢 <b>Скидка честная</b> ({result['confidence']}%)\n"

    text += f"[{bar}]\n\n"
    text += result["verdict"] + "\n"

    if result["details"]:
        text += "\n<b>Детали:</b>\n"
        for d in result["details"]:
            text += f"  {d}\n"

    active_plan = user.active_plan if user else "FREE"
    await callback.message.edit_text(
        text, reply_markup=product_actions_kb(product_id, active_plan)
    )


@router.callback_query(F.data.startswith("cheaper_"))
async def cb_find_cheaper(callback: CallbackQuery):
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
            "Доступно в PRO и PREMIUM.\n\n"
            "💎 Улучшите план!",
            reply_markup=upgrade_kb(),
        )
        await callback.answer()
        return

    await callback.answer("🔍 Ищу...")

    from bot.services.search_cheaper import find_cheaper, format_cheaper_results
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
            "🛡 <b>Проверка продавца</b>\n\nДоступно в PRO и PREMIUM.",
            reply_markup=upgrade_kb(),
        )
        await callback.answer()
        return

    await callback.answer("🛡 Проверяю...")

    from bot.services.seller_check import check_seller, format_seller_check
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
        text, reply_markup=product_actions_kb(product_id, active_plan)
    )
