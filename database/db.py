from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy import select, update, delete, func
from datetime import datetime, timedelta
from typing import Optional

from database.models import Base, User, Product, PriceRecord, MonitoredProduct, Payment, PlanType
from config import config


class Database:
    def __init__(self):
        self.engine = create_async_engine(config.db.url, echo=False)
        self.session_factory = async_sessionmaker(
            self.engine, class_=AsyncSession, expire_on_commit=False
        )

    async def init(self):
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    async def close(self):
        await self.engine.dispose()

    # ==================== USERS ====================

    async def get_or_create_user(
        self, telegram_id: int, username: str = None, first_name: str = None
    ) -> User:
        async with self.session_factory() as session:
            result = await session.execute(
                select(User).where(User.telegram_id == telegram_id)
            )
            user = result.scalar_one_or_none()

            if not user:
                user = User(
                    telegram_id=telegram_id,
                    username=username,
                    first_name=first_name,
                )
                session.add(user)
                await session.commit()
                await session.refresh(user)
            else:
                # Update info
                user.username = username
                user.first_name = first_name
                user.updated_at = datetime.utcnow()
                await session.commit()

            return user

    async def get_user(self, telegram_id: int) -> Optional[User]:
        async with self.session_factory() as session:
            result = await session.execute(
                select(User).where(User.telegram_id == telegram_id)
            )
            return result.scalar_one_or_none()

    async def check_and_increment_usage(self, telegram_id: int) -> tuple[bool, int, int]:
        """
        Проверяет лимит и увеличивает счётчик.
        Returns: (allowed, used, limit)
        """
        from config import PlanLimits

        async with self.session_factory() as session:
            result = await session.execute(
                select(User).where(User.telegram_id == telegram_id)
            )
            user = result.scalar_one_or_none()
            if not user:
                return False, 0, 0

            # Сброс счётчика если новый день
            today = datetime.utcnow().date()
            if user.checks_reset_date is None or user.checks_reset_date.date() < today:
                user.checks_today = 0
                user.checks_reset_date = datetime.utcnow()

            plan = user.active_plan
            limits = PlanLimits.get(plan)
            max_checks = limits["checks_per_day"]

            if user.checks_today >= max_checks:
                return False, user.checks_today, max_checks

            user.checks_today += 1
            await session.commit()
            return True, user.checks_today, max_checks

    async def activate_plan(self, telegram_id: int, plan: str, days: int = 30):
        async with self.session_factory() as session:
            result = await session.execute(
                select(User).where(User.telegram_id == telegram_id)
            )
            user = result.scalar_one_or_none()
            if user:
                user.plan = plan
                user.plan_expires_at = datetime.utcnow() + timedelta(days=days)
                await session.commit()

    async def get_total_users(self) -> int:
        async with self.session_factory() as session:
            result = await session.execute(select(func.count(User.id)))
            return result.scalar() or 0

    # ==================== PRODUCTS ====================

    async def get_or_create_product(
        self, url: str, marketplace: str, external_id: str = None
    ) -> Product:
        async with self.session_factory() as session:
            # Поиск по external_id и marketplace
            if external_id:
                result = await session.execute(
                    select(Product).where(
                        Product.marketplace == marketplace,
                        Product.external_id == external_id
                    )
                )
                product = result.scalar_one_or_none()
                if product:
                    return product

            # Поиск по URL
            result = await session.execute(
                select(Product).where(Product.url == url)
            )
            product = result.scalar_one_or_none()

            if not product:
                product = Product(
                    url=url,
                    marketplace=marketplace,
                    external_id=external_id,
                )
                session.add(product)
                await session.commit()
                await session.refresh(product)

            return product

    async def update_product(self, product_id: int, **kwargs):
        async with self.session_factory() as session:
            await session.execute(
                update(Product).where(Product.id == product_id).values(**kwargs)
            )
            await session.commit()

    async def get_product(self, product_id: int) -> Optional[Product]:
        async with self.session_factory() as session:
            result = await session.execute(
                select(Product).where(Product.id == product_id)
            )
            return result.scalar_one_or_none()

    # ==================== PRICE RECORDS ====================

    async def add_price_record(
        self, product_id: int, price: float,
        original_price: float = None, discount_percent: float = None
    ):
        async with self.session_factory() as session:
            record = PriceRecord(
                product_id=product_id,
                price=price,
                original_price=original_price,
                discount_percent=discount_percent,
            )
            session.add(record)
            await session.commit()

    async def get_price_history(
        self, product_id: int, days: int = 365
    ) -> list[PriceRecord]:
        async with self.session_factory() as session:
            since = datetime.utcnow() - timedelta(days=days)
            result = await session.execute(
                select(PriceRecord)
                .where(
                    PriceRecord.product_id == product_id,
                    PriceRecord.recorded_at >= since
                )
                .order_by(PriceRecord.recorded_at.asc())
            )
            return list(result.scalars().all())

    # ==================== MONITORING ====================

    async def add_monitor(
        self, user_id: int, product_id: int,
        target_price: float = None
    ) -> tuple[bool, str]:
        """Returns (success, message)"""
        from config import PlanLimits

        async with self.session_factory() as session:
            # Get user
            result = await session.execute(
                select(User).where(User.id == user_id)
            )
            user = result.scalar_one_or_none()
            if not user:
                return False, "Пользователь не найден"

            plan = user.active_plan
            limits = PlanLimits.get(plan)
            max_items = limits["monitor_items"]

            if max_items == 0:
                return False, "Мониторинг недоступен на бесплатном плане"

            # Count current monitors
            result = await session.execute(
                select(func.count(MonitoredProduct.id)).where(
                    MonitoredProduct.user_id == user_id,
                    MonitoredProduct.is_active == True
                )
            )
            current_count = result.scalar() or 0

            if current_count >= max_items:
                return False, f"Достигнут лимит мониторинга ({max_items} товаров)"

            # Check if already monitoring
            result = await session.execute(
                select(MonitoredProduct).where(
                    MonitoredProduct.user_id == user_id,
                    MonitoredProduct.product_id == product_id,
                )
            )
            existing = result.scalar_one_or_none()

            if existing:
                existing.is_active = True
                existing.target_price = target_price
                await session.commit()
                return True, "Мониторинг обновлён"

            monitor = MonitoredProduct(
                user_id=user_id,
                product_id=product_id,
                target_price=target_price,
            )
            session.add(monitor)
            await session.commit()
            return True, "Товар добавлен в мониторинг"

    async def get_user_monitors(self, telegram_id: int) -> list[dict]:
        async with self.session_factory() as session:
            result = await session.execute(
                select(User).where(User.telegram_id == telegram_id)
            )
            user = result.scalar_one_or_none()
            if not user:
                return []

            result = await session.execute(
                select(MonitoredProduct, Product)
                .join(Product, MonitoredProduct.product_id == Product.id)
                .where(
                    MonitoredProduct.user_id == user.id,
                    MonitoredProduct.is_active == True
                )
            )
            rows = result.all()
            return [
                {
                    "monitor": m,
                    "product": p
                }
                for m, p in rows
            ]

    async def remove_monitor(self, user_id: int, product_id: int):
        async with self.session_factory() as session:
            await session.execute(
                update(MonitoredProduct)
                .where(
                    MonitoredProduct.user_id == user_id,
                    MonitoredProduct.product_id == product_id
                )
                .values(is_active=False)
            )
            await session.commit()

    async def get_all_active_monitors(self) -> list[dict]:
        async with self.session_factory() as session:
            result = await session.execute(
                select(MonitoredProduct, Product, User)
                .join(Product, MonitoredProduct.product_id == Product.id)
                .join(User, MonitoredProduct.user_id == User.id)
                .where(MonitoredProduct.is_active == True)
            )
            return [
                {"monitor": m, "product": p, "user": u}
                for m, p, u in result.all()
            ]

    async def update_monitor_notified(self, monitor_id: int, price: float):
        async with self.session_factory() as session:
            await session.execute(
                update(MonitoredProduct)
                .where(MonitoredProduct.id == monitor_id)
                .values(last_notified_price=price)
            )
            await session.commit()

    # ==================== PAYMENTS ====================

    async def create_payment(
        self, user_id: int, plan: str, amount: float,
        yookassa_id: str, payment_url: str
    ) -> Payment:
        async with self.session_factory() as session:
            # Получаем user по telegram_id
            result = await session.execute(
                select(User).where(User.telegram_id == user_id)
            )
            user = result.scalar_one_or_none()
            if not user:
                return None

            payment = Payment(
                user_id=user.id,
                plan=plan,
                amount=amount,
                yookassa_id=yookassa_id,
                payment_url=payment_url,
            )
            session.add(payment)
            await session.commit()
            await session.refresh(payment)
            return payment

    async def complete_payment(self, yookassa_id: str) -> Optional[Payment]:
        async with self.session_factory() as session:
            result = await session.execute(
                select(Payment).where(Payment.yookassa_id == yookassa_id)
            )
            payment = result.scalar_one_or_none()
            if not payment:
                return None

            payment.status = "succeeded"
            payment.paid_at = datetime.utcnow()

            # Activate plan for user
            result = await session.execute(
                select(User).where(User.id == payment.user_id)
            )
            user = result.scalar_one_or_none()
            if user:
                user.plan = payment.plan
                user.plan_expires_at = datetime.utcnow() + timedelta(days=30)

            await session.commit()
            return payment

    async def get_payment_by_yookassa_id(self, yookassa_id: str) -> Optional[Payment]:
        async with self.session_factory() as session:
            result = await session.execute(
                select(Payment).where(Payment.yookassa_id == yookassa_id)
            )
            return result.scalar_one_or_none()


# Singleton
_db: Optional[Database] = None


async def get_db() -> Database:
    global _db
    if _db is None:
        _db = Database()
        await _db.init()
    return _db