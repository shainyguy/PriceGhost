import asyncio
import logging
from datetime import datetime

from aiogram import Bot

from database.db import get_db
from bot.services.scraper import scrape_product
from bot.utils.helpers import format_price
from bot.utils.url_parser import get_marketplace_emoji

logger = logging.getLogger(__name__)


async def check_monitored_prices(bot: Bot):
    """
    Проверяет цены отслеживаемых товаров и отправляет уведомления.
    Запускается периодически (раз в 2-4 часа).
    """
    logger.info("🔄 Starting price check for monitored products...")

    db = await get_db()
    monitors = await db.get_all_active_monitors()

    if not monitors:
        logger.info("No active monitors")
        return

    logger.info(f"Checking {len(monitors)} monitored products")

    # Группируем по товару, чтобы не делать дубли запросов
    product_ids_checked = set()
    product_new_prices = {}

    for item in monitors:
        product = item["product"]

        if product.id in product_ids_checked:
            continue

        product_ids_checked.add(product.id)

        try:
            # Скрапим новую цену
            data = await scrape_product(product.marketplace, product.external_id)

            if data and data.get("current_price", 0) > 0:
                new_price = data["current_price"]
                product_new_prices[product.id] = new_price

                # Сохраняем в историю
                await db.add_price_record(
                    product_id=product.id,
                    price=new_price,
                    original_price=data.get("original_price"),
                    discount_percent=data.get("discount_percent"),
                )

                # Обновляем товар
                await db.update_product(
                    product.id,
                    current_price=new_price,
                    original_price=data.get("original_price"),
                    updated_at=datetime.utcnow(),
                )

            # Задержка между запросами
            await asyncio.sleep(2)

        except Exception as e:
            logger.error(f"Error checking product {product.id}: {e}")
            continue

    # Отправляем уведомления
    for item in monitors:
        monitor = item["monitor"]
        product = item["product"]
        user = item["user"]

        new_price = product_new_prices.get(product.id)
        if new_price is None:
            continue

        old_price = product.current_price or new_price
        should_notify = False
        notification_text = ""

        # Уведомление о любом снижении
        if monitor.notify_any_drop and new_price < old_price:
            # Не уведомлять если уже уведомляли об этой цене
            if monitor.last_notified_price and new_price >= monitor.last_notified_price:
                continue

            saving = old_price - new_price
            saving_pct = (saving / old_price * 100) if old_price > 0 else 0

            mp_emoji = get_marketplace_emoji(product.marketplace)
            title = product.title[:50] if product.title else "Товар"

            notification_text = (
                f"📉 <b>Цена снизилась!</b>\n\n"
                f"{mp_emoji} {title}\n\n"
                f"💰 Было: <s>{format_price(old_price)}</s>\n"
                f"💰 Стало: <b>{format_price(new_price)}</b>\n"
                f"📉 Экономия: {format_price(saving)} (-{saving_pct:.1f}%)\n\n"
                f"🔗 {product.url}"
            )
            should_notify = True

        # Уведомление о достижении целевой цены
        if monitor.target_price and new_price <= monitor.target_price:
            if monitor.last_notified_price and new_price >= monitor.last_notified_price:
                continue

            mp_emoji = get_marketplace_emoji(product.marketplace)
            title = product.title[:50] if product.title else "Товар"

            notification_text = (
                f"🎯 <b>Цена достигла цели!</b>\n\n"
                f"{mp_emoji} {title}\n\n"
                f"🎯 Целевая цена: {format_price(monitor.target_price)}\n"
                f"💰 Текущая: <b>{format_price(new_price)}</b>\n\n"
                f"🏃 Скорее покупай!\n"
                f"🔗 {product.url}"
            )
            should_notify = True

        if should_notify and notification_text:
            try:
                await bot.send_message(
                    chat_id=user.telegram_id,
                    text=notification_text,
                    parse_mode="HTML",
                    disable_web_page_preview=True,
                )
                await db.update_monitor_notified(monitor.id, new_price)
                logger.info(
                    f"Notification sent to {user.telegram_id} "
                    f"for product {product.id}"
                )
            except Exception as e:
                logger.error(
                    f"Failed to send notification to {user.telegram_id}: {e}"
                )

    logger.info("✅ Price check completed")


async def run_scheduler(bot: Bot, interval_hours: int = 3):
    """
    Запускает периодическую проверку цен.
    """
    logger.info(f"📅 Scheduler started (interval: {interval_hours}h)")

    while True:
        try:
            await check_monitored_prices(bot)
        except Exception as e:
            logger.error(f"Scheduler error: {e}")

        # Ждём следующей проверки
        await asyncio.sleep(interval_hours * 3600)