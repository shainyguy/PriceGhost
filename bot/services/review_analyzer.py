import logging
import re
from typing import Dict, Any, List, Optional

from bot.services.scraper import scrape_reviews
from bot.services.gigachat import get_gigachat

logger = logging.getLogger(__name__)

# Паттерны фейковых отзывов
FAKE_PATTERNS = [
    r"всё (отлично|замечательно|прекрасно|супер)\.?\s*$",
    r"^(хорошо|нормально|ок|класс|супер|огонь)\.?\s*$",
    r"рекомендую\.?\s*$",
    r"всем советую",
    r"^5\s*(звёзд|баллов)?\.?\s*$",
    r"^отличн(о|ый товар)\.?\s*$",
    r"(быстрая доставка|пришло быстро)\.?\s*$",
    r"^(товар|всё) соответствует (описанию|фото)",
]

# Минимальная длина «настоящего» отзыва
MIN_REAL_REVIEW_LEN = 30


def _detect_fake_patterns(text: str) -> List[str]:
    """Проверяет текст на паттерны фейковых отзывов"""
    found = []
    text_lower = text.lower().strip()
    for pattern in FAKE_PATTERNS:
        if re.search(pattern, text_lower):
            found.append(pattern)
    return found


def _basic_fake_score(review: dict) -> float:
    """
    Базовый скор фейковости (0-1).
    0 = точно настоящий, 1 = точно фейк
    """
    score = 0.0
    text = review.get("text", "").strip()

    # Слишком короткий
    if len(text) < 10:
        score += 0.4
    elif len(text) < MIN_REAL_REVIEW_LEN:
        score += 0.2

    # Максимальный рейтинг + короткий текст
    rating = review.get("rating", 0)
    if rating == 5 and len(text) < 30:
        score += 0.3

    # Паттерны
    patterns = _detect_fake_patterns(text)
    if patterns:
        score += 0.15 * len(patterns)

    # Нет конкретики (нет цифр, размеров и т.д.)
    has_specifics = bool(re.search(r"\d+", text))
    if not has_specifics and len(text) < 50:
        score += 0.1

    # Только позитив, ни одного "но" / "минус" / "недостат"
    has_criticism = bool(
        re.search(r"(но |минус|недостат|жаль|к сожалению|не понравил)", text.lower())
    )
    if not has_criticism and rating == 5 and len(text) < 60:
        score += 0.1

    return min(score, 1.0)


async def analyze_reviews(
    marketplace: str,
    product_id: str,
    product_title: str = "",
) -> Dict[str, Any]:
    """
    Полный анализ отзывов товара:
    - Скачивает отзывы
    - Определяет фейковые
    - Считает реальный рейтинг
    - Извлекает плюсы/минусы через AI
    """
    result = {
        "total_reviews": 0,
        "analyzed": 0,
        "fake_count": 0,
        "fake_percent": 0,
        "real_rating": 0,
        "marketplace_rating": 0,
        "top_pros": [],
        "top_cons": [],
        "ai_summary": "",
        "suspicious_patterns": [],
        "rating_distribution": {},
        "reviews_sample": [],
    }

    # 1. Скачиваем отзывы
    reviews = await scrape_reviews(marketplace, product_id, limit=100)

    if not reviews:
        result["ai_summary"] = "Не удалось получить отзывы для анализа."
        return result

    result["total_reviews"] = len(reviews)
    result["analyzed"] = len(reviews)

    # 2. Базовый анализ фейков
    fake_count = 0
    real_ratings = []
    all_ratings = []

    for review in reviews:
        fake_score = _basic_fake_score(review)
        review["fake_score"] = fake_score

        rating = review.get("rating", 0)
        if rating > 0:
            all_ratings.append(rating)

        if fake_score >= 0.5:
            fake_count += 1
        else:
            if rating > 0:
                real_ratings.append(rating)

    result["fake_count"] = fake_count
    result["fake_percent"] = round(
        (fake_count / len(reviews) * 100) if reviews else 0, 1
    )

    # Рейтинги
    if all_ratings:
        result["marketplace_rating"] = round(sum(all_ratings) / len(all_ratings), 1)

    if real_ratings:
        result["real_rating"] = round(sum(real_ratings) / len(real_ratings), 1)
    else:
        result["real_rating"] = result["marketplace_rating"]

    # Распределение рейтингов
    dist = {1: 0, 2: 0, 3: 0, 4: 0, 5: 0}
    for r in all_ratings:
        r_int = max(1, min(5, int(r)))
        dist[r_int] += 1
    result["rating_distribution"] = dist

    # Паттерны подозрительности
    short_five_star = sum(
        1 for r in reviews
        if r.get("rating", 0) == 5 and len(r.get("text", "")) < 20
    )
    if short_five_star > len(reviews) * 0.3:
        result["suspicious_patterns"].append(
            f"⚠️ {short_five_star} отзывов — 5 звёзд с текстом менее 20 символов"
        )

    same_day_reviews = {}
    for r in reviews:
        date = r.get("date", "")[:10]
        if date:
            same_day_reviews[date] = same_day_reviews.get(date, 0) + 1

    for date, count in same_day_reviews.items():
        if count > 10:
            result["suspicious_patterns"].append(
                f"⚠️ {count} отзывов за один день ({date}) — возможна накрутка"
            )

    # 3. AI-анализ через GigaChat
    ai_text = await _ai_analyze_reviews(reviews, product_title)
    if ai_text:
        result["ai_summary"] = ai_text

        # Парсим плюсы/минусы из AI ответа
        pros, cons = _parse_pros_cons(ai_text)
        result["top_pros"] = pros
        result["top_cons"] = cons

    # 4. Примеры подозрительных отзывов
    suspicious = sorted(reviews, key=lambda r: r.get("fake_score", 0), reverse=True)
    result["reviews_sample"] = [
        {
            "text": r["text"][:100],
            "rating": r.get("rating", 0),
            "fake_score": round(r.get("fake_score", 0) * 100),
            "author": r.get("author", "Аноним"),
        }
        for r in suspicious[:3]
        if r.get("fake_score", 0) >= 0.5
    ]

    return result


async def _ai_analyze_reviews(
    reviews: list, product_title: str
) -> Optional[str]:
    """Анализ отзывов через GigaChat"""
    if not reviews:
        return None

    gigachat = get_gigachat()

    # Собираем тексты отзывов (не все, чтобы уместиться в контекст)
    review_texts = []
    for r in reviews[:40]:
        text = r.get("text", "").strip()
        if text and len(text) > 10:
            rating = r.get("rating", "?")
            pros = r.get("pros", "")
            cons = r.get("cons", "")
            entry = f"[{rating}★] {text}"
            if pros:
                entry += f" | Плюсы: {pros}"
            if cons:
                entry += f" | Минусы: {cons}"
            review_texts.append(entry[:200])

    if not review_texts:
        return None

    reviews_block = "\n".join(review_texts)

    system_prompt = (
        "Ты — эксперт по анализу отзывов на товары. "
        "Твоя задача: проанализировать отзывы, выделить реальные плюсы и минусы, "
        "определить есть ли признаки накрутки отзывов. "
        "Отвечай структурированно и кратко, на русском языке."
    )

    prompt = f"""Проанализируй отзывы на товар "{product_title}":

{reviews_block}

Дай анализ в формате:

📊 ОБЩАЯ ОЦЕНКА: (честная оценка товара)

✅ ГЛАВНЫЕ ПЛЮСЫ:
1. ...
2. ...
3. ...

❌ ГЛАВНЫЕ МИНУСЫ:
1. ...
2. ...
3. ...

🔍 ПРИЗНАКИ НАКРУТКИ: (есть или нет, почему)

💡 РЕКОМЕНДАЦИЯ: (стоит покупать или нет)"""

    response = await gigachat.ask(
        prompt=prompt,
        system_prompt=system_prompt,
        temperature=0.3,
        max_tokens=1200,
    )

    return response


def _parse_pros_cons(ai_text: str):
    """Парсит плюсы и минусы из AI ответа"""
    pros = []
    cons = []

    lines = ai_text.split("\n")
    mode = None

    for line in lines:
        line = line.strip()
        if "ПЛЮС" in line.upper():
            mode = "pros"
            continue
        elif "МИНУС" in line.upper():
            mode = "cons"
            continue
        elif "ПРИЗНАК" in line.upper() or "РЕКОМЕНДАЦ" in line.upper():
            mode = None
            continue

        if mode and line and (line[0].isdigit() or line.startswith("-") or line.startswith("•")):
            # Убираем нумерацию
            cleaned = re.sub(r"^[\d.\-•\s]+", "", line).strip()
            if cleaned:
                if mode == "pros":
                    pros.append(cleaned)
                else:
                    cons.append(cleaned)

    return pros[:5], cons[:5]


def format_review_analysis(data: Dict[str, Any]) -> str:
    """Форматирует результат анализа отзывов"""
    text = "🤖 <b>AI-анализ отзывов</b>\n\n"

    text += f"📝 Проанализировано: <b>{data['analyzed']}</b> отзывов\n"

    # Рейтинги
    mp_rating = data["marketplace_rating"]
    real_rating = data["real_rating"]
    diff = mp_rating - real_rating

    text += f"⭐ Рейтинг маркетплейса: <b>{mp_rating}</b>\n"

    if abs(diff) > 0.3:
        text += f"🎯 Реальный рейтинг: <b>{real_rating}</b>"
        if diff > 0:
            text += f" (завышен на {diff:.1f})\n"
        else:
            text += f" (занижен на {abs(diff):.1f})\n"
    else:
        text += f"🎯 Реальный рейтинг: <b>{real_rating}</b> ✅\n"

    # Фейки
    fake_pct = data["fake_percent"]
    if fake_pct > 30:
        text += f"\n🚨 <b>Подозрительных отзывов: {data['fake_count']} ({fake_pct}%)</b>\n"
    elif fake_pct > 15:
        text += f"\n⚠️ Подозрительных отзывов: {data['fake_count']} ({fake_pct}%)\n"
    else:
        text += f"\n✅ Подозрительных отзывов: {data['fake_count']} ({fake_pct}%)\n"

    # Распределение рейтингов
    dist = data.get("rating_distribution", {})
    if dist:
        text += "\n📊 <b>Распределение:</b>\n"
        total = sum(dist.values()) or 1
        for star in range(5, 0, -1):
            count = dist.get(star, 0)
            pct = count / total * 100
            bar_len = int(pct / 5)
            bar = "█" * bar_len + "░" * (20 - bar_len)
            text += f"  {'⭐' * star}{'☆' * (5-star)} [{bar}] {count} ({pct:.0f}%)\n"

    # Подозрительные паттерны
    if data.get("suspicious_patterns"):
        text += "\n🔍 <b>Подозрительные паттерны:</b>\n"
        for pattern in data["suspicious_patterns"]:
            text += f"  {pattern}\n"

    # Примеры фейковых отзывов
    if data.get("reviews_sample"):
        text += "\n🤥 <b>Примеры подозрительных отзывов:</b>\n"
        for r in data["reviews_sample"]:
            text += (
                f"  ⚠️ [{r['rating']}★] «{r['text']}...» "
                f"(фейк: {r['fake_score']}%)\n"
            )

    # AI-выжимка
    if data.get("ai_summary"):
        text += f"\n{'─' * 30}\n\n"
        text += data["ai_summary"]

    # Если нет AI, но есть плюсы/минусы
    elif data.get("top_pros") or data.get("top_cons"):
        if data["top_pros"]:
            text += "\n✅ <b>Главные плюсы:</b>\n"
            for p in data["top_pros"]:
                text += f"  • {p}\n"
        if data["top_cons"]:
            text += "\n❌ <b>Главные минусы:</b>\n"
            for c in data["top_cons"]:
                text += f"  • {c}\n"

    return text