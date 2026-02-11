from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import CommandStart, Command

from database.db import get_db
from bot.keyboards.inline import main_menu_kb
from bot.keyboards.reply import main_reply_kb

router = Router()

WELCOME_TEXT = """
👻 <b>PriceGhost</b> — Призрак цен

Я помогу тебе покупать умно:

🔍 <b>Проверка цен</b> — отправь ссылку на товар
📈 <b>История</b> — график цены за год
🚨 <b>Разоблачение скидок</b> — покажу фейковые акции
🔔 <b>Мониторинг</b> — уведомлю когда цена упадёт
🔎 <b>Поиск дешевле</b> — найду на других площадках
🤖 <b>AI-анализ</b> — разоблачу фейковые отзывы

<b>Поддерживаемые площадки:</b>
🟣 Wildberries  🔵 Ozon  🟠 AliExpress  🟡 Amazon

Просто отправь мне ссылку на товар! 👇
"""

HELP_TEXT = """
❓ <b>Как пользоваться PriceGhost</b>

<b>1.</b> Скопируй ссылку на товар с маркетплейса
<b>2.</b> Отправь её мне в чат
<b>3.</b> Получи полный анализ цены!

<b>Команды:</b>
/start — Главное меню
/profile — Твой профиль
/plans — Тарифные планы
/monitors — Отслеживаемые товары
/help — Помощь

<b>Поддерживаемые ссылки:</b>
• wildberries.ru/catalog/123456789
• ozon.ru/product/...
• aliexpress.com/item/...
• amazon.com/dp/...

<b>Бесплатный план:</b> 3 проверки/день
<b>PRO:</b> 30 проверок + мониторинг + поиск
<b>PREMIUM:</b> безлимит + AI + прогнозы
"""


@router.message(CommandStart())
async def cmd_start(message: Message):
    db = await get_db()
    await db.get_or_create_user(
        telegram_id=message.from_user.id,
        username=message.from_user.username,
        first_name=message.from_user.first_name,
    )
    await message.answer(
        WELCOME_TEXT,
        parse_mode="HTML",
        reply_markup=main_menu_kb(),
    )
    await message.answer(
        "⌨️ Или используй кнопки:",
        reply_markup=main_reply_kb(),
    )


@router.message(Command("help"))
@router.message(F.text == "❓ Помощь")
async def cmd_help(message: Message):
    await message.answer(HELP_TEXT, parse_mode="HTML", reply_markup=main_menu_kb())


@router.callback_query(F.data == "help")
async def cb_help(callback: CallbackQuery):
    await callback.message.edit_text(
        HELP_TEXT, parse_mode="HTML", reply_markup=main_menu_kb()
    )
    await callback.answer()


@router.callback_query(F.data == "back_to_menu")
async def cb_back_to_menu(callback: CallbackQuery):
    await callback.message.edit_text(
        WELCOME_TEXT, parse_mode="HTML", reply_markup=main_menu_kb()
    )
    await callback.answer()


@router.callback_query(F.data == "check_price")
async def cb_check_price(callback: CallbackQuery):
    await callback.message.edit_text(
        "🔍 <b>Проверка товара</b>\n\n"
        "Отправь мне ссылку на товар с любого маркетплейса:\n\n"
        "🟣 Wildberries\n"
        "🔵 Ozon\n"
        "🟠 AliExpress\n"
        "🟡 Amazon\n\n"
        "Просто вставь ссылку в чат 👇",
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(F.text == "🔍 Проверить товар")
async def reply_check_price(message: Message):
    await message.answer(
        "🔍 <b>Проверка товара</b>\n\n"
        "Отправь мне ссылку на товар с любого маркетплейса:\n\n"
        "🟣 Wildberries  🔵 Ozon  🟠 AliExpress  🟡 Amazon\n\n"
        "Просто вставь ссылку в чат 👇",
        parse_mode="HTML",
    )