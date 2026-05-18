
import asyncio
import logging
import html
import os
import random
import re
import string
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    InlineKeyboardMarkup, InlineKeyboardButton,
    LabeledPrice, FSInputFile
)
import json
from datetime import datetime
from urllib.parse import quote


BOT_TOKEN = os.environ.get("BOT_TOKEN")
ADMIN_ID = int(os.environ.get("ADMIN_ID", "0"))
DEALS_CHANNEL_ID = os.environ.get("DEALS_CHANNEL_ID")

# Base directory (project root)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# Log buffer for messages emitted before the event loop starts
LOG_BUFFER: list[str] = []


class TelegramLogHandler(logging.Handler):
    """Logging handler that forwards log records to admin via Telegram.

    Records emitted before the asyncio loop starts are buffered in `LOG_BUFFER`
    and flushed in `main()`.
    """

    def __init__(self, bot_instance, admin_id):
        super().__init__()
        self.bot = bot_instance
        self.admin_id = admin_id

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = self.format(record)
            text = f"<pre>{html.escape(msg)}</pre>"
            try:
                loop = asyncio.get_running_loop()
                # schedule send on the running loop
                loop.create_task(self.bot.send_message(self.admin_id, text, parse_mode="HTML"))
            except RuntimeError:
                # no running loop yet — buffer the message
                LOG_BUFFER.append(text)
        except Exception:
            self.handleError(record)


# Configure logging: console + Telegram channel
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.INFO)
console_handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s: %(message)s'))

root_logger = logging.getLogger()
root_logger.setLevel(logging.INFO)
root_logger.handlers = []
root_logger.addHandler(console_handler)

# Add Telegram log handler for sending important logs to the log channel
class ChannelLogHandler(logging.Handler):
    """Sends log messages to the configured Telegram channel."""
    def __init__(self, bot_instance, channel_getter):
        super().__init__()
        self.bot = bot_instance
        self.channel_getter = channel_getter
        self.setLevel(logging.WARNING)

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = self.format(record)
            channel_id = self.channel_getter()
            if not channel_id:
                return
            text = f"<pre>{html.escape(msg)}</pre>"
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(self._send(channel_id, text))
            except RuntimeError:
                LOG_BUFFER.append(text)
        except Exception:
            self.handleError(record)

    async def _send(self, channel_id, text):
        try:
            cid = int(channel_id) if channel_id.lstrip('-').isdigit() else channel_id
            await self.bot.send_message(cid, text, parse_mode="HTML")
        except Exception:
            pass

DEALS_FILE = "deals.json"
TRUSTED_FILE = "trusted.json"
WALLETS_FILE = "wallets.json"
LOG_CHANNEL_FILE = "log_channel.json"


def load_trusted():
    if os.path.exists(TRUSTED_FILE):
        with open(TRUSTED_FILE, "r", encoding="utf-8") as f:
            return set(json.load(f))
    return set()


def save_trusted(trusted: set):
    with open(TRUSTED_FILE, "w", encoding="utf-8") as f:
        json.dump(list(trusted), f)


def is_authorized(user_id: int) -> bool:
    """Проверяет, является ли пользователь админом или доверенным."""
    if user_id == ADMIN_ID:
        return True
    return user_id in load_trusted()


def grant_payment_access(user_id: int) -> bool:
    if user_id == ADMIN_ID:
        return False
    trusted = load_trusted()
    already_trusted = user_id in trusted
    trusted.add(user_id)
    save_trusted(trusted)
    return not already_trusted

PAYMENT_METHODS = {
    "stars":   {"name": "⭐ Звёзды",      "emoji": "⭐"},
    "ton":     {"name": "💎 TON",          "emoji": "💎"},
    "usdt":    {"name": "💵 USDT (TON)",   "emoji": "💵"},
    "cardsbp": {"name": "💳 Карта/СБП",   "emoji": "💳"},
}

SUPPORT_USERNAME = "@EscrowTrusty"
ESCROW_USERNAME = "@EscrowTrusty"
BOT_NAME = "trustlyDeal"

# Визуальный разделитель
SEP = "━━━━━━━━━━━━━━━━━━━━"



def format_payment_amount(deal):
    method = deal.get("payment_method", "stars")
    price = deal.get("price", 0)
    if method == "stars":
        return f"{price} STARS"
    if method == "ton":
        return f"{price} TON"
    if method == "usdt":
        return f"{price} USDT (TON)"
    if method == "cardsbp":
        return f"{price} Карта/СБП"
    return f"{price} {PAYMENT_METHODS.get(method, {}).get('name', method)}"


def created_order_text(deal, deal_link):
    return (
        "<blockquote>✅ <b>Ордер создан</b></blockquote>\n\n"
        f"<blockquote>💰 Сумма: {format_payment_amount(deal)}</blockquote>\n\n"
        f"<blockquote>🧾 Описание: <code>{html.escape(str(deal['item']))}</code></blockquote>\n\n"
        f"<blockquote>🔗 Ссылка для покупателя:\n<code>{deal_link}</code></blockquote>\n\n"
        "<blockquote>Отправьте ордер покупателю кнопкой ниже или скопируйте ссылку вручную.</blockquote>\n\n"
        f"<blockquote>🛡 Передача товара выполняется только через менеджера: <b>{ESCROW_USERNAME}</b></blockquote>\n\n"
        "<blockquote>📌 Покупатель оплачивает строго по реквизитам в этом ордере.</blockquote>"
    )


def seller_payment_confirmed_text(deal):
    tag = get_order_tag(deal)
    item = html.escape(str(deal.get("item", "")))
    amount = html.escape(format_payment_amount(deal))

    return (
        f"<blockquote>✅ <b>Ордер #{tag} оплачен</b></blockquote>\n\n"
        f"<blockquote>📦 Товар: <code>{item}</code></blockquote>\n\n"
        f"<blockquote>💰 Сумма: {amount}</blockquote>\n\n"
        f"<blockquote>🛡 Передайте товар только менеджеру: <b>{ESCROW_USERNAME}</b></blockquote>\n\n"
        "<blockquote>⚠️ Не передавайте товар напрямую покупателю. "
        "Если товар будет передан не менеджеру, выплата не будет одобрена.</blockquote>\n\n"
        "<blockquote>После передачи товара менеджеру нажмите кнопку ниже.</blockquote>"
    )


def seller_manager_transfer_confirmed_text(deal):
    tag = get_order_tag(deal)
    item = html.escape(str(deal.get("item", "")))
    amount = html.escape(format_payment_amount(deal))

    return (
        f"<blockquote>📦 <b>Товар передан менеджеру</b></blockquote>\n\n"
        f"<blockquote>🔖 Ордер #{tag}</blockquote>\n\n"
        f"<blockquote>📦 Товар: <code>{item}</code></blockquote>\n\n"
        f"<blockquote>💰 Сумма: {amount}</blockquote>\n\n"
        f"<blockquote>🛡 Менеджер получил товар и передаст его покупателю.</blockquote>\n\n"
        "<blockquote>💸 Оплата будет получена автоматически после завершения передачи.</blockquote>\n\n"
        "<blockquote>⏳ Дополнительных действий от вас не требуется.</blockquote>"
    )


def load_deals():
    if os.path.exists(DEALS_FILE):
        with open(DEALS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_deals(deals):
    with open(DEALS_FILE, "w", encoding="utf-8") as f:
        json.dump(deals, f, ensure_ascii=False, indent=2)


def load_wallets():
    if os.path.exists(WALLETS_FILE):
        with open(WALLETS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_wallets(wallets):
    with open(WALLETS_FILE, "w", encoding="utf-8") as f:
        json.dump(wallets, f, ensure_ascii=False, indent=2)


def get_user_wallets(user_id: int):
    return load_wallets().get(str(user_id), {})


def set_user_wallet(user_id: int, method: str, requisites: str):
    wallets = load_wallets()
    user_wallets = wallets.setdefault(str(user_id), {})
    user_wallets[method] = requisites
    save_wallets(wallets)


def load_log_channel():
    """Загружает ID канала для логов из файла."""
    if os.path.exists(LOG_CHANNEL_FILE):
        with open(LOG_CHANNEL_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data.get("channel_id")
    return None


def save_log_channel(channel_id: str):
    """Сохраняет ID канала для логов в файл."""
    with open(LOG_CHANNEL_FILE, "w", encoding="utf-8") as f:
        json.dump({"channel_id": channel_id}, f)


def delete_user_wallet(user_id: int, method: str):
    wallets = load_wallets()
    user_wallets = wallets.get(str(user_id), {})
    user_wallets.pop(method, None)
    if not user_wallets:
        wallets.pop(str(user_id), None)
    save_wallets(wallets)


def short_wallet(value: str, limit: int = 32):
    value = value.strip()
    if len(value) <= limit:
        return value
    return f"{value[:16]}...{value[-10:]}"


def is_valid_telegram_username(value: str):
    return bool(re.fullmatch(r"@[A-Za-z0-9_]{5,32}", value.strip()))


def is_valid_ton_address(value: str):
    value = value.strip()
    if re.fullmatch(r"[UE]Q[A-Za-z0-9_-]{46}", value):
        return True
    return bool(re.fullmatch(r"[A-Fa-f0-9]{64}", value))


def is_luhn_valid(number: str):
    total = 0
    reverse_digits = list(map(int, reversed(number)))
    for index, digit in enumerate(reverse_digits):
        if index % 2 == 1:
            digit *= 2
            if digit > 9:
                digit -= 9
        total += digit
    return total % 10 == 0


def is_valid_card_or_sbp(value: str):
    digits = re.sub(r"\D", "", value)
    has_card = 13 <= len(digits) <= 19 and is_luhn_valid(digits)
    has_phone = 10 <= len(digits) <= 15 and (
        value.strip().startswith("+") or digits.startswith(("7", "8", "9"))
    )
    return has_card or has_phone


def validate_requisites(method: str, value: str):
    value = (value or "").strip()
    if not value:
        return False, "❌ Реквизиты не должны быть пустыми."

    if method == "stars":
        if is_valid_telegram_username(value):
            return True, ""
        return False, (
            "❌ Укажите Telegram username получателя в формате <code>@username</code>.\n"
            "Username должен быть от 5 до 32 символов: латиница, цифры или подчёркивание."
        )

    if method in ("ton", "usdt"):
        if is_valid_ton_address(value):
            return True, ""
        return False, (
            "❌ Укажите корректный TON-адрес.\n"
            "Обычно он начинается с <code>UQ</code> или <code>EQ</code> и содержит 48 символов."
        )

    if method == "cardsbp":
        if is_valid_card_or_sbp(value):
            return True, ""
        return False, (
            "❌ Укажите реальный номер карты или телефон для СБП.\n"
            "Пример карты: <code>4276 1234 5678 9012</code>\n"
            "Пример СБП: <code>+79991234567 / Сбербанк</code>"
        )

    return True, ""


def get_next_id():
    deals = load_deals()
    return max((int(k) for k in deals.keys()), default=0) + 1


def now():
    return datetime.now().strftime("%d.%m.%Y %H:%M")


STATUS = {
    "created":        "🆕 Создан",
    "pending_pay":    "⏳ Ожидает оплаты",
    "pending_manual": "⏳ Ожидает оплаты",
    "paid":           "✅ Оплачен",
    "shipped":        "📦 Передан менеджеру",
    "confirm_pend":   "💸 Выплата автоматически",
    "completed":      "🎉 Завершён",
    "cancelled":      "❌ Отменён",
}


def gen_hash_id():
    return ''.join(random.choices(string.ascii_lowercase + string.digits, k=10))


def get_order_tag(deal):
    return deal.get("hash_id") or f"ord{deal['id']}"


def find_deal_by_tag(raw_tag: str):
    token = raw_tag.strip().replace("deal_", "", 1).lstrip("#")
    deals = load_deals()

    for key, deal in deals.items():
        if deal.get("hash_id") == token:
            return int(key), deal

    if token.isdigit():
        deal = deals.get(token)
        if deal:
            return int(token), deal

    return None, None


def count_completed(seller_id):
    deals = load_deals()
    return sum(1 for d in deals.values()
               if d.get("seller_id") == seller_id and d.get("status") == "completed")


def deal_info(deal, show_id=True):
    """Compact format used in admin notifications."""
    s = STATUS.get(deal["status"], deal["status"])
    pm = PAYMENT_METHODS.get(deal.get("payment_method"), {})
    tag = get_order_tag(deal)
    lines = []
    if show_id:
        lines.append(f"<blockquote>🔖 <b>Ордер #{tag}</b></blockquote>")
    lines.append(f"<blockquote>📦 Товар: <code>{html.escape(str(deal['item']))}</code></blockquote>")
    if deal.get("payment_method") == "stars":
        lines.append(f"<blockquote>💰 Сумма: {deal['price']} ⭐</blockquote>")
    else:
        lines.append(f"<blockquote>💰 Сумма: {deal['price']} | {pm.get('name', '')}</blockquote>")
    seller = deal.get("seller_username") or "—"
    lines.append(f"<blockquote>👤 Продавец: @{seller}</blockquote>")
    lines.append(f"<blockquote>📊 Статус: {s}</blockquote>")
    lines.append(f"<blockquote>🕐 Создан: {deal['created_at']}</blockquote>")
    if deal.get("requisites"):
        if deal.get("payment_method") == "stars":
            lines.append(f"<blockquote>⭐ Получатель Stars: <code>{html.escape(deal['requisites'])}</code></blockquote>")
        else:
            lines.append(f"<blockquote>💳 Реквизиты: <code>{html.escape(deal['requisites'])}</code></blockquote>")
    return "\n\n".join(lines)


def deal_view(deal, role="buyer"):
    """Blockquote-style message shown to buyer/seller when viewing an order."""
    pm = deal.get("payment_method", "stars")
    tag = get_order_tag(deal)
    seller = deal.get("seller_username") or "—"
    seller_id = deal.get("seller_id", "")
    completed = count_completed(seller_id)
    price = deal["price"]
    item = deal["item"]
    status = STATUS.get(deal["status"], deal["status"])

    lines = [
        f"<blockquote>🔖 <b>Ордер #{tag}</b></blockquote>",
        f"<blockquote>👤 Продавец: @{seller}</blockquote>",
        f"<blockquote>📈 Успешные ордера: {completed}</blockquote>",
    ]

    if role == "buyer":
        lines.append(f"<blockquote>🛍 Вы покупаете: <code>{html.escape(str(item))}</code></blockquote>")
    else:
        lines.append(f"<blockquote>📦 Товар: <code>{html.escape(str(item))}</code></blockquote>")

    if pm == "stars":
        lines.append(f"<blockquote>⭐ Цена: {price} звёзд</blockquote>")
        lines.append(f"<blockquote>💬 Оплата происходит из баланса звёзд Telegram</blockquote>")
    else:
        pm_name = PAYMENT_METHODS.get(pm, {}).get("name", pm)
        lines.append(f"<blockquote>💰 Цена: {price} | {pm_name}</blockquote>")
        if deal.get("requisites"):
            lines.append(f"<blockquote>🏦 Адрес оплаты:</blockquote>")
            lines.append(f"<blockquote><code>{html.escape(deal['requisites'])}</code></blockquote>")
        lines.append(f"<blockquote>📝 Комментарий (memo): {get_order_tag(deal)}</blockquote>")

    lines.append(f"<blockquote>📊 Статус: {status}</blockquote>")
    return "\n\n".join(lines)


def main_menu_kb(user_id=None):
    buttons = [
        [InlineKeyboardButton(text="💼 Кошельки",      callback_data="wallets")],
        [InlineKeyboardButton(text="🔒 Создать ордер",  callback_data="new_deal")],
        [InlineKeyboardButton(text="📋 Мои ордера",     callback_data="my_deals")],
        [InlineKeyboardButton(text="🛡 Безопасность",   callback_data="security")],
        [InlineKeyboardButton(text="Поддержка",      callback_data="support")],
    ]
    if user_id == ADMIN_ID:
        buttons.append([InlineKeyboardButton(text="🛠 Панель админа", callback_data="admin_panel")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def back_btn():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ В меню", callback_data="main_menu")]
    ])


def wallet_prompt(method: str):
    wallet_prompts = {
        "stars": (
            "⭐ <b>Получатель звёзд</b>\n\n"
            "Укажите @username получателя\n\n"
            "<blockquote>⭐ Минимум: 50 звёзд</blockquote>"
        ),
        "ton": (
            "💎 <b>Кошелёк TON</b>\n\n"
            "Введите адрес TON-кошелька получателя\n\n"
            "<blockquote>💡 Пример: UQBxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx</blockquote>"
        ),
        "usdt": (
            "💵 <b>Кошелёк USDT (TON)</b>\n\n"
            "Введите адрес USDT-кошелька получателя (сеть TON)\n\n"
            "<blockquote>💡 Пример: UQBxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx</blockquote>"
        ),
        "cardsbp": (
            "💳 <b>Карта / СБП</b>\n\n"
            "Введите номер карты или телефон для СБП\n\n"
            "<blockquote>💡 Карта: 4276 1234 5678 9012 / Иван И.\n"
            "СБП: +79991234567 / Сбербанк</blockquote>"
        ),
    }
    return wallet_prompts.get(method, "Введите реквизиты для оплаты:")


def wallet_menu_kb(user_id: int):
    user_wallets = get_user_wallets(user_id)
    rows = []
    for method, meta in PAYMENT_METHODS.items():
        saved = user_wallets.get(method)
        label = meta["name"]
        if saved:
            label += " ✅"
        rows.append([InlineKeyboardButton(text=label, callback_data=f"wallet_set_{method}")])
        if saved:
            rows.append([InlineKeyboardButton(
                text=f"🗑 Удалить {meta['name']}",
                callback_data=f"wallet_del_{method}"
            )])
        rows.append([InlineKeyboardButton(text="◀️ В меню", callback_data="main_menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def wallet_menu_text(user_id: int):
    user_wallets = get_user_wallets(user_id)
    lines = [
        "💼 <b>Кошельки</b>",
        "",
        "Здесь можно сохранить реквизиты для быстрых ордеров.",
        "",
    ]
    if user_wallets:
        lines.append("<b>Сохранено:</b>")
        for method, value in user_wallets.items():
            name = PAYMENT_METHODS.get(method, {}).get("name", method)
            lines.append(f"• {name}: <code>{html.escape(short_wallet(value))}</code>")
    else:
        lines.append("<blockquote>Пока нет сохранённых реквизитов.</blockquote>")
    return "\n".join(lines)


async def ask_deal_price(message: types.Message, state: FSMContext):
    await state.set_state(DealCreate.price)
    await message.answer(
        "💰 <b>Сумма ордера</b>\n\n"
        "Введите сумму ордера (только цифры)\n\n"
        "<blockquote>💡 Для Звёзд — количество звёзд\n"
        "Для остальных — сумма в нужной валюте</blockquote>",
        parse_mode="HTML",
        reply_markup=back_btn()
    )


# ==========================================
# FSM
# ==========================================

class DealCreate(StatesGroup):
    pay_method = State()  # 1 — выбор метода оплаты
    wallet     = State()  # 2 — реквизиты / username    
    price      = State()  # 3 — сумма
    item       = State()  # 4 — название товара


class WalletEdit(StatesGroup):
    value = State()


# ==========================================
# /start
# ==========================================

@dp.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    await state.clear()

    args = message.text.split()
    if len(args) > 1 and args[1].startswith("deal_"):
        deal_id, _deal = find_deal_by_tag(args[1])
        if deal_id:
            await show_deal(message, deal_id)
            return

        welcome_photo = FSInputFile(os.path.join(BASE_DIR, "attached_assets", "photo_2026-05-14_15-10-18.jpg"))
    await message.answer_photo(
        photo=welcome_photo,
        caption=f"<blockquote>👋 <b>Добро пожаловать в {BOT_NAME}</b></blockquote>\n\n"
                "<blockquote>🛡 Безопасные ордера с передачей товара через менеджера.</blockquote>\n\n"
                f"<blockquote>📋 Комиссия сервиса: 1%</blockquote>\n\n"
                f"<blockquote>🆘 Поддержка: {SUPPORT_USERNAME}</blockquote>",
        parse_mode="HTML",
        reply_markup=main_menu_kb(message.from_user.id)
    )


# ==========================================
# ПОМОЩЬ
# ==========================================

@dp.callback_query(F.data == "help")
async def cb_help(callback: types.CallbackQuery):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ В меню", callback_data="main_menu")]
    ])
    await callback.message.answer(
        "📖 <b>Как работает гарант-бот:</b>\n\n"
        "<b>Продавец:</b>\n"
        "1. Нажимает ➕ Создать сделку\n"
        "2. Вводит товар, цену, @покупателя\n"
        "3. Выбирает метод оплаты и вводит реквизиты\n"
        "4. Отправляет покупателю ссылку\n\n"
        "<b>Покупатель:</b>\n"
        "1. Открывает ссылку от продавца\n"
        "2. Переводит деньги по реквизитам\n"
        "3. Нажимает «✅ Я оплатил»\n"
        "4. Ждёт подтверждения от гаранта\n"
        "5. Получает товар и подтверждает\n\n"
        "<b>Гарант (админ):</b>\n"
        "• Подтверждает оплату командой /buy #hash\n"
        "• Одобряет выплату продавцу",
        parse_mode="HTML",
        reply_markup=kb
    )
    await callback.answer()


@dp.message(Command("help"))
async def cmd_help(message: types.Message):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ В меню", callback_data="main_menu")]
    ])
    await message.answer(
        "📖 <b>Как работает гарант-бот:</b>\n\n"
        "<b>Продавец:</b>\n"
        "1. Нажимает ➕ Создать сделку\n"
        "2. Вводит товар, цену, @покупателя\n"
        "3. Выбирает метод оплаты и вводит реквизиты\n"
        "4. Отправляет покупателю ссылку\n\n"
        "<b>Покупатель:</b>\n"
        "1. Открывает ссылку от продавца\n"
        "2. Переводит деньги по реквизитам\n"
        "3. Нажимает «✅ Я оплатил»\n"
        "4. Ждёт подтверждения от гаранта\n"
        "5. Получает товар и подтверждает\n\n"
        "<b>Гарант (админ):</b>\n"
        "• Подтверждает оплату командой /buy #hash\n"
        "• Одобряет выплату продавцу",
        parse_mode="HTML",
        reply_markup=kb
    )


@dp.callback_query(F.data == "main_menu")
async def cb_main_menu(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    welcome_photo = FSInputFile(os.path.join(BASE_DIR, "attached_assets", "photo_2026-05-14_15-10-18.jpg"))
    await callback.message.answer_photo(
        photo=welcome_photo,
        caption=f"<blockquote>👋 <b>Добро пожаловать в {BOT_NAME}</b></blockquote>\n\n"
                "<blockquote>🛡 Безопасные ордера с передачей товара через менеджера.</blockquote>\n\n"
                f"<blockquote>📋 Комиссия сервиса: 1%</blockquote>\n\n"
                f"<blockquote>🆘 Поддержка: {SUPPORT_USERNAME}</blockquote>",
        parse_mode="HTML",
        reply_markup=main_menu_kb(callback.from_user.id)
    )
    await callback.answer()


# ==========================================
# НОВЫЕ РАЗДЕЛЫ МЕНЮ
# ==========================================

@dp.callback_query(F.data == "wallets")
async def cb_wallets(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.answer(
        wallet_menu_text(callback.from_user.id),
        parse_mode="HTML",
        reply_markup=wallet_menu_kb(callback.from_user.id)
    )
    await callback.answer()


@dp.callback_query(F.data.startswith("wallet_set_"))
async def cb_wallet_set(callback: types.CallbackQuery, state: FSMContext):
    method = callback.data.replace("wallet_set_", "", 1)
    if method not in PAYMENT_METHODS:
        await callback.answer("Неизвестный тип реквизитов", show_alert=True)
        return

    await state.set_state(WalletEdit.value)
    await state.update_data(wallet_method=method)
    await callback.message.answer(
        f"{wallet_prompt(method)}\n\n"
        "<blockquote>Отправьте новые реквизиты одним сообщением. "
        "Они будут сохранены только в вашем профиле.</blockquote>",
        parse_mode="HTML",
        reply_markup=back_btn()
    )
    await callback.answer()


@dp.message(WalletEdit.value)
async def save_wallet_value(message: types.Message, state: FSMContext):
    data = await state.get_data()
    method = data.get("wallet_method")
    value = (message.text or "").strip()

    if method not in PAYMENT_METHODS:
        await state.clear()
        await message.answer("❌ Не удалось определить тип реквизитов.", reply_markup=back_btn())
        return

    is_valid, error_text = validate_requisites(method, value)
    if not is_valid:
        await message.answer(error_text, parse_mode="HTML")
        return

    set_user_wallet(message.from_user.id, method, value)
    await state.clear()
    await message.answer(
        "✅ <b>Реквизиты сохранены</b>\n\n"
        f"{PAYMENT_METHODS[method]['name']}: <code>{html.escape(short_wallet(value))}</code>",
        parse_mode="HTML",
        reply_markup=wallet_menu_kb(message.from_user.id)
    )


@dp.callback_query(F.data.startswith("wallet_del_"))
async def cb_wallet_delete(callback: types.CallbackQuery):
    method = callback.data.replace("wallet_del_", "", 1)
    if method not in PAYMENT_METHODS:
        await callback.answer("Неизвестный тип реквизитов", show_alert=True)
        return

    delete_user_wallet(callback.from_user.id, method)
    await callback.message.answer(
        "🗑 <b>Реквизиты удалены</b>\n\n" + wallet_menu_text(callback.from_user.id),
        parse_mode="HTML",
        reply_markup=wallet_menu_kb(callback.from_user.id)
    )
    await callback.answer()


@dp.callback_query(F.data == "security")
async def cb_security(callback: types.CallbackQuery):
    await callback.message.answer(
        "<blockquote>🛡 <b>Безопасный ордер</b></blockquote>\n\n"
        "<blockquote>Покупатель оплачивает по реквизитам продавца.</blockquote>\n\n"
        f"<blockquote>Товар передаётся только менеджеру: <b>{ESCROW_USERNAME}</b></blockquote>\n\n"
        "<blockquote>Оплата продавцу проходит автоматически после завершения передачи.</blockquote>\n\n"
        "<blockquote>Ордер можно отменить до момента оплаты.</blockquote>",
        parse_mode="HTML",
        reply_markup=back_btn()
    )
    await callback.answer()


@dp.callback_query(F.data == "referral")
async def cb_referral(callback: types.CallbackQuery):
    await callback.message.answer(
        "👥 <b>Реферальная система</b>\n\n"
        "Приглашайте друзей и зарабатывайте с каждой их сделки.\n\n"
        "<blockquote>🔧 Раздел находится в разработке</blockquote>",
        parse_mode="HTML",
        reply_markup=back_btn()
    )
    await callback.answer()


@dp.callback_query(F.data == "exchange")
async def cb_exchange(callback: types.CallbackQuery):
    await callback.message.answer(
        "🔄 <b>Обменник</b>\n\n"
        "Быстрый обмен валют по выгодному курсу.\n\n"
        "<blockquote>🔧 Раздел находится в разработке</blockquote>",
        parse_mode="HTML",
        reply_markup=back_btn()
    )
    await callback.answer()


@dp.callback_query(F.data == "support")
async def cb_support(callback: types.CallbackQuery):
    await callback.message.answer(
        f"🆘 <b>Тех. Поддержка</b>\n\n"
        f"По всем вопросам обращайтесь к нашей поддержке:\n\n"
        f"<blockquote>🕐 Поддержка 24/7: {SUPPORT_USERNAME}</blockquote>",
        parse_mode="HTML",
        reply_markup=back_btn()
    )
    await callback.answer()


@dp.callback_query(F.data == "language")
async def cb_language(callback: types.CallbackQuery):
    await callback.message.answer(
        "🌐 <b>Язык / Language</b>\n\n"
        "Выберите язык интерфейса:",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🇷🇺 Русский ✅", callback_data="lang_ru")],
            [InlineKeyboardButton(text="🇬🇧 English",    callback_data="lang_en")],
            [InlineKeyboardButton(text="◀️ В меню",      callback_data="main_menu")],
        ])
    )
    await callback.answer()


@dp.callback_query(F.data.startswith("lang_"))
async def cb_set_language(callback: types.CallbackQuery):
    await callback.answer("🔧 Скоро будет доступно!", show_alert=True)


# ==========================================
# СОЗДАНИЕ СДЕЛКИ
# ==========================================

@dp.callback_query(F.data == "new_deal")
async def new_deal_btn(callback: types.CallbackQuery, state: FSMContext):
    await state.set_state(DealCreate.pay_method)
    await callback.message.answer(
        "<blockquote>🛡 <b>Безопасный ордер</b></blockquote>\n\n"
        "<blockquote>Покупатель оплатит по вашим реквизитам.</blockquote>\n\n"
        f"<blockquote>Товар передаётся только менеджеру: <b>{ESCROW_USERNAME}</b></blockquote>\n\n"
        "<blockquote>Оплата продавцу проходит автоматически после завершения передачи.</blockquote>\n\n"
        "<blockquote>Выберите способ оплаты со стороны покупателя.</blockquote>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💎 TON",          callback_data="method_ton")],
            [InlineKeyboardButton(text="💵 USDT (TON)",   callback_data="method_usdt")],
            [InlineKeyboardButton(text="💳 Карта/СБП",    callback_data="method_cardsbp")],
            [InlineKeyboardButton(text="⭐ Звёзды",        callback_data="method_stars")],
            [InlineKeyboardButton(text="◀️ В меню",       callback_data="main_menu")],
        ])
    )
    await callback.answer()


@dp.callback_query(F.data.startswith("method_"), DealCreate.pay_method)
async def choose_method(callback: types.CallbackQuery, state: FSMContext):
    method = callback.data.split("_")[1]
    await state.update_data(pay_method=method)
    await callback.message.edit_reply_markup(reply_markup=None)
    await state.set_state(DealCreate.wallet)

    saved_wallet = get_user_wallets(callback.from_user.id).get(method)
    rows = []
    if saved_wallet:
        rows.append([InlineKeyboardButton(
            text=f"✅ Использовать сохранённые: {short_wallet(saved_wallet, 24)}",
            callback_data="dealwallet_saved"
        )])
    rows.append([InlineKeyboardButton(text="✍️ Ввести вручную", callback_data="dealwallet_manual")])
    rows.append([InlineKeyboardButton(text="◀️ В меню", callback_data="main_menu")])

    await callback.message.answer(
        wallet_prompt(method),
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows)
    )
    await callback.answer()


@dp.callback_query(F.data == "dealwallet_saved", DealCreate.wallet)
async def use_saved_wallet(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    method = data.get("pay_method")
    saved_wallet = get_user_wallets(callback.from_user.id).get(method)

    if not saved_wallet:
        await callback.answer("Сохранённые реквизиты не найдены", show_alert=True)
        return

    await state.update_data(requisites=saved_wallet)
    await callback.message.edit_reply_markup(reply_markup=None)
    await ask_deal_price(callback.message, state)
    await callback.answer()


@dp.callback_query(F.data == "dealwallet_manual", DealCreate.wallet)
async def use_manual_wallet(callback: types.CallbackQuery):
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer(
        "Отправьте реквизиты для этого ордера одним сообщением.",
        reply_markup=back_btn()
    )
    await callback.answer()


@dp.message(DealCreate.wallet)
async def create_wallet(message: types.Message, state: FSMContext):
    data = await state.get_data()
    method = data.get("pay_method")
    value = (message.text or "").strip()
    is_valid, error_text = validate_requisites(method, value)
    if not is_valid:
        await message.answer(error_text, parse_mode="HTML")
        return

    await state.update_data(requisites=value)
    await ask_deal_price(message, state)


@dp.message(DealCreate.price)
async def create_price(message: types.Message, state: FSMContext):
    if not message.text.strip().isdigit() or int(message.text.strip()) <= 0:
        await message.answer(
            "❌ Введи целое число больше 0.\nНапример: <b>1500</b>",
            parse_mode="HTML"
        )
        return
    await state.update_data(price=int(message.text.strip()))
    await state.set_state(DealCreate.item)
    await message.answer(
        "📦 <b>Название товара</b>\n\n"
        "Введите название товара или услуги\n\n"
        "<blockquote>💡 Например: Аккаунт Spotify, Дизайн логотипа, Minecraft ключ</blockquote>",
        parse_mode="HTML",
        reply_markup=back_btn()
    )


@dp.message(DealCreate.item)
async def create_item(message: types.Message, state: FSMContext):
    await state.update_data(item=message.text.strip())
    await finish_deal_creation(message, state, message.from_user)


async def finish_deal_creation(message: types.Message, state: FSMContext, user):
    data = await state.get_data()
    deal_id = get_next_id()
    deals = load_deals()
    seller_username = (user.username or "").lower()

    deals[str(deal_id)] = {
        "id":              deal_id,
        "hash_id":         gen_hash_id(),
        "item":            data["item"],
        "price":           data["price"],
        "seller_id":       user.id,
        "seller_username": seller_username,
        "buyer_username":  "",
        "buyer_id":        None,
        "payment_method":  data["pay_method"],
        "requisites":      data.get("requisites", ""),
        "status":          "created",
        "created_at":      now(),
        "paid_at":         None,
        "shipped_at":      None,
        "completed_at":    None,
    }
    save_deals(deals)
    await state.clear()

    bot_info = await bot.get_me()
    tag = get_order_tag(deals[str(deal_id)])
    deal_link = f"https://t.me/{bot_info.username}?start=deal_{tag}"
    share_text = f"Открой ордер #{tag} в гаранте {BOT_NAME} по ссылке:"
    share_url = f"https://t.me/share/url?url={quote(deal_link)}&text={quote(share_text)}"

    await message.answer(
        created_order_text(deals[str(deal_id)], deal_link),
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Поделиться ордером", url=share_url)],
            [InlineKeyboardButton(text="Тех. Поддержка", callback_data="support")],
        ])
    )
    # Send admin notification and log the event
    await notify_admin(f"🆕 <b>Новый ордер #{tag}</b>\n\n{deal_info(deals[str(deal_id)])}")
    try:
        d = deals[str(deal_id)]
        seller = d.get('seller_username') or d.get('seller_id')
        item = d.get('item', '')
        price = d.get('price', '')
        logging.info(f"Ордер #{deal_id} создан — {item} | {price}. Продавец: @{seller}")
    except Exception:
        logging.info(f"Ордер #{deal_id} создан")

    # Send log to the log channel about new deal
    await send_log_to_channel(
        f"🆕 <b>[ЛОГ] Новый ордер #{tag}</b>\n\n"
        f"{deal_info(deals[str(deal_id)])}\n\n"
        f"━━━━━━━━━━━━━━━━"
    )

    # Also post to deals channel if configured
    if DEALS_CHANNEL_ID:
        try:
            try:
                cid = int(DEALS_CHANNEL_ID)
            except Exception:
                cid = DEALS_CHANNEL_ID
            await bot.send_message(cid, f"🆕 <b>Новый ордер #{tag}</b>\n\n{deal_info(deals[str(deal_id)])}", parse_mode="HTML")
        except Exception as e:
            logging.warning(f"Не удалось отправить сделку в канал: {e}")


# ==========================================
# ПРОСМОТР СДЕЛКИ
# ==========================================

async def show_deal(message: types.Message, deal_id: int):
    deals = load_deals()
    deal = deals.get(str(deal_id))

    if not deal:
        await message.answer(
            "❌ Ордер не найден",
            reply_markup=back_btn()
        )
        return

    user_id = message.from_user.id
    username = (message.from_user.username or "").lower()

    is_seller = (user_id == deal["seller_id"])
    if is_seller:
        await message.answer(
            "🚫 <b>Это ваш ордер</b>\n\n"
            "<blockquote>Нельзя открывать собственный ордер как покупатель.</blockquote>\n\n"
            "<blockquote>Отправьте ссылку покупателю через кнопку «Поделиться ордером».</blockquote>",
            parse_mode="HTML",
            reply_markup=back_btn()
        )
        return

    # If buyer_id already registered — match by ID
    # If not yet registered and this person is not the seller — they are the buyer
    # (anyone who gets the link and isn't the seller is the buyer)
    already_registered_buyer = (deal.get("buyer_id") == user_id)
    username_match = username and (username == deal["buyer_username"])
    new_buyer = (not is_seller) and (deal.get("buyer_id") is None)
    is_buyer = already_registered_buyer or username_match or new_buyer

    # First time buyer opens the link — register them and activate the deal
    if is_buyer and deal.get("buyer_id") is None:
        deal["buyer_id"] = user_id
        if deal["status"] == "created":
            deal["status"] = "pending_pay"
            try:
                buyer_display = username or user_id
                logging.debug(f"Сделка #{deal_id} перешла в статус 'pending_pay' — покупатель: @{buyer_display}")
            except Exception:
                pass
        deals[str(deal_id)] = deal
        save_deals(deals)

    pm = deal.get("payment_method", "stars")
    role = "seller" if is_seller else "buyer"
    text = deal_view(deal, role=role)
    buttons = []

    if is_buyer and deal["status"] == "pending_pay":
        if pm == "stars":
            buttons.append([InlineKeyboardButton(
                text="Оплатить",
                callback_data=f"pay_{deal_id}"
            )])
        else:
            buttons.append([InlineKeyboardButton(
                text="✅ Я оплатил",
                callback_data=f"ipaid_{deal_id}"
            )])

    elif is_buyer and deal["status"] == "pending_manual":
        buttons.append([InlineKeyboardButton(
            text="⏳ Ожидаем подтверждения...",
            callback_data="noop"
        )])

    elif is_buyer and deal["status"] == "shipped":
        buttons.append([InlineKeyboardButton(
            text="✅ Получил товар",
            callback_data=f"received_{deal_id}"
        )])

    elif is_seller and deal["status"] == "paid":
        buttons.append([InlineKeyboardButton(
            text="📦 Товар передан менеджеру",
            callback_data=f"shipped_{deal_id}"
        )])

    if is_seller and deal["status"] in ("created", "pending_pay"):
        buttons.append([InlineKeyboardButton(
            text="❌ Отменить ордер",
            callback_data=f"cancel_order_{deal_id}"
        )])

    # Только продавец может отменить ордер (до оплаты)

    kb = InlineKeyboardMarkup(inline_keyboard=buttons)

    await message.answer(text, parse_mode="HTML", reply_markup=kb)


@dp.callback_query(F.data == "noop")
async def noop_cb(callback: types.CallbackQuery):
    await callback.answer()


# ==========================================
# ОПЛАТА STARS
# ==========================================

@dp.callback_query(F.data.startswith("pay_"))
async def pay_stars(callback: types.CallbackQuery):
    deal_id = int(callback.data.split("_")[1])
    deals = load_deals()
    deal = deals.get(str(deal_id))

    if not deal:
        await callback.answer("❌ Ордер не найден", show_alert=True)
        return
    if deal["status"] != "pending_pay":
        await callback.answer("❌ Оплата недоступна", show_alert=True)
        return

    tag = get_order_tag(deal)
    await bot.send_invoice(
        chat_id=callback.from_user.id,
        title=f"Гарант — Ордер #{tag}",
        description=f"Товар: {deal['item']}. Stars заморожены до подтверждения получения.",
        payload=f"deal_{deal_id}",
        currency="XTR",
        prices=[LabeledPrice(label=deal["item"], amount=deal["price"])]
    )
    await callback.answer()


@dp.pre_checkout_query()
async def pre_checkout(pcq: types.PreCheckoutQuery):
    await bot.answer_pre_checkout_query(pcq.id, ok=True)


@dp.message(F.successful_payment)
async def payment_done(message: types.Message):
    payload = message.successful_payment.invoice_payload
    deal_id = int(payload.split("_")[1])
    deals = load_deals()
    deal = deals.get(str(deal_id))
    if not deal:
        return

    deal["status"] = "paid"
    deal["paid_at"] = now()
    deal["buyer_id"] = message.from_user.id
    save_deals(deals)
    try:
        buyer = message.from_user
        buyer_display = (buyer.username or buyer.id)
        logging.debug(f"Сделка #{deal_id} оплачена — покупатель: @{buyer_display}")
    except Exception:
        pass

    tag = get_order_tag(deal)
    await message.answer(
        f"<b>Оплата по ордеру #{tag} учтена</b>",
        parse_mode="HTML"
    )

    # Если оплата в звёздах — отдельное сообщение о списании
    if deal.get("payment_method") == "stars":
        await message.answer(
            f"<blockquote><b>⭐ С вашего баланса успешно было списано {deal['price']} звёзд</b></blockquote>\n\n\n"
            f"Ордер #{tag} оплачен",
            parse_mode="HTML"
        )

    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="📦 Товар передан менеджеру", callback_data=f"shipped_{deal_id}")
    ]])
    try:
        await bot.send_message(
            deal["seller_id"],
            seller_payment_confirmed_text(deal),
            parse_mode="HTML",
            reply_markup=kb
        )
    except Exception:
        pass

    await notify_admin(f"💸 <b>Оплата Stars — Ордер #{tag}</b>\n\n{deal_info(deal)}")
    await send_log_to_channel(
        f"💸 <b>[ЛОГ] Оплата Stars — Ордер #{tag}</b>\n\n"
        f"{deal_info(deal)}\n\n"
        f"━━━━━━━━━━━━━━━━"
    )


# ==========================================
# РУЧНАЯ ОПЛАТА — покупатель нажал "Я оплатил"
# ==========================================

@dp.callback_query(F.data.startswith("ipaid_"))
async def buyer_paid_manual(callback: types.CallbackQuery):
    deal_id = int(callback.data.split("_")[1])
    deals = load_deals()
    deal = deals.get(str(deal_id))

    if not deal:
        await callback.answer("❌ Ордер не найден", show_alert=True)
        return
    if deal["status"] != "pending_pay":
        await callback.answer("❌ Уже обработано", show_alert=True)
        return

    deal["status"] = "pending_manual"
    deal["buyer_id"] = callback.from_user.id
    save_deals(deals)

    tag = get_order_tag(deal)
    await callback.message.edit_text(
        f"<blockquote>⏳ Ожидаем подтверждения оплаты</blockquote>\n\n"
        f"<blockquote>Ордер #{tag}: {deal['item']}</blockquote>",
        parse_mode="HTML",
        reply_markup=back_btn()
    )

    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(
            text=f"✅ Подтвердить оплату #{tag}",
            callback_data=f"confirmpay_{deal_id}"
        )
    ]])
    await notify_admin(
        f"💰 <b>Покупатель сообщил об оплате — Ордер #{tag}</b>\n\n"
        f"{deal_info(deal)}\n\nПроверь поступление и подтверди:\n"
        f"или введи /buy #{tag}",
        reply_markup=kb
    )
    await callback.answer("⏳ Ожидай подтверждения от гаранта!", show_alert=True)
    try:
        reporter = callback.from_user
        reporter_display = (reporter.username or reporter.id)
        logging.debug(f"Сделка #{deal_id} помечена 'pending_manual' — сообщил: @{reporter_display}")
    except Exception:
        pass


# ==========================================
# ЗАПРОС ДОСТУПА К КОМАНДАМ ОПЛАТЫ
# ==========================================

@dp.message(lambda m: m.text and m.text.strip().split()[0].split("@")[0].lower() == "/ma")
async def cmd_request_payment_access(message: types.Message):
    if is_authorized(message.from_user.id):
        await message.answer(
            "✅ У вас уже есть доступ.\n\n"
            "Можно подтверждать оплату командой <code>/buy #hash</code>.",
            parse_mode="HTML"
        )
        return

    user = message.from_user
    username = f"@{user.username}" if user.username else "без username"
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Выдать доступ", callback_data=f"access_grant_{user.id}"),
        InlineKeyboardButton(text="❌ Отклонить", callback_data=f"access_deny_{user.id}"),
    ]])

    await message.answer("⏳ Заявка отправлена админу. Ожидайте подтверждения.")
    try:
        await bot.send_message(
            ADMIN_ID,
            "🔐 <b>Запрос доступа к командам оплаты</b>\n\n"
            f"Пользователь: {html.escape(username)}\n"
            f"ID: <code>{user.id}</code>\n\n"
            "После подтверждения он сможет использовать /buy #hash.",
            parse_mode="HTML",
            reply_markup=kb
        )
    except Exception:
        await message.answer("❌ Не удалось отправить заявку админу. Напишите в поддержку.")


@dp.callback_query(F.data.startswith("access_grant_"))
async def cb_access_grant(callback: types.CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("🚫 Нет доступа", show_alert=True)
        return

    target_id = int(callback.data.split("_")[2])
    was_new = grant_payment_access(target_id)
    status_text = "выдан" if was_new else "уже был выдан"

    await callback.message.edit_text(
        f"✅ Доступ пользователю <code>{target_id}</code> {status_text}.",
        parse_mode="HTML"
    )
    try:
        await bot.send_message(
            target_id,
            "✅ <b>Админ подтвердил доступ</b>\n\n"
            "Теперь можно подтверждать оплату командой <code>/buy #hash</code>.",
            parse_mode="HTML"
        )
    except Exception:
        pass
    await callback.answer("Доступ выдан")


@dp.callback_query(F.data.startswith("access_deny_"))
async def cb_access_deny(callback: types.CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("🚫 Нет доступа", show_alert=True)
        return

    target_id = int(callback.data.split("_")[2])
    await callback.message.edit_text(
        f"❌ Заявка пользователя <code>{target_id}</code> отклонена.",
        parse_mode="HTML"
    )
    try:
        await bot.send_message(target_id, "❌ Админ отклонил заявку на доступ.")
    except Exception:
        pass
    await callback.answer("Заявка отклонена")


# ==========================================
# ВЫДАЧА / ОТЗЫВ ПРАВ НА ОПЛАТУ
# ==========================================

@dp.message(lambda m: m.text and m.text.startswith("/grant") and m.from_user.id == ADMIN_ID)
async def cmd_grant(message: types.Message):
    parts = message.text.strip().split()
    if len(parts) < 2:
        await message.answer(
            "❌ Использование: <code>/grant USER_ID</code>\n"
            "Например: <code>/grant 123456789</code>",
            parse_mode="HTML"
        )
        return
    try:
        target_id = int(parts[1])
    except ValueError:
        await message.answer("❌ USER_ID должен быть числом", parse_mode="HTML")
        return

    if target_id == ADMIN_ID:
        await message.answer("ℹ️ Это уже администратор", parse_mode="HTML")
        return
    grant_payment_access(target_id)
    await message.answer(
        f"✅ Пользователю <code>{target_id}</code> выданы права на подтверждение оплаты.\n\n"
        f"Теперь он может использовать /buy #hash",
        parse_mode="HTML"
    )


@dp.message(lambda m: m.text and m.text.startswith("/revoke") and m.from_user.id == ADMIN_ID)
async def cmd_revoke(message: types.Message):
    parts = message.text.strip().split()
    if len(parts) < 2:
        await message.answer(
            "❌ Использование: <code>/revoke USER_ID</code>\n"
            "Например: <code>/revoke 123456789</code>",
            parse_mode="HTML"
        )
        return
    try:
        target_id = int(parts[1])
    except ValueError:
        await message.answer("❌ USER_ID должен быть числом", parse_mode="HTML")
        return

    trusted = load_trusted()
    if target_id in trusted:
        trusted.discard(target_id)
        save_trusted(trusted)
        await message.answer(
            f"✅ Права пользователя <code>{target_id}</code> отозваны.",
            parse_mode="HTML"
        )
    else:
        await message.answer(
            f"ℹ️ Пользователь <code>{target_id}</code> не имел прав.",
            parse_mode="HTML"
        )


@dp.message(lambda m: m.text and m.text.strip() == "/trusted" and m.from_user.id == ADMIN_ID)
async def cmd_trusted_list(message: types.Message):
    trusted = load_trusted()
    if not trusted:
        await message.answer("📋 Список доверенных пользователей пуст.")
        return
    ids = "\n".join(f"• <code>{uid}</code>" for uid in trusted)
    await message.answer(
        f"📋 <b>Доверенные пользователи:</b>\n\n{ids}",
        parse_mode="HTML"
    )


# ==========================================
# КОМАНДА /buy #hash — подтвердить оплату
# ==========================================

@dp.message(lambda m: m.text and is_authorized(m.from_user.id) and
            (m.text.startswith("/buy ") or m.text.strip() == "/buy"))
async def admin_buy_command(message: types.Message):
    parts = message.text.strip().split()
    if len(parts) < 2:
        await message.answer(
            "❌ Использование: <code>/buy #hashid</code>\n"
            "Например: <code>/buy #abc123xyz0</code>",
            parse_mode="HTML"
        )
        return

    raw = parts[1].lstrip("#")
    deals = load_deals()

    deal = None
    deal_id = None
    for k, d in deals.items():
        if d.get("hash_id") == raw:
            deal = d
            deal_id = int(k)
            break

    if not deal:
        await message.answer(f"❌ Ордер <code>#{raw}</code> не найден", parse_mode="HTML")
        return
    if deal["status"] not in ("pending_pay", "pending_manual"):
        await message.answer(
            f"❌ Нельзя подтвердить оплату.\n"
            f"Статус: {STATUS.get(deal['status'], deal['status'])}"
        )
        return

    deal["status"] = "paid"
    deal["paid_at"] = now()
    deals[str(deal_id)] = deal
    save_deals(deals)
    try:
        buyer = deal.get('buyer_username') or deal.get('buyer_id') or '—'
        logging.debug(f"Сделка #{deal_id} оплачена (админ) — покупатель: @{buyer}")
    except Exception:
        pass

    tag = get_order_tag(deal)
    await message.answer(
        f"✅ <b>Ордер #{tag} подтверждён!</b>\n\n{deal_info(deal)}",
        parse_mode="HTML"
    )

    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="📦 Товар передан менеджеру", callback_data=f"shipped_{deal_id}")
    ]])
    try:
        await bot.send_message(
            deal["seller_id"],
            seller_payment_confirmed_text(deal),
            parse_mode="HTML",
            reply_markup=kb
            )
    except Exception:
            pass

    if deal.get("buyer_id"):
            try:
                await bot.send_message(
                    deal["buyer_id"],
                    f"<b>Оплата по ордеру #{tag} учтена</b>",
                    parse_mode="HTML"
                )
                if deal.get("payment_method") == "stars":
                    await bot.send_message(
                        deal["buyer_id"],
                        f"<blockquote><b>⭐ С вашего баланса успешно было списано {deal['price']} звёзд</b></blockquote>\n\n\n"
                        f"Ордер #{tag} оплачен",
                        parse_mode="HTML"
                    )
            except Exception:
                pass

    await send_log_to_channel(
        f"✅ <b>[ЛОГ] Оплата подтверждена — Ордер #{tag}</b>\n\n"
        f"{deal_info(deal)}\n\n"
        f"Подтвердил: @{message.from_user.username or 'админ'}\n"
        f"━━━━━━━━━━━━━━━━"
        )

# ==========================================
# КНОПКА ПОДТВЕРЖДЕНИЯ ОПЛАТЫ (АДМИН)
# ==========================================

@dp.callback_query(F.data.startswith("confirmpay_"))
async def admin_confirm_pay_btn(callback: types.CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("🚫 Нет доступа", show_alert=True)
        return

    deal_id = int(callback.data.split("_")[1])
    deals = load_deals()
    deal = deals.get(str(deal_id))

    if not deal:
        await callback.answer("❌ Ордер не найден", show_alert=True)
        return
    if deal["status"] not in ("pending_pay", "pending_manual"):
        await callback.answer("❌ Уже обработано", show_alert=True)
        return

        deal["status"] = "paid"
    deal["paid_at"] = now()
    save_deals(deals)

    tag = get_order_tag(deal)
    await callback.message.edit_text(
        f"✅ <b>Оплата подтверждена! Ордер #{tag}</b>",
        parse_mode="HTML"
    )

    if deal.get("buyer_id"):
        try:
            await bot.send_message(
                deal["buyer_id"],
                f"<b>Оплата по ордеру #{tag} учтена</b>",
                parse_mode="HTML"
            )
            if deal.get("payment_method") == "stars":
                await bot.send_message(
                    deal["buyer_id"],
                    f"<blockquote><b>⭐ С вашего баланса успешно было списано {deal['price']} звёзд</b></blockquote>\n\n\n"
                    f"Ордер #{tag} оплачен",
                    parse_mode="HTML"
                )
        except Exception:
            pass

    await callback.answer("✅ Оплата подтверждена!", show_alert=True)


# ==========================================
# ОТПРАВКА ТОВАРА
# ==========================================

@dp.callback_query(F.data.startswith("shipped_"))
async def confirm_shipped(callback: types.CallbackQuery):
    deal_id = int(callback.data.split("_")[1])
    deals = load_deals()
    deal = deals.get(str(deal_id))

    if not deal:
        await callback.answer("❌ Ордер не найден", show_alert=True)
        return
    if deal["seller_id"] != callback.from_user.id:
        await callback.answer("🚫 Это не ваш ордер", show_alert=True)
        return
    if deal["status"] != "paid":
        await callback.answer("❌ Нельзя подтвердить отправку", show_alert=True)
        return

    deal["status"] = "shipped"
    deal["shipped_at"] = now()
    save_deals(deals)

    tag = get_order_tag(deal)
    await callback.message.edit_text(
        seller_manager_transfer_confirmed_text(deal),
        parse_mode="HTML",
        reply_markup=back_btn()
    )

    if deal["buyer_id"]:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Получил товар", callback_data=f"received_{deal_id}")],
        ])
        try:
            text = deal_view(deal, role="buyer")
            await bot.send_message(
                deal["buyer_id"],
                text,
                parse_mode="HTML",
                reply_markup=kb
            )
        except Exception:
            pass

    await notify_admin(f"📦 <b>Товар передан менеджеру — Ордер #{tag}</b>\n\n{deal_info(deal)}")
    await callback.answer("📦 Передача менеджеру зафиксирована!")
    try:
        seller = callback.from_user
        seller_display = (seller.username or seller.id)
        logging.debug(f"Сделка #{deal_id} — товар отправлен. Продавец: @{seller_display}")
    except Exception:
        pass


# ==========================================
# ПОДТВЕРЖДЕНИЕ ПОЛУЧЕНИЯ
# ==========================================

@dp.callback_query(F.data.startswith("received_"))
async def confirm_received(callback: types.CallbackQuery):
    deal_id = int(callback.data.split("_")[1])
    deals = load_deals()
    deal = deals.get(str(deal_id))

    if not deal:
        await callback.answer("❌ Ордер не найден", show_alert=True)
        return
    if deal["buyer_id"] != callback.from_user.id:
        await callback.answer("🚫 Это не ваш ордер", show_alert=True)
        return
    if deal["status"] != "shipped":
        await callback.answer("❌ Нельзя подтвердить", show_alert=True)
        return

    deal["status"] = "confirm_pend"
    save_deals(deals)

    tag = get_order_tag(deal)
    await callback.message.edit_text(
        f"<blockquote>✅ Получение подтверждено!</blockquote>\n\n"
        f"Ордер #{tag} завершён",
        parse_mode="HTML",
        reply_markup=back_btn()
    )

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text=f"💸 Одобрить выплату → @{deal['seller_username']}",
            callback_data=f"approve_{deal_id}"
        )],
    ])
    await notify_admin(
        f"💸 <b>Запрос на выплату — Ордер #{tag}</b>\n\n"
        f"{deal_info(deal)}\n\n"
        f"Покупатель подтвердил получение.\n"
        f"Переведи деньги продавцу @{deal['seller_username']} и нажми одобрить:",
        reply_markup=kb
    )
    await callback.answer("⏳ Ожидай выплаты!", show_alert=True)
    try:
        confirmer = callback.from_user
        confirmer_display = (confirmer.username or confirmer.id)
        logging.debug(f"Сделка #{deal_id} — покупатель подтвердил получение. Покупатель: @{confirmer_display}")
    except Exception:
        pass


# ==========================================
# ОДОБРЕНИЕ ВЫПЛАТЫ
# ==========================================

@dp.callback_query(F.data.startswith("approve_"))
async def admin_approve(callback: types.CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("🚫 Нет доступа", show_alert=True)
        return

    deal_id = int(callback.data.split("_")[1])
    deals = load_deals()
    deal = deals.get(str(deal_id))

    if not deal:
        await callback.answer("❌ Ордер не найден", show_alert=True)
        return
    if deal["status"] != "confirm_pend":
        await callback.answer("❌ Ордер уже обработан", show_alert=True)
        return

    deal["status"] = "completed"
    deal["completed_at"] = now()
    save_deals(deals)
    tag = get_order_tag(deal)

    await callback.message.edit_text(
        f"✅ <b>Выплата одобрена!</b>\n\n{deal_info(deal)}",
        parse_mode="HTML"
    )

    try:
        await bot.send_message(
            deal["seller_id"],
            f"🎉 <b>Ордер #{tag} завершён!</b>\n\n"
            f"📦 {deal['item']} — {deal['price']}\n\n"
            f"Гарант одобрил выплату 💸",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="◀️ В меню", callback_data="main_menu")]
            ])
        )
    except Exception:
        pass

    if deal["buyer_id"]:
        try:
            await bot.send_message(
                deal["buyer_id"],
                f"🎉 <b>Ордер #{tag} успешно завершён!</b>\n\nСпасибо за использование гарант-бота!",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="◀️ В меню", callback_data="main_menu")]
                ])
            )
        except Exception:
            pass

    await callback.answer("✅ Выплата одобрена!")
    try:
        approver = callback.from_user
        approver_display = (approver.username or approver.id)
        logging.debug(f"Сделка #{deal_id} завершена — одобрено: @{approver_display}")
    except Exception:
        pass


# ==========================================

@dp.callback_query(F.data.startswith("cancel_order_"))
async def cancel_order(callback: types.CallbackQuery):
    deal_id = int(callback.data.split("_")[2])
    deals = load_deals()
    deal = deals.get(str(deal_id))

    if not deal:
        await callback.answer("❌ Ордер не найден", show_alert=True)
        return

    user_id = callback.from_user.id
    is_seller = (user_id == deal.get("seller_id"))

    if not is_seller:
        await callback.answer("🚫 Только продавец может отменить ордер", show_alert=True)
        return

    if deal["status"] not in ("created", "pending_pay"):
        await callback.answer("❌ Ордер уже нельзя отменить", show_alert=True)
        return

    tag = get_order_tag(deal)
    deal["status"] = "cancelled"
    save_deals(deals)

    initiator = "продавец"
    await callback.message.edit_text(
        f"<blockquote>❌ Ордер #{tag} отменён</blockquote>\n\n"
        f"<blockquote>📦 Товар: {deal['item']}</blockquote>\n\n"
        f"<blockquote>💰 Сумма: {format_payment_amount(deal)}</blockquote>\n\n"
        f"<blockquote>Инициатор отмены: {initiator}</blockquote>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="◀️ В меню", callback_data="main_menu")]
        ])
    )

    if deal.get("buyer_id"):
        try:
            await bot.send_message(
                deal["buyer_id"],
                f"<blockquote>❌ Ордер #{tag} отменён продавцом</blockquote>\n\n"
                f"<blockquote>📦 Товар: {deal['item']}</blockquote>\n\n"
                f"<blockquote>💰 Сумма: {format_payment_amount(deal)}</blockquote>",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="◀️ В меню", callback_data="main_menu")]
                ])
            )
        except Exception:
            pass

    await send_log_to_channel(
        f"❌ <b>[ЛОГ] Ордер отменён — #{tag}</b>\n\n"
        f"{deal_info(deal)}\n\n"
        f"Инициатор: {initiator}\n"
        f"━━━━━━━━━━━━━━━━"
    )

    await callback.answer("❌ Ордер отменён")




# ==========================================
# МОИ СДЕЛКИ
# ==========================================

@dp.callback_query(F.data == "my_deals")
async def cb_my_deals(callback: types.CallbackQuery):
    await _show_my_deals(callback.message, callback.from_user)
    await callback.answer()


async def _show_my_deals(message: types.Message, user):
    deals = load_deals()
    uid = user.id
    uname = (user.username or "").lower()

    mine = [d for d in deals.values()
            if d["seller_id"] == uid
            or d.get("buyer_username") == uname
            or d.get("buyer_id") == uid]

    if not mine:
        await message.answer(
            "<blockquote>📋 <b>Мои ордера</b></blockquote>\n\n"
            "<blockquote>Пока нет созданных или открытых ордеров.</blockquote>",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔒 Создать ордер", callback_data="new_deal")],
                [InlineKeyboardButton(text="◀️ В меню",          callback_data="main_menu")],
            ])
        )
        return

    text = "📋 <b>Мои ордера</b>\n\n"
    for d in list(mine)[-10:]:
        role = "Продавец" if d["seller_id"] == uid else "Покупатель"
        tag = get_order_tag(d)
        text += (
            f"<blockquote>🔖 <b>#{tag}</b></blockquote>\n"
            f"<blockquote>📦 Товар: <code>{html.escape(str(d['item']))}</code></blockquote>\n"
            f"<blockquote>💰 Сумма: {html.escape(format_payment_amount(d))}</blockquote>\n"
            f"<blockquote>📊 Статус: {STATUS.get(d['status'], d['status'])}</blockquote>\n"
            f"<blockquote>👤 Роль: {role}</blockquote>\n\n"
        )

    await message.answer(
        text,
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="◀️ В меню", callback_data="main_menu")]
        ])
    )


# ==========================================
# ПАНЕЛЬ АДМИНА
# ==========================================

@dp.callback_query(F.data == "admin_panel")
async def cb_admin_panel(callback: types.CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("🚫 Нет доступа", show_alert=True)
        return
    await _show_admin_panel(callback.message)
    await callback.answer()


async def _show_admin_panel(message: types.Message):
    deals = load_deals()
    total = len(deals)
    active = sum(1 for d in deals.values() if d["status"] not in ("completed", "cancelled"))
    pend = sum(1 for d in deals.values() if d["status"] == "confirm_pend")
    manual = sum(1 for d in deals.values() if d["status"] == "pending_manual")

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"⏳ Ожидают оплаты ({manual})", callback_data="admin_manual")],
        [InlineKeyboardButton(text=f"💸 Автовыплата ({pend})",      callback_data="admin_pending")],
        [InlineKeyboardButton(text=f"📊 Активные ({active})",       callback_data="admin_active")],
        [InlineKeyboardButton(text="◀️ В меню",                     callback_data="main_menu")],
    ])

    await message.answer(
        f"<blockquote>🛠 <b>Панель администратора</b></blockquote>\n\n"
        f"<blockquote>📊 Всего ордеров: <b>{total}</b></blockquote>\n\n"
        f"<blockquote>🔄 Активных: <b>{active}</b></blockquote>\n\n"
        f"<blockquote>⏳ Ожидают оплаты: <b>{manual}</b></blockquote>\n\n"
        f"<blockquote>💸 Автовыплата: <b>{pend}</b></blockquote>\n\n"
        f"<blockquote>Команда для оплаты: <code>/buy #hash</code></blockquote>",
        parse_mode="HTML",
        reply_markup=kb
    )


@dp.callback_query(F.data == "admin_manual")
async def admin_show_manual(callback: types.CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("🚫 Нет доступа", show_alert=True)
        return
    deals = load_deals()
    manual = [d for d in deals.values() if d["status"] == "pending_manual"]
    if not manual:
        await callback.answer("Нет ордеров в ожидании оплаты", show_alert=True)
        return
    for d in manual:
        kb = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(
                text=f"✅ Подтвердить оплату #{get_order_tag(d)}",
                callback_data=f"confirmpay_{d['id']}"
            )
        ]])
        await callback.message.answer(deal_info(d), parse_mode="HTML", reply_markup=kb)
    await callback.answer()


@dp.callback_query(F.data == "admin_pending")
async def admin_show_pending(callback: types.CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("🚫 Нет доступа", show_alert=True)
        return
    deals = load_deals()
    pend = [d for d in deals.values() if d["status"] == "confirm_pend"]
    if not pend:
        await callback.answer("Нет ордеров на автовыплате", show_alert=True)
        return
    for d in pend:
        kb = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(
                text=f"💸 Одобрить выплату → @{d['seller_username']}",
                callback_data=f"approve_{d['id']}"
            )
        ]])
        await callback.message.answer(deal_info(d), parse_mode="HTML", reply_markup=kb)
    await callback.answer()



@dp.callback_query(F.data == "admin_active")
async def admin_show_active(callback: types.CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("🚫 Нет доступа", show_alert=True)
        return
    deals = load_deals()
    active = [d for d in deals.values() if d["status"] not in ("completed", "cancelled")]
    if not active:
        await callback.answer("Нет активных ордеров", show_alert=True)
        return
    text = "📊 <b>Активные ордера:</b>\n\n"
    for d in active[-20:]:
        s = STATUS.get(d["status"], d["status"])
        text += (
            f"<blockquote>🔖 <b>#{get_order_tag(d)}</b></blockquote>\n"
            f"<blockquote>📦 Товар: <code>{html.escape(str(d['item']))}</code></blockquote>\n"
            f"<blockquote>💰 Сумма: {html.escape(format_payment_amount(d))}</blockquote>\n"
            f"<blockquote>📊 Статус: {s}</blockquote>\n\n"
        )
    await callback.message.answer(
        text,
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 Назад", callback_data="admin_panel")]
        ])
    )
    await callback.answer()


# ==========================================
# ВСПОМОГАТЕЛЬНЫЕ
# ==========================================

async def notify_admin(text: str = "", reply_markup=None):
    # Admin notifications are disabled.
    return


# ==========================================
# ЛОГИ В ОТДЕЛЬНЫЙ КАНАЛ (настраивается админом)
# ==========================================


async def send_log_to_channel(text: str):
    """Отправляет лог-сообщение в канал логов, заданный админом через /setlog.
    Если канал не задан — пропускает.
    """
    channel_id = load_log_channel()
    if not channel_id:
        return
    try:
        try:
            cid = int(channel_id)
        except Exception:
            cid = channel_id
        await bot.send_message(cid, text, parse_mode="HTML")
    except Exception as e:
        logging.warning(f"Не удалось отправить лог в канал: {e}")


@dp.message(Command("setlog"))
async def cmd_setlog(message: types.Message):
    """Админ задаёт ID канала (или username) для логов сделок."""
    if message.from_user.id != ADMIN_ID:
        await message.answer("🚫 Нет доступа")
        return

    parts = message.text.strip().split()
    if len(parts) < 2:
        await message.answer(
            "❌ Использование: <code>/setlog CHANNEL_ID</code>\n\n"
            "Где CHANNEL_ID — ID канала (число) или @username канала.\n\n"
            "Примеры:\n"
            "<code>/setlog -1001234567890</code>\n"
            "<code>/setlog @mychannel</code>\n\n"
            "Бот должен быть администратором канала!",
            parse_mode="HTML"
        )
        return

    raw = parts[1].strip()
    save_log_channel(raw)
    await message.answer(
        f"✅ <b>Канал для логов установлен!</b>\n\n"
        f"<code>{html.escape(raw)}</code>\n\n"
        f"Теперь все логи сделок будут приходить туда.\n\n"
        f"Проверьте, что бот добавлен в администраторы канала.",
        parse_mode="HTML"
    )


@dp.message(Command("logstatus"))
async def cmd_logstatus(message: types.Message):
    """Показывает текущий канал для логов."""
    if message.from_user.id != ADMIN_ID:
        await message.answer("🚫 Нет доступа")
        return

    channel_id = load_log_channel()
    if not channel_id:
        await message.answer(
            "📋 <b>Статус канала логов</b>\n\n"
            "❌ Канал для логов <b>не задан</b>.\n\n"
            "Используйте <code>/setlog CHANNEL_ID</code>, чтобы задать канал.",
            parse_mode="HTML"
        )
        return

    await message.answer(
        f"📋 <b>Статус канала логов</b>\n\n"
        f"✅ Канал: <code>{html.escape(channel_id)}</code>\n\n"
        f"Для смены используйте <code>/setlog НОВЫЙ_ID</code>",
        parse_mode="HTML"
    )


async def main():
    print("🤝 Гарант-бот запущен!")
    # Clear any buffered log messages captured before the loop started
    if LOG_BUFFER:
        LOG_BUFFER.clear()

    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
