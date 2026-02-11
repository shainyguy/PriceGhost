from typing import Any, Awaitable, Callable, Dict
from aiogram import BaseMiddleware
from aiogram.types import Message, CallbackQuery
from datetime import datetime, timedelta
import asyncio


class ThrottlingMiddleware(BaseMiddleware):
    """Защита от спама"""

    def __init__(self, rate_limit: float = 0.5):
        self.rate_limit = rate_limit
        self.user_last_request: Dict[int, datetime] = {}

    async def __call__(
        self,
        handler: Callable[[Message, Dict[str, Any]], Awaitable[Any]],
        event: Message | CallbackQuery,
        data: Dict[str, Any],
    ) -> Any:
        user_id = event.from_user.id if event.from_user else 0

        now = datetime.utcnow()
        last = self.user_last_request.get(user_id)

        if last and (now - last).total_seconds() < self.rate_limit:
            if isinstance(event, CallbackQuery):
                await event.answer("⏳ Подождите немного...", show_alert=False)
            return

        self.user_last_request[user_id] = now
        return await handler(event, data)