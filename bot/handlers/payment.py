from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import Command

from database.db import get_db
from bot.keyboards.inline import plans_kb, payment_kb, back_to_menu_kb, main_menu_kb
from bot.services.yookassa_service import create_payment, check_payment_status
from bot.utils.helpers import plan_badge

router = Router()

PLANS_TEXT = """
💎 <b>Тарифные планы PriceGhost</b>

┌──────────────────────────────────┐
│  🆓 <b>FREE</b> (0₽)                    │
├──────────────────────────────────┤
│  ✅ 3 проверки цены в день       │
│  ✅ История за 30 дней           │
│  ✅ Детектор фейковых скидок     │
└──────────────────────────────────┘

┌──────────────────────────────────┐
│  ⭐ <b>PRO</b> (490₽/мес)   ПОПУЛЯРНЫЙ  │
├──────────────────────────────────┤
│  ✅ 30 проверок в день           │
│  ✅ История за 1 год + график    │
│  ✅ Мониторинг 20 товаров        │
│  ✅ Уведомления о снижении       │
│  ✅ Поиск на других площадках    │
│  ✅ Проверка продавца            │
└──────────────────────────────────┘

┌──────────────────────────────────┐
│  👑 <b>PREMIUM</b> (990₽/мес)           │
├──────────────────────────────────┤
│  Всё из PRO, плюс:              │
│  ✅ Безлимит проверок            │
│  ✅ Мониторинг 50 товаров        │
│  ✅ AI-анализ отзывов            │
│  ✅ Поиск аналогов дешевле       │
│  ✅ Прогноз цен + календарь      │
│  ✅ Кешбэк и промокоды           │
│  ✅ Приоритетная поддержка       │
└──────────────────────────────────┘
"""


@router.message(Command("plans"))
@router.message(F.text == "💎 Тарифы")
async def cmd_plans(message: Message):
    await message.answer(PLANS_TEXT, parse_mode="HTML", reply_markup=plans_kb())


@router.callback_query(F.data == "plans")
async def cb_plans(callback: CallbackQuery):
    await callback.message.edit_text(
        PLANS_TEXT, parse_mode="HTML", reply_markup=plans_kb()
    )
    await callback.answer()


@router.callback_query(F.data.in_({"buy_pro", "buy_premium"}))
async def cb_buy_plan(callback: CallbackQuery):
    plan = "PRO" if callback.data == "buy_pro" else "PREMIUM"
    amount = 490 if plan == "PRO" else 990

    await callback.answer("⏳ Создаю платёж...")

    # Создаём платёж в ЮKassa
    payment_id, payment_url = await create_payment(
        plan=plan,
        telegram_id=callback.from_user.id
    )

    if not payment_id or not payment_url:
        await callback.message.edit_text(
            "❌ Ошибка создания платежа. Попробуйте позже.",
            reply_markup=back_to_menu_kb()
        )
        return

    # Сохраняем в БД
    db = await get_db()
    await db.create_payment(
        user_id=callback.from_user.id,
        plan=plan,
        amount=float(amount),
        yookassa_id=payment_id,
        payment_url=payment_url,
    )

    text = f"""
💳 <b>Оплата {plan_badge(plan)}</b>

💰 Сумма: <b>{amount}₽</b>
📋 Период: <b>1 месяц</b>

Нажми «Оплатить» для перехода на страницу оплаты.
После оплаты нажми «Проверить оплату» ✅

🔒 Безопасная оплата через ЮKassa
"""

    await callback.message.edit_text(
        text,
        parse_mode="HTML",
        reply_markup=payment_kb(payment_url, payment_id),
    )


@router.callback_query(F.data.startswith("check_payment_"))
async def cb_check_payment(callback: CallbackQuery):
    payment_id = callback.data.replace("check_payment_", "")

    status = await check_payment_status(payment_id)

    if status == "succeeded":
        db = await get_db()
        payment = await db.complete_payment(payment_id)

        if payment:
            await callback.message.edit_text(
                f"🎉 <b>Оплата прошла успешно!</b>\n\n"
                f"✅ Тариф {plan_badge(payment.plan)} активирован на 30 дней!\n\n"
                f"Наслаждайся всеми возможностями PriceGhost! 👻",
                parse_mode="HTML",
                reply_markup=main_menu_kb(),
            )
        else:
            await callback.message.edit_text(
                "❌ Платёж не найден в базе данных.",
                reply_markup=back_to_menu_kb(),
            )
    elif status == "pending":
        await callback.answer(
            "⏳ Оплата ещё не поступила. Подожди немного и попробуй снова.",
            show_alert=True,
        )
    elif status == "canceled":
        await callback.message.edit_text(
            "❌ Платёж был отменён.",
            reply_markup=plans_kb(),
        )
    else:
        await callback.answer(
            "⏳ Статус: обработка. Попробуй через минуту.",
            show_alert=True,
        )