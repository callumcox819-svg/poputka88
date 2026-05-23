# Telegram Mass Mailer Bot

Telegram-бот для массовой **email**-рассылки через SMTP с корректной MIME-кодировкой.

## Кодировки

| Режим | Когда использовать |
|--------|----------------------|
| **7bit** | Только чистый ASCII, без длинных строк — максимальная совместимость |
| **quoted-printable** | UTF-8, HTML с латиницей — обычно лучший выбор после 7bit |
| **base64** | Тяжёлый Unicode, большие HTML |
| **auto** | Бот сам выбирает оптимальный вариант |

## Быстрый старт

1. Создай бота у [@BotFather](https://t.me/BotFather), скопируй токен.
2. Скопируй `.env.example` → `.env`, заполни `BOT_TOKEN`, `ADMIN_IDS`, SMTP.
3. Установка и запуск:

```bash
cd telegram-mailer-bot
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python bot.py
```

4. В Telegram: `/new` → тема → текст → формат → кодировка → список email → **Запустить**.

## Команды

- `/start` — справка
- `/new` — новая кампания
- `/status 1` — прогресс кампании #1

## Важно

- Рассылка идёт по **email (SMTP)**, не в личку Telegram-пользователям.
- Соблюдай законы и политику провайдера (opt-in, отписка, лимиты).
- `SEND_DELAY_SEC` снижает риск блокировки SMTP.
