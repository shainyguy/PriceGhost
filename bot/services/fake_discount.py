import logging
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta

from database.db import get_db

logger = logging.getLogger(__name__)


async def analyze_fake_discount(
    product_id: int,
    current_price: float,
    original_price: float,
    marketplace_discount: float = 0,
) -> Dict[str, Any]:
    """
    Анализирует, является ли скидка фейковой.
    Ищет паттерн: подъём цены -> "скидка" -> цена примерно как раньше.
    """
    db = await get_db()
    records = await db.get_price_history(product_id, days=180)

    result = {
        "is_fake": False,
        "confidence": 0,  # 0-100
        "verdict": "",
        "details": [],
        "real_discount": 0,
        "fake_markup": 0,
        "current_price": current_price,
        "original_price": original_price,
        "marketplace_discount": marketplace_discount,
        "history_min": None,
        "history_avg": None,
        "history_max": None,
    }

    if not records or len(records) < 2:
        result["verdict"] = "📊 Недостаточно данных для анализа. Мы начали отслеживать этот товар."
        return result

    prices = [r.price for r in records if r.price > 0]

    if not prices:
        result["verdict"] = "📊 Нет данных о ценах."
        return result

    history_min = min(prices)
    history_max = max(prices)
    history_avg = sum(prices) / len(prices)

    result["history_min"] = history_min
    result["history_avg"] = round(history_avg, 2)
    result["history_max"] = history_max

    # === АНАЛИЗ ФЕЙКОВОЙ СКИДКИ ===

    # 1. Проверка: "оригинальная" цена завышена относительно исторической
    if original_price > 0 and original_price > current_price:
        claimed_discount = ((original_price - current_price) / original_price) * 100

        # Реальная скидка от средней исторической
        real_from_avg = 0
        if history_avg > 0:
            real_from_avg = ((history_avg - current_price) / history_avg) * 100

        # Реальная скидка от исторического минимума
        real_from_min = 0
        if history_min > 0:
            real_from_min = ((history_min - current_price) / history_min) * 100

        result["real_discount"] = round(real_from_avg, 1)

        # Паттерн фейковой скидки
        # Если текущая цена выше или почти равна средней — скидка фейковая
        if current_price >= history_avg * 0.95:
            result["is_fake"] = True
            result["confidence"] = 85

            # Ищем подъём цены перед "скидкой"
            markup_detected = _detect_price_markup(records)
            if markup_detected:
                result["confidence"] = 95
                result["fake_markup"] = markup_detected["markup_percent"]
                result["details"].append(
                    f"📈 Цена была поднята на {markup_detected['markup_percent']:.0f}% "
                    f"({markup_detected['from_price']:,.0f}₽ → {markup_detected['to_price']:,.0f}₽) "
                    f"перед «скидкой»"
                )

            result["details"].append(
                f"🏷 Магазин заявляет скидку: {claimed_discount:.0f}%"
            )
            result["details"].append(
                f"📊 Реальная скидка от средней цены: {real_from_avg:.1f}%"
            )
            result["details"].append(
                f"💡 Историческая средняя: {history_avg:,.0f}₽"
            )
            result["details"].append(
                f"📉 Исторический минимум: {history_min:,.0f}₽"
            )

            if current_price >= history_avg:
                result["verdict"] = (
                    f"🚨 <b>ФЕЙКОВАЯ СКИДКА!</b>\n\n"
                    f"Магазин заявляет скидку <b>{claimed_discount:.0f}%</b>, "
                    f"но текущая цена <b>{current_price:,.0f}₽</b> "
                    f"{'выше' if current_price > history_avg else 'равна'} "
                    f"средней исторической <b>{history_avg:,.0f}₽</b>.\n\n"
                    f"Цена была искусственно завышена до <b>{original_price:,.0f}₽</b>, "
                    f"чтобы создать видимость скидки."
                )
            else:
                result["verdict"] = (
                    f"⚠️ <b>СКИДКА ПРЕУВЕЛИЧЕНА</b>\n\n"
                    f"Заявлено: <b>-{claimed_discount:.0f}%</b>\n"
                    f"Реально от средней: <b>{real_from_avg:+.1f}%</b>\n\n"
                    f"Текущая цена лишь немного ниже обычной."
                )

        elif current_price <= history_min * 1.05:
            # Цена действительно хорошая
            result["is_fake"] = False
            result["confidence"] = 80
            result["real_discount"] = round(real_from_avg, 1)
            result["verdict"] = (
                f"✅ <b>СКИДКА НАСТОЯЩАЯ!</b>\n\n"
                f"Текущая цена <b>{current_price:,.0f}₽</b> — "
                f"близка к историческому минимуму <b>{history_min:,.0f}₽</b>.\n\n"
                f"Реальная скидка от средней: <b>{real_from_avg:.1f}%</b>\n"
                f"🎉 Хорошее время для покупки!"
            )

        else:
            # Средний вариант
            result["is_fake"] = False
            result["confidence"] = 60
            result["real_discount"] = round(real_from_avg, 1)
            result["verdict"] = (
                f"🤔 <b>СКИДКА ЧАСТИЧНО РЕАЛЬНАЯ</b>\n\n"
                f"Заявлено: <b>-{claimed_discount:.0f}%</b>\n"
                f"Реально от средней: <b>{real_from_avg:+.1f}%</b>\n"
                f"До минимума (<b>{history_min:,.0f}₽</b>) ещё есть запас."
            )

    else:
        # Нет заявленной скидки
        if current_price <= history_min * 1.05:
            result["verdict"] = (
                f"✅ Цена <b>{current_price:,.0f}₽</b> близка к "
                f"историческому минимуму <b>{history_min:,.0f}₽</b>.\n"
                f"Хорошее время для покупки!"
            )
        elif current_price >= history_max * 0.95:
            result["verdict"] = (
                f"⚠️ Цена <b>{current_price:,.0f}₽</b> близка к "
                f"историческому максимуму <b>{history_max:,.0f}₽</b>.\n"
                f"Рекомендуем подождать."
            )
        else:
            result["verdict"] = (
                f"📊 Цена <b>{current_price:,.0f}₽</b> в пределах нормы.\n"
                f"Средняя: <b>{history_avg:,.0f}₽</b> | "
                f"Мин: <b>{history_min:,.0f}₽</b> | "
                f"Макс: <b>{history_max:,.0f}₽</b>"
            )

    return result


def _detect_price_markup(
    records: list, lookback_days: int = 60
) -> Optional[Dict]:
    """
    Ищет резкий подъём цены перед текущей «скидкой».
    """
    if len(records) < 3:
        return None

    cutoff = datetime.utcnow() - timedelta(days=lookback_days)
    recent = [r for r in records if r.recorded_at >= cutoff]

    if len(recent) < 3:
        return None

    prices = [r.price for r in recent if r.price > 0]
    if len(prices) < 3:
        return None

    # Ищем максимальный подъём
    max_rise = 0
    from_price = 0
    to_price = 0

    for i in range(1, len(prices)):
        if prices[i - 1] > 0:
            rise = (prices[i] - prices[i - 1]) / prices[i - 1] * 100
            if rise > max_rise:
                max_rise = rise
                from_price = prices[i - 1]
                to_price = prices[i]

    if max_rise > 15:  # Подъём больше 15%
        return {
            "markup_percent": max_rise,
            "from_price": from_price,
            "to_price": to_price,
        }

    return None