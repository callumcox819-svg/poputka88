from aiogram.types import KeyboardButton, ReplyKeyboardMarkup

# Тексты reply-кнопок (как в happy88)
MAIN_MENU_TEXTS: frozenset[str] = frozenset(
    {
        "⚙️ Настройки",
        "Настройки",
        "⚡ Быстрое добавление",
        "⚡ Быстрое добавление (Gmail)",
        "▶️ Запустить рассылку",
        "⏹ Остановить рассылку",
        "⏹ Стоп рассылка",
        "/stop",
        "/stopsend",
        "📊 Статус рассылки",
        "🧪 Тест маил",
        "👑 Админ-панель",
        "🔥 Админ-панель",
        "/admin",
    }
)

BTN_SETTINGS = "⚙️ Настройки"
BTN_QUICK_ADD = "⚡ Быстрое добавление"
BTN_START_MAIL = "▶️ Запустить рассылку"
BTN_STOP_MAIL = "⏹ Остановить рассылку"
BTN_STATUS = "📊 Статус рассылки"
BTN_TEST_MAIL = "🧪 Тест маил"

# Для FSM: не перехватывать как ввод
MENU_BUTTONS = MAIN_MENU_TEXTS


def is_main_menu_text(text: str | None) -> bool:
    t = (text or "").strip()
    if t in MAIN_MENU_TEXTS:
        return True
    tl = t.casefold().replace("\ufe0f", "")
    return "настройки" in tl


async def main_menu_kb_for(telegram_id: int) -> ReplyKeyboardMarkup:
    from services.bot_roles import user_is_admin

    return main_keyboard(show_admin=await user_is_admin(telegram_id))


def main_keyboard(*, show_admin: bool = False) -> ReplyKeyboardMarkup:
    rows = [
        [KeyboardButton(text=BTN_SETTINGS)],
        [KeyboardButton(text=BTN_QUICK_ADD)],
        [
            KeyboardButton(text=BTN_START_MAIL),
            KeyboardButton(text=BTN_STOP_MAIL),
        ],
        [KeyboardButton(text=BTN_STATUS)],
        [KeyboardButton(text=BTN_TEST_MAIL)],
    ]
    if show_admin:
        rows.append([KeyboardButton(text="👑 Админ-панель")])
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)
