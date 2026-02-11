import logging
from typing import Dict, Any, Optional
from datetime import datetime

from bot.services.price_history import get_monthly_avg_prices, get_price_stats
from bot.services.gigachat import get_gigachat
from bot.services.chart import generate_monthly_chart

logger = logging.getLogger(__name__)

MONTH_NAMES = [
    "", "Январь", "Февраль", "Март", "Апрель", "Май", "Июнь",
    "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь"
]

MONTH_NAMES_SHORT = [
    "", "Янв", "Фев", "Мар", "Апр", "Май", "Июн",
    "Июл", "Авг", "Сен", "Окт", "Ноя", "Дек"
]

# Общие тренды по категориям
CATEGORY_TRENDS = {
    "электроника": {
        "best_months": [1, 2, 3, 11],
        "worst_months": [9, 12],
        "tip": "Электроника дешевеет после Нового года и в Чёрную пятницу",
    },
    "одежда": {
        "best_months": [1, 2, 7, 8],
        "worst_months": [3, 4, 9, 10],
        "tip": "Одежду лучше покупать на сезонных распродажах (янв-фев, июл-авг)",
    },
    "обувь": {
        "best_months": [1, 2, 7, 8],
        "worst_months": [3, 9, 10],
        "tip": "Обувь дешевеет в конце сезона",
    },
    "бытовая техника": {
        "best_months": [1, 2, 3, 11],
        "worst_months": [8, 9, 12],
        "tip": "Технику лучше покупать в начале года или на Чёрную пятницу",
    },
    "косметика": {
        "best_months": [1, 3, 11],
        "worst_months": [2, 12],
        "tip": "Косметика дорожает перед 8 марта и Новым годом",
    },
    "детские товары": {
        "best_months": [1, 2, 6],
        "worst_months": [8, 9, 12],
        "tip": "Детские товары дорожают к школе (авг-сен) и к НГ",
    },
    "спорт": {
        "best_months": [1, 2, 7],
        "worst_months": [3, 4, 9],
        "tip": "Спорттовары дешевле зимой и в середине лета",
    },
    "default": {
        "best_months": [1, 2, 11],
        "worst_months": [12],
        "tip": "Лучшее время для покупок — после Нового года и Чёрная пятница",
    },
}


def _get_category_trend(category: str) -> dict:
    """Подбирает тренд по категории"""
    category_lower = (category or "").lower()
    for key, value in CATEGORY_TRENDS.items():
        if key != "default" and key in category_lower:
            return value
    return CATEGORY_TRENDS["default"]


async def predict_price(
    product_id: int,
    title: str = "",
    category: str = "",
    current_price: float = 0,
) -> Dict[str, Any]:
    """
    Прогноз цены:
    1. Анализ истории по месяцам
    2. Определение лучшего времени для покупки
    3. AI-прогноз
    """
    result = {
        "has_history": False,
        "monthly_prices": {},
        "best_month": None,
        "worst_month": None,
        "best_saving_percent": 0,
        "current_vs_avg": 0,
        "recommendation": "",
        "category_tip": "",
        "ai_prediction": "",
        "monthly_chart": None,
    }

    # 1. История по месяцам
    monthly = await get_monthly_avg_prices(product_id)

    if monthly and len(monthly) >= 3:
        result["has_history"] = True
        result["monthly_prices"] = monthly

        # Лучший/худший месяц
        best_month = min(monthly, key=monthly.get)
        worst_month = max(monthly, key=monthly.get)
        best_price = monthly[best_month]
        worst_price = monthly[worst_month]

        result["best_month"] = best_month
        result["worst_month"] = worst_month

        if worst_price > 0:
            result["best_saving_percent"] = round(
                (1 - best_price / worst_price) * 100, 1
            )

        # Текущая vs средняя
        avg = sum(monthly.values()) / len(monthly)
        if avg > 0:
            result["current_vs_avg"] = round(
                ((current_price - avg) / avg) * 100, 1
            )

        # Генерируем график
        try:
            chart = await generate_monthly_chart(
                monthly, title=f"Средние цены: {title[:40]}"
            )
            result["monthly_chart"] = chart
        except Exception as e:
            logger.error(f"Monthly chart error: {e}")

    # 2. Общие тренды по категории
    category_trend = _get_category_trend(category)
    result["category_tip"] = category_trend["tip"]

    # 3. Формируем рекомендацию
    now_month = datetime.utcnow().month

    if result["has_history"]:
        best = result["best_month"]
        saving = result["best_saving_percent"]

        if now_month == best:
            result["recommendation"] = (
                f"🎉 <b>Сейчас лучшее время!</b>\n"
                f"Исторически {MONTH_NAMES[best]} — самый дешёвый месяц "
                f"(экономия до {saving:.0f}%)."
            )
        elif now_month in category_trend.get("best_months", []):
            result["recommendation"] = (
                f"✅ <b>Хорошее время для покупки!</b>\n"
                f"Этот месяц обычно один из лучших для данной категории."
            )
        elif now_month in category_trend.get("worst_months", []):
            months_to_wait = best - now_month
            if months_to_wait < 0:
                months_to_wait += 12
            result["recommendation"] = (
                f"⏳ <b>Лучше подождать!</b>\n"
                f"Исторически цена дешевеет на <b>{saving:.0f}%</b> "
                f"в {MONTH_NAMES[best]}е (через ~{months_to_wait} мес.).\n"
                f"Сейчас не лучшее время для покупки."
            )
        else:
            result["recommendation"] = (
                f"🤔 <b>Средний период.</b>\n"
                f"Лучший месяц — {MONTH_NAMES[best]} (дешевле на {saving:.0f}%).\n"
                f"Можно купить сейчас, но есть шанс на более низкую цену."
            )

        # Сравнение с текущей ценой
        diff = result["current_vs_avg"]
        if diff > 10:
            result["recommendation"] += (
                f"\n\n⚠️ Текущая цена на <b>{diff:.0f}%</b> выше средней. "
                f"Рекомендуем подождать."
            )
        elif diff < -10:
            result["recommendation"] += (
                f"\n\n🎉 Текущая цена на <b>{abs(diff):.0f}%</b> ниже средней. "
                f"Хорошая сделка!"
            )
    else:
        result["recommendation"] = (
            f"📊 Недостаточно исторических данных для персонального прогноза.\n\n"
            f"💡 {category_trend['tip']}"
        )

    # 4. AI-прогноз
    if result["has_history"]:
        ai_pred = await _ai_price_prediction(
            title, category, current_price,
            result["monthly_prices"], now_month
        )
        if ai_pred:
            result["ai_prediction"] = ai_pred

    return result


async def _ai_price_prediction(
    title: str,
    category: str,
    current_price: float,
    monthly_prices: dict,
    current_month: int,
) -> Optional[str]:
    """AI прогноз через GigaChat"""
    gigachat = get_gigachat()

    monthly_text = "\n".join(
        f"  {MONTH_NAMES[m]}: {p:,.0f}₽"
        for m, p in sorted(monthly_prices.items())
    )

    prompt = f"""Товар: "{title}"
Категория: {category or "не указана"}
Текущая цена: {current_price:,.0f}₽
Сейчас: {MONTH_NAMES[current_month]}

Средние цены по месяцам:
{monthly_text}

На основе этих данных:
1. Когда лучше всего покупать? (конкретный месяц)
2. Ожидается ли снижение цены в ближайшие 1-2 месяца?
3. Стоит ли покупать сейчас или подождать?

Ответь кратко (3-4 предложения)."""

    response = await gigachat.ask(
        prompt=prompt,
        system_prompt=(
            "Ты — аналитик цен. Делай прогнозы на основе исторических данных. "
            "Отвечай кратко и конкретно, на русском."
        ),
        temperature=0.3,
        max_tokens=400,
    )

    return response


def format_prediction(data: Dict[str, Any], title: str = "") -> str:
    """Форматирует прогноз цен"""
    from bot.utils.helpers import format_price

    text = "📅 <b>Прогноз цен и календарь</b>\n\n"

    if title:
        text += f"📦 {title[:50]}\n\n"

    # Рекомендация
    if data.get("recommendation"):
        text += data["recommendation"] + "\n\n"

    # Лучший/худший месяц
    if data.get("best_month") and data.get("worst_month"):
        monthly = data["monthly_prices"]
        best = data["best_month"]
        worst = data["worst_month"]

        text += "📊 <b>Календарь цен:</b>\n"
        text += f"  🟢 Дешевле всего: <b>{MONTH_NAMES[best]}</b>"
        text += f" (~{format_price(monthly[best])})\n"
        text += f"  🔴 Дороже всего: <b>{MONTH_NAMES[worst]}</b>"
        text += f" (~{format_price(monthly[worst])})\n"
        text += f"  💰 Максимальная экономия: <b>{data['best_saving_percent']:.0f}%</b>\n\n"

        # Мини-календарь
        text += "<b>Цены по месяцам:</b>\n"
        for month_num in range(1, 13):
            if month_num in monthly:
                price = monthly[month_num]
                emoji = "🟢" if month_num == best else "🔴" if month_num == worst else "⚪"
                text += f"  {emoji} {MONTH_NAMES_SHORT[month_num]}: {format_price(price)}\n"

        text += "\n"

    # Совет по категории
    if data.get("category_tip"):
        text += f"💡 <b>Совет:</b> {data['category_tip']}\n\n"

    # AI-прогноз
    if data.get("ai_prediction"):
        text += f"{'─' * 25}\n\n"
        text += f"🤖 <b>AI-прогноз:</b>\n{data['ai_prediction']}\n"

    return text