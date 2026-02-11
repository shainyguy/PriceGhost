import logging

from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from database.db import get_db
from config import PlanLimits
from bot.keyboards.inline import (
    monitor_confirm_kb, monitors_list_kb,
    upgrade_kb, back_to_menu_kb, product_actions_kb
)
from bot.utils.helpers import format_price

logger = logging.getLogger(__name__)
router = Router()


class MonitorStates(StatesGroup):
    waiting_target_price = State()


@router.callback_query(F.data.startswith("monitor_"))
async def cb_start_monitor(callback: CallbackQuery):
    """Начать мониторинг товара"""
    product_id = int(callback.data.replace("monitor_", ""))
    db = await get_db()
    user = await db.get_user(callback.from_user.id)

    if not user:
        await callback.answer("Ошибка", show_alert=True)
        return

    active_plan = user.active_plan
    limits = PlanLimits.get(active_plan)

    if not limits.get("notifications"):
        await callback.message.edit_text(
            "🔔 <b>Мониторинг цен</b>\n\n"
            "Эта функция доступна в тарифах PRO и PREMIUM.\n\n"
            "• PRO: мониторинг до 20 товаров\n"
            "• PREMIUM: мониторинг до 50 товаров\n\n"
            "💎 Улучшите план!",
            reply_markup=upgrade_kb(),
        )
        await callback.answer()
        return

    await callback.message.edit_text(
        "🔔 <b>Настройка мониторинга</b>\n\n"
        "Выберите тип уведомлений:",
        reply_markup=monitor_confirm_kb(product_id),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("mon_any_"))
async def cb_monitor_any(callback: CallbackQuery):
    """Мониторить любое снижение"""
    product_id = int(callback.data.replace("mon_any_", ""))
    db = await get_db()
    user = await db.get_user(callback.from_user.id)

    if not user:
        await callback.answer("Ошибка", show_alert=True)
        return

    success, msg = await db.add_monitor(
        user_id=user.id,
        product_id=product_id,
        target_price=None,
    )

    if success:
        product = await db.get_product(product_id)
        await callback.message.edit_text(
            f"✅ <b>Мониторинг включён!</b>\n\n"
            f"📦 {product.title[:60] if product and product.title else 'Товар'}\n"
            f"💰 Текущая цена: {format_price(product.current_price) if product else 'N/A'}\n\n"
            f"🔔 Я уведомлю тебя при ЛЮБОМ снижении цены.",
            reply_markup=product_actions_kb(product_id, user.active_plan),
        )
    else:
        await callback.message.edit_text(
            f"❌ {msg}",
            reply_markup=product_actions_kb(product_id, user.active_plan),
        )

    await callback.answer()


@router.callback_query(F.data.startswith("mon_target_"))
async def cb_monitor_target(callback: CallbackQuery, state: FSMContext):
    """Указать целевую цену"""
    product_id = int(callback.data.replace("mon_target_", ""))

    await state.update_data(monitor_product_id=product_id)
    await state.set_state(MonitorStates.waiting_target_price)

    db = await get_db()
    product = await db.get_product(product_id)

    await callback.message.edit_text(
        f"🎯 <b>Укажите желаемую цену</b>\n\n"
        f"📦 {product.title[:60] if product and product.title else 'Товар'}\n"
        f"💰 Текущая: {format_price(product.current_price) if product else 'N/A'}\n\n"
        f"Введите цену в рублях (только число):",
    )
    await callback.answer()


@router.message(MonitorStates.waiting_target_price)
async def handle_target_price(message: Message, state: FSMContext):
    """Обработка введённой целевой цены"""
    data = await state.get_data()
    product_id = data.get("monitor_product_id")

    try:
        target_price = float(message.text.strip().replace(" ", "").replace(",", "."))
        if target_price <= 0:
            raise ValueError
    except (ValueError, TypeError):
        await message.answer("❌ Введите корректное число (например: 2500)")
        return

    await state.clear()

    db = await get_db()
    user = await db.get_user(message.from_user.id)

    if not user:
        await message.answer("❌ Ошибка. Попробуйте /start")
        return

    success, msg = await db.add_monitor(
        user_id=user.id,
        product_id=product_id,
        target_price=target_price,
    )

    product = await db.get_product(product_id)

    if success:
        await message.answer(
            f"✅ <b>Мониторинг включён!</b>\n\n"
            f"📦 {product.title[:60] if product and product.title else 'Товар'}\n"
            f"💰 Текущая цена: {format_price(product.current_price) if product else 'N/A'}\n"
            f"🎯 Желаемая цена: <b>{format_price(target_price)}</b>\n\n"
            f"🔔 Уведомлю, когда цена достигнет цели!",
            reply_markup=product_actions_kb(product_id, user.active_plan),
        )
    else:
        await message.answer(
            f"❌ {msg}",
            reply_markup=product_actions_kb(product_id, user.active_plan),
        )


# ==================== СПИСОК МОНИТОРИНГА ====================

@router.message(Command("monitors"))
@router.message(F.text == "📊 Мои товары")
async def cmd_monitors(message: Message):
    logger.info(f"MONITORS from {message.from_user.id}")
    db = await get_db()
    monitors = await db.get_user_monitors(message.from_user.id)
    
    if not monitors:
        await message.answer(
            "📊 <b>Мои товары</b>\n\n"
            "Список пуст.\n\n"
            "Чтобы добавить товар:\n"
            "1. Отправь ссылку на товар\n"
            "2. Нажми кнопку 🔔 Мониторить",
            reply_markup=back_to_menu_kb(),
        )
        return

    text = f"📊 <b>Отслеживаемые товары ({len(monitors)})</b>\n\n"
    for i, item in enumerate(monitors, 1):
        product = item["product"]
        monitor = item["monitor"]
        title = product.title[:40] if product.title else f"Товар #{product.id}"
        text += f"{i}. 📦 <b>{title}</b>\n"
        text += f"   💰 {format_price(product.current_price)}"
        if monitor.target_price:
            text += f" | 🎯 {format_price(monitor.target_price)}"
        text += "\n"

    await message.answer(text, reply_markup=monitors_list_kb(monitors)),
    )
    await callback.answer()


async def _show_monitors(message: Message):
    db = await get_db()
    monitors = await db.get_user_monitors(message.from_user.id)

    if not monitors:
        await message.answer(
            "📊 <b>Мои товары</b>\n\n"
            "Список пуст. Отправь ссылку на товар и добавь в мониторинг! 🔔",
            reply_markup=back_to_menu_kb(),
        )
        return

    text = f"📊 <b>Отслеживаемые товары ({len(monitors)})</b>\n\n"

    for i, item in enumerate(monitors, 1):
        product = item["product"]
        monitor = item["monitor"]
        title = product.title[:40] if product.title else f"Товар #{product.id}"

        text += f"{i}. 📦 <b>{title}</b>\n"
        text += f"   💰 {format_price(product.current_price)}"

        if monitor.target_price:
            text += f" | 🎯 {format_price(monitor.target_price)}"
        text += "\n"

    await message.answer(
        text,
        reply_markup=monitors_list_kb(monitors),
    )


@router.callback_query(F.data.startswith("unmonitor_"))
async def cb_unmonitor(callback: CallbackQuery):
    """Удалить из мониторинга"""
    product_id = int(callback.data.replace("unmonitor_", ""))
    db = await get_db()
    user = await db.get_user(callback.from_user.id)

    if user:
        await db.remove_monitor(user.id, product_id)

    await callback.answer("❌ Удалено из мониторинга")

    # Обновляем список
    monitors = await db.get_user_monitors(callback.from_user.id)

    if not monitors:
        await callback.message.edit_text(
            "📊 <b>Мои товары</b>\n\nСписок пуст.",
            reply_markup=back_to_menu_kb(),
        )
    else:
        text = f"📊 <b>Отслеживаемые товары ({len(monitors)})</b>\n\n"
        for i, item in enumerate(monitors, 1):
            product = item["product"]
            title = product.title[:40] if product.title else f"Товар #{product.id}"
            text += f"{i}. 📦 {title} — {format_price(product.current_price)}\n"

        await callback.message.edit_text(
            text,
            reply_markup=monitors_list_kb(monitors),

        )
