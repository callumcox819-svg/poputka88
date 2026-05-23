"""Главное меню настроек — как в happy88."""

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def settings_menu_kb(flags: dict[str, bool]) -> InlineKeyboardMarkup:
    def dot(on: bool, label: str) -> str:
        return ("🟢 " if on else "🔴 ") + label

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="📊 Приоритет\nотправки", callback_data="priority_menu"
                ),
                InlineKeyboardButton(text="🧾 Пресеты", callback_data="presets_menu"),
            ],
            [
                InlineKeyboardButton(
                    text=dot(flags.get("smart_mode", False), "Умный режим"),
                    callback_data="ref_toggle:smart_mode",
                ),
                InlineKeyboardButton(
                    text="📄 Умные пресеты", callback_data="smart_presets_menu"
                ),
            ],
            [
                InlineKeyboardButton(
                    text=dot(flags.get("spoofing", False), "Спуфинг"),
                    callback_data="ref_toggle:spoofing",
                ),
                InlineKeyboardButton(
                    text="👤 Имя для\nспуфинга", callback_data="spoof_name_menu"
                ),
            ],
            [
                InlineKeyboardButton(
                    text=dot(flags.get("block_control", False), "Контроль\nблокировок"),
                    callback_data="ref_toggle:block_control",
                ),
            ],
            [
                InlineKeyboardButton(text="📧 E-mail", callback_data="settings_accounts"),
                InlineKeyboardButton(text="🌐 Прокси", callback_data="settings_proxies"),
            ],
            [
                InlineKeyboardButton(text="🧮 Интервал", callback_data="settings_timings"),
                InlineKeyboardButton(text="🔑 Ключ", callback_data="gag_show:key"),
            ],
            [
                InlineKeyboardButton(text="🧾 Профиль", callback_data="gag_show:profile"),
                InlineKeyboardButton(text="🍀 Скрыть", callback_data="ref_hide"),
            ],
        ]
    )


def back_settings_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="settings_open")]
        ]
    )
