from typing import Any, Awaitable, Callable, Dict

from aiogram import BaseMiddleware
from aiogram.types import Message, TelegramObject

from config import Settings


class AdminOnlyMiddleware(BaseMiddleware):
    def __init__(self, settings: Settings) -> None:
        self._admin_ids = settings.admin_ids

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        user = getattr(event, "from_user", None)
        if user is None or user.id not in self._admin_ids:
            if isinstance(event, Message):
                await event.answer("Доступ только для администраторов.")
            return None
        return await handler(event, data)
