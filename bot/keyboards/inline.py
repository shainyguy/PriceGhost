from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder


def main_menu_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="🔍 Проверить товар", callback_data="check_price"),
    )
    builder.row(
        InlineKeyboardButton(text="📊 Мои товары", callback_data="my_monitors"),
        InlineKeyboardButton(text="👤 Профиль", callback_data="profile"),
    )
    builder.row(
        InlineKeyboardButton(text="💎 Тарифы", callback_data="plans"),
        InlineKeyboardButton(text="❓ Помощь", callback_data="help"),
    )
    return builder.as_markup()


def plans_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="⭐ PRO — 490₽/мес", callback_data="buy_pro"),
    )
    builder.row(
        InlineKeyboardButton(text="👑 PREMIUM — 990₽/мес", callback_data="buy_premium"),
    )
    builder.row(
        InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_menu"),
    )
    return builder.as_markup()


def product_actions_kb(product_id: int, plan: str = "FREE") -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()

    builder.row(
        InlineKeyboardButton(
            text="📈 История цен",
            callback_data=f"history_{product_id}"
        ),
        InlineKeyboardButton(
            text="🚨 Фейк-скидка?",
            callback_data=f"fake_{product_id}"
        ),
    )

    if plan in ("PRO", "PREMIUM"):
        builder.row(
            InlineKeyboardButton(
                text="🔔 Мониторить",
                callback_data=f"monitor_{product_id}"
            ),
            InlineKeyboardButton(
                text="🔍 Дешевле",
                callback_data=f"cheaper_{product_id}"
            ),
        )
        builder.row(
            InlineKeyboardButton(
                text="🛡 Продавец",
                callback_data=f"seller_{product_id}"
            ),
        )

    if plan == "PREMIUM":
        builder.row(
            InlineKeyboardButton(
                text="🤖 AI-отзывы",
                callback_data=f"reviews_{product_id}"
            ),
            InlineKeyboardButton(
                text="📦 Аналоги",
                callback_data=f"analogs_{product_id}"
            ),
        )
        builder.row(
            InlineKeyboardButton(
                text="📅 Прогноз цен",
                callback_data=f"predict_{product_id}"
            ),
            InlineKeyboardButton(
                text="💸 Кешбэк",
                callback_data=f"cashback_{product_id}"
            ),
        )

    builder.row(
        InlineKeyboardButton(text="◀️ Меню", callback_data="back_to_menu"),
    )
    return builder.as_markup()


def monitor_confirm_kb(product_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text="🔔 Уведомлять о ЛЮБОМ снижении",
            callback_data=f"mon_any_{product_id}"
        ),
    )
    builder.row(
        InlineKeyboardButton(
            text="🎯 Указать желаемую цену",
            callback_data=f"mon_target_{product_id}"
        ),
    )
    builder.row(
        InlineKeyboardButton(text="◀️ Назад", callback_data=f"product_{product_id}"),
    )
    return builder.as_markup()


def monitors_list_kb(monitors: list) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for item in monitors:
        product = item["product"]
        title = product.title[:35] if product.title else f"Товар #{product.id}"
        builder.row(
            InlineKeyboardButton(
                text=f"📦 {title}",
                callback_data=f"product_{product.id}"
            ),
            InlineKeyboardButton(
                text="❌",
                callback_data=f"unmonitor_{product.id}"
            ),
        )
    builder.row(
        InlineKeyboardButton(text="◀️ Меню", callback_data="back_to_menu"),
    )
    return builder.as_markup()


def payment_kb(payment_url: str, payment_id: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="💳 Оплатить", url=payment_url),
    )
    builder.row(
        InlineKeyboardButton(
            text="✅ Проверить оплату",
            callback_data=f"check_payment_{payment_id}"
        ),
    )
    builder.row(
        InlineKeyboardButton(text="◀️ Назад", callback_data="plans"),
    )
    return builder.as_markup()


def back_to_menu_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="◀️ Меню", callback_data="back_to_menu"),
    )
    return builder.as_markup()


def upgrade_kb() -> InlineKeyboardMarkup:
    """Кнопка апгрейда для заблокированных функций"""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="💎 Улучшить план", callback_data="plans"),
    )
    builder.row(
        InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_menu"),
    )
    return builder.as_markup()