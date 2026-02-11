from datetime import datetime


def format_price(price: float, currency: str = "₽") -> str:
    """Форматирует цену: 3200 -> 3 200₽"""
    if price is None:
        return "N/A"
    formatted = f"{price:,.0f}".replace(",", " ")
    return f"{formatted}{currency}"


def format_percent(value: float) -> str:
    """Форматирует процент"""
    if value is None:
        return "N/A"
    return f"{value:+.1f}%"


def format_date(dt: datetime) -> str:
    if dt is None:
        return "N/A"
    return dt.strftime("%d.%m.%Y")


def format_datetime(dt: datetime) -> str:
    if dt is None:
        return "N/A"
    return dt.strftime("%d.%m.%Y %H:%M")


def plan_badge(plan: str) -> str:
    badges = {
        "FREE": "🆓 FREE",
        "PRO": "⭐ PRO",
        "PREMIUM": "👑 PREMIUM",
    }
    return badges.get(plan.upper(), plan)


def truncate(text: str, max_len: int = 50) -> str:
    if len(text) <= max_len:
        return text
    return text[:max_len - 3] + "..."