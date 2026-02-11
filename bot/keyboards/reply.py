from aiogram.types import ReplyKeyboardMarkup, KeyboardButton
from aiogram.utils.keyboard import ReplyKeyboardBuilder


def main_reply_kb() -> ReplyKeyboardMarkup:
    builder = ReplyKeyboardBuilder()
    builder.row(
        KeyboardButton(text="🔍 Проверить товар"),
    )
    builder.row(
        KeyboardButton(text="📊 Мои товары"),
        KeyboardButton(text="👤 Профиль"),
    )
    builder.row(
        KeyboardButton(text="💎 Тарифы"),
        KeyboardButton(text="❓ Помощь"),
    )
    return builder.as_markup(resize_keyboard=True)