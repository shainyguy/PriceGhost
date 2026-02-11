from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import Command

from database.db import get_db
from bot.keyboards.inline import main_menu_kb, plans_kb
from bot.utils.helpers import format_datetime, plan_badge
from config import PlanLimits

router = Router()


async def get_profile_text(telegram_id: int) -> str:
    db = await get_db()
    user = await db.get_user(telegram_id)
    if not user:
        return "❌ Пользователь не найден"

    active_plan = user.active_plan
    limits = PlanLimits.get(active_plan)

    text = f"""
👤 <b>Твой профиль</b>

🆔 ID: <code>{user.telegram_id}</code>
📛 Имя: {user.first_name or 'Не указано'}
📋 Тариф: {plan_badge(active_plan)}
"""

    if active_plan != "FREE" and user.plan_expires_at:
        text += f"⏳ Действует до: {format_datetime(user.plan_expires_at)}\n"

    text += f"""
📊 <b>Использование сегодня:</b>
├ Проверок: {user.checks_today} / {limits['checks_per_day']}
"""

    if limits["monitor_items"] > 0:
        monitors = await db.get_user_monitors(telegram_id)
        text += f"├ Мониторинг: {len(monitors)} / {limits['monitor_items']}\n"
    else:
        text += "├ Мониторинг: ❌ (доступно в PRO)\n"

    text += f"""
📅 Дата регистрации: {format_datetime(user.created_at)}

{'💎 Хочешь больше возможностей? Жми «Тарифы»!' if active_plan == 'FREE' else '✨ Спасибо за подписку!'}
"""
    return text


@router.message(Command("profile"))
@router.message(F.text == "👤 Профиль")
async def cmd_profile(message: Message):
    text = await get_profile_text(message.from_user.id)
    await message.answer(text, parse_mode="HTML", reply_markup=main_menu_kb())


@router.callback_query(F.data == "profile")
async def cb_profile(callback: CallbackQuery):
    text = await get_profile_text(callback.from_user.id)
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=main_menu_kb())
    await callback.answer()