import asyncio
import logging
import re
from typing import Dict, Any, List, Optional

from bot.services.gigachat import get_gigachat

logger = logging.getLogger(__name__)

# Известные кешбэк-сервисы и их ставки
CASHBACK_SERVICES = {
    "wildberries": [
        {
            "name": "Тинькофф Кешбэк",
            "rate": "до 5%",
            "type": "карта",
            "details": "При оплате картой Тинькофф (если WB в выбранных категориях)",
        },
        {
            "name": "СберСпасибо",
            "rate": "до 3%",
            "type": "бонусы",
            "details": "Бонусы Спасибо при оплате картой Сбера",
        },
        {
            "name": "Мегабонус",
            "rate": "до 3.5%",
            "type": "кешбэк-сервис",
            "details": "Через расширение Megabonus",
        },
        {
            "name": "LetyShops",
            "rate": "до 2.5%",
            "type": "кешбэк-сервис",
            "details": "Кешбэк через LetyShops",
        },
    ],
    "ozon": [
        {
            "name": "Ozon Карта",
            "rate": "до 5%",
            "type": "карта",
            "details": "Кешбэк баллами Ozon при оплате Ozon Картой",
        },
        {
            "name": "Тинькофф Кешбэк",
            "rate": "до 5%",
            "type": "карта",
            "details": "При выборе категории «Маркетплейсы»",
        },
        {
            "name": "Мегабонус",
            "rate": "до 3%",
            "type": "кешбэк-сервис",
            "details": "Через расширение Megabonus",
        },
        {
            "name": "LetyShops",
            "rate": "до 3.5%",
            "type": "кешбэк-сервис",
            "details": "Кешбэк через LetyShops",
        },
    ],
    "aliexpress": [
        {
            "name": "EPN Cashback",
            "rate": "до 10%",
            "type": "кешбэк-сервис",
            "details": "Один из лучших кешбэков для AliExpress",
        },
        {
            "name": "LetyShops",
            "rate": "до 8.5%",
            "type": "кешбэк-сервис",
            "details": "Высокий кешбэк через LetyShops",
        },
        {
            "name": "Мегабонус",
            "rate": "до 7%",
            "type": "кешбэк-сервис",
            "details": "Через расширение Megabonus",
        },
        {
            "name": "Тинькофф Кешбэк",
            "rate": "до 5%",
            "type": "карта",
            "details": "При выборе категории «Всё онлайн»",
        },
    ],
    "amazon": [
        {
            "name": "LetyShops",
            "rate": "до 3%",
            "type": "кешбэк-сервис",
            "details": "Кешбэк через LetyShops",
        },
        {
            "name": "Тинькофф Кешбэк",
            "rate": "до 5%",
            "type": "карта",
            "details": "При выборе категории «Всё онлайн»",
        },
    ],
}

# Известные промокоды (условно — в реальности нужен API)
PROMO_HINTS = {
    "wildberries": [
        "Проверьте раздел «Акции» на главной WB",
        "Подпишитесь на бренд — иногда приходят купоны",
        "Товары из «Ликвидации» дешевле на 20-60%",
    ],
    "ozon": [
        "Проверьте раздел «Монетки» — скидка до 25%",
        "Ozon Premium даёт бесплатную доставку",
        "Баллы Ozon Карты = реальные рубли",
        "Проверьте «Товар дня» — скидки до 50%",
    ],
    "aliexpress": [
        "Купоны продавца — на странице магазина",
        "«Выбор покупателей» — проверенные товары со скидкой",
        "Распродажи 11.11, 3.28, 6.18 — скидки до 70%",
    ],
    "amazon": [
        "Amazon Prime Day (июль) — большие скидки",
        "Subscribe & Save — скидка за подписку",
        "Warehouse Deals — уценённые товары",
    ],
}


async def get_cashback_info(
    marketplace: str,
    current_price: float,
    title: str = "",
    category: str = "",
) -> Dict[str, Any]:
    """Агрегатор кешбэков и промокодов"""

    result = {
        "cashback_options": [],
        "promo_tips": [],
        "best_cashback": None,
        "max_saving": 0,
        "final_price_estimate": current_price,
        "ai_tips": "",
    }

    # 1. Кешбэк-сервисы
    services = CASHBACK_SERVICES.get(marketplace, [])
    for svc in services:
        rate_match = re.search(r"([\d.]+)", svc["rate"])
        max_rate = float(rate_match.group(1)) if rate_match else 0
        saving = round(current_price * max_rate / 100, 2)

        result["cashback_options"].append({
            "name": svc["name"],
            "rate": svc["rate"],
            "type": svc["type"],
            "details": svc["details"],
            "max_saving": saving,
        })

    # Лучший кешбэк
    if result["cashback_options"]:
        best = max(result["cashback_options"], key=lambda x: x["max_saving"])
        result["best_cashback"] = best
        result["max_saving"] = best["max_saving"]
        result["final_price_estimate"] = round(
            current_price - best["max_saving"], 2
        )

    # 2. Промо-советы
    result["promo_tips"] = PROMO_HINTS.get(marketplace, [])

    # 3. AI-советы по экономии
    ai_tips = await _ai_saving_tips(
        marketplace, title, category, current_price
    )
    if ai_tips:
        result["ai_tips"] = ai_tips

    return result


async def _ai_saving_tips(
    marketplace: str,
    title: str,
    category: str,
    price: float,
) -> Optional[str]:
    """AI-советы по экономии"""
    gigachat = get_gigachat()

    prompt = f"""Товар: "{title}" на {marketplace}, цена {price:,.0f}₽.
Категория: {category or "не указана"}.

Дай 3-4 практичных совета как сэкономить при покупке этого товара.
Учитывай специфику площадки {marketplace}.
Ответь кратко, в виде списка."""

    response = await gigachat.ask(
        prompt=prompt,
        system_prompt=(
            "Ты — эксперт по экономии на онлайн-покупках в России. "
            "Даёшь конкретные практичные советы. Отвечай на русском."
        ),
        temperature=0.4,
        max_tokens=400,
    )

    return response


def format_cashback_info(data: Dict[str, Any], current_price: float) -> str:
    """Форматирует информацию о кешбэках"""
    from bot.utils.helpers import format_price

    text = "💸 <b>Кешбэк и промокоды</b>\n\n"
    text += f"📌 Цена товара: <b>{format_price(current_price)}</b>\n\n"

    # Кешбэк-сервисы
    options = data.get("cashback_options", [])
    if options:
        text += "💳 <b>Доступные кешбэки:</b>\n\n"

        # Сортируем по экономии
        options_sorted = sorted(options, key=lambda x: x["max_saving"], reverse=True)

        for i, opt in enumerate(options_sorted, 1):
            is_best = opt == data.get("best_cashback")
            star = " ⭐ ЛУЧШИЙ" if is_best else ""

            type_emoji = {
                "карта": "💳",
                "бонусы": "🎁",
                "кешбэк-сервис": "🔄",
            }.get(opt["type"], "💰")

            text += f"{i}. {type_emoji} <b>{opt['name']}</b>{star}\n"
            text += f"   Ставка: <b>{opt['rate']}</b>\n"
            text += f"   Экономия: до <b>{format_price(opt['max_saving'])}</b>\n"
            text += f"   ℹ️ {opt['details']}\n\n"

        # Лучший вариант
        if data.get("best_cashback"):
            best = data["best_cashback"]
            final = data.get("final_price_estimate", current_price)
            text += f"{'─' * 25}\n"
            text += (
                f"💰 <b>Лучший вариант:</b> {best['name']} ({best['rate']})\n"
                f"💵 Финальная цена: ~<b>{format_price(final)}</b>\n"
                f"📉 Экономия: до <b>{format_price(data.get('max_saving', 0))}</b>\n\n"
            )
    else:
        text += "💳 Информация о кешбэках для этой площадки не найдена.\n\n"

    # Промо-советы
    tips = data.get("promo_tips", [])
    if tips:
        text += "🏷 <b>Советы по промокодам:</b>\n"
        for tip in tips:
            text += f"  • {tip}\n"
        text += "\n"

    # AI-советы
    if data.get("ai_tips"):
        text += f"{'─' * 25}\n\n"
        text += f"🤖 <b>AI-советы по экономии:</b>\n{data['ai_tips']}\n"

    return text