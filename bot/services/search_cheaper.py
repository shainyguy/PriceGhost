import asyncio
import logging
from typing import List, Dict, Any

from bot.services.scraper import search_products

logger = logging.getLogger(__name__)

# Площадки для поиска
ALL_MARKETPLACES = ["wildberries", "ozon"]


async def find_cheaper(
    title: str,
    current_price: float,
    current_marketplace: str,
    brand: str = "",
) -> List[Dict[str, Any]]:
    """
    Ищет такой же или похожий товар дешевле на других площадках.
    """
    # Формируем поисковый запрос
    query = title
    if brand:
        # Если бренд уже в названии, не дублируем
        if brand.lower() not in title.lower():
            query = f"{brand} {title}"

    # Обрезаем слишком длинный запрос
    query_words = query.split()[:8]
    query = " ".join(query_words)

    results = []
    search_marketplaces = [
        mp for mp in ALL_MARKETPLACES if mp != current_marketplace
    ]

    # Параллельный поиск на всех площадках
    tasks = [
        search_products(mp, query, limit=5)
        for mp in search_marketplaces
    ]

    search_results = await asyncio.gather(*tasks, return_exceptions=True)

    for mp, sr in zip(search_marketplaces, search_results):
        if isinstance(sr, Exception):
            logger.error(f"Search error on {mp}: {sr}")
            continue

        if not isinstance(sr, list):
            continue

        for item in sr:
            if item.get("price", 0) > 0:
                saving = current_price - item["price"]
                saving_percent = (saving / current_price * 100) if current_price > 0 else 0

                results.append({
                    "marketplace": mp,
                    "title": item.get("title", ""),
                    "price": item["price"],
                    "original_price": item.get("original_price", 0),
                    "rating": item.get("rating", 0),
                    "reviews_count": item.get("reviews_count", 0),
                    "seller": item.get("seller", ""),
                    "url": item.get("url", ""),
                    "saving": round(saving, 2),
                    "saving_percent": round(saving_percent, 1),
                })

    # Сортируем по цене
    results.sort(key=lambda x: x["price"])

    return results


def format_cheaper_results(
    results: List[Dict], current_price: float
) -> str:
    """Форматирует результаты поиска дешевле"""
    if not results:
        return (
            "🔍 <b>Поиск на других площадках</b>\n\n"
            "К сожалению, не удалось найти аналоги.\n"
            "Попробуйте проверить позже — мы расширяем базу."
        )

    from bot.utils.url_parser import get_marketplace_emoji, get_marketplace_name
    from bot.utils.helpers import format_price

    text = f"🔍 <b>Найдено на других площадках</b>\n"
    text += f"📌 Текущая цена: <b>{format_price(current_price)}</b>\n\n"

    cheaper = [r for r in results if r["saving"] > 0]
    same_or_more = [r for r in results if r["saving"] <= 0]

    if cheaper:
        text += "💰 <b>Дешевле:</b>\n\n"
        for i, r in enumerate(cheaper[:5], 1):
            emoji = get_marketplace_emoji(r["marketplace"])
            mp_name = get_marketplace_name(r["marketplace"])
            text += (
                f"{i}. {emoji} <b>{mp_name}</b>\n"
                f"   📦 {r['title'][:60]}\n"
                f"   💰 <b>{format_price(r['price'])}</b>"
                f" (экономия {format_price(r['saving'])}, -{r['saving_percent']:.0f}%)\n"
            )
            if r.get("rating"):
                text += f"   ⭐ {r['rating']}"
                if r.get("reviews_count"):
                    text += f" ({r['reviews_count']} отзывов)"
                text += "\n"
            text += f"   🔗 {r['url']}\n\n"
    else:
        text += "✅ Текущая цена — лучшая из найденных!\n\n"

    if same_or_more and len(cheaper) < 3:
        text += "📋 <b>Такая же цена или дороже:</b>\n"
        for r in same_or_more[:3]:
            emoji = get_marketplace_emoji(r["marketplace"])
            text += f"  {emoji} {format_price(r['price'])} — {r['title'][:40]}\n"

    return text