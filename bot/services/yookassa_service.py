import uuid
from typing import Optional, Tuple
from yookassa import Configuration, Payment as YKPayment
from config import config

# Init YooKassa
Configuration.account_id = config.yookassa.shop_id
Configuration.secret_key = config.yookassa.secret_key

PLAN_PRICES = {
    "PRO": {
        "amount": "490.00",
        "description": "PriceGhost PRO — 1 месяц",
    },
    "PREMIUM": {
        "amount": "990.00",
        "description": "PriceGhost PREMIUM — 1 месяц",
    },
}


async def create_payment(
    plan: str, telegram_id: int
) -> Tuple[Optional[str], Optional[str]]:
    """
    Создаёт платёж в ЮKassa.
    Returns: (payment_id, confirmation_url)
    """
    if plan not in PLAN_PRICES:
        return None, None

    plan_info = PLAN_PRICES[plan]
    idempotence_key = str(uuid.uuid4())

    try:
        payment = YKPayment.create(
            {
                "amount": {
                    "value": plan_info["amount"],
                    "currency": "RUB",
                },
                "confirmation": {
                    "type": "redirect",
                    "return_url": f"https://t.me/PriceGhostBot?start=paid_{plan.lower()}",
                },
                "capture": True,
                "description": plan_info["description"],
                "metadata": {
                    "telegram_id": str(telegram_id),
                    "plan": plan,
                },
            },
            idempotence_key,
        )
        return payment.id, payment.confirmation.confirmation_url
    except Exception as e:
        print(f"YooKassa error: {e}")
        return None, None


async def check_payment_status(payment_id: str) -> Optional[str]:
    """Проверяет статус платежа. Returns: status string"""
    try:
        payment = YKPayment.find_one(payment_id)
        return payment.status
    except Exception as e:
        print(f"YooKassa check error: {e}")
        return None