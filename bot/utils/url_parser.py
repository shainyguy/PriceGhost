import re
from typing import Optional, Tuple


def parse_marketplace_url(url: str) -> Tuple[Optional[str], Optional[str]]:
    """
    Определяет маркетплейс и ID товара по URL.
    Returns: (marketplace, product_id) or (None, None)
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
            return "wildberries", match.group(1)

    # Ozon
    ozon_patterns = [
        r'ozon\.ru/product/[^/]*-(\d+)',
        r'ozon\.ru/product/(\d+)',
        r'ozon\.ru/t/(\w+)',
    ]
    for pattern in ozon_patterns:
        match = re.search(pattern, url)
        if match:
            return "ozon", match.group(1)

    # AliExpress
    ali_patterns = [
        r'aliexpress\.(?:com|ru)/item/(\d+)',
        r'aliexpress\.(?:com|ru)/.*?/(\d+)\.html',
        r'a\.aliexpress\.com/_(\w+)',
    ]
    for pattern in ali_patterns:
        match = re.search(pattern, url)
        if match:
            return "aliexpress", match.group(1)

    # Amazon
    amazon_patterns = [
        r'amazon\.(?:com|co\.uk|de|fr|it|es)/dp/([A-Z0-9]{10})',
        r'amazon\.(?:com|co\.uk|de|fr|it|es)/.*?/dp/([A-Z0-9]{10})',
        r'amzn\.to/(\w+)',
    ]
    for pattern in amazon_patterns:
        match = re.search(pattern, url)
        if match:
            return "amazon", match.group(1)

    return None, None


def is_valid_url(text: str) -> bool:
    """Проверяет, является ли текст URL маркетплейса"""
    marketplace, _ = parse_marketplace_url(text)
    return marketplace is not None


def get_marketplace_emoji(marketplace: str) -> str:
    emojis = {
        "wildberries": "🟣",
        "ozon": "🔵",
        "aliexpress": "🟠",
        "amazon": "🟡",
    }
    return emojis.get(marketplace, "🏪")


def get_marketplace_name(marketplace: str) -> str:
    names = {
        "wildberries": "Wildberries",
        "ozon": "Ozon",
        "aliexpress": "AliExpress",
        "amazon": "Amazon",
    }
    return names.get(marketplace, marketplace.title())