import logging
from typing import Dict, Any, Optional

from bot.services.scraper import scrape_seller

logger = logging.getLogger(__name__)


async def check_seller(
    marketplace: str,
    seller_id: str,
    seller_name: str = "",
    product_data: dict = None,
) -> Dict[str, Any]:
    """
    Проверка продавца: рейтинг, надёжность, предупреждения.
    """
    result = {
        "name": seller_name,
        "id": seller_id,
        "marketplace": marketplace,
        "trust_score": 50,  # 0-100
        "warnings": [],
        "positive": [],
        "details": {},
    }

    # Пытаемся получить данные о продавце
    seller_data = None
    if seller_id:
        seller_data = await scrape_seller(marketplace, seller_id)

    if seller_data:
        result["details"] = seller_data
        result["name"] = seller_data.get("name", seller_name)

        # Оценка надёжности
        trust = 50

        # Есть ИНН/ОГРН — +20
        if seller_data.get("inn") or seller_data.get("ogrn"):
            trust += 20
            result["positive"].append("✅ Зарегистрированное юр. лицо (есть ИНН/ОГРН)")
        else:
            result["warnings"].append("⚠️ Нет данных о юридическом лице")

        # Количество товаров
        products_count = seller_data.get("total_products", 0)
        if products_count > 1000:
            trust += 15
            result["positive"].append(f"✅ Большой ассортимент ({products_count}+ товаров)")
        elif products_count > 100:
            trust += 10
            result["positive"].append(f"✅ Средний ассортимент ({products_count} товаров)")
        elif products_count > 0:
            trust += 5
            result["warnings"].append(f"⚠️ Мало товаров ({products_count})")

        # Рейтинг продавца
        seller_rating = seller_data.get("rating", 0)
        if seller_rating >= 4.5:
            trust += 15
            result["positive"].append(f"✅ Высокий рейтинг: {seller_rating}/5")
        elif seller_rating >= 4.0:
            trust += 10
            result["positive"].append(f"✅ Хороший рейтинг: {seller_rating}/5")
        elif seller_rating >= 3.0:
            trust += 0
            result["warnings"].append(f"⚠️ Средний рейтинг: {seller_rating}/5")
        elif seller_rating > 0:
            trust -= 10
            result["warnings"].append(f"🚨 Низкий рейтинг: {seller_rating}/5")

        result["trust_score"] = min(100, max(0, trust))

    else:
        # Нет данных о продавце — базовый анализ
        if seller_name:
            result["warnings"].append("⚠️ Не удалось получить детали о продавце")
        else:
            result["warnings"].append("❌ Продавец неизвестен")
            result["trust_score"] = 30

    # Анализ данных из товара
    if product_data:
        rating = product_data.get("rating", 0)
        reviews = product_data.get("reviews_count", 0)

        if reviews > 1000:
            result["positive"].append(f"✅ Много отзывов на товар ({reviews})")
        elif reviews > 100:
            result["positive"].append(f"✅ Достаточно отзывов ({reviews})")
        elif reviews < 10:
            result["warnings"].append(f"⚠️ Очень мало отзывов ({reviews})")

        if rating >= 4.5 and reviews > 100:
            result["positive"].append("✅ Стабильно высокий рейтинг товара")
        elif rating < 3.5 and reviews > 50:
            result["warnings"].append("🚨 Низкий рейтинг при достаточном кол-ве отзывов")

    return result


def format_seller_check(data: Dict[str, Any]) -> str:
    """Форматирует результат проверки продавца"""
    from bot.utils.url_parser import get_marketplace_emoji, get_marketplace_name

    emoji = get_marketplace_emoji(data["marketplace"])
    mp_name = get_marketplace_name(data["marketplace"])

    # Индикатор доверия
    score = data["trust_score"]
    if score >= 75:
        trust_emoji = "🟢"
        trust_label = "Надёжный"
    elif score >= 50:
        trust_emoji = "🟡"
        trust_label = "Средний"
    elif score >= 25:
        trust_emoji = "🟠"
        trust_label = "Сомнительный"
    else:
        trust_emoji = "🔴"
        trust_label = "Ненадёжный"

    # Прогресс-бар
    filled = int(score / 10)
    bar = "█" * filled + "░" * (10 - filled)

    text = f"🛡 <b>Проверка продавца</b>\n\n"
    text += f"{emoji} Площадка: <b>{mp_name}</b>\n"
    text += f"🏪 Продавец: <b>{data['name'] or 'Неизвестен'}</b>\n"
    text += f"🆔 ID: <code>{data['id'] or 'N/A'}</code>\n\n"

    text += f"{trust_emoji} Доверие: <b>{trust_label}</b> ({score}/100)\n"
    text += f"[{bar}]\n\n"

    # Детали юр. лица
    details = data.get("details", {})
    if details.get("inn"):
        text += f"📋 ИНН: <code>{details['inn']}</code>\n"
    if details.get("ogrn"):
        text += f"📋 ОГРН: <code>{details['ogrn']}</code>\n"
    if details.get("trade_mark"):
        text += f"™ Торговая марка: {details['trade_mark']}\n"
    if details.get("total_products"):
        text += f"📦 Товаров: {details['total_products']}\n"
    if details.get("legal_address"):
        text += f"📍 {details['legal_address'][:80]}\n"

    text += "\n"

    if data["positive"]:
        text += "<b>Плюсы:</b>\n"
        for p in data["positive"]:
            text += f"  {p}\n"
        text += "\n"

    if data["warnings"]:
        text += "<b>Предупреждения:</b>\n"
        for w in data["warnings"]:
            text += f"  {w}\n"
        text += "\n"

    # Итоговая рекомендация
    if score >= 75:
        text += "💚 <b>Рекомендация:</b> Можно покупать с уверенностью."
    elif score >= 50:
        text += "💛 <b>Рекомендация:</b> Обратите внимание на отзывы."
    else:
        text += "❤️ <b>Рекомендация:</b> Будьте осторожны, проверьте отзывы тщательно."

    return text