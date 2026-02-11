import logging
from datetime import datetime

from aiogram import Router, F
from aiogram.types import Message
from aiogram.filters import Command

from database.db import get_db
from config import config

logger = logging.getLogger(__name__)
router = Router()


def is_admin(user_id: int) -> bool:
    return user_id in config.bot.admin_ids


@router.message(Command("admin"))
async def cmd_admin(message: Message):
    """Админ-панель"""
    if not is_admin(message.from_user.id):
        return

    db = await get_db()
    total_users = await db.get_total_users()

    # Считаем подписчиков по планам
    from sqlalchemy import select, func
    from database.models import User, MonitoredProduct, Payment

    async with db.session_factory() as session:
        # Пользователи по планам
        result = await session.execute(
            select(User.plan, func.count(User.id)).group_by(User.plan)
        )
        plan_stats = {row[0]: row[1] for row in result.all()}

        # Активные мониторы
        result = await session.execute(
            select(func.count(MonitoredProduct.id)).where(
                MonitoredProduct.is_active == True
            )
        )
        active_monitors = result.scalar() or 0

        # Оплаты
        result = await session.execute(
            select(func.count(Payment.id)).where(
                Payment.status == "succeeded"
            )
        )
        total_payments = result.scalar() or 0

        result = await session.execute(
            select(func.sum(Payment.amount)).where(
                Payment.status == "succeeded"
            )
        )
        total_revenue = result.scalar() or 0

        # Сегодняшние пользователи
        today = datetime.utcnow().date()
        result = await session.execute(
            select(func.count(User.id)).where(
                func.date(User.created_at) == today
            )
        )
        new_today = result.scalar() or 0

    text = f"""
👑 <b>ADMIN PANEL — PriceGhost</b>

📊 <b>Пользователи:</b>
├ Всего: <b>{total_users}</b>
├ Новых сегодня: <b>{new_today}</b>
├ FREE: {plan_stats.get('FREE', 0)}
├ PRO: {plan_stats.get('PRO', 0)}
└ PREMIUM: {plan_stats.get('PREMIUM', 0)}

📦 <b>Мониторинг:</b>
└ Активных отслеживаний: <b>{active_monitors}</b>

💰 <b>Финансы:</b>
├ Успешных оплат: <b>{total_payments}</b>
└ Доход: <b>{total_revenue:,.0f}₽</b>

🕐 Время: {datetime.utcnow().strftime('%d.%m.%Y %H:%M')} UTC
"""
    await message.answer(text, parse_mode="HTML")


@router.message(Command("broadcast"))
async def cmd_broadcast(message: Message):
    """Рассылка всем пользователям"""
    if not is_admin(message.from_user.id):
        return

    # Формат: /broadcast Текст сообщения
    text = message.text.replace("/broadcast", "").strip()

    if not text:
        await message.answer(
            "Использование: /broadcast <текст сообщения>\n\n"
            "Пример:\n/broadcast 🎉 Новая функция! Теперь бот умеет..."
        )
        return

    db = await get_db()

    from sqlalchemy import select
    from database.models import User

    async with db.session_factory() as session:
        result = await session.execute(select(User.telegram_id))
        user_ids = [row[0] for row in result.all()]

    sent = 0
    failed = 0
    bot = message.bot

    status_msg = await message.answer(
        f"📤 Рассылка: 0/{len(user_ids)}..."
    )

    for uid in user_ids:
        try:
            await bot.send_message(
                chat_id=uid,
                text=f"📢 <b>Уведомление от PriceGhost</b>\n\n{text}",
                parse_mode="HTML",
            )
            sent += 1
        except Exception:
            failed += 1

        if (sent + failed) % 50 == 0:
            try:
                await status_msg.edit_text(
                    f"📤 Рассылка: {sent + failed}/{len(user_ids)}...\n"
                    f"✅ {sent} | ❌ {failed}"
                )
            except Exception:
                pass

        # Задержка для API limits
        import asyncio
        await asyncio.sleep(0.05)

    await status_msg.edit_text(
        f"✅ <b>Рассылка завершена!</b>\n\n"
        f"📤 Отправлено: {sent}\n"
        f"❌ Не доставлено: {failed}\n"
        f"📊 Всего: {len(user_ids)}"
    )


@router.message(Command("give_plan"))
async def cmd_give_plan(message: Message):
    """Выдать план пользователю: /give_plan <user_id> <plan> <days>"""
    if not is_admin(message.from_user.id):
        return

    parts = message.text.split()
    if len(parts) < 3:
        await message.answer(
            "Использование: /give_plan <telegram_id> <plan> [days]\n\n"
            "Пример: /give_plan 123456789 PREMIUM 30"
        )
        return

    try:
        target_id = int(parts[1])
        plan = parts[2].upper()
        days = int(parts[3]) if len(parts) > 3 else 30

        if plan not in ("FREE", "PRO", "PREMIUM"):
            await message.answer("❌ План должен быть: FREE, PRO или PREMIUM")
            return

        db = await get_db()
        await db.activate_plan(target_id, plan, days)

        await message.answer(
            f"✅ План <b>{plan}</b> выдан пользователю "
            f"<code>{target_id}</code> на {days} дней.",
            parse_mode="HTML",
        )

        # Уведомляем пользователя
        try:
            from bot.utils.helpers import plan_badge
            await message.bot.send_message(
                chat_id=target_id,
                text=(
                    f"🎁 <b>Вам активирован план {plan_badge(plan)}!</b>\n\n"
                    f"Действует {days} дней. Наслаждайтесь! 👻"
                ),
                parse_mode="HTML",
            )
        except Exception:
            pass

    except ValueError:
        await message.answer("❌ Некорректные параметры. ID и дни должны быть числами.")


@router.message(Command("stats"))
async def cmd_stats(message: Message):
    """Краткая статистика"""
    if not is_admin(message.from_user.id):
        return

    db = await get_db()
    total = await db.get_total_users()

    from sqlalchemy import select, func
    from database.models import Product, PriceRecord

    async with db.session_factory() as session:
        result = await session.execute(select(func.count(Product.id)))
        total_products = result.scalar() or 0

        result = await session.execute(select(func.count(PriceRecord.id)))
        total_records = result.scalar() or 0

    await message.answer(
        f"📊 <b>Быстрая статистика</b>\n\n"
        f"👥 Пользователей: {total}\n"
        f"📦 Товаров в базе: {total_products}\n"
        f"📈 Записей цен: {total_records}",
        parse_mode="HTML",
    )