from aiogram.types import KeyboardButton, ReplyKeyboardMarkup

BTN_SETTINGS = "⚙️ Настройки"
BTN_START_MAIL = "▶️ Запустить рассылку"
BTN_QUICK_ADD = "➕ Быстрое добавление"
BTN_STOP_MAIL = "⏹ Стоп рассылка"
BTN_CHECK_EMAILS = "✅ Проверка почт"

MENU_BUTTONS = frozenset({
    BTN_SETTINGS,
    BTN_START_MAIL,
    BTN_QUICK_ADD,
    BTN_STOP_MAIL,
    BTN_CHECK_EMAILS,
})


def main_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=BTN_START_MAIL), KeyboardButton(text=BTN_STOP_MAIL)],
            [KeyboardButton(text=BTN_QUICK_ADD), KeyboardButton(text=BTN_CHECK_EMAILS)],
            [KeyboardButton(text=BTN_SETTINGS)],
        ],
        resize_keyboard=True,
    )
