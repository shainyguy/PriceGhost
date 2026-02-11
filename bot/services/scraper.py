import re
import json
import asyncio
import logging
from typing import Optional, Dict, Any
from datetime import datetime

import aiohttp
from bs4 import BeautifulSoup
from fake_useragent import UserAgent

logger = logging.getLogger(__name__)

ua = UserAgent()


def _get_headers() -> dict:
    return {
        "User-Agent": ua.random,
        "Accept": "application/json, text/html, */*",
        "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
    }


class BaseScraper:
    """Базовый класс скрапера"""

    async def fetch(self, url: str, as_json: bool = False) -> Any:
        headers = _get_headers()
        timeout = aiohttp.ClientTimeout(total=15)
        try:
            async with aiohttp.ClientSession(
                timeout=timeout, headers=headers
            ) as session:
                async with session.get(url, ssl=False) as resp:
                    if resp.status == 200:
                        if as_json:
                            return await resp.json(content_type=None)
                        return await resp.text()
                    else:
                        logger.warning(f"HTTP {resp.status} for {url}")
                        return None
        except Exception as e:
            logger.error(f"Fetch error {url}: {e}")
            return None

    async def get_product_info(self, product_id: str) -> Optional[Dict[str, Any]]:
        raise NotImplementedError

    async def get_reviews(self, product_id: str, limit: int = 100) -> list:
        raise NotImplementedError

    async def get_seller_info(self, seller_id: str) -> Optional[Dict[str, Any]]:
        raise NotImplementedError

    async def search(self, query: str, limit: int = 10) -> list:
        raise NotImplementedError


class WildberriesScraper(BaseScraper):
    """Скрапер Wildberries через API"""

    BASE_API = "https://card.wb.ru/cards/v2/detail"
    SEARCH_API = "https://search.wb.ru/exactmatch/ru/common/v7/search"
    SELLER_API = "https://suppliers-shipment.wildberries.ru/api/v1/suppliers"
    FEEDBACKS_API = "https://feedbacks{shard}.wb.ru/feedbacks/v2/{product_id}"

    async def get_product_info(self, product_id: str) -> Optional[Dict[str, Any]]:
        url = (
            f"{self.BASE_API}?appType=1&curr=rub&dest=-1257786"
            f"&spp=30&nm={product_id}"
        )
        data = await self.fetch(url, as_json=True)

        if not data:
            return None

        try:
            products = data.get("data", {}).get("products", [])
            if not products:
                return None

            p = products[0]

            # Цены
            sizes = p.get("sizes", [{}])
            price_info = {}
            for s in sizes:
                price_data = s.get("price", {})
                if price_data:
                    price_info = price_data
                    break

            current_price = price_info.get("product", 0) / 100 if price_info.get("product") else 0
            original_price = price_info.get("basic", 0) / 100 if price_info.get("basic") else 0
            sale_price = price_info.get("total", 0) / 100 if price_info.get("total") else current_price

            # Используем самую актуальную цену
            final_price = sale_price if sale_price > 0 else current_price

            # Скидка
            discount = 0
            if original_price > 0 and final_price > 0 and original_price > final_price:
                discount = round((1 - final_price / original_price) * 100, 1)

            # Рейтинг
            rating = p.get("reviewRating", 0)
            feedbacks = p.get("feedbacks", 0)

            # Продавец
            supplier_id = p.get("supplierId")
            supplier_name = p.get("supplier", "Неизвестен")

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
            category = ""
            subject_name = p.get("subjectName", "")
            parent_name = p.get("subjectParentName", "")
            if parent_name and subject_name:
                category = f"{parent_name} / {subject_name}"
            elif subject_name:
                category = subject_name

            return {
                "external_id": product_id,
                "marketplace": "wildberries",
                "title": title,
                "brand": brand,
                "category": category,
                "current_price": final_price,
                "original_price": original_price,
                "discount_percent": discount,
                "rating": rating,
                "reviews_count": feedbacks,
                "seller_name": supplier_name,
                "seller_id": str(supplier_id) if supplier_id else None,
                "image_url": image_url,
                "url": f"https://www.wildberries.ru/catalog/{product_id}/detail.aspx",
                "raw_data": p,
            }

        except Exception as e:
            logger.error(f"WB parse error: {e}")
            return None

    def _get_basket(self, vol: int) -> str:
        """Определяет номер корзины по volume"""
        if vol <= 143:
            return "01"
        elif vol <= 287:
            return "02"
        elif vol <= 431:
            return "03"
        elif vol <= 719:
            return "04"
        elif vol <= 1007:
            return "05"
        elif vol <= 1061:
            return "06"
        elif vol <= 1115:
            return "07"
        elif vol <= 1169:
            return "08"
        elif vol <= 1313:
            return "09"
        elif vol <= 1601:
            return "10"
        elif vol <= 1655:
            return "11"
        elif vol <= 1919:
            return "12"
        elif vol <= 2045:
            return "13"
        elif vol <= 2189:
            return "14"
        elif vol <= 2405:
            return "15"
        elif vol <= 2621:
            return "16"
        elif vol <= 2837:
            return "17"
        else:
            return "18"

    async def search(self, query: str, limit: int = 10) -> list:
        url = (
            f"{self.SEARCH_API}?appType=1&curr=rub&dest=-1257786"
            f"&query={query}&resultset=catalog&spp=30&suppressSpellcheck=false"
        )
        data = await self.fetch(url, as_json=True)
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
        """Получаем отзывы WB"""
        # Пробуем разные шарды
        reviews = []
        for shard in range(1, 3):
            url = (
                f"https://feedbacks{shard}.wb.ru/feedbacks/v2/{product_id}"
            )
            data = await self.fetch(url, as_json=True)
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
        """Получаем информацию о продавце WB"""
        url = f"https://www.wildberries.ru/webapi/seller/data/short/{seller_id}"
        data = await self.fetch(url, as_json=True)

        if not data:
            # Альтернативный API
            url2 = f"https://static-basket-01.wbbasket.ru/vol0/data/seller-info/{seller_id}.json"
            data = await self.fetch(url2, as_json=True)

        if data:
            return {
                "name": data.get("supplierName", data.get("name", "Неизвестен")),
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
    """Скрапер Ozon"""

    async def get_product_info(self, product_id: str) -> Optional[Dict[str, Any]]:
        """Парсинг Ozon через мобильное API или HTML"""
        url = f"https://www.ozon.ru/product/{product_id}/"
        headers = _get_headers()
        headers["User-Agent"] = (
            "Mozilla/5.0 (Linux; Android 10; SM-G975F) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Mobile Safari/537.36"
        )

        timeout = aiohttp.ClientTimeout(total=15)
        try:
            async with aiohttp.ClientSession(
                timeout=timeout, headers=headers
            ) as session:
                async with session.get(url, ssl=False) as resp:
                    if resp.status != 200:
                        return None
                    html = await resp.text()

            soup = BeautifulSoup(html, "lxml")

            # Извлекаем JSON-LD
            title = ""
            price = 0
            original_price = 0
            image_url = ""
            brand = ""
            rating = 0
            reviews_count = 0

            # Парсим title из meta
            meta_title = soup.find("meta", {"property": "og:title"})
            if meta_title:
                title = meta_title.get("content", "")

            # Парсим цену из meta
            meta_price = soup.find("meta", {"property": "product:price:amount"})
            if meta_price:
                try:
                    price = float(meta_price.get("content", "0"))
                except (ValueError, TypeError):
                    pass

            # Ищем JSON-LD
            scripts = soup.find_all("script", {"type": "application/ld+json"})
            for script in scripts:
                try:
                    jdata = json.loads(script.string)
                    if isinstance(jdata, dict):
                        if jdata.get("@type") == "Product":
                            title = title or jdata.get("name", "")
                            brand = jdata.get("brand", {}).get("name", "") if isinstance(jdata.get("brand"), dict) else ""
                            image_url = jdata.get("image", "")
                            if isinstance(image_url, list) and image_url:
                                image_url = image_url[0]

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
                return None

            discount = 0
            if original_price > price > 0:
                discount = round((1 - price / original_price) * 100, 1)

            return {
                "external_id": product_id,
                "marketplace": "ozon",
                "title": title,
                "brand": brand,
                "category": "",
                "current_price": price,
                "original_price": original_price if original_price > price else price,
                "discount_percent": discount,
                "rating": rating,
                "reviews_count": reviews_count,
                "seller_name": "",
                "seller_id": None,
                "image_url": image_url,
                "url": f"https://www.ozon.ru/product/{product_id}/",
                "raw_data": {},
            }

        except Exception as e:
            logger.error(f"Ozon parse error: {e}")
            return None

    async def search(self, query: str, limit: int = 10) -> list:
        url = f"https://www.ozon.ru/search/?text={query}&from_global=true"
        html = await self.fetch(url)
        results = []

        if html:
            soup = BeautifulSoup(html, "lxml")
            scripts = soup.find_all("script", {"type": "application/ld+json"})
            for script in scripts:
                try:
                    jdata = json.loads(script.string)
                    if isinstance(jdata, dict) and jdata.get("@type") == "ItemList":
                        items = jdata.get("itemListElement", [])
                        for item in items[:limit]:
                            product = item.get("item", {})
                            offers = product.get("offers", {})
                            results.append({
                                "external_id": "",
                                "marketplace": "ozon",
                                "title": product.get("name", ""),
                                "price": float(offers.get("price", 0)),
                                "original_price": 0,
                                "rating": 0,
                                "reviews_count": 0,
                                "seller": "",
                                "url": product.get("url", ""),
                            })
                except (json.JSONDecodeError, AttributeError):
                    continue

        return results

    async def get_reviews(self, product_id: str, limit: int = 100) -> list:
        return []

    async def get_seller_info(self, seller_id: str) -> Optional[Dict[str, Any]]:
        return None


class AliExpressScraper(BaseScraper):
    """Скрапер AliExpress"""

    async def get_product_info(self, product_id: str) -> Optional[Dict[str, Any]]:
        url = f"https://aliexpress.ru/item/{product_id}.html"
        html = await self.fetch(url)

        if not html:
            return None

        try:
            soup = BeautifulSoup(html, "lxml")

            title = ""
            price = 0
            original_price = 0
            image_url = ""

            meta_title = soup.find("meta", {"property": "og:title"})
            if meta_title:
                title = meta_title.get("content", "")

            meta_image = soup.find("meta", {"property": "og:image"})
            if meta_image:
                image_url = meta_image.get("content", "")

            # Ищем цену в скриптах
            scripts = soup.find_all("script")
            for script in scripts:
                if script.string and "skuAmount" in script.string:
                    price_match = re.search(
                        r'"formattedAmount"\s*:\s*"([\d\s,.]+)"', script.string
                    )
                    if price_match:
                        price_str = price_match.group(1).replace(" ", "").replace(",", ".")
                        try:
                            price = float(price_str)
                        except ValueError:
                            pass
                    break

            # JSON-LD
            ld_scripts = soup.find_all("script", {"type": "application/ld+json"})
            for script in ld_scripts:
                try:
                    jdata = json.loads(script.string)
                    if isinstance(jdata, dict) and jdata.get("@type") == "Product":
                        title = title or jdata.get("name", "")
                        offers = jdata.get("offers", {})
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
                "external_id": product_id,
                "marketplace": "aliexpress",
                "title": title,
                "brand": "",
                "category": "",
                "current_price": price,
                "original_price": original_price if original_price else price,
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
            logger.error(f"AliExpress parse error: {e}")
            return None

    async def search(self, query: str, limit: int = 10) -> list:
        return []

    async def get_reviews(self, product_id: str, limit: int = 100) -> list:
        return []


class AmazonScraper(BaseScraper):
    """Скрапер Amazon"""

    async def get_product_info(self, product_id: str) -> Optional[Dict[str, Any]]:
        url = f"https://www.amazon.com/dp/{product_id}"
        html = await self.fetch(url)

        if not html:
            return None

        try:
            soup = BeautifulSoup(html, "lxml")

            title = ""
            price = 0
            original_price = 0
            image_url = ""
            rating = 0
            reviews_count = 0

            # Title
            title_el = soup.find("span", {"id": "productTitle"})
            if title_el:
                title = title_el.get_text(strip=True)

            # Price
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

            # Image
            img = soup.find("img", {"id": "landingImage"})
            if img:
                image_url = img.get("src", "")

            # Rating
            rating_el = soup.find("span", {"data-hook": "rating-out-of-text"})
            if rating_el:
                r_match = re.search(r"([\d.]+)", rating_el.get_text())
                if r_match:
                    rating = float(r_match.group(1))

            # Reviews count
            reviews_el = soup.find("span", {"data-hook": "total-review-count"})
            if reviews_el:
                r_match = re.search(r"([\d,]+)", reviews_el.get_text())
                if r_match:
                    reviews_count = int(r_match.group(1).replace(",", ""))

            if not title:
                return None

            return {
                "external_id": product_id,
                "marketplace": "amazon",
                "title": title,
                "brand": "",
                "category": "",
                "current_price": price,
                "original_price": original_price if original_price else price,
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
            logger.error(f"Amazon parse error: {e}")
            return None

    async def search(self, query: str, limit: int = 10) -> list:
        return []

    async def get_reviews(self, product_id: str, limit: int = 100) -> list:
        return []


# ==================== ФАБРИКА ====================

def get_scraper(marketplace: str) -> BaseScraper:
    """Возвращает нужный скрапер по маркетплейсу"""
    scrapers = {
        "wildberries": WildberriesScraper(),
        "ozon": OzonScraper(),
        "aliexpress": AliExpressScraper(),
        "amazon": AmazonScraper(),
    }
    return scrapers.get(marketplace, BaseScraper())


async def scrape_product(
    marketplace: str, product_id: str
) -> Optional[Dict[str, Any]]:
    """Главная функция скрапинга товара"""
    scraper = get_scraper(marketplace)
    return await scraper.get_product_info(product_id)


async def search_products(
    marketplace: str, query: str, limit: int = 10
) -> list:
    """Поиск товаров на маркетплейсе"""
    scraper = get_scraper(marketplace)
    return await scraper.search(query, limit)


async def scrape_reviews(
    marketplace: str, product_id: str, limit: int = 100
) -> list:
    """Получение отзывов"""
    scraper = get_scraper(marketplace)
    return await scraper.get_reviews(product_id, limit)


async def scrape_seller(
    marketplace: str, seller_id: str
) -> Optional[Dict[str, Any]]:
    """Информация о продавце"""
    scraper = get_scraper(marketplace)
    return await scraper.get_seller_info(seller_id)