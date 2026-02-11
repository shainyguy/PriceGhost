import asyncio
import logging
from typing import List, Dict, Any

from bot.services.scraper import search_products
from bot.services.gigachat import get_gigachat

logger = logging.getLogger(__name__)


async def find_analogs(
    title: str,
    brand: str,
    category: str,
    current_price: float,
    marketplace: str,
) -> Dict[str, Any]:
    """
    Находит аналоги товара:
    1. Тот же товар у других продавцов
    2. Похожие товары других брендов дешевле
    """
    result = {
        "same_product": [],
        "cheaper_analogs": [],
        "ai_recommendation": "",
    }

    # Формируем запросы для поиска
    # 1. Точный поиск (тот же товар)
    exact_query = f"{brand} {title}".strip()
    exact_words = exact_query.split()[:6]
    exact_query = " ".join(exact_words)

    # 2. Поиск аналогов (категория без бренда)
    analog_query = title
    # Убираем бренд из запроса
    if brand:
        analog_query = title.replace(brand, "").strip()
    analog_words = analog_query.split()[:5]
    analog_query = " ".join(analog_words)

    # Ищем на всех площадках
    all_marketplaces = ["wildberries", "ozon"]

    # Параллельный поиск
    exact_tasks = [
        search_products(mp, exact_query, limit=5)
        for mp in all_marketplaces
    ]
    analog_tasks = [
        search_products(mp, analog_query, limit=8)
        for mp in all_marketplaces
    ]

    all_tasks = exact_tasks + analog_tasks
    all_results = await asyncio.gather(*all_tasks, return_exceptions=True)

    exact_results = all_results[:len(exact_tasks)]
    analog_results = all_results[len(exact_tasks):]

    # Обрабатываем точные результаты
    for mp, sr in zip(all_marketplaces, exact_results):
        if isinstance(sr, Exception) or not isinstance(sr, list):
            continue
        for item in sr:
            if item.get("price", 0) > 0:
                saving = current_price - item["price"]
                result["same_product"].append({
                    "marketplace": mp,
                    "title": item.get("title", ""),
                    "price": item["price"],
                    "saving": round(saving, 2),
                    "saving_percent": round(
                        saving / current_price * 100 if current_price > 0 else 0, 1
                    ),
                    "rating": item.get("rating", 0),
                    "reviews_count": item.get("reviews_count", 0),
                    "seller": item.get("seller", ""),
                    "url": item.get("url", ""),
                })

    # Обрабатываем аналоги
    for mp, sr in zip(all_marketplaces, analog_results):
        if isinstance(sr, Exception) or not isinstance(sr, list):
            continue
        for item in sr:
            price = item.get("price", 0)
            if price > 0 and price < current_price * 0.9:
                # Только значительно дешевле
                saving = current_price - price
                result["cheaper_analogs"].append({
                    "marketplace": mp,
                    "title": item.get("title", ""),
                    "price": price,
                    "saving": round(saving, 2),
                    "saving_percent": round(
                        saving / current_price * 100 if current_price > 0 else 0, 1
                    ),
                    "rating": item.get("rating", 0),
                    "reviews_count": item.get("reviews_count", 0),
                    "url": item.get("url", ""),
                })

    # Сортируем по цене
    result["same_product"].sort(key=lambda x: x["price"])
    result["cheaper_analogs"].sort(key=lambda x: x["price"])

    # Убираем дубли
    result["same_product"] = result["same_product"][:5]
    result["cheaper_analogs"] = result["cheaper_analogs"][:5]

    # AI-рекомендация
    if result["same_product"] or result["cheaper_analogs"]:
        ai_rec = await _ai_analog_recommendation(
            title, brand, current_price,
            result["same_product"][:3],
            result["cheaper_analogs"][:3],
        )
        if ai_rec:
            result["ai_recommendation"] = ai_rec

    return result


async def _ai_analog_recommendation(
    title: str,
    brand: str,
    current_price: float,
    same_products: list,
    analogs: list,
) -> str:
    """AI рекомендация по аналогам"""
    gigachat = get_gigachat()

    same_text = ""
    for p in same_products:
        same_text += f"- {p['title'][:50]}: {p['price']}₽ ({p['marketplace']})\n"

    analog_text = ""
    for a in analogs:
        analog_text += f"- {a['title'][:50]}: {a['price']}₽ ({a['marketplace']})\n"

    prompt = f"""Товар: "{title}" (бренд: {brand}), цена: {current_price}₽

Тот же товар у других продавцов:
{same_text if same_text else "Не найдено"}

Возможные аналоги дешевле:
{analog_text if analog_text else "Не найдено"}

Дай краткую рекомендацию покупателю (2-3 предложения):
- Стоит ли переплачивать за бренд?
- Какой вариант лучший по соотношению цена/качество?"""

    response = await gigachat.ask(
        prompt=prompt,
        system_prompt="Ты — эксперт по покупкам. Отвечай кратко и по делу, на русском.",
        temperature=0.4,
        max_tokens=300,
    )

    return response


def format_analogs_result(data: Dict[str, Any], current_price: float) -> str:
    """Форматирует результат поиска аналогов"""
    from bot.utils.helpers import format_price
    from bot.utils.url_parser import get_marketplace_emoji, get_marketplace_name

    text = "📦 <b>Поиск аналогов</b>\n\n"
    text += f"📌 Текущая цена: <b>{format_price(current_price)}</b>\n\n"

    # Тот же товар
    same = data.get("same_product", [])
    if same:
        text += "🔄 <b>Тот же товар у других продавцов:</b>\n\n"
        for i, p in enumerate(same[:5], 1):
            emoji = get_marketplace_emoji(p["marketplace"])
            mp_name = get_marketplace_name(p["marketplace"])

            price_str = format_price(p["price"])
            saving_str = ""
            if p["saving"] > 0:
                saving_str = f" (💰 -{format_price(p['saving'])})"
            elif p["saving"] < 0:
                saving_str = f" (дороже на {format_price(abs(p['saving']))})"

            text += f"{i}. {emoji} <b>{mp_name}</b>\n"
            text += f"   📦 {p['title'][:55]}\n"
            text += f"   💰 <b>{price_str}</b>{saving_str}\n"

            if p.get("rating"):
                text += f"   ⭐ {p['rating']}"
                if p.get("reviews_count"):
                    text += f" ({p['reviews_count']} отз.)"
                text += "\n"

            if p.get("url"):
                text += f"   🔗 {p['url']}\n"

            text += "\n"
    else:
        text += "🔄 Тот же товар у других продавцов не найден.\n\n"

    # Аналоги дешевле
    analogs = data.get("cheaper_analogs", [])
    if analogs:
        text += "💡 <b>Похожие товары дешевле:</b>\n\n"
        for i, a in enumerate(analogs[:5], 1):
            emoji = get_marketplace_emoji(a["marketplace"])

            text += f"{i}. {emoji} {a['title'][:55]}\n"
            text += f"   💰 <b>{format_price(a['price'])}</b>"
            text += f" (дешевле на {a['saving_percent']:.0f}%)\n"

            if a.get("rating"):
                text += f"   ⭐ {a['rating']}\n"

            if a.get("url"):
                text += f"   🔗 {a['url']}\n"
            text += "\n"
    else:
        text += "💡 Значительно более дешёвые аналоги не найдены.\n\n"

    # AI рекомендация
    if data.get("ai_recommendation"):
        text += f"{'─' * 25}\n\n"
        text += f"🤖 <b>AI-рекомендация:</b>\n{data['ai_recommendation']}\n"

    return text