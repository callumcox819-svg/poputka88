"""Диагностика слэш-команд: python scripts/diag_commands.py"""

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import aiohttp
from aiogram import Bot
from aiogram.types import MenuButtonCommands

from config import load_settings
from services.bot_commands import BOT_COMMANDS, register_bot_commands


async def raw_api(token: str, method: str, **params) -> dict:
    url = f"https://api.telegram.org/bot{token}/{method}"
    async with aiohttp.ClientSession() as session:
        async with session.post(url, json=params) as resp:
            return await resp.json()


async def main() -> None:
    settings = load_settings()
    token = settings.bot_token
    bot = Bot(token=token)

    print("=== BEFORE ===")
    for lang in ("", "ru", "en"):
        r = await raw_api(
            token,
            "getMyCommands",
            scope={"type": "default"},
            language_code=lang if lang else None,
        )
        cmds = r.get("result", [])
        print(f"default lang={lang or '∅'}: {[c['command'] for c in cmds]}")

    print("\n=== REGISTER ===")
    await register_bot_commands(bot)
    await bot.set_chat_menu_button(menu_button=MenuButtonCommands())

    print("\n=== AFTER (aiogram get_my_commands) ===")
    for lang in (None, "ru", "en"):
        cmds = await bot.get_my_commands(language_code=lang)
        print(f"lang={lang}: {[c.command for c in cmds]}")

    print("\n=== AFTER (raw API) ===")
    for lang in ("", "ru", "en"):
        payload = {"scope": {"type": "default"}}
        if lang:
            payload["language_code"] = lang
        r = await raw_api(token, "getMyCommands", **payload)
        print(f"default lang={lang or '∅'}: {json.dumps(r.get('result'), ensure_ascii=False)}")

    menu = await raw_api(token, "getChatMenuButton")
    print("\nmenu_button:", json.dumps(menu.get("result"), ensure_ascii=False))

    await bot.session.close()
    print("\nDone.")


if __name__ == "__main__":
    asyncio.run(main())
