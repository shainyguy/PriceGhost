import os
from dataclasses import dataclass, field
from dotenv import load_dotenv

load_dotenv()


@dataclass
class BotConfig:
    token: str = os.getenv("BOT_TOKEN", "")
    admin_ids: list[int] = field(default_factory=lambda: [
        int(x.strip()) for x in os.getenv("ADMIN_IDS", "0").split(",") if x.strip()
    ])


@dataclass
class YookassaConfig:
    shop_id: str = os.getenv("YOOKASSA_SHOP_ID", "")
    secret_key: str = os.getenv("YOOKASSA_SECRET_KEY", "")


@dataclass
class GigaChatConfig:
    auth_key: str = os.getenv("GIGACHAT_AUTH_KEY", "")
    scope: str = os.getenv("GIGACHAT_SCOPE", "GIGACHAT_API_PERS")
    token_url: str = "https://ngw.devices.sberbank.ru:9443/api/v2/oauth"
    api_url: str = "https://gigachat.devices.sberbank.ru/api/v1"


@dataclass
class DatabaseConfig:
    url: str = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///priceghost.db")


@dataclass
class WebhookConfig:
    url: str = os.getenv("WEBHOOK_URL", "").rstrip("/")
    path: str = os.getenv("WEBHOOK_PATH", "/webhook")
    host: str = os.getenv("WEB_SERVER_HOST", "0.0.0.0")
    port: int = int(os.getenv("WEB_SERVER_PORT", "8080"))

    def __post_init__(self):
        # Гарантируем чистые пути
        self.url = self.url.rstrip("/")
        if self.path and not self.path.startswith("/"):
            self.path = "/" + self.path
        self.path = "/" + self.path.strip("/")

    @property
    def full_url(self) -> str:
        return f"{self.url}{self.path}"


@dataclass
class PlanLimits:
    FREE = {
        "checks_per_day": 3,
        "history_days": 30,
        "monitor_items": 0,
        "fake_discount": True,
        "notifications": False,
        "search_cheaper": False,
        "seller_check": False,
        "ai_reviews": False,
        "analogs": False,
        "price_predict": False,
        "cashback": False,
        "chart": False,
    }
    PRO = {
        "checks_per_day": 30,
        "history_days": 365,
        "monitor_items": 20,
        "fake_discount": True,
        "notifications": True,
        "search_cheaper": True,
        "seller_check": True,
        "ai_reviews": False,
        "analogs": False,
        "price_predict": False,
        "cashback": False,
        "chart": True,
    }
    PREMIUM = {
        "checks_per_day": 999999,
        "history_days": 365,
        "monitor_items": 50,
        "fake_discount": True,
        "notifications": True,
        "search_cheaper": True,
        "seller_check": True,
        "ai_reviews": True,
        "analogs": True,
        "price_predict": True,
        "cashback": True,
        "chart": True,
    }

    @classmethod
    def get(cls, plan: str) -> dict:
        return getattr(cls, plan.upper(), cls.FREE)


@dataclass
class Config:
    bot: BotConfig = field(default_factory=BotConfig)
    yookassa: YookassaConfig = field(default_factory=YookassaConfig)
    gigachat: GigaChatConfig = field(default_factory=GigaChatConfig)
    db: DatabaseConfig = field(default_factory=DatabaseConfig)
    webhook: WebhookConfig = field(default_factory=WebhookConfig)
    plans: PlanLimits = field(default_factory=PlanLimits)


config = Config()
