import re
import logging
from typing import Optional, Tuple

import aiohttp
import ssl
import certifi

logger = logging.getLogger(__name__)


def parse_marketplace_url(url: str) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """
    Returns: (marketplace, product_id, full_url)
    """
    url = url.strip()

    # Wildberries
    wb_patterns = [
        r'wildberries\.ru/catalog/(\d+)',
        r'wb\.ru/catalog/(\d+)',
    ]
    for pattern in wb_patterns:
        match = re.search(pattern, url)
        if match:
            pid = match.group(1)
            return "wildberries", pid, f"https://www.wildberries.ru/catalog/{pid}/detail.aspx"

    # Ozon — полная ссылка
    ozon_full = re.search(r'ozon\.ru/product/[^/]*?-(\d+)', url)
    if ozon_full:
        pid = ozon_full.group(1)
        return "ozon", pid, url

    ozon_full2 = re.search(r'ozon\.ru/product/(\d+)', url)
    if ozon_full2:
        pid = ozon_full2.group(1)
        return "ozon", pid, url

    # Ozon — короткая ссылка (нужен редирект)
    ozon_short = re.search(r'ozon\.ru/t/(\w+)', url)
    if ozon_short:
        return "ozon_short", ozon_short.group(1), url

    # AliExpress
    ali_patterns = [
        r'aliexpress\.(?:com|ru)/item/(\d+)',
        r'aliexpress\.(?:com|ru)/.*?/(\d+)\.html',
    ]
    for pattern in ali_patterns:
        match = re.search(pattern, url)
        if match:
            return "aliexpress", match.group(1), url

    # Amazon
    amazon_patterns = [
        r'amazon\.(?:com|co\.uk|de)/dp/([A-Z0-9]{10})',
        r'amazon\.(?:com|co\.uk|de)/.*?/dp/([A-Z0-9]{10})',
    ]
    for pattern in amazon_patterns:
        match = re.search(pattern, url)
        if match:
            return "amazon", match.group(1), url

    return None, None, None


async def resolve_short_url(url: str) -> Optional[str]:
    """Резолвит короткие ссылки (ozon.ru/t/xxx) через редирект"""
    logger.info(f"Resolving short URL: {url}")
    try:
        ssl_ctx = ssl.create_default_context(cafile=certifi.where())
        async with aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=10),
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131.0.0.0 Safari/537.36",
            }
        ) as session:
            async with session.get(url, ssl=ssl_ctx, allow_redirects=False) as resp:
                if resp.status in (301, 302, 303, 307, 308):
                    location = resp.headers.get("Location", "")
                    logger.info(f"Redirected to: {location}")
                    return location
                # Если нет редиректа — пробуем follow
                async with session.get(url, ssl=ssl_ctx, allow_redirects=True) as resp2:
                    final_url = str(resp2.url)
                    logger.info(f"Final URL: {final_url}")
                    return final_url
    except Exception as e:
        logger.error(f"Resolve error: {e}")
        return None


def is_valid_url(text: str) -> bool:
    marketplace, _, _ = parse_marketplace_url(text)
    return marketplace is not None


def get_marketplace_emoji(marketplace: str) -> str:
    return {
        "wildberries": "🟣",
        "ozon": "🔵",
        "aliexpress": "🟠",
        "amazon": "🟡",
    }.get(marketplace, "🏪")


def get_marketplace_name(marketplace: str) -> str:
    return {
        "wildberries": "Wildberries",
        "ozon": "Ozon",
        "aliexpress": "AliExpress",
        "amazon": "Amazon",
    }.get(marketplace, marketplace.title())
