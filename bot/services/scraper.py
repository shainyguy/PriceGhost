import re
import json
import asyncio
import logging
import ssl
from typing import Optional, Dict, Any

import aiohttp
import certifi
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)


OZON_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Linux; Android 10; SM-G975F) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Mobile Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ru-RU,ru;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Cache-Control": "max-age=0",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Upgrade-Insecure-Requests": "1",
}


async def _ozon_fetch(url: str) -> Optional[str]:
    """Специальный fetch для Ozon с обходом блокировки"""
    logger.info(f"OZON FETCH: {url[:100]}")
    try:
        ssl_ctx = ssl.create_default_context(cafile=certifi.where())
        
        # Пробуем разные User-Agent
        agents = [
            "Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Mobile Safari/537.36",
            "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        ]
        
        for ua in agents:
            headers = {**OZON_HEADERS, "User-Agent": ua}
            async with aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=15),
                headers=headers,
            ) as session:
                async with session.get(url, ssl=ssl_ctx) as resp:
                    logger.info(f"  OZON -> {resp.status} (UA: {ua[:30]})")
                    if resp.status == 200:
                        return await resp.text()
                    elif resp.status == 403:
                        continue
                    else:
                        return None
        
        logger.warning("OZON: all User-Agents blocked")
        return None
    except Exception as e:
        logger.error(f"OZON fetch error: {e}")
        return None


def _get_ssl():
    return ssl.create_default_context(cafile=certifi.where())


def _headers():
    return {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131.0.0.0 Safari/537.36",
        "Accept": "*/*",
        "Accept-Language": "ru-RU,ru;q=0.9",
        "Origin": "https://www.wildberries.ru",
        "Referer": "https://www.wildberries.ru/",
    }


async def _fetch(url: str) -> Optional[str]:
    logger.info(f"FETCH: {url[:120]}")
    try:
        async with aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=15),
            headers=_headers(),
        ) as s:
            async with s.get(url, ssl=_get_ssl()) as r:
                logger.info(f"  -> {r.status}")
                if r.status == 200:
                    return await r.text()
                return None
    except Exception as e:
        logger.error(f"  -> ERROR: {e}")
        return None


async def _fetch_json(url: str) -> Any:
    text = await _fetch(url)
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


# ===================== WB BASKET =====================

def _wb_basket_num(vol: int) -> str:
    """Актуальная таблица корзин WB (2025)"""
    ranges = [
        (143, "01"), (287, "02"), (431, "03"), (719, "04"),
        (1007, "05"), (1061, "06"), (1115, "07"), (1169, "08"),
        (1313, "09"), (1601, "10"), (1655, "11"), (1919, "12"),
        (2045, "13"), (2189, "14"), (2405, "15"), (2621, "16"),
        (2837, "17"), (3071, "18"), (3305, "19"), (3539, "20"),
        (3773, "21"), (4007, "22"), (4241, "23"), (4475, "24"),
        (4709, "25"), (4943, "26"), (5177, "27"), (5411, "28"),
        (5645, "29"), (5879, "30"), (6113, "31"), (6347, "32"),
        (6581, "33"), (6815, "34"), (7049, "35"), (7283, "36"),
        (7517, "37"), (7751, "38"), (7985, "39"), (8219, "40"),
        (8453, "41"), (8687, "42"), (8921, "43"), (9155, "44"),
        (9389, "45"), (9623, "46"), (9857, "47"), (10091, "48"),
        (10325, "49"), (10559, "50"),
    ]
    for limit, num in ranges:
        if vol <= limit:
            return num
    # Для очень новых товаров — формула
    basket = 18 + (vol - 2837) // 234
    if basket > 50:
        basket = 50
    return f"{basket:02d}"


def _wb_host(product_id: str) -> tuple:
    pid = int(product_id)
    vol = pid // 100000
    part = pid // 1000
    basket = _wb_basket_num(vol)
    host = f"basket-{basket}.wbbasket.ru"
    return host, vol, part


# ===================== WB SCRAPE =====================

async def _wb_scrape(product_id: str) -> Optional[Dict[str, Any]]:
    host, vol, part = _wb_host(product_id)
    base = f"https://{host}/vol{vol}/part{part}/{product_id}"

    logger.info(f"=== WB START: {product_id} | {host} vol={vol} part={part} ===")

    # 1. Карточка
    card = None
    for path in ["/info/ru/card.json", "/info/card.json"]:
        card = await _fetch_json(f"{base}{path}")
        if card:
            logger.info("WB: card OK")
            break

    # 2. Цена
    price_data = None
    for path in ["/info/sellers.json", "/info/price-history.json"]:
        price_data = await _fetch_json(f"{base}{path}")
        if price_data:
            logger.info("WB: price OK")
            break

    # 3. Card API fallback
    api_product = None
    if not card and not price_data:
        for dest in ["-1257786", "-5803327", "123585924", "-1029256"]:
            url = (
                f"https://card.wb.ru/cards/v2/detail"
                f"?appType=1&curr=rub&dest={dest}&spp=30&nm={product_id}"
            )
            data = await _fetch_json(url)
            if data:
                prods = data.get("data", {}).get("products", [])
                if prods:
                    api_product = prods[0]
                    logger.info(f"WB: card API OK dest={dest}")
                    break

    # Собираем данные
    title = ""
    brand = ""
    category = ""
    current_price = 0
    original_price = 0
    rating = 0
    reviews_count = 0
    seller_name = ""
    seller_id = None

    if card:
        title = card.get("imt_name", card.get("name", ""))
        selling = card.get("selling", {})
        brand = selling.get("brand_name", card.get("brand", ""))
        seller_name = selling.get("supplier_name", "")
        sid = selling.get("supplier_id")
        seller_id = str(sid) if sid else None
        subj = card.get("subj_name", "")
        root = card.get("subj_root_name", "")
        category = f"{root} / {subj}" if root and subj else subj

    if api_product:
        if not title:
            brand = api_product.get("brand", "")
            name = api_product.get("name", "")
            title = f"{brand} {name}".strip()
        if not seller_name:
            seller_name = api_product.get("supplier", "")
        if not seller_id:
            sid = api_product.get("supplierId")
            seller_id = str(sid) if sid else None
        rating = api_product.get("reviewRating", 0)
        reviews_count = api_product.get("feedbacks", 0)
        if not category:
            subj = api_product.get("subjectName", "")
            parent = api_product.get("subjectParentName", "")
            category = f"{parent} / {subj}" if parent and subj else subj

        for s in api_product.get("sizes", []):
            p = s.get("price", {})
            if p:
                current_price = p.get("total", 0) / 100
                original_price = p.get("basic", 0) / 100
                break

    if price_data and current_price == 0:
        if isinstance(price_data, dict):
            for s in price_data.get("sizes", []):
                p = s.get("price", {})
                if p:
                    current_price = p.get("total", 0) / 100
                    original_price = p.get("basic", 0) / 100
                    break
        elif isinstance(price_data, list) and price_data:
            last = price_data[-1]
            if isinstance(last.get("price"), dict):
                current_price = last["price"].get("RUB", 0) / 100

    discount = 0
    if original_price > current_price > 0:
        discount = round((1 - current_price / original_price) * 100, 1)

    image_url = f"https://{host}/vol{vol}/part{part}/{product_id}/images/big/1.webp"

    if not title and not current_price:
        logger.error(f"WB: no data for {product_id}")
        return None

    if not title:
        title = f"Товар WB #{product_id}"

    full_title = title
    if brand and brand.lower() not in title.lower():
        full_title = f"{brand} {title}"

    result = {
        "external_id": product_id,
        "marketplace": "wildberries",
        "title": full_title,
        "brand": brand,
        "category": category,
        "current_price": current_price,
        "original_price": original_price if original_price else current_price,
        "discount_percent": discount,
        "rating": rating,
        "reviews_count": reviews_count,
        "seller_name": seller_name,
        "seller_id": seller_id,
        "image_url": image_url,
        "url": f"https://www.wildberries.ru/catalog/{product_id}/detail.aspx",
        "raw_data": {},
    }
    logger.info(f"=== WB OK: {full_title[:50]}, price={current_price} ===")
    return result


async def _wb_search(query: str, limit: int = 10) -> list:
    for dest in ["-1257786", "-5803327"]:
        url = (
            f"https://search.wb.ru/exactmatch/ru/common/v7/search"
            f"?appType=1&curr=rub&dest={dest}"
            f"&query={query}&resultset=catalog&spp=30"
        )
        data = await _fetch_json(url)
        if data and data.get("data", {}).get("products"):
            results = []
            for p in data["data"]["products"][:limit]:
                pid = str(p.get("id", ""))
                pi = {}
                for s in p.get("sizes", []):
                    pd = s.get("price", {})
                    if pd:
                        pi = pd
                        break
                results.append({
                    "external_id": pid,
                    "marketplace": "wildberries",
                    "title": f"{p.get('brand','')} {p.get('name','')}".strip(),
                    "price": pi.get("total", 0) / 100 if pi.get("total") else 0,
                    "original_price": pi.get("basic", 0) / 100 if pi.get("basic") else 0,
                    "rating": p.get("reviewRating", 0),
                    "reviews_count": p.get("feedbacks", 0),
                    "seller": p.get("supplier", ""),
                    "url": f"https://www.wildberries.ru/catalog/{pid}/detail.aspx",
                })
            return results
    return []


async def _wb_reviews(product_id: str, limit: int = 100) -> list:
    reviews = []
    for shard in range(1, 3):
        url = f"https://feedbacks{shard}.wb.ru/feedbacks/v2/{product_id}"
        data = await _fetch_json(url)
        if data and data.get("feedbacks"):
            for r in (data["feedbacks"] or [])[:limit]:
                reviews.append({
                    "text": r.get("text", ""),
                    "rating": r.get("productValuation", 0),
                    "date": r.get("createdDate", ""),
                    "author": r.get("wbUserDetails", {}).get("name", "Аноним"),
                    "pros": r.get("pros", ""),
                    "cons": r.get("cons", ""),
                })
            break
    return reviews


async def _wb_seller(seller_id: str) -> Optional[Dict[str, Any]]:
    url = f"https://static-basket-01.wbbasket.ru/vol0/data/seller-info/{seller_id}.json"
    data = await _fetch_json(url)
    if data:
        return {
            "name": data.get("supplierName", data.get("name", "")),
            "id": seller_id,
            "trade_mark": data.get("trademark", ""),
            "ogrn": data.get("ogrn", ""),
            "inn": data.get("inn", ""),
            "legal_address": data.get("legalAddress", ""),
            "rating": data.get("valuation", 0),
            "total_products": data.get("productsCount", 0),
        }
    return None


# ===================== OZON =====================

async def _ozon_scrape(product_id: str) -> Optional[Dict[str, Any]]:
    logger.info(f"OZON: {product_id}")
    
    # Пробуем разные форматы URL
    urls = [
        f"https://www.ozon.ru/product/{product_id}/",
        f"https://m.ozon.ru/product/{product_id}/",
        f"https://ozon.ru/product/{product_id}/",
    ]
    
    html = None
    for url in urls:
        html = await _ozon_fetch(url)
        if html:
            break
    
    if not html:
        logger.error(f"OZON: blocked for {product_id}")
        return None

    try:
        soup = BeautifulSoup(html, "lxml")
        title = ""
        price = 0
        image_url = ""
        brand = ""
        rating = 0
        reviews_count = 0

        # Meta tags
        mt = soup.find("meta", {"property": "og:title"})
        if mt: title = mt.get("content", "")
        
        mp = soup.find("meta", {"property": "product:price:amount"})
        if mp:
            try: price = float(mp.get("content", "0"))
            except: pass
        
        mi = soup.find("meta", {"property": "og:image"})
        if mi: image_url = mi.get("content", "")

        # JSON-LD
        for s in soup.find_all("script", {"type": "application/ld+json"}):
            try:
                j = json.loads(s.string or "{}")
                if isinstance(j, dict) and j.get("@type") == "Product":
                    title = title or j.get("name", "")
                    b = j.get("brand")
                    brand = b.get("name", "") if isinstance(b, dict) else ""
                    img = j.get("image", "")
                    if isinstance(img, list) and img:
                        image_url = image_url or img[0]
                    elif isinstance(img, str):
                        image_url = image_url or img
                    o = j.get("offers", {})
                    if isinstance(o, dict):
                        try: price = price or float(o.get("price", 0))
                        except: pass
                    a = j.get("aggregateRating", {})
                    if isinstance(a, dict):
                        try:
                            rating = float(a.get("ratingValue", 0))
                            reviews_count = int(a.get("reviewCount", 0))
                        except: pass
            except: continue

        # Парсинг цены из HTML если не нашли в meta/ld
        if price == 0:
            price_patterns = [
                r'"price"\s*:\s*"?(\d[\d\s]*)"?',
                r'\"finalPrice\"\s*:\s*(\d+)',
            ]
            page_text = str(soup)
            for pattern in price_patterns:
                match = re.search(pattern, page_text)
                if match:
                    price_str = match.group(1).replace(" ", "")
                    try:
                        price = float(price_str)
                        if price > 0:
                            break
                    except: pass

        if not title and not price:
            logger.error(f"OZON: no data for {product_id}")
            return None

        logger.info(f"OZON OK: {title[:40]}, price={price}")
        return {
            "external_id": product_id, "marketplace": "ozon",
            "title": title, "brand": brand, "category": "",
            "current_price": price, "original_price": price,
            "discount_percent": 0, "rating": rating,
            "reviews_count": reviews_count, "seller_name": "",
            "seller_id": None, "image_url": image_url,
            "url": f"https://www.ozon.ru/product/{product_id}/",
            "raw_data": {},
        }
    except Exception as e:
        logger.error(f"OZON error: {e}")
        return None


# ===================== ALI =====================

async def _ali_scrape(product_id: str) -> Optional[Dict[str, Any]]:
    url = f"https://aliexpress.ru/item/{product_id}.html"
    html = await _fetch(url)
    if not html: return None
    try:
        soup = BeautifulSoup(html, "lxml")
        title = ""
        price = 0
        image_url = ""
        mt = soup.find("meta", {"property": "og:title"})
        if mt: title = mt.get("content", "")
        mi = soup.find("meta", {"property": "og:image"})
        if mi: image_url = mi.get("content", "")
        for s in soup.find_all("script", {"type": "application/ld+json"}):
            try:
                j = json.loads(s.string or "{}")
                if isinstance(j, dict) and j.get("@type") == "Product":
                    title = title or j.get("name", "")
                    o = j.get("offers", {})
                    if isinstance(o, dict):
                        try: price = price or float(o.get("lowPrice", o.get("price", 0)))
                        except: pass
            except: continue
        if not title: return None
        return {
            "external_id": product_id, "marketplace": "aliexpress",
            "title": title, "brand": "", "category": "",
            "current_price": price, "original_price": price,
            "discount_percent": 0, "rating": 0, "reviews_count": 0,
            "seller_name": "", "seller_id": None, "image_url": image_url,
            "url": url, "raw_data": {},
        }
    except Exception as e:
        logger.error(f"ALI error: {e}")
        return None


# ===================== AMAZON =====================

async def _amazon_scrape(product_id: str) -> Optional[Dict[str, Any]]:
    url = f"https://www.amazon.com/dp/{product_id}"
    html = await _fetch(url)
    if not html: return None
    try:
        soup = BeautifulSoup(html, "lxml")
        title = ""
        price = 0
        image_url = ""
        te = soup.find("span", {"id": "productTitle"})
        if te: title = te.get_text(strip=True)
        pe = soup.find("span", class_="a-price-whole")
        if pe:
            ps = pe.get_text(strip=True).replace(",", "")
            fr = soup.find("span", class_="a-price-fraction")
            if fr: ps += "." + fr.get_text(strip=True)
            try: price = float(ps)
            except: pass
        img = soup.find("img", {"id": "landingImage"})
        if img: image_url = img.get("src", "")
        if not title: return None
        return {
            "external_id": product_id, "marketplace": "amazon",
            "title": title, "brand": "", "category": "",
            "current_price": price, "original_price": price,
            "discount_percent": 0, "rating": 0, "reviews_count": 0,
            "seller_name": "", "seller_id": None, "image_url": image_url,
            "url": url, "raw_data": {},
        }
    except Exception as e:
        logger.error(f"AMAZON error: {e}")
        return None


# ===================== PUBLIC API =====================

async def scrape_product(marketplace: str, product_id: str) -> Optional[Dict[str, Any]]:
    logger.info(f"SCRAPE: {marketplace} / {product_id}")
    funcs = {
        "wildberries": _wb_scrape,
        "ozon": _ozon_scrape,
        "aliexpress": _ali_scrape,
        "amazon": _amazon_scrape,
    }
    func = funcs.get(marketplace)
    if not func:
        return None
    result = await func(product_id)
    if result:
        logger.info(f"SCRAPE OK: {result['title'][:40]} = {result.get('current_price')}")
    else:
        logger.error(f"SCRAPE FAIL: {marketplace}/{product_id}")
    return result


async def search_products(marketplace: str, query: str, limit: int = 10) -> list:
    if marketplace == "wildberries":
        return await _wb_search(query, limit)
    return []


async def scrape_reviews(marketplace: str, product_id: str, limit: int = 100) -> list:
    if marketplace == "wildberries":
        return await _wb_reviews(product_id, limit)
    return []


async def scrape_seller(marketplace: str, seller_id: str) -> Optional[Dict[str, Any]]:
    if marketplace == "wildberries":
        return await _wb_seller(seller_id)
    return None

