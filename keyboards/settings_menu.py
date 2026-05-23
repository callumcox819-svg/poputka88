from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def settings_inline() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📬 SMTP-аккаунты", callback_data="set:accounts")],
            [InlineKeyboardButton(text="⏱ Задержка между письмами", callback_data="set:delay")],
            [InlineKeyboardButton(text="📥 IMAP — входящие", callback_data="set:imap")],
            [InlineKeyboardButton(text="◀️ Закрыть", callback_data="set:close")],
        ]
    )
