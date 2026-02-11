import logging
from typing import Optional, Dict, Any, List
from datetime import datetime, timedelta

from database.db import get_db
from bot.services.scraper import scrape_product

logger = logging.getLogger(__name__)


async def fetch_and_save_price(
    marketplace: str, product_id: str, url: str
) -> Optional[Dict[str, Any]]:
    """
    Скрапит товар, сохраняет/обновляет в БД, записывает цену.
    Возвращает dict с инфой о товаре.
    """
    db = await get_db()

    # Скрапим товар
    product_data = await scrape_product(marketplace, product_id)

    if not product_data:
        return None

    # Получаем/создаём товар в БД
    db_product = await db.get_or_create_product(
        url=url,
        marketplace=marketplace,
        external_id=product_id,
    )

    # Обновляем данные товара
    await db.update_product(
        db_product.id,
        title=product_data.get("title"),
        brand=product_data.get("brand"),
        category=product_data.get("category"),
        image_url=product_data.get("image_url"),
        seller_name=product_data.get("seller_name"),
        seller_id=product_data.get("seller_id"),
        current_price=product_data.get("current_price"),
        original_price=product_data.get("original_price"),
        rating=product_data.get("rating"),
        reviews_count=product_data.get("reviews_count"),
        updated_at=datetime.utcnow(),
    )

    # Записываем цену
    current_price = product_data.get("current_price", 0)
    if current_price > 0:
        await db.add_price_record(
            product_id=db_product.id,
            price=current_price,
            original_price=product_data.get("original_price"),
            discount_percent=product_data.get("discount_percent"),
        )

    # Добавляем ID из базы
    product_data["db_id"] = db_product.id

    return product_data


async def get_price_stats(product_id: int, days: int = 365) -> Dict[str, Any]:
    """
    Статистика по ценам: мин, макс, средняя, текущая, тренд.
    """
    db = await get_db()
    records = await db.get_price_history(product_id, days)

    if not records:
        return {
            "has_data": False,
            "records_count": 0,
        }

    prices = [r.price for r in records if r.price > 0]

    if not prices:
        return {
            "has_data": False,
            "records_count": 0,
        }

    current_price = prices[-1]
    min_price = min(prices)
    max_price = max(prices)
    avg_price = sum(prices) / len(prices)

    # Тренд за последние 30 дней
    thirty_days_ago = datetime.utcnow() - timedelta(days=30)
    recent_records = [r for r in records if r.recorded_at >= thirty_days_ago]
    recent_prices = [r.price for r in recent_records if r.price > 0]

    trend = "stable"
    trend_percent = 0
    if len(recent_prices) >= 2:
        first_recent = recent_prices[0]
        last_recent = recent_prices[-1]
        if first_recent > 0:
            trend_percent = ((last_recent - first_recent) / first_recent) * 100
            if trend_percent > 3:
                trend = "up"
            elif trend_percent < -3:
                trend = "down"

    # Когда была мин. и макс. цена
    min_record = min(records, key=lambda r: r.price if r.price > 0 else float('inf'))
    max_record = max(records, key=lambda r: r.price)

    return {
        "has_data": True,
        "records_count": len(records),
        "current_price": current_price,
        "min_price": min_price,
        "max_price": max_price,
        "avg_price": round(avg_price, 2),
        "min_date": min_record.recorded_at,
        "max_date": max_record.recorded_at,
        "trend": trend,
        "trend_percent": round(trend_percent, 1),
        "records": records,
        "prices": prices,
    }


async def get_monthly_avg_prices(product_id: int) -> Dict[int, float]:
    """
    Средняя цена по месяцам (для прогнозов).
    Returns: {month_number: avg_price}
    """
    db = await get_db()
    records = await db.get_price_history(product_id, days=730)  # 2 года

    monthly: Dict[int, List[float]] = {}
    for r in records:
        if r.price > 0:
            month = r.recorded_at.month
            if month not in monthly:
                monthly[month] = []
            monthly[month].append(r.price)

    return {
        month: round(sum(prices) / len(prices), 2)
        for month, prices in monthly.items()
    }