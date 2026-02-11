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
        "Accept": "application/json, text/html, */*",
        "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
    }

    if marketplace == "wildberries":
        base["User-Agent"] = (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/131.0.0.0 Safari/537.36"
        )
        base["Origin"] = "https://www.wildberries.ru"
        base["Referer"] = "https://www.wildberries.ru/"
    else:
        base["User-Agent"] = (
            "Mozilla/5.0 (Linux; Android 10; SM-G975F) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/131.0.0.0 Mobile Safari/537.36"
        )

    return base


def _get_ssl_context():
    ctx = ssl.create_default_context(cafile=certifi.where())
    return ctx


class BaseScraper:
    async def fetch(self, url: str, as_json: bool = False, marketplace: str = "") -> Any:
        headers = _get_headers(marketplace)
        timeout = aiohttp.ClientTimeout(total=20)
        ssl_ctx = _get_ssl_context()

        logger.info(f"FETCH: {url}")

        try:
            async with aiohttp.ClientSession(
                timeout=timeout,
                headers=headers,
            ) as session:
                async with session.get(url, ssl=ssl_ctx) as resp:
                    logger.info(f"RESPONSE: {resp.status} from {url[:80]}")

                    if resp.status == 200:
                        if as_json:
                            text = await resp.text()
                            logger.info(f"JSON body length: {len(text)}")
                            try:
                                return json.loads(text)
                            except json.JSONDecodeError as e:
                                logger.error(f"JSON decode error: {e}")
                                logger.error(f"Body preview: {text[:300]}")
                                return None
                        return await resp.text()
                    else:
                        body = await resp.text()
                        logger.warning(f"HTTP {resp.status}: {body[:200]}")
                        return None
        except asyncio.TimeoutError:
            logger.error(f"TIMEOUT: {url}")
            return None
        except aiohttp.ClientError as e:
            logger.error(f"CLIENT ERROR {url}: {e}")
            return None
        except Exception as e:
            logger.error(f"FETCH ERROR {url}: {type(e).__name__}: {e}")
            return None


class WildberriesScraper(BaseScraper):
    """Wildberries через публичное API"""

    async def get_product_info(self, product_id: str) -> Optional[Dict[str, Any]]:
        logger.info(f"WB: fetching product {product_id}")

        # Пробуем несколько вариантов API
        urls = [
            (
                f"https://card.wb.ru/cards/v2/detail"
                f"?appType=1&curr=rub&dest=-1257786&spp=30&nm={product_id}"
            ),
            (
                f"https://card.wb.ru/cards/v1/detail"
                f"?appType=1&curr=rub&dest=-1257786&spp=30&nm={product_id}"
            ),
            (
                f"https://card.wb.ru/cards/detail"
                f"?appType=1&curr=rub&dest=-1257786&spp=30&nm={product_id}"
            ),
        ]

        data = None
        for url in urls:
            data = await self.fetch(url, as_json=True, marketplace="wildberries")
            if data and data.get("data", {}).get("products"):
                logger.info(f"WB: got data from {url[:60]}")
                break
            else:
                logger.info(f"WB: no products from {url[:60]}")
                data = None

        if not data:
            logger.error(f"WB: all API endpoints failed for {product_id}")
            return None

        try:
            products = data.get("data", {}).get("products", [])
            if not products:
                logger.error(f"WB: empty products list for {product_id}")
                return None

            p = products[0]
            logger.info(f"WB: product found: {p.get('name', 'NO NAME')}")

            # Цены
            sizes = p.get("sizes", [])
            price_info = {}
            for s in sizes:
                pd = s.get("price", {})
                if pd:
                    price_info = pd
                    break

            logger.info(f"WB: raw price_info: {price_info}")

            current_price = price_info.get("product", 0)
            if current_price:
                current_price = current_price / 100

            original_price = price_info.get("basic", 0)
            if original_price:
                original_price = original_price / 100

            sale_price = price_info.get("total", 0)
            if sale_price:
                sale_price = sale_price / 100

            final_price = sale_price if sale_price > 0 else current_price

            logger.info(f"WB: price={final_price}, original={original_price}")

            # Скидка
            discount = 0
            if original_price > 0 and final_price > 0 and original_price > final_price:
                discount = round((1 - final_price / original_price) * 100, 1)

            # Бренд и название
            brand = p.get("brand", "")
            name = p.get("name", "")
            title = f"{brand} {name}".strip() if brand else name

            # Картинка
            vol = int(product_id) // 100000
            part = int(product_id) // 1000
            basket = self._get_basket(vol)
            image_url = (
                f"https://basket-{basket}.wbbasket.ru/vol{vol}/part{part}"
                f"/{product_id}/images/big/1.webp"
            )

            # Категория
            subject_name = p.get("subjectName", "")
            parent_name = p.get("subjectParentName", "")
            category = ""
            if parent_name and subject_name:
                category = f"{parent_name} / {subject_name}"
            elif subject_name:
                category = subject_name

            result = {
                "external_id": product_id,
                "marketplace": "wildberries",
                "title": title,
                "brand": brand,
                "category": category,
                "current_price": final_price,
                "original_price": original_price,
                "discount_percent": discount,
                "rating": p.get("reviewRating", 0),
                "reviews_count": p.get("feedbacks", 0),
                "seller_name": p.get("supplier", ""),
                "seller_id": str(p.get("supplierId", "")) or None,
                "image_url": image_url,
                "url": f"https://www.wildberries.ru/catalog/{product_id}/detail.aspx",
                "raw_data": {},
            }

            logger.info(f"WB: SUCCESS - {title[:50]}, price={final_price}")
            return result

        except Exception as e:
            logger.error(f"WB parse error: {type(e).__name__}: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return None

    def _get_basket(self, vol: int) -> str:
        if vol <= 143: return "01"
        elif vol <= 287: return "02"
        elif vol <= 431: return "03"
        elif vol <= 719: return "04"
        elif vol <= 1007: return "05"
        elif vol <= 1061: return "06"
        elif vol <= 1115: return "07"
        elif vol <= 1169: return "08"
        elif vol <= 1313: return "09"
        elif vol <= 1601: return "10"
        elif vol <= 1655: return "11"
        elif vol <= 1919: return "12"
        elif vol <= 2045: return "13"
        elif vol <= 2189: return "14"
        elif vol <= 2405: return "15"
        elif vol <= 2621: return "16"
        elif vol <= 2837: return "17"
        else: return "18"

    async def search(self, query: str, limit: int = 10) -> list:
        url = (
            f"https://search.wb.ru/exactmatch/ru/common/v7/search"
            f"?appType=1&curr=rub&dest=-1257786"
            f"&query={query}&resultset=catalog&spp=30"
        )
        data = await self.fetch(url, as_json=True, marketplace="wildberries")
        if not data:
            return []

        results = []
        try:
            products = data.get("data", {}).get("products", [])
            for p in products[:limit]:
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
        except Exception as e:
            logger.error(f"WB search error: {e}")

        return results

    async def get_reviews(self, product_id: str, limit: int = 100) -> list:
        reviews = []
        for shard in range(1, 3):
            url = f"https://feedbacks{shard}.wb.ru/feedbacks/v2/{product_id}"
            data = await self.fetch(url, as_json=True, marketplace="wildberries")
            if data and "feedbacks" in data:
                raw = data.get("feedbacks", []) or []
                for r in raw[:limit]:
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
        logger.info(f"OZON: fetching product {product_id}")
        url = f"https://www.ozon.ru/product/{product_id}/"
        html = await self.fetch(url, marketplace="ozon")

        if not html:
            logger.error(f"OZON: no HTML for {product_id}")
            return None

        try:
            soup = BeautifulSoup(html, "lxml")

            title = ""
            price = 0
            image_url = ""
            brand = ""
            rating = 0
            reviews_count = 0

            meta_title = soup.find("meta", {"property": "og:title"})
            if meta_title:
                title = meta_title.get("content", "")

            meta_price = soup.find("meta", {"property": "product:price:amount"})
            if meta_price:
                try:
                    price = float(meta_price.get("content", "0"))
                except (ValueError, TypeError):
                    pass

            scripts = soup.find_all("script", {"type": "application/ld+json"})
            for script in scripts:
                try:
                    jdata = json.loads(script.string or "{}")
                    if isinstance(jdata, dict) and jdata.get("@type") == "Product":
                        title = title or jdata.get("name", "")
                        brand = jdata.get("brand", {}).get("name", "") if isinstance(jdata.get("brand"), dict) else ""
                        img = jdata.get("image", "")
                        if isinstance(img, list) and img:
                            image_url = img[0]
                        elif isinstance(img, str):
                            image_url = img

                        offers = jdata.get("offers", {})
                        if isinstance(offers, dict):
                            try:
                                price = price or float(offers.get("price", 0))
                            except (ValueError, TypeError):
                                pass

                        agg = jdata.get("aggregateRating", {})
                        if isinstance(agg, dict):
                            try:
                                rating = float(agg.get("ratingValue", 0))
                                reviews_count = int(agg.get("reviewCount", 0))
                            except (ValueError, TypeError):
                                pass
                except (json.JSONDecodeError, AttributeError):
                    continue

            if not title and not price:
                logger.error(f"OZON: no title/price for {product_id}")
                return None

            logger.info(f"OZON: SUCCESS - {title[:50]}, price={price}")

            return {
                "external_id": product_id,
                "marketplace": "ozon",
                "title": title,
                "brand": brand,
                "category": "",
                "current_price": price,
                "original_price": price,
                "discount_percent": 0,
                "rating": rating,
                "reviews_count": reviews_count,
                "seller_name": "",
                "seller_id": None,
                "image_url": image_url,
                "url": f"https://www.ozon.ru/product/{product_id}/",
                "raw_data": {},
            }

        except Exception as e:
            logger.error(f"OZON parse error: {e}")
            return None

    async def search(self, query: str, limit: int = 10) -> list:
        return []

    async def get_reviews(self, product_id: str, limit: int = 100) -> list:
        return []

    async def get_seller_info(self, seller_id: str) -> Optional[Dict[str, Any]]:
        return None


class AliExpressScraper(BaseScraper):
    async def get_product_info(self, product_id: str) -> Optional[Dict[str, Any]]:
        logger.info(f"ALI: fetching {product_id}")
        url = f"https://aliexpress.ru/item/{product_id}.html"
        html = await self.fetch(url)

        if not html:
            return None

        try:
            soup = BeautifulSoup(html, "lxml")

            title = ""
            price = 0
            image_url = ""

            meta_title = soup.find("meta", {"property": "og:title"})
            if meta_title:
                title = meta_title.get("content", "")

            meta_image = soup.find("meta", {"property": "og:image"})
            if meta_image:
                image_url = meta_image.get("content", "")

            ld_scripts = soup.find_all("script", {"type": "application/ld+json"})
            for script in ld_scripts:
                try:
                    jdata = json.loads(script.string or "{}")
                    if isinstance(jdata, dict) and jdata.get("@type") == "Product":
                        title = title or jdata.get("name", "")
                        offers = jdata.get("offers", {})
                        if isinstance(offers, dict):
                            try:
                                price = price or float(
                                    offers.get("lowPrice", offers.get("price", 0))
                                )
                            except (ValueError, TypeError):
                                pass
                except (json.JSONDecodeError, AttributeError):
                    continue

            if not title:
                return None

            return {
                "external_id": product_id,
                "marketplace": "aliexpress",
                "title": title,
                "brand": "",
                "category": "",
                "current_price": price,
                "original_price": price,
                "discount_percent": 0,
                "rating": 0,
                "reviews_count": 0,
                "seller_name": "",
                "seller_id": None,
                "image_url": image_url,
                "url": url,
                "raw_data": {},
            }
        except Exception as e:
            logger.error(f"ALI parse error: {e}")
            return None

    async def search(self, query: str, limit: int = 10) -> list:
        return []

    async def get_reviews(self, product_id: str, limit: int = 100) -> list:
        return []

    async def get_seller_info(self, seller_id: str) -> Optional[Dict[str, Any]]:
        return None


class AmazonScraper(BaseScraper):
    async def get_product_info(self, product_id: str) -> Optional[Dict[str, Any]]:
        logger.info(f"AMAZON: fetching {product_id}")
        url = f"https://www.amazon.com/dp/{product_id}"
        html = await self.fetch(url)

        if not html:
            return None

        try:
            soup = BeautifulSoup(html, "lxml")

            title = ""
            price = 0
            image_url = ""
            rating = 0
            reviews_count = 0

            title_el = soup.find("span", {"id": "productTitle"})
            if title_el:
                title = title_el.get_text(strip=True)

            price_el = soup.find("span", class_="a-price-whole")
            if price_el:
                fraction = soup.find("span", class_="a-price-fraction")
                price_str = price_el.get_text(strip=True).replace(",", "")
                if fraction:
                    price_str += "." + fraction.get_text(strip=True)
                try:
                    price = float(price_str)
                except ValueError:
                    pass

            img = soup.find("img", {"id": "landingImage"})
            if img:
                image_url = img.get("src", "")

            if not title:
                return None

            return {
                "external_id": product_id,
                "marketplace": "amazon",
                "title": title,
                "brand": "",
                "category": "",
                "current_price": price,
                "original_price": price,
                "discount_percent": 0,
                "rating": rating,
                "reviews_count": reviews_count,
                "seller_name": "",
                "seller_id": None,
                "image_url": image_url,
                "url": url,
                "raw_data": {},
            }
        except Exception as e:
            logger.error(f"AMAZON parse error: {e}")
            return None

    async def search(self, query: str, limit: int = 10) -> list:
        return []

    async def get_reviews(self, product_id: str, limit: int = 100) -> list:
        return []

    async def get_seller_info(self, seller_id: str) -> Optional[Dict[str, Any]]:
        return None


# ==================== ФАБРИКА ====================

def get_scraper(marketplace: str) -> BaseScraper:
    scrapers = {
        "wildberries": WildberriesScraper(),
        "ozon": OzonScraper(),
        "aliexpress": AliExpressScraper(),
        "amazon": AmazonScraper(),
    }
    return scrapers.get(marketplace, BaseScraper())


async def scrape_product(marketplace: str, product_id: str) -> Optional[Dict[str, Any]]:
    logger.info(f"SCRAPE: {marketplace} / {product_id}")
    scraper = get_scraper(marketplace)
    result = await scraper.get_product_info(product_id)
    if result:
        logger.info(f"SCRAPE OK: {result.get('title', '')[:40]} = {result.get('current_price')}")
    else:
        logger.error(f"SCRAPE FAILED: {marketplace} / {product_id}")
    return result


async def search_products(marketplace: str, query: str, limit: int = 10) -> list:
    scraper = get_scraper(marketplace)
    return await scraper.search(query, limit)


async def scrape_reviews(marketplace: str, product_id: str, limit: int = 100) -> list:
    scraper = get_scraper(marketplace)
    return await scraper.get_reviews(product_id, limit)


async def scrape_seller(marketplace: str, seller_id: str) -> Optional[Dict[str, Any]]:
    scraper = get_scraper(marketplace)
    return await scraper.get_seller_info(seller_id)
