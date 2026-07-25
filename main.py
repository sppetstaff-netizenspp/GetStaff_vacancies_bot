import asyncio
import json
import logging
import os
from datetime import datetime
from aiohttp import web
import pandas as pd

from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    ReplyKeyboardRemove,
)

# ----------------- 1. НАСТРОЙКИ -----------------
BOT_TOKEN = "829/492499:AAFl01-G7eYXGK4nmAUB1nuVKfN18hhBg9w"
PUBLIC_CHANNEL_ID = -1002265325769
ADMIN_CHAT_ID = 841445348

# Ссылка на вашу Гугл-таблицу (экспорт в CSV)
SPREADSHEET_ID = "1Tb7iR-if_ySEfyrd_I_TXGm7FUhpFG9rrFj4cib6Dg"
SHEET_GID = "0"
GOOGLE_SHEET_URL = f"https://docs.google.com/spreadsheets/d/{SPREADSHEET_ID}/export?format=csv&gid={SHEET_GID}"

# Инициализация бота
storage = MemoryStorage()
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=storage)
router = Router()
dp.include_router(router)

logging.basicConfig(level=logging.INFO)


# ----------------- 2. ВЕБ-СЕРВЕР (ДЛЯ RENDER) -----------------
async def web_server():
    app = web.Application()
    app.router.add_get("/", lambda r: web.Response(text="Bot is running!"))
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get("PORT", 8080))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()


# ----------------- 3. ЗАПУСК -----------------
async def main():
    # Запускаем фоновый веб-сервер
    await web_server()
    logging.info("Веб-сервер запущен, начинаем polling бота...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
