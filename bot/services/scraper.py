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


def _get_headers(marketplace: str = "") -> dict:
    base = {
        "Accept": "*/*",
        "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
        "Connection": "keep-alive",
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/131.0.0.0 Safari/537.36"
        ),
    }
    if marketplace == "wildberries":
        base["Origin"] = "https://www.wildberries.ru"
        base["Referer"] = "https://www.wildberries.ru/"
    return base


def _get_ssl_context():
    ctx = ssl.create_default_context(cafile=certifi.where())
    return ctx


class BaseScraper:
    async def fetch(self, url: str, as_json: bool = False, marketplace: str = "") -> Any:
        headers = _get_headers(marketplace)
        timeout = aiohttp.ClientTimeout(total=20)
        ssl_ctx = _get_ssl_context()
        logger.info(f"FETCH: {url[:100]}")

        try:
            async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
                async with session.get(url, ssl=ssl_ctx) as resp:
                    logger.info(f"RESP: {resp.status} from {url[:80]}")
                    if resp.status == 200:
                        if as_json:
                            text = await resp.text()
                            try:
                                return json.loads(text)
                            except json.JSONDecodeError as e:
                                logger.error(f"JSON error: {e}, body: {text[:200]}")
                                return None
                        return await resp.text()
                    else:
                        body = await resp.text()
                        logger.warning(f"HTTP {resp.status}: {body[:200]}")
                        return None
        except asyncio.TimeoutError:
            logger.error(f"TIMEOUT: {url[:80]}")
            return None
        except Exception as e:
            logger.error(f"FETCH ERROR: {type(e).__name__}: {e}")
            return None


class WildberriesScraper(BaseScraper):
    """WB скрапер через basket API (работает всегда)"""

    def _get_basket_num(self, vol: int) -> str:
        ranges = [
            (143, "01"), (287, "02"), (431, "03"), (719, "04"),
            (1007, "05"), (1061, "06"), (1115, "07"), (1169, "08"),
            (1313, "09"), (1601, "10"), (1655, "11"), (1919, "12"),
            (2045, "13"), (2189, "14"), (2405, "15"), (2621, "16"),
            (2837, "17"),
        ]
        for limit, num in ranges:
            if vol <= limit:
                return num
        return "18"

    def _get_basket_host(self, product_id: str) -> tuple:
        """Возвращает (basket_host, vol, part)"""
        pid = int(product_id)
        vol = pid // 100000
        part = pid // 1000
        basket = self._get_basket_num(vol)
        host = f"basket-{basket}.wbbasket.ru"
        return host, vol, part

    async def get_product_info(self, product_id: str) -> Optional[Dict[str, Any]]:
        logger.info(f"WB: fetching {product_id}")

        # СПОСОБ 1: Basket API (карточка товара) — работает без блокировок
        info = await self._fetch_via_basket(product_id)
        if info:
            return info

        # СПОСОБ 2: Card API с разными параметрами
        info = await self._fetch_via_card_api(product_id)
        if info:
            return info

        logger.error(f"WB: all methods failed for {product_id}")
        return None

    async def _fetch_via_basket(self, product_id: str) -> Optional[Dict[str, Any]]:
        """Прямой доступ через basket — самый надёжный"""
        host, vol, part = self._get_basket_host(product_id)

        # Пробуем разные пути к карточке
        card_urls = [
            f"https://{host}/vol{vol}/part{part}/{product_id}/info/ru/card.json",
            f"https://{host}/vol{vol}/part{part}/{product_id}/info/card.json",
        ]

        card_data = None
        for url in card_urls:
            card_data = await self.fetch(url, as_json=True, marketplace="wildberries")
            if card_data:
                logger.info(f"WB BASKET: got card data")
                break

        # Получаем цену отдельно
        price_urls = [
            f"https://{host}/vol{vol}/part{part}/{product_id}/info/price-history.json",
            f"https://{host}/vol{vol}/part{part}/{product_id}/info/sellers.json",
        ]

        price_data = None
        for url in price_urls:
            price_data = await self.fetch(url, as_json=True, marketplace="wildberries")
            if price_data:
                logger.info(f"WB BASKET: got price data")
                break

        if not card_data:
            logger.warning(f"WB BASKET: no card data for {product_id}")
            return None

        try:
            # Парсим карточку
            title = card_data.get("imt_name", card_data.get("name", ""))
            brand = card_data.get("selling", {}).get("brand_name", "")
            if not brand:
                brand = card_data.get("brand", "")

            subj_name = card_data.get("subj_name", "")
            subj_root = card_data.get("subj_root_name", "")
            category = f"{subj_root} / {subj_name}" if subj_root and subj_name else subj_name

            # Описание
            description = card_data.get("description", "")

            # Seller
            seller_name = card_data.get("selling", {}).get("supplier_name", "")
            seller_id = str(card_data.get("selling", {}).get("supplier_id", ""))

            # Цена из sellers.json
            current_price = 0
            original_price = 0
            discount = 0

            if price_data:
                if isinstance(price_data, list):
                    # price-history.json
                    if price_data:
                        latest = price_data[-1] if price_data else {}
                        current_price = latest.get("price", {}).get("RUB", 0) / 100 if isinstance(latest.get("price"), dict) else 0
                elif isinstance(price_data, dict):
                    # sellers.json
                    sizes = price_data.get("sizes", [])
                    for s in sizes:
                        sp = s.get("price", {})
                        if sp:
                            current_price = sp.get("total", 0) / 100
                            original_price = sp.get("basic", 0) / 100
                            break

            if original_price > current_price > 0:
                discount = round((1 - current_price / original_price) * 100, 1)

            # Картинка
            image_url = f"https://{host}/vol{vol}/part{part}/{product_id}/images/big/1.webp"

            if not title:
                # Пробуем собрать из данных
                title = f"{brand} {card_data.get('nm_id', product_id)}".strip()

            result = {
                "external_id": product_id,
                "marketplace": "wildberries",
                "title": f"{brand} {title}".strip() if brand and brand not in title else title,
                "brand": brand,
                "category": category,
                "current_price": current_price,
                "original_price": original_price if original_price else current_price,
                "discount_percent": discount,
                "rating": 0,
                "reviews_count": 0,
                "seller_name": seller_name,
                "seller_id": seller_id if seller_id != "0" else None,
                "image_url": image_url,
                "url": f"https://www.wildberries.ru/catalog/{product_id}/detail.aspx",
                "raw_data": {},
            }

            logger.info(f"WB BASKET OK: {result['title'][:50]}, price={current_price}")
            return result

        except Exception as e:
            logger.error(f"WB BASKET parse error: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return None

    async def _fetch_via_card_api(self, product_id: str) -> Optional[Dict[str, Any]]:
        """Через card.wb.ru API — может блокироваться"""
        dests = ["-1257786", "-5803327", "123585924"]
        versions = ["v2", "v1"]

        for ver in versions:
            for dest in dests:
                url = (
                    f"https://card.wb.ru/cards/{ver}/detail"
                    f"?appType=1&curr=rub&dest={dest}"
                    f"&spp=30&ab_testing=false&nm={product_id}"
                )
                data = await self.fetch(url, as_json=True, marketplace="wildberries")

                if data and data.get("data", {}).get("products"):
                    products = data["data"]["products"]
                    p = products[0]

                    sizes = p.get("sizes", [])
                    price_info = {}
                    for s in sizes:
                        pd = s.get("price", {})
                        if pd:
                            price_info = pd
                            break

                    current_price = price_info.get("total", 0) / 100 if price_info.get("total") else 0
                    original_price = price_info.get("basic", 0) / 100 if price_info.get("basic") else 0
                    sale = price_info.get("product", 0) / 100 if price_info.get("product") else current_price

                    final_price = current_price if current_price > 0 else sale

                    discount = 0
                    if original_price > final_price > 0:
                        discount = round((1 - final_price / original_price) * 100, 1)

                    brand = p.get("brand", "")
                    name = p.get("name", "")
                    title = f"{brand} {name}".strip() if brand else name

                    host, vol, part = self._get_basket_host(product_id)
                    image_url = f"https://{host}/vol{vol}/part{part}/{product_id}/images/big/1.webp"

                    subj = p.get("subjectName", "")
                    parent = p.get("subjectParentName", "")
                    category = f"{parent} / {subj}" if parent and subj else subj

                    result = {
                        "external_id": product_id,
                        "marketplace": "wildberries",
                        "title": title,
                        "brand": brand,
                        "category": category,
                        "current_price": final_price,
                        "original_price": original_price if original_price else final_price,
                        "discount_percent": discount,
                        "rating": p.get("reviewRating", 0),
                        "reviews_count": p.get("feedbacks", 0),
                        "seller_name": p.get("supplier", ""),
                        "seller_id": str(p.get("supplierId", "")) or None,
                        "image_url": image_url,
                        "url": f"https://www.wildberries.ru/catalog/{product_id}/detail.aspx",
                        "raw_data": {},
                    }

                    logger.info(f"WB CARD API OK: {title[:40]}, price={final_price}")
                    return result

        return None

    async def search(self, query: str, limit: int = 10) -> list:
        dests = ["-1257786", "-5803327"]
        for dest in dests:
            url = (
                f"https://search.wb.ru/exactmatch/ru/common/v7/search"
                f"?appType=1&curr=rub&dest={dest}"
                f"&query={query}&resultset=catalog&spp=30"
            )
            data = await self.fetch(url, as_json=True, marketplace="wildberries")
            if data and data.get("data", {}).get("products"):
                results = []
                for p in data["data"]["products"][:limit]:
                    pid = str(p.get("id", ""))
                    sizes = p.get("sizes", [{}])
                    price_info = {}
                    for s in sizes:
                        pd = s.get("price", {})
                        if pd:
                            price_info = pd
                            break

                    price = price_info.get("total", 0) / 100 if price_info.get("total") else 0
                    original = price_info.get("basic", 0) / 100 if price_info.get("basic") else 0
                    brand = p.get("brand", "")
                    name = p.get("name", "")

                    results.append({
                        "external_id": pid,
                        "marketplace": "wildberries",
                        "title": f"{brand} {name}".strip(),
                        "price": price,
                        "original_price": original,
                        "rating": p.get("reviewRating", 0),
                        "reviews_count": p.get("feedbacks", 0),
                        "seller": p.get("supplier", ""),
                        "url": f"https://www.wildberries.ru/catalog/{pid}/detail.aspx",
                    })
                return results
        return []

    async def get_reviews(self, product_id: str, limit: int = 100) -> list:
        reviews = []
        for shard in range(1, 3):
            url = f"https://feedbacks{shard}.wb.ru/feedbacks/v2/{product_id}"
            data = await self.fetch(url, as_json=True, marketplace="wildberries")
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

    async def get_seller_info(self, seller_id: str) -> Optional[Dict[str, Any]]:
        url = f"https://static-basket-01.wbbasket.ru/vol0/data/seller-info/{seller_id}.json"
        data = await self.fetch(url, as_json=True, marketplace="wildberries")
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


class OzonScraper(BaseScraper):
    async def get_product_info(self, product_id: str) -> Optional[Dict[str, Any]]:
        logger.info(f"OZON: fetching {product_id}")
        url = f"https://www.ozon.ru/product/{product_id}/"
        html = await self.fetch(url, marketplace="ozon")
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
            if mt:
                title = mt.get("content", "")

            mp = soup.find("meta", {"property": "product:price:amount"})
            if mp:
                try:
                    price = float(mp.get("content", "0"))
                except (ValueError, TypeError):
                    pass

            for script in soup.find_all("script", {"type": "application/ld+json"}):
                try:
                    jd = json.loads(script.string or "{}")
                    if isinstance(jd, dict) and jd.get("@type") == "Product":
                        title = title or jd.get("name", "")
                        b = jd.get("brand")
                        brand = b.get("name", "") if isinstance(b, dict) else ""
                        img = jd.get("image", "")
                        image_url = img[0] if isinstance(img, list) and img else (img if isinstance(img, str) else "")
                        offers = jd.get("offers", {})
                        if isinstance(offers, dict):
                            try:
                                price = price or float(offers.get("price", 0))
                            except (ValueError, TypeError):
                                pass
                        agg = jd.get("aggregateRating", {})
                        if isinstance(agg, dict):
                            try:
                                rating = float(agg.get("ratingValue", 0))
                                reviews_count = int(agg.get("reviewCount", 0))
                            except (ValueError, TypeError):
                                pass
                except (json.JSONDecodeError, AttributeError):
                    continue

            if not title and not price:
                return None

            logger.info(f"OZON OK: {title[:40]}, price={price}")
            return {
                "external_id": product_id,
                "marketplace": "ozon",
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

    async def search(self, query: str, limit: int = 10) -> list:
        return []

    async def get_reviews(self, product_id: str, limit: int = 100) -> list:
        return []

    async def get_seller_info(self, seller_id: str) -> Optional[Dict[str, Any]]:
        return None


class AliExpressScraper(BaseScraper):
    async def get_product_info(self, product_id: str) -> Optional[Dict[str, Any]]:
        url = f"https://aliexpress.ru/item/{product_id}.html"
        html = await self.fetch(url)
        if not html:
            return None
        try:
            soup = BeautifulSoup(html, "lxml")
            title = ""
            price = 0
            image_url = ""

            mt = soup.find("meta", {"property": "og:title"})
            if mt:
                title = mt.get("content", "")
            mi = soup.find("meta", {"property": "og:image"})
            if mi:
                image_url = mi.get("content", "")

            for script in soup.find_all("script", {"type": "application/ld+json"}):
                try:
                    jd = json.loads(script.string or "{}")
                    if isinstance(jd, dict) and jd.get("@type") == "Product":
                        title = title or jd.get("name", "")
                        offers = jd.get("offers", {})
                        if isinstance(offers, dict):
                            try:
                                price = price or float(offers.get("lowPrice", offers.get("price", 0)))
                            except (ValueError, TypeError):
                                pass
                except (json.JSONDecodeError, AttributeError):
                    continue

            if not title:
                return None
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

    async def search(self, query: str, limit: int = 10) -> list:
        return []
    async def get_reviews(self, product_id: str, limit: int = 100) -> list:
        return []
    async def get_seller_info(self, seller_id: str) -> Optional[Dict[str, Any]]:
        return None


class AmazonScraper(BaseScraper):
    async def get_product_info(self, product_id: str) -> Optional[Dict[str, Any]]:
        url = f"https://www.amazon.com/dp/{product_id}"
        html = await self.fetch(url)
        if not html:
            return None
        try:
            soup = BeautifulSoup(html, "lxml")
            title = ""
            price = 0
            image_url = ""
            te = soup.find("span", {"id": "productTitle"})
            if te:
                title = te.get_text(strip=True)
            pe = soup.find("span", class_="a-price-whole")
            if pe:
                fr = soup.find("span", class_="a-price-fraction")
                ps = pe.get_text(strip=True).replace(",", "")
                if fr:
                    ps += "." + fr.get_text(strip=True)
                try:
                    price = float(ps)
                except ValueError:
                    pass
            img = soup.find("img", {"id": "landingImage"})
            if img:
                image_url = img.get("src", "")
            if not title:
                return None
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

    async def search(self, query: str, limit: int = 10) -> list:
        return []
    async def get_reviews(self, product_id: str, limit: int = 100) -> list:
        return []
    async def get_seller_info(self, seller_id: str) -> Optional[Dict[str, Any]]:
        return None


def get_scraper(marketplace: str) -> BaseScraper:
    return {
        "wildberries": WildberriesScraper(),
        "ozon": OzonScraper(),
        "aliexpress": AliExpressScraper(),
        "amazon": AmazonScraper(),
    }.get(marketplace, BaseScraper())


async def scrape_product(marketplace: str, product_id: str) -> Optional[Dict[str, Any]]:
    logger.info(f"SCRAPE: {marketplace} / {product_id}")
    scraper = get_scraper(marketplace)
    result = await scraper.get_product_info(product_id)
    if result:
        logger.info(f"SCRAPE OK: {result['title'][:40]} = {result.get('current_price')}")
    else:
        logger.error(f"SCRAPE FAIL: {marketplace} / {product_id}")
    return result


async def search_products(marketplace: str, query: str, limit: int = 10) -> list:
    return await get_scraper(marketplace).search(query, limit)


async def scrape_reviews(marketplace: str, product_id: str, limit: int = 100) -> list:
    return await get_scraper(marketplace).get_reviews(product_id, limit)


async def scrape_seller(marketplace: str, seller_id: str) -> Optional[Dict[str, Any]]:
    return await get_scraper(marketplace).get_seller_info(seller_id)
