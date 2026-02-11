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
                else:
                    body = await r.text()
                    logger.warning(f"  -> body: {body[:150]}")
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
    except json.JSONDecodeError as e:
        logger.error(f"  -> JSON error: {e}, body: {text[:150]}")
        return None


# ===================== WILDBERRIES =====================

def _wb_basket(product_id: str) -> tuple:
    pid = int(product_id)
    vol = pid // 100000
    part = pid // 1000

    ranges = [
        (143,"01"),(287,"02"),(431,"03"),(719,"04"),
        (1007,"05"),(1061,"06"),(1115,"07"),(1169,"08"),
        (1313,"09"),(1601,"10"),(1655,"11"),(1919,"12"),
        (2045,"13"),(2189,"14"),(2405,"15"),(2621,"16"),
        (2837,"17"),
    ]
    basket = "18"
    for limit, num in ranges:
        if vol <= limit:
            basket = num
            break

    host = f"basket-{basket}.wbbasket.ru"
    return host, vol, part


async def _wb_scrape(product_id: str) -> Optional[Dict[str, Any]]:
    logger.info(f"=== WB SCRAPE START: {product_id} ===")

    host, vol, part = _wb_basket(product_id)
    base = f"https://{host}/vol{vol}/part{part}/{product_id}"

    logger.info(f"WB basket: {host}, vol={vol}, part={part}")

    # 1. Карточка товара
    card = None
    card_urls = [
        f"{base}/info/ru/card.json",
        f"{base}/info/card.json",
    ]
    for url in card_urls:
        card = await _fetch_json(url)
        if card:
            logger.info(f"WB: card.json OK")
            break

    # 2. Цена
    price_data = None
    price_urls = [
        f"{base}/info/sellers.json",
        f"{base}/info/price-history.json",
    ]
    for url in price_urls:
        price_data = await _fetch_json(url)
        if price_data:
            logger.info(f"WB: price data OK")
            break

    # 3. Card API (fallback)
    card_api_data = None
    if not card or not price_data:
        for dest in ["-1257786", "-5803327", "123585924", "-1029256"]:
            for ver in ["v2", "v1"]:
                url = (
                    f"https://card.wb.ru/cards/{ver}/detail"
                    f"?appType=1&curr=rub&dest={dest}&spp=30&nm={product_id}"
                )
                data = await _fetch_json(url)
                if data:
                    products = data.get("data", {}).get("products", [])
                    if products:
                        card_api_data = products[0]
                        logger.info(f"WB: card API OK (dest={dest}, ver={ver})")
                        break
            if card_api_data:
                break

    # Собираем результат
    title = ""
    brand = ""
    category = ""
    current_price = 0
    original_price = 0
    rating = 0
    reviews_count = 0
    seller_name = ""
    seller_id = None

    # Из card.json
    if card:
        title = card.get("imt_name", card.get("name", ""))
        brand = card.get("selling", {}).get("brand_name", card.get("brand", ""))
        subj = card.get("subj_name", "")
        root = card.get("subj_root_name", "")
        category = f"{root} / {subj}" if root and subj else subj
        seller_name = card.get("selling", {}).get("supplier_name", "")
        sid = card.get("selling", {}).get("supplier_id")
        seller_id = str(sid) if sid else None

    # Из card API
    if card_api_data:
        if not title:
            b = card_api_data.get("brand", "")
            n = card_api_data.get("name", "")
            title = f"{b} {n}".strip()
            brand = b
        if not seller_name:
            seller_name = card_api_data.get("supplier", "")
        sid = card_api_data.get("supplierId")
        if sid and not seller_id:
            seller_id = str(sid)
        rating = card_api_data.get("reviewRating", 0)
        reviews_count = card_api_data.get("feedbacks", 0)

        subj = card_api_data.get("subjectName", "")
        parent = card_api_data.get("subjectParentName", "")
        if not category:
            category = f"{parent} / {subj}" if parent and subj else subj

        # Цена из card API
        for s in card_api_data.get("sizes", []):
            p = s.get("price", {})
            if p:
                current_price = p.get("total", 0) / 100
                original_price = p.get("basic", 0) / 100
                break

    # Из sellers.json / price-history.json
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

    # Скидка
    discount = 0
    if original_price > current_price > 0:
        discount = round((1 - current_price / original_price) * 100, 1)

    image_url = f"https://{host}/vol{vol}/part{part}/{product_id}/images/big/1.webp"

    if not title and not current_price:
        logger.error(f"WB: no data at all for {product_id}")
        return None

    if not title:
        title = f"Товар WB #{product_id}"

    result = {
        "external_id": product_id,
        "marketplace": "wildberries",
        "title": f"{brand} {title}".strip() if brand and brand.lower() not in title.lower() else title,
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

    logger.info(f"=== WB RESULT: {result['title'][:50]}, price={current_price} ===")
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
                price_info = {}
                for s in p.get("sizes", []):
                    pd = s.get("price", {})
                    if pd:
                        price_info = pd
                        break
                results.append({
                    "external_id": pid,
                    "marketplace": "wildberries",
                    "title": f"{p.get('brand','')} {p.get('name','')}".strip(),
                    "price": price_info.get("total", 0) / 100 if price_info.get("total") else 0,
                    "original_price": price_info.get("basic", 0) / 100 if price_info.get("basic") else 0,
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
    url = f"https://www.ozon.ru/product/{product_id}/"
    html = await _fetch(url)
    if not html:
        return None

    try:
        soup = BeautifulSoup(html, "lxml")
        title = ""
        price = 0
        image_url = ""
        brand = ""
        rating = 0
        reviews_count = 0

        mt = soup.find("meta", {"property": "og:title"})
        if mt: title = mt.get("content", "")
        mp = soup.find("meta", {"property": "product:price:amount"})
        if mp:
            try: price = float(mp.get("content", "0"))
            except: pass

        for s in soup.find_all("script", {"type": "application/ld+json"}):
            try:
                j = json.loads(s.string or "{}")
                if isinstance(j, dict) and j.get("@type") == "Product":
                    title = title or j.get("name", "")
                    b = j.get("brand")
                    brand = b.get("name", "") if isinstance(b, dict) else ""
                    img = j.get("image", "")
                    image_url = img[0] if isinstance(img, list) and img else (img if isinstance(img, str) else "")
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

        if not title and not price: return None
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
        logger.error(f"Unknown marketplace: {marketplace}")
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
