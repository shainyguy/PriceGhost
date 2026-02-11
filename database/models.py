from datetime import datetime
from sqlalchemy import (
    Column, Integer, BigInteger, String, Float, Boolean,
    DateTime, Text, ForeignKey, Index, Enum as SAEnum
)
from sqlalchemy.orm import DeclarativeBase, relationship
import enum


class Base(DeclarativeBase):
    pass


class PlanType(str, enum.Enum):
    FREE = "FREE"
    PRO = "PRO"
    PREMIUM = "PREMIUM"


class Marketplace(str, enum.Enum):
    WILDBERRIES = "wildberries"
    OZON = "ozon"
    ALIEXPRESS = "aliexpress"
    AMAZON = "amazon"
    UNKNOWN = "unknown"


class PaymentStatus(str, enum.Enum):
    PENDING = "pending"
    SUCCEEDED = "succeeded"
    CANCELED = "canceled"


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    telegram_id = Column(BigInteger, unique=True, nullable=False, index=True)
    username = Column(String(255), nullable=True)
    first_name = Column(String(255), nullable=True)
    plan = Column(String(20), default=PlanType.FREE.value)
    plan_expires_at = Column(DateTime, nullable=True)
    checks_today = Column(Integer, default=0)
    checks_reset_date = Column(DateTime, default=datetime.utcnow)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    is_blocked = Column(Boolean, default=False)

    # Relationships
    monitored_products = relationship("MonitoredProduct", back_populates="user", cascade="all, delete-orphan")
    payments = relationship("Payment", back_populates="user", cascade="all, delete-orphan")

    @property
    def is_premium(self) -> bool:
        if self.plan == PlanType.PREMIUM.value and self.plan_expires_at:
            return self.plan_expires_at > datetime.utcnow()
        return False

    @property
    def is_pro(self) -> bool:
        if self.plan in (PlanType.PRO.value, PlanType.PREMIUM.value) and self.plan_expires_at:
            return self.plan_expires_at > datetime.utcnow()
        return False

    @property
    def active_plan(self) -> str:
        if self.plan_expires_at and self.plan_expires_at > datetime.utcnow():
            return self.plan
        return PlanType.FREE.value

    def __repr__(self):
        return f"<User(id={self.id}, tg={self.telegram_id}, plan={self.plan})>"


class Product(Base):
    __tablename__ = "products"

    id = Column(Integer, primary_key=True, autoincrement=True)
    url = Column(Text, nullable=False)
    marketplace = Column(String(50), nullable=False)
    external_id = Column(String(255), nullable=True)  # ID товара на площадке
    title = Column(Text, nullable=True)
    brand = Column(String(255), nullable=True)
    category = Column(String(255), nullable=True)
    image_url = Column(Text, nullable=True)
    seller_name = Column(String(255), nullable=True)
    seller_id = Column(String(255), nullable=True)
    current_price = Column(Float, nullable=True)
    original_price = Column(Float, nullable=True)  # "до скидки"
    rating = Column(Float, nullable=True)
    reviews_count = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    price_records = relationship("PriceRecord", back_populates="product", cascade="all, delete-orphan")
    monitored_by = relationship("MonitoredProduct", back_populates="product", cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_product_marketplace_ext", "marketplace", "external_id"),
    )

    def __repr__(self):
        return f"<Product(id={self.id}, {self.marketplace}: {self.title[:30] if self.title else 'N/A'})>"


class PriceRecord(Base):
    __tablename__ = "price_records"

    id = Column(Integer, primary_key=True, autoincrement=True)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False)
    price = Column(Float, nullable=False)
    original_price = Column(Float, nullable=True)
    discount_percent = Column(Float, nullable=True)
    recorded_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    product = relationship("Product", back_populates="price_records")

    __table_args__ = (
        Index("ix_price_product_date", "product_id", "recorded_at"),
    )


class MonitoredProduct(Base):
    __tablename__ = "monitored_products"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False)
    target_price = Column(Float, nullable=True)  # Желаемая цена
    notify_any_drop = Column(Boolean, default=True)  # Уведомлять о любом снижении
    last_notified_price = Column(Float, nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    user = relationship("User", back_populates="monitored_products")
    product = relationship("Product", back_populates="monitored_by")

    __table_args__ = (
        Index("ix_monitor_user_product", "user_id", "product_id", unique=True),
    )


class Payment(Base):
    __tablename__ = "payments"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    yookassa_id = Column(String(255), unique=True, nullable=True)
    amount = Column(Float, nullable=False)
    currency = Column(String(10), default="RUB")
    plan = Column(String(20), nullable=False)  # PRO / PREMIUM
    status = Column(String(20), default=PaymentStatus.PENDING.value)
    payment_url = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    paid_at = Column(DateTime, nullable=True)

    # Relationships
    user = relationship("User", back_populates="payments")

    def __repr__(self):
        return f"<Payment(id={self.id}, user={self.user_id}, plan={self.plan}, status={self.status})>"