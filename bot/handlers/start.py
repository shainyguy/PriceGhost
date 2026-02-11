import logging

from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import CommandStart, Command

from database.db import get_db
from bot.keyboards.inline import main_menu_kb
from bot.keyboards.reply import main_reply_kb

logger = logging.getLogger(__name__)
router = Router()

WELCOME_TEXT = (
    "👻 <b>PriceGhost</b> — Призрак цен\n\n"
    "Я помогу тебе покупать умно:\n\n"
    "🔍 <b>Проверка цен</b> — отправь ссылку на товар\n"
    "📈 <b>История</b> — график цены за год\n"
    "🚨 <b>Разоблачение скидок</b> — покажу фейковые акции\n"
    "🔔 <b>Мониторинг</b> — уведомлю когда цена упадёт\n"
    "🔎 <b>Поиск дешевле</b> — найду на других площадках\n"
    "🤖 <b>AI-анализ</b> — разоблачу фейковые отзывы\n\n"
    "Просто отправь мне ссылку на товар! 👇"
)

HELP_TEXT = (
    "❓ <b>Как пользоваться PriceGhost</b>\n\n"
    "1. Скопируй ссылку на товар\n"
    "2. Отправь её мне в чат\n"
    "3. Получи полный анализ цены!\n\n"
    "Команды:\n"
    "/start — Главное меню\n"
    "/profile — Твой профиль\n"
    "/plans — Тарифные планы\n"
    "/help — Помощь"
)


@router.message(CommandStart())
async def cmd_start(message: Message):
    logger.info(f"START from user {message.from_user.id} ({message.from_user.username})")

    try:
        db = await get_db()
        await db.get_or_create_user(
            telegram_id=message.from_user.id,
            username=message.from_user.username,
            first_name=message.from_user.first_name,
        )
        logger.info(f"User {message.from_user.id} saved to DB")
    except Exception as e:
        logger.error(f"DB error in start: {e}")

    try:
        await message.answer(WELCOME_TEXT, reply_markup=main_menu_kb())
        logger.info(f"Welcome sent to {message.from_user.id}")
    except Exception as e:
        logger.error(f"Send error in start: {e}")

    try:
        await message.answer("⌨️ Или используй кнопки:", reply_markup=main_reply_kb())
    except Exception as e:
        logger.error(f"Reply KB error: {e}")


@router.message(Command("help"))
@router.message(F.text == "❓ Помощь")
async def cmd_help(message: Message):
    logger.info(f"HELP from {message.from_user.id}")
    await message.answer(HELP_TEXT, reply_markup=main_menu_kb())


@router.callback_query(F.data == "help")
async def cb_help(callback: CallbackQuery):
    await callback.message.edit_text(HELP_TEXT, reply_markup=main_menu_kb())
    await callback.answer()


@router.callback_query(F.data == "back_to_menu")
async def cb_back_to_menu(callback: CallbackQuery):
    await callback.message.edit_text(WELCOME_TEXT, reply_markup=main_menu_kb())
    await callback.answer()


@router.callback_query(F.data == "check_price")
async def cb_check_price(callback: CallbackQuery):
    await callback.message.edit_text(
        "🔍 <b>Проверка товара</b>\n\n"
        "Отправь мне ссылку на товар:\n\n"
        "🟣 Wildberries\n"
        "🔵 Ozon\n"
        "🟠 AliExpress\n"
        "🟡 Amazon\n\n"
        "Просто вставь ссылку в чат 👇",
    )
    await callback.answer()


@router.message(F.text == "🔍 Проверить товар")
async def reply_check_price(message: Message):
    await message.answer(
        "🔍 Отправь ссылку на товар с маркетплейса 👇",
    )
