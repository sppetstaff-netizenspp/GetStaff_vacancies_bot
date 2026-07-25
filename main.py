import asyncio
from datetime import datetime
import hashlib
import json
import logging
import os
from aiohttp import web
import pandas as pd

from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
)

# ----------------- 1. НАСТРОЙКИ И ТОКЕНЫ -----------------
BOT_TOKEN = "829/492499:AAFl01-G7eYXGK4nmAUB1nuVKfN18hhBg9w"
PUBLIC_CHANNEL_ID = -1002265325769
ADMIN_CHAT_ID = 841445348

# Настройки Google Таблицы
SPREADSHEET_ID = "1Tb7iR-if_ySEfyrd_I_TXGm7FUhpFG9rrFj4cib6Dg"
# Примечание: GID листа можно посмотреть в адресе браузера при открытии нужной вкладки (например, gid=0)
SHEET_GID = "0"
GOOGLE_SHEET_URL = f"https://docs.google.com/spreadsheets/d/{SPREADSHEET_ID}/export?format=csv&gid={SHEET_GID}"

HISTORY_FILE = "published_history.json"

# Состояния FSM для сбора откликов
class ApplyFSM(StatesGroup):
    waiting_for_name = State()
    waiting_for_phone = State()

# Инициализация бота
storage = MemoryStorage()
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=storage)
router = Router()
dp.include_router(router)

logging.basicConfig(level=logging.INFO)


# ----------------- 2. ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ -----------------
def load_history() -> dict:
    """Загрузка истории публикаций из json."""
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logging.error(f"Ошибка чтения истории: {e}")
    return {}


def save_history(history: dict):
    """Сохранение истории публикаций в json."""
    try:
        with open(HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(history, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logging.error(f"Ошибка сохранения истории: {e}")


def compute_row_hash(row: pd.Series) -> str:
    """Генерация слепка (хэша) строки для отслеживания изменений."""
    row_str = "|".join([str(val) for val in row.values if pd.notna(val)])
    return hashlib.md5(row_str.encode("utf-8")).hexdigest()


def fetch_vacancies_df() -> pd.DataFrame:
    """Загрузка данных из Google Таблицы."""
    try:
        df = pd.read_csv(GOOGLE_SHEET_URL)
        df.columns = df.columns.str.strip()
        return df
    except Exception as e:
        logging.error(f"Ошибка загрузки Google Таблицы: {e}")
        return pd.DataFrame()


# ----------------- 3. ЛОГИКА ПУБЛИКАЦИИ В КАНАЛ -----------------
async def publish_vacancies() -> int:
    """Проверка таблицы и публикация новых/измененных вакансий."""
    df = fetch_vacancies_df()
    if df.empty:
        logging.warning("Таблица вакансий пуста или недоступна.")
        return 0

    history = load_history()
    today_str = datetime.now().strftime("%Y-%m-%d")
    published_count = 0

    bot_info = await bot.get_me()
    bot_username = bot_info.username

    for idx, row in df.iterrows():
        # Проверяем флаг 'Публикация'
        pub_flag = row.get("Публикация")
        if pd.isna(pub_flag):
            continue
        
        try:
            if float(pub_flag) != 1.0:
                continue
        except ValueError:
            if str(pub_flag).strip().upper() not in ["1", "TRUE", "ДА"]:
                continue

        vac_key = f"vac_{idx}"
        curr_hash = compute_row_hash(row)

        # Проверка истории: выкладывали ли уже сегодня
        if vac_key in history:
            prev_data = history[vac_key]
            if prev_data.get("date") == today_str and prev_data.get("hash") == curr_hash:
                continue  # Пропускаем, если уже выложено сегодня и без изменений

        # Формируем короткий анонс для канала
        project = str(row.get("Проект", "")).strip() if pd.notna(row.get("Проект")) else ""
        company = str(row.get("Компания", "")).strip() if pd.notna(row.get("Компания")) else "GetStaff"
        title = str(row.get("Должность", "")).strip() if pd.notna(row.get("Должность")) else "Вакансия"
        city = str(row.get("Город", "")).strip() if pd.notna(row.get("Город")) else ""
        metro = str(row.get("Метро", "")).strip() if pd.notna(row.get("Метро")) else ""
        payment = str(row.get("Оплата", "")).strip() if pd.notna(row.get("Оплата")) else ""
        rate = str(row.get("Ставка/час/смена/месяц", "")).strip() if pd.notna(row.get("Ставка/час/смена/месяц")) else ""

        header = f"🏢 <b>{project or company}</b>\n"
        body = f"📌 <b>Вакансия:</b> {title}\n"

        loc_parts = [p for p in [city, f"м. {metro}" if metro else ""] if p]
        if loc_parts:
            body += f"📍 <b>Локация:</b> {', '.join(loc_parts)}\n"

        rate_parts = [p for p in [rate, f"({payment})" if payment else ""] if p]
        if rate_parts:
            body += f"💰 <b>Ставка:</b> {' '.join(rate_parts)}\n"

        post_text = f"{header}{body}\n👇 <i>Нажмите кнопку ниже, чтобы узнать подробности и откликнуться:</i>"

        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="📄 Читать полностью и откликнуться",
                        url=f"https://t.me/{bot_username}?start={vac_key}",
                    )
                ]
            ]
        )

        try:
            await bot.send_message(
                chat_id=PUBLIC_CHANNEL_ID,
                text=post_text,
                reply_markup=kb,
                parse_mode="HTML",
            )
            history[vac_key] = {"date": today_str, "hash": curr_hash}
            published_count += 1
            await asyncio.sleep(1.5)  # Задержка между постами
        except Exception as e:
            logging.error(f"Ошибка публикации вакансии {vac_key}: {e}")

    save_history(history)
    return published_count


# ----------------- 4. ХЕНДЛЕРЫ И ДИАЛОГИ В БОТЕ -----------------
@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    args = message.text.split()
    # Если переход из канала по кнопке "Читать полностью"
    if len(args) > 1 and args[1].startswith("vac_"):
        vac_id = args[1].replace("vac_", "")
        await show_vacancy_details(message, vac_id)
        return

    # Главное меню для администратора
    if message.from_user.id == ADMIN_CHAT_ID:
        kb = ReplyKeyboardMarkup(
            keyboard=[[KeyboardButton(text="🚀 Отправить невыложенные вакансии")]],
            resize_keyboard=True,
        )
        await message.answer("Привет! Бот автопубликации запущен и готов к работе.", reply_markup=kb)
    else:
        await message.answer("Здравствуйте! Выберите интересующую вас вакансию в нашем Telegram-канале.")


async def show_vacancy_details(message: Message, vac_id: str):
    """Отображение подробной карточки вакансии в ЛС соискателю."""
    df = fetch_vacancies_df()
    if df.empty:
        await message.answer("К сожалению, не удалось загрузить данные по вакансии.")
        return

    try:
        idx = int(vac_id)
        if idx not in df.index:
            await message.answer("Вакансия не найдена или была удалена.")
            return
        row = df.loc[idx]
    except Exception:
        await message.answer("Некорректная ссылка на вакансию.")
        return

    company = str(row.get("Компания", "")).strip() if pd.notna(row.get("Компания")) else "GetStaff"
    project = str(row.get("Проект", "")).strip() if pd.notna(row.get("Проект")) else ""
    city = str(row.get("Город", "")).strip() if pd.notna(row.get("Город")) else ""
    metro = str(row.get("Метро", "")).strip() if pd.notna(row.get("Метро")) else ""
    address = str(row.get("Адрес места работы", "")).strip() if pd.notna(row.get("Адрес места работы")) else ""
    citizenship = str(row.get("Гражданство", "")).strip() if pd.notna(row.get("Гражданство")) else ""
    age = str(row.get("Возраст", "")).strip() if pd.notna(row.get("Возраст")) else ""
    title = str(row.get("Должность", "")).strip() if pd.notna(row.get("Должность")) else "Вакансия"
    duties = str(row.get("Обязанности/требования", "")).strip() if pd.notna(row.get("Обязанности/требования")) else ""
    schedule = str(row.get("График", "")).strip() if pd.notna(row.get("График")) else ""
    work_time = str(row.get("Время", "")).strip() if pd.notna(row.get("Время")) else ""
    payment = str(row.get("Оплата", "")).strip() if pd.notna(row.get("Оплата")) else ""
    rate = str(row.get("Ставка/час/смена/месяц", "")).strip() if pd.notna(row.get("Ставка/час/смена/месяц")) else ""

    text = f"📌 <b>{title}</b>"
    if project:
        text += f" ({project})"
    text += f"\n🏢 <b>Компания:</b> {company}\n"

    locs = [p for p in [city, metro, address] if p]
    if locs:
        text += f"📍 <b>Адрес / Локация:</b> {', '.join(locs)}\n"

    reqs = []
    if citizenship:
        reqs.append(f"Гражданство: {citizenship}")
    if age:
        reqs.append(f"Возраст: {age}")
    if reqs:
        text += f"👥 <b>Требования:</b> {'; '.join(reqs)}\n"

    times = [p for p in [schedule, work_time] if p]
    if times:
        text += f"⏰ <b>График / Время:</b> {', '.join(times)}\n"

    rates = [p for p in [rate, f"({payment})" if payment else ""] if p]
    if rates:
        text += f"💰 <b>Оплата:</b> {' '.join(rates)}\n"

    if duties:
        text += f"\n📝 <b>Обязанности и условия:</b>\n{duties}"

    kb = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="✅ Откликнуться на вакансию", callback_data=f"apply_{idx}")]]
    )
    await message.answer(text, reply_markup=kb, parse_mode="HTML")


# ----------------- 5. СБОР ОТКЛИКА (ИМЯ И ТЕЛЕФОН) -----------------
@router.callback_query(F.data.startswith("apply_"))
async def process_apply_start(callback: CallbackQuery, state: FSMContext):
    vac_id = callback.data.replace("apply_", "")
    await state.update_data(vac_id=vac_id)
    await state.set_state(ApplyFSM.waiting_for_name)

    await callback.message.answer(
        "📝 <b>Оформление отклика</b>\n\nПожалуйста, введите ваше <b>Имя</b>:",
        reply_markup=ReplyKeyboardRemove(),
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(ApplyFSM.waiting_for_name)
async def process_name(message: Message, state: FSMContext):
    name = message.text.strip() if message.text else ""
    if not name:
        await message.answer("Пожалуйста, введите ваше имя текстовым сообщением.")
        return

    await state.update_data(applicant_name=name)
    await state.set_state(ApplyFSM.waiting_for_phone)

    kb = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="📱 Поделиться номером телефона", request_contact=True)]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )
    await message.answer(
        "Отлично! Теперь отправьте ваш <b>номер телефона</b> (нажмите кнопку ниже или введите номер вручную):",
        reply_markup=kb,
        parse_mode="HTML",
    )


@router.message(ApplyFSM.waiting_for_phone)
async def process_phone(message: Message, state: FSMContext):
    phone = ""
    if message.contact:
        phone = message.contact.phone_number
    elif message.text:
        phone = message.text.strip()

    if not phone:
        await message.answer("Пожалуйста, отправьте контакт по кнопке или укажите номер вручную.")
        return

    data = await state.get_data()
    vac_id = data.get("vac_id")
    applicant_name = data.get("applicant_name")

    # Получаем информацию о вакансии для менеджера
    df = fetch_vacancies_df()
    vac_title = "Вакансия"
    project = ""
    if not df.empty and int(vac_id) in df.index:
        row = df.loc[int(vac_id)]
        vac_title = str(row.get("Должность", "Вакансия")).strip()
        project = str(row.get("Проект", "")).strip()

    username_str = f"@{message.from_user.username}" if message.from_user.username else "не указан"

    lead_text = (
        f"🔔 <b>НОВЫЙ ОТКЛИК НА ВАКАНСИЮ!</b>\n\n"
        f"📌 <b>Вакансия:</b> {vac_title} {f'({project})' if project else ''}\n"
        f"🆔 <b>ID Строки:</b> {vac_id}\n\n"
        f"👤 <b>Имя соискателя:</b> {applicant_name}\n"
        f"📞 <b>Телефон:</b> {phone}\n"
        f"💬 <b>Telegram:</b> {username_str} (ID: <code>{message.from_user.id}</code>)"
    )

    # Отправляем заявку администратору
    try:
        await bot.send_message(chat_id=ADMIN_CHAT_ID, text=lead_text, parse_mode="HTML")
    except Exception as e:
        logging.error(f"Ошибка отправки отклика менеджеру: {e}")

    await state.clear()
    await message.answer(
        "<b>Спасибо! Ваша заявка успешно принята.</b>\nНаш менеджер свяжется с вами в ближайшее время.",
        reply_markup=ReplyKeyboardRemove(),
        parse_mode="HTML",
    )


# ----------------- 6. РУЧНОЙ ЗАПУСК И ПЛАНИРОВЩИК -----------------
@router.message(F.text == "🚀 Отправить невыложенные вакансии")
@router.message(Command("publish"))
async def handle_manual_publish(message: Message):
    if message.from_user.id != ADMIN_CHAT_ID:
        return
    await message.answer("🔄 Проверяю Google Таблицу на наличие новых или измененных вакансий...")
    count = await publish_vacancies()
    if count > 0:
        await message.answer(f"✅ Успешно выложено / обновлено вакансий: <b>{count}</b>", parse_mode="HTML")
    else:
        await message.answer("ℹ️ Все отмеченные вакансии уже выложены за сегодня и не имели корректировок.")


async def periodic_checker():
    """Фоновая проверка каждые 30 минут."""
    while True:
        try:
            await asyncio.sleep(1800)
            logging.info("Фоновый запуск проверки вакансий...")
            count = await publish_vacancies()
            if count > 0:
                logging.info(f"Автоматически отправлено вакансий: {count}")
        except Exception as e:
            logging.error(f"Ошибка в фоновой проверке: {e}")


# ----------------- 7. ВЕБ-СЕРВЕР И ЗАПУСК -----------------
async def web_server():
    app = web.Application()
    app.router.add_get("/", lambda r: web.Response(text="Bot is running!"))
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get("PORT", 8080))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()


async def main():
    await web_server()
    logging.info("Веб-сервер запущен.")
    asyncio.create_task(periodic_checker())
    logging.info("Polling бота запущен...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
