import os
import re
import shutil
import zipfile
import asyncio
import threading
from datetime import datetime, date, timedelta

import libsql_experimental as libsql
from flask import Flask
from pyrogram import Client, filters, enums
from pyrogram.types import (
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    ReplyKeyboardMarkup,
    KeyboardButton,
    Message,
)


# ============================================================
# CONFIG
# ============================================================
API_ID = int(os.environ["API_ID"])
API_HASH = os.environ["API_HASH"]
BOT_TOKEN = os.environ["BOT_TOKEN"]

TURSO_URL = os.environ.get("TURSO_URL", "")
TURSO_TOKEN = os.environ.get("TURSO_TOKEN", "")
LOCAL_DB = "/tmp/bot_replica.db"

BASE_DIR = "user_files"
STICKER_DIR = "stickers"
ADMIN_ID = int(os.environ.get("ADMIN_ID", "1663567950"))
DEBOUNCE_SEC = 1.5
AUTO_ZIP_DELAY = 60
PREMIUM_DAYS = 25

FREE_LIMITS = {
    "storage": 300 * 1024 * 1024,
    "files": 25,
    "daily_zips": 3,
}

PREMIUM_LIMITS = {
    "storage": 1024 * 1024 * 1024,
    "files": 50,
    "daily_zips": 12,
}

PAYMENT_SETTINGS = {
    "card": "payment_card",
    "visa": "payment_visa",
    "usdt_bep20": "payment_usdt_bep20",
    "usdt_trc20": "payment_usdt_trc20",
    "usdt_polygon": "payment_usdt_polygon",
}

ZIP_SEMAPHORE: asyncio.Semaphore = None


# ============================================================
# IN-MEMORY STATE
# ============================================================
required_channels: dict = {}
user_status_msg: dict = {}
user_welcome_msg: dict = {}
user_join_msg: dict = {}
user_auto_zip: dict = {}
user_debounce: dict = {}
user_downloading: dict = {}
user_reserved_bytes: dict = {}
user_excess: dict = {}
user_limit_debounce: dict = {}
user_storage_rej: dict = {}
waiting_for_admin_input: dict = {}
admin_broadcast_target: dict = {}
waiting_for_payment_screenshot: dict = {}
waiting_for_zip_name: dict = {}


# ============================================================
# TEXTS
# ============================================================
TEXTS = {
    "uz": {
        "choose_lang": "🌍 Tilni tanlang:",
        "lang_set": "✅ Til saqlandi!",
        "change_lang": "🌍 Tilni o'zgartirish",
        "welcome": (
            "✅ Til saqlandi!\n\n"
            "👋 Salom, *{name}*!\n\n"
            "📦 Fayllaringizni ZIP arxivga yig'ib beraman.\n\n"
            "📋 *Bepul tarif:*\n"
            "• Max 25 ta fayl\n"
            "• Max 300 MB\n"
            "• Kuniga 3 ta ZIP\n\n"
            "⭐ Premium tugmasi orqali kengaytirilgan tarifni yoqishingiz mumkin."
        ),
        "join_required": (
            "👋 Botdan foydalanish uchun quyidagi kanal(lar)ga obuna bo'ling.\n\n"
            "✅ Obuna bo'lgach «Tekshirish» tugmasini bosing."
        ),
        "join_check_btn": "✅ Tekshirish",
        "join_ok": "✅ Obuna tasdiqlandi!",
        "join_fail": "❌ Hali obuna bo'lmadingiz.",
        "files_saved": "✅ *{count} ta fayl* qabul qilindi!\n\n👇 ZIP yasash tugmasini bosing:",
        "receiving": "📥 *{count} ta fayl qabul qilinmoqda...* kutib turing",
        "ready_btn": "📦 ZIP yasash",
        "zip_wait": "⏳ Fayllar hali yuklanmoqda, biroz kuting.",
        "zip_queue": "⏳ ZIP navbatda. Jarayon bo'shashi bilan boshlanadi.",
        "zip_caption": "📦 *ZIP tayyor!*",
        "no_files": "⚠️ Avval fayl yuboring.",
        "zip_error": "❌ ZIP yaratishda xato bo'ldi. Qaytadan urinib ko'ring.",
        "creating_zip": "⚙️ ZIP yaratilmoqda, iltimos kuting.",
        "auto_zip_done": "🤖 Avtomatik ZIP yaratildi.",
        "banned": "🚫 Siz bloklangansiz.",
        "daily_limit": "⛔ Bugungi ZIP limiti tugadi. Ertaga yana urinib ko'ring.",
        "premium_priority_started": "🚀 Siz Premium foydalanuvchisiz, ZIP jarayoni navbatsiz boshlandi!",
        "premium_name_prompt": (
            "✍️ Premium foydalanuvchi sifatida ZIP uchun ixtiyoriy nom yuboring.\n\n"
            "Yoki pastdagi tugma orqali standart nomdan foydalaning."
        ),
        "premium_name_default": "📝 Standart nom",
        "premium_name_cancel": "❌ Bekor qilish",
        "premium_name_cancelled": "❌ ZIP nomlash bekor qilindi.",
        "premium_btn": "⭐ Premium",
        "premium_choose_method": (
            "⭐ *Premium bo'limi*\n\n"
            "{status}\n\n"
            "Premium tarif:\n"
            "• Max 50 ta fayl\n"
            "• Max 1 GB\n"
            "• Kuniga 12 ta ZIP\n"
            "• Navbatsiz ZIP\n"
            "• Ixtiyoriy ZIP nomi\n\n"
            "Quyidagi to'lov usulini tanlang:"
        ),
        "premium_free_status": "Siz hozircha oddiy foydalanuvchisiz.",
        "premium_active_status": "Siz Premium foydalanuvchisiz. Amal qilish muddati: *{expiry}*.",
        "premium_choose_crypto": "💎 Qaysi USDT tarmog'ini tanlaysiz?",
        "payment_not_configured": "⚠️ Bu rekvizit hali admin tomonidan kiritilmagan.",
        "payment_details": (
            "💳 *To'lov rekviziti*\n\n"
            "*Usul:* {label}\n"
            "`{value}`\n\n"
            "To'lov qilganingizdan keyin «To'lov qildim» tugmasini bosing."
        ),
        "payment_done_btn": "✅ To'lov qildim",
        "payment_screenshot_ask": (
            "📸 To'lov skrinshotini yuboring.\n"
            "Istasangiz, skrinshot captionida summani ham yozib yuboring."
        ),
        "payment_submitted": "✅ To'lov arizangiz adminga yuborildi. Tekshiruvdan keyin javob olasiz.",
        "payment_approved": "🎉 Premium faollashtirildi! 25 kunlik tarif sizga muvaffaqiyatli berildi.",
        "payment_rejected": "❌ Premium arizangiz rad etildi.\n\nSabab: {reason}",
        "premium_expiry_warn": (
            "⏰ Premium tarifingiz tugashiga 1 kun qoldi.\n"
            "Muddat: *{expiry}*.\n\n"
            "Davom ettirish uchun yana to'lov qilishingiz mumkin."
        ),
        "storage_full": (
            "⚠️ Xotira limiti tugadi.\n\n"
            "✅ Qabul qilindi: *{accepted} ta fayl*\n"
            "❌ Qabul qilinmadi: *{rejected} ta fayl*\n"
            "💾 Band: *{used}* / *{max_size}*"
        ),
        "files_limit": (
            "⛔ Fayl cheklovi.\n\n"
            "✅ Qabul qilindi: *{accepted} ta fayl*\n"
            "❌ Qabul qilinmadi: *{rejected} ta fayl*\n"
            "📦 Limit: *{max_files} ta fayl*"
        ),
        "settings_saved": "✅ Saqlandi.",
    },
    "en": {
        "choose_lang": "🌍 Choose language:",
        "lang_set": "✅ Language saved!",
        "change_lang": "🌍 Change language",
        "welcome": (
            "✅ Language saved!\n\n"
            "👋 Hello, *{name}*!\n\n"
            "📦 I collect your files into a ZIP archive.\n\n"
            "📋 *Free plan:*\n"
            "• Max 25 files\n"
            "• Max 300 MB\n"
            "• 3 ZIPs per day\n\n"
            "⭐ You can enable the upgraded plan through the Premium button."
        ),
        "join_required": (
            "👋 Please join the required channels first.\n\n"
            "✅ After joining, press «Check»."
        ),
        "join_check_btn": "✅ Check",
        "join_ok": "✅ Subscription confirmed!",
        "join_fail": "❌ You have not joined yet.",
        "files_saved": "✅ *{count} file(s)* received!\n\n👇 Press Create ZIP:",
        "receiving": "📥 *Receiving {count} file(s)...* please wait",
        "ready_btn": "📦 Create ZIP",
        "zip_wait": "⏳ Files are still uploading, please wait.",
        "zip_queue": "⏳ ZIP is queued. It will start as soon as possible.",
        "zip_caption": "📦 *ZIP is ready!*",
        "no_files": "⚠️ Send files first.",
        "zip_error": "❌ Failed to create ZIP.",
        "creating_zip": "⚙️ Creating ZIP, please wait.",
        "auto_zip_done": "🤖 Auto ZIP created.",
        "banned": "🚫 You are blocked.",
        "daily_limit": "⛔ Daily ZIP limit reached. Please try again tomorrow.",
        "premium_priority_started": "🚀 You are a Premium user, your ZIP started without queue!",
        "premium_name_prompt": (
            "✍️ As a Premium user, you can send an optional ZIP name.\n\n"
            "Or use the default button below."
        ),
        "premium_name_default": "📝 Default name",
        "premium_name_cancel": "❌ Cancel",
        "premium_name_cancelled": "❌ ZIP naming cancelled.",
        "premium_btn": "⭐ Premium",
        "premium_choose_method": (
            "⭐ *Premium section*\n\n"
            "{status}\n\n"
            "Premium plan:\n"
            "• Max 50 files\n"
            "• Max 1 GB\n"
            "• 12 ZIPs per day\n"
            "• Queue bypass\n"
            "• Custom ZIP name\n\n"
            "Choose a payment method:"
        ),
        "premium_free_status": "You are currently on the free plan.",
        "premium_active_status": "You are a Premium user. Expires at: *{expiry}*.",
        "premium_choose_crypto": "💎 Choose a USDT network:",
        "payment_not_configured": "⚠️ This payment method is not configured yet.",
        "payment_details": (
            "💳 *Payment details*\n\n"
            "*Method:* {label}\n"
            "`{value}`\n\n"
            "After payment, press «I paid»."
        ),
        "payment_done_btn": "✅ I Paid",
        "payment_screenshot_ask": "📸 Send the payment screenshot. You can add the amount in the caption.",
        "payment_submitted": "✅ Your payment request was sent to admin.",
        "payment_approved": "🎉 Premium activated! Your 25-day plan is now active.",
        "payment_rejected": "❌ Your Premium request was rejected.\n\nReason: {reason}",
        "premium_expiry_warn": (
            "⏰ Your Premium plan expires in 1 day.\n"
            "Expiry: *{expiry}*.\n\n"
            "You can renew it with another payment."
        ),
        "storage_full": (
            "⚠️ Storage limit reached.\n\n"
            "✅ Accepted: *{accepted} file(s)*\n"
            "❌ Rejected: *{rejected} file(s)*\n"
            "💾 Used: *{used}* / *{max_size}*"
        ),
        "files_limit": (
            "⛔ File limit reached.\n\n"
            "✅ Accepted: *{accepted} file(s)*\n"
            "❌ Rejected: *{rejected} file(s)*\n"
            "📦 Limit: *{max_files} files*"
        ),
        "settings_saved": "✅ Saved.",
    },
}


# ============================================================
# DB
# ============================================================
_db_conn = None


def now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def today_str() -> str:
    return date.today().isoformat()


def parse_dt(value: str):
    if not value:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(value, fmt)
        except Exception:
            continue
    return None


def get_db():
    global _db_conn
    if _db_conn is not None:
        return _db_conn
    if not TURSO_URL or not TURSO_TOKEN:
        raise RuntimeError("TURSO_URL va TURSO_TOKEN to'ldirilmagan!")
    _db_conn = libsql.connect(LOCAL_DB, sync_url=TURSO_URL, auth_token=TURSO_TOKEN)
    _db_conn.sync()
    print("[DB] Turso ulandi")
    return _db_conn


def db_sync():
    if _db_conn:
        try:
            _db_conn.sync()
        except Exception as e:
            print(f"[db_sync xato] {e}")


def init_db():
    c = get_db()
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            telegram_id     INTEGER UNIQUE NOT NULL,
            first_name      TEXT DEFAULT '',
            last_name       TEXT DEFAULT '',
            username        TEXT DEFAULT '',
            language        TEXT DEFAULT 'uz',
            waiting_zip     INTEGER DEFAULT 0,
            is_banned       INTEGER DEFAULT 0,
            is_premium      INTEGER DEFAULT 0,
            premium_expiry  TEXT DEFAULT '',
            premium_warned  INTEGER DEFAULT 0,
            daily_zip_count INTEGER DEFAULT 0,
            daily_zip_date  TEXT DEFAULT '',
            joined_at       TEXT NOT NULL
        )
    """
    )
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS channels (
            chat_id     INTEGER PRIMARY KEY,
            title       TEXT DEFAULT '',
            username    TEXT DEFAULT '',
            invite_link TEXT DEFAULT ''
        )
    """
    )
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS settings (
            key   TEXT PRIMARY KEY,
            value TEXT DEFAULT ''
        )
    """
    )
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS zip_stats (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            date        TEXT NOT NULL,
            telegram_id INTEGER NOT NULL,
            zip_count   INTEGER DEFAULT 0,
            total_mb    REAL DEFAULT 0.0,
            file_count  INTEGER DEFAULT 0
        )
    """
    )
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS payments (
            id                    INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id               INTEGER NOT NULL,
            method                TEXT DEFAULT '',
            status                TEXT DEFAULT 'pending',
            screenshot_id         TEXT DEFAULT '',
            amount                TEXT DEFAULT '',
            admin_message_chat_id INTEGER DEFAULT 0,
            admin_message_id      INTEGER DEFAULT 0,
            rejection_reason      TEXT DEFAULT '',
            created_at            TEXT NOT NULL,
            reviewed_at           TEXT DEFAULT ''
        )
    """
    )

    for col, dfn in [
        ("waiting_zip", "INTEGER DEFAULT 0"),
        ("is_banned", "INTEGER DEFAULT 0"),
        ("is_premium", "INTEGER DEFAULT 0"),
        ("premium_expiry", "TEXT DEFAULT ''"),
        ("premium_warned", "INTEGER DEFAULT 0"),
        ("daily_zip_count", "INTEGER DEFAULT 0"),
        ("daily_zip_date", "TEXT DEFAULT ''"),
    ]:
        try:
            c.execute(f"ALTER TABLE users ADD COLUMN {col} {dfn}")
        except Exception:
            pass

    for col, dfn in [("username", "TEXT DEFAULT ''"), ("invite_link", "TEXT DEFAULT ''")]:
        try:
            c.execute(f"ALTER TABLE channels ADD COLUMN {col} {dfn}")
        except Exception:
            pass

    for col, dfn in [
        ("method", "TEXT DEFAULT ''"),
        ("status", "TEXT DEFAULT 'pending'"),
        ("screenshot_id", "TEXT DEFAULT ''"),
        ("amount", "TEXT DEFAULT ''"),
        ("admin_message_chat_id", "INTEGER DEFAULT 0"),
        ("admin_message_id", "INTEGER DEFAULT 0"),
        ("rejection_reason", "TEXT DEFAULT ''"),
        ("reviewed_at", "TEXT DEFAULT ''"),
    ]:
        try:
            c.execute(f"ALTER TABLE payments ADD COLUMN {col} {dfn}")
        except Exception:
            pass

    c.commit()
    db_sync()
    ensure_setting_defaults()
    cleanup_expired_premium_sync()


def ensure_setting_defaults():
    c = get_db()
    for key in PAYMENT_SETTINGS.values():
        c.execute("INSERT OR IGNORE INTO settings(key, value) VALUES(?, '')", (key,))
    c.commit()
    db_sync()


# ============================================================
# HELPERS: USERS / PREMIUM
# ============================================================
def upsert_user(user, lang=None):
    c = get_db()
    c.execute(
        """
        INSERT INTO users(telegram_id,first_name,last_name,username,language,joined_at,daily_zip_date)
        VALUES(?,?,?,?,?,?,?)
        ON CONFLICT(telegram_id) DO UPDATE SET
            first_name=excluded.first_name,
            last_name=excluded.last_name,
            username=excluded.username,
            language=COALESCE(?, language)
    """,
        (
            user.id,
            user.first_name or "",
            user.last_name or "",
            user.username or "",
            lang or "uz",
            now_str(),
            today_str(),
            lang,
        ),
    )
    c.commit()
    db_sync()


def get_lang(uid: int):
    row = get_db().execute("SELECT language FROM users WHERE telegram_id=?", (uid,)).fetchone()
    return row[0] if row else None


def tx(uid: int, key: str, **kwargs) -> str:
    lang = get_lang(uid) or "uz"
    text = TEXTS.get(lang, TEXTS["uz"]).get(key, key)
    return text.format(**kwargs) if kwargs else text


def get_user_row(uid: int):
    cleanup_expired_premium_for_user(uid)
    row = get_db().execute(
        """
        SELECT telegram_id, first_name, last_name, username, language, joined_at,
               is_banned, is_premium, premium_expiry, daily_zip_count, daily_zip_date
        FROM users
        WHERE telegram_id=?
    """,
        (uid,),
    ).fetchone()
    return row


def is_banned(uid: int) -> bool:
    row = get_db().execute("SELECT is_banned FROM users WHERE telegram_id=?", (uid,)).fetchone()
    return bool(row[0]) if row else False


def ban_user(uid: int):
    c = get_db()
    c.execute("UPDATE users SET is_banned=1 WHERE telegram_id=?", (uid,))
    c.commit()
    db_sync()


def unban_user(uid: int):
    c = get_db()
    c.execute("UPDATE users SET is_banned=0 WHERE telegram_id=?", (uid,))
    c.commit()
    db_sync()


def cleanup_expired_premium_sync():
    c = get_db()
    c.execute(
        """
        UPDATE users
        SET is_premium=0, premium_expiry='', premium_warned=0
        WHERE is_premium=1 AND premium_expiry<>'' AND premium_expiry<=?
    """,
        (now_str(),),
    )
    c.commit()
    db_sync()


def cleanup_expired_premium_for_user(uid: int):
    c = get_db()
    c.execute(
        """
        UPDATE users
        SET is_premium=0, premium_expiry='', premium_warned=0
        WHERE telegram_id=? AND is_premium=1 AND premium_expiry<>'' AND premium_expiry<=?
    """,
        (uid, now_str()),
    )
    c.commit()
    db_sync()


def is_premium(uid: int) -> bool:
    cleanup_expired_premium_for_user(uid)
    row = get_db().execute("SELECT is_premium FROM users WHERE telegram_id=?", (uid,)).fetchone()
    return bool(row[0]) if row else False


def get_premium_expiry(uid: int) -> str:
    cleanup_expired_premium_for_user(uid)
    row = get_db().execute("SELECT premium_expiry FROM users WHERE telegram_id=?", (uid,)).fetchone()
    return row[0] if row and row[0] else ""


def get_limits(uid: int) -> dict:
    return PREMIUM_LIMITS if is_premium(uid) else FREE_LIMITS


def ensure_daily_zip_counter(uid: int):
    c = get_db()
    row = c.execute("SELECT daily_zip_count, daily_zip_date FROM users WHERE telegram_id=?", (uid,)).fetchone()
    if not row:
        return
    if row[1] != today_str():
        c.execute(
            "UPDATE users SET daily_zip_count=0, daily_zip_date=? WHERE telegram_id=?",
            (today_str(), uid),
        )
        c.commit()
        db_sync()


def get_daily_zip_count(uid: int) -> int:
    ensure_daily_zip_counter(uid)
    row = get_db().execute("SELECT daily_zip_count FROM users WHERE telegram_id=?", (uid,)).fetchone()
    return row[0] if row else 0


def add_zip_stat(uid: int, mb: float, fcount: int):
    c = get_db()
    d = today_str()
    existing = c.execute(
        "SELECT id FROM zip_stats WHERE date=? AND telegram_id=?",
        (d, uid),
    ).fetchone()
    if existing:
        c.execute(
            """
            UPDATE zip_stats
            SET zip_count=zip_count+1, total_mb=total_mb+?, file_count=file_count+?
            WHERE id=?
        """,
            (mb, fcount, existing[0]),
        )
    else:
        c.execute(
            """
            INSERT INTO zip_stats(date, telegram_id, zip_count, total_mb, file_count)
            VALUES(?,?,1,?,?)
        """,
            (d, uid, mb, fcount),
        )
    c.execute(
        "UPDATE users SET daily_zip_count=daily_zip_count+1, daily_zip_date=? WHERE telegram_id=?",
        (today_str(), uid),
    )
    c.commit()
    db_sync()


def grant_premium(uid: int, days: int = PREMIUM_DAYS):
    c = get_db()
    row = c.execute("SELECT premium_expiry FROM users WHERE telegram_id=?", (uid,)).fetchone()
    current_expiry = parse_dt(row[0]) if row and row[0] else None
    start_from = current_expiry if current_expiry and current_expiry > datetime.now() else datetime.now()
    new_expiry = start_from + timedelta(days=days)
    c.execute(
        """
        UPDATE users
        SET is_premium=1, premium_expiry=?, premium_warned=0
        WHERE telegram_id=?
    """,
        (new_expiry.strftime("%Y-%m-%d %H:%M:%S"), uid),
    )
    c.commit()
    db_sync()
    return new_expiry


def user_count() -> int:
    return get_db().execute("SELECT COUNT(*) FROM users").fetchone()[0]


def today_count() -> int:
    return get_db().execute(
        "SELECT COUNT(*) FROM users WHERE joined_at LIKE ?",
        (f"{today_str()}%",),
    ).fetchone()[0]


def premium_user_count() -> int:
    cleanup_expired_premium_sync()
    return get_db().execute("SELECT COUNT(*) FROM users WHERE is_premium=1").fetchone()[0]


def free_user_count() -> int:
    cleanup_expired_premium_sync()
    return get_db().execute("SELECT COUNT(*) FROM users WHERE is_premium=0").fetchone()[0]


def all_users() -> list:
    cleanup_expired_premium_sync()
    return get_db().execute(
        """
        SELECT telegram_id, first_name, last_name, username, language, joined_at,
               is_banned, is_premium, premium_expiry, daily_zip_count
        FROM users
        ORDER BY id DESC
    """
    ).fetchall()


def get_user_by_id(tid: int):
    cleanup_expired_premium_for_user(tid)
    return get_db().execute(
        """
        SELECT telegram_id, first_name, last_name, username, language, joined_at,
               is_banned, is_premium, premium_expiry, daily_zip_count
        FROM users
        WHERE telegram_id=?
    """,
        (tid,),
    ).fetchone()


def get_global_stats() -> dict:
    c = get_db()
    cleanup_expired_premium_sync()
    today = today_str()
    total_zips = c.execute("SELECT COALESCE(SUM(zip_count),0) FROM zip_stats").fetchone()[0]
    today_zips = c.execute("SELECT COALESCE(SUM(zip_count),0) FROM zip_stats WHERE date=?", (today,)).fetchone()[0]
    total_mb = c.execute("SELECT COALESCE(SUM(total_mb),0) FROM zip_stats").fetchone()[0]
    today_mb = c.execute("SELECT COALESCE(SUM(total_mb),0) FROM zip_stats WHERE date=?", (today,)).fetchone()[0]
    total_files = c.execute("SELECT COALESCE(SUM(file_count),0) FROM zip_stats").fetchone()[0]
    return {
        "total_zips": total_zips,
        "today_zips": today_zips,
        "total_mb": total_mb,
        "today_mb": today_mb,
        "total_files": total_files,
        "premium_users": premium_user_count(),
        "free_users": free_user_count(),
    }


# ============================================================
# HELPERS: CHANNELS / SETTINGS / PAYMENTS
# ============================================================
def _load_channels():
    global required_channels
    rows = get_db().execute("SELECT chat_id, title, username, invite_link FROM channels").fetchall()
    required_channels = {
        row[0]: {
            "title": row[1] or "",
            "username": (row[2] or "").lstrip("@"),
            "invite_link": row[3] or "",
        }
        for row in rows
    }


def add_channel(chat_id: int, title: str, username: str = "", invite_link: str = ""):
    username = (username or "").lstrip("@")
    c = get_db()
    c.execute(
        "INSERT OR REPLACE INTO channels(chat_id, title, username, invite_link) VALUES(?,?,?,?)",
        (chat_id, title, username, invite_link),
    )
    c.commit()
    db_sync()
    required_channels[chat_id] = {
        "title": title,
        "username": username,
        "invite_link": invite_link,
    }


def remove_channel(chat_id: int):
    c = get_db()
    c.execute("DELETE FROM channels WHERE chat_id=?", (chat_id,))
    c.commit()
    db_sync()
    required_channels.pop(chat_id, None)


def get_channels() -> dict:
    return {cid: info.copy() for cid, info in required_channels.items()}


def get_setting(key: str) -> str:
    row = get_db().execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return row[0] if row else ""


def set_setting(key: str, value: str):
    c = get_db()
    c.execute("INSERT OR REPLACE INTO settings(key, value) VALUES(?, ?)", (key, value.strip()))
    c.commit()
    db_sync()


def get_all_payment_settings() -> dict:
    return {key: get_setting(key) for key in PAYMENT_SETTINGS.values()}


def payment_method_label(method: str) -> str:
    labels = {
        "card": "Uzcard / Humo",
        "visa": "Visa",
        "usdt_bep20": "USDT (BEP20)",
        "usdt_trc20": "USDT (TRC20)",
        "usdt_polygon": "USDT (Plasma/Polygon)",
    }
    return labels.get(method, method)


def create_payment(user_id: int, method: str, screenshot_id: str, amount: str) -> int:
    c = get_db()
    c.execute(
        """
        INSERT INTO payments(user_id, method, status, screenshot_id, amount, created_at)
        VALUES(?, ?, 'pending', ?, ?, ?)
    """,
        (user_id, method, screenshot_id, amount, now_str()),
    )
    c.commit()
    db_sync()
    return c.execute("SELECT last_insert_rowid()").fetchone()[0]


def set_payment_admin_message(payment_id: int, chat_id: int, message_id: int):
    c = get_db()
    c.execute(
        "UPDATE payments SET admin_message_chat_id=?, admin_message_id=? WHERE id=?",
        (chat_id, message_id, payment_id),
    )
    c.commit()
    db_sync()


def get_payment(payment_id: int):
    return get_db().execute(
        """
        SELECT id, user_id, method, status, screenshot_id, amount,
               admin_message_chat_id, admin_message_id, rejection_reason, created_at
        FROM payments
        WHERE id=?
    """,
        (payment_id,),
    ).fetchone()


def approve_payment(payment_id: int):
    c = get_db()
    c.execute(
        "UPDATE payments SET status='approved', reviewed_at=? WHERE id=?",
        (now_str(), payment_id),
    )
    c.commit()
    db_sync()


def reject_payment(payment_id: int, reason: str):
    c = get_db()
    c.execute(
        "UPDATE payments SET status='rejected', rejection_reason=?, reviewed_at=? WHERE id=?",
        (reason, now_str(), payment_id),
    )
    c.commit()
    db_sync()


def list_pending_payments(limit: int = 20) -> list:
    return get_db().execute(
        """
        SELECT id, user_id, method, amount, created_at
        FROM payments
        WHERE status='pending'
        ORDER BY id DESC
        LIMIT ?
    """,
        (limit,),
    ).fetchall()


# ============================================================
# FILE HELPERS
# ============================================================
def user_dir(uid: int) -> str:
    path = os.path.join(BASE_DIR, str(uid))
    os.makedirs(path, exist_ok=True)
    return path


def disk_used(uid: int) -> int:
    folder = user_dir(uid)
    return sum(
        os.path.getsize(os.path.join(folder, item))
        for item in os.listdir(folder)
        if os.path.isfile(os.path.join(folder, item))
    )


def file_count(uid: int) -> int:
    folder = user_dir(uid)
    return len(
        [item for item in os.listdir(folder) if os.path.isfile(os.path.join(folder, item))]
    )


def total_disk_all() -> int:
    total = 0
    if not os.path.exists(BASE_DIR):
        return total
    for folder in os.listdir(BASE_DIR):
        fp = os.path.join(BASE_DIR, folder)
        if not os.path.isdir(fp):
            continue
        for item in os.listdir(fp):
            path = os.path.join(fp, item)
            if os.path.isfile(path):
                total += os.path.getsize(path)
    return total


def all_users_disk() -> list:
    rows = []
    if not os.path.exists(BASE_DIR):
        return rows
    for folder in os.listdir(BASE_DIR):
        try:
            uid = int(folder)
        except ValueError:
            continue
        used = disk_used(uid)
        if used > 0:
            rows.append((uid, used))
    rows.sort(key=lambda item: item[1], reverse=True)
    return rows


_file_counter = 0
_file_counter_lock = threading.Lock()


def unique_path(directory: str, filename: str) -> str:
    global _file_counter
    with _file_counter_lock:
        _file_counter += 1
        counter = _file_counter
    base, ext = os.path.splitext(filename)
    stamp = datetime.now().strftime("%H%M%S_%f")
    return os.path.join(directory, f"{base}_{stamp}_{counter}{ext}")


def fmt_size(value: int) -> str:
    if value < 1024 ** 2:
        return f"{value / 1024:.1f} KB"
    return f"{value / 1024 ** 2:.1f} MB"


def sanitize_filename(filename: str) -> str:
    name = re.sub(r'[\\/:*?"<>|]', "_", filename)
    name = re.sub(r"\s+", "_", name)
    name = name.strip("._")
    return name or f"file_{datetime.now():%Y%m%d_%H%M%S}"


def make_zip_name(user, custom_name: str = "") -> str:
    if custom_name:
        cleaned = sanitize_filename(custom_name)
        cleaned = os.path.splitext(cleaned)[0]
        cleaned = cleaned[:80]
        return cleaned or f"user_{user.id}_{datetime.now():%d%m%y_%H%M}"
    base = (user.first_name or "") + ("_" + user.last_name if user.last_name else "")
    base = re.sub(r"\s+", "_", base.strip())
    base = re.sub(r"[^\w\-]", "", base)
    if not base:
        base = f"user_{user.id}"
    return f"{base}_{datetime.now():%d%m%y_%H%M}"


def main_menu(uid: int):
    return ReplyKeyboardMarkup(
        [[KeyboardButton(tx(uid, "premium_btn"))]],
        resize_keyboard=True,
    )


def get_broadcast_recipients(target: str) -> list:
    cleanup_expired_premium_sync()
    base_query = "SELECT telegram_id FROM users WHERE is_banned=0"
    params = ()
    if target == "free":
        base_query += " AND is_premium=0"
    elif target == "premium":
        base_query += " AND is_premium=1"
    return [row[0] for row in get_db().execute(base_query, params).fetchall()]


# ============================================================
# GENERIC ASYNC HELPERS
# ============================================================
async def safe_delete(msg):
    if msg is None:
        return
    try:
        await msg.delete()
    except Exception:
        pass


async def send_sticker(client, chat_id: int, name: str):
    path = os.path.join(STICKER_DIR, f"{name}.webp")
    if os.path.exists(path):
        try:
            await client.send_sticker(chat_id, path)
        except Exception:
            pass


async def error_to_admin(client, context: str, uid: int, err: Exception):
    try:
        await client.send_message(
            ADMIN_ID,
            f"🚨 *XATOLIK*\n\n📍 `{context}`\n👤 `{uid}`\n"
            f"❗ `{type(err).__name__}: {err}`\n"
            f"🕐 {now_str()}",
            parse_mode=enums.ParseMode.MARKDOWN,
        )
    except Exception as inner:
        print(f"[error_to_admin] {inner}")


def schedule_task(store: dict, uid: int, coro):
    loop = asyncio.get_running_loop()
    old = store.get(uid)
    if old and not old.done():
        old.cancel()
    store[uid] = loop.create_task(coro)


async def cancel_task(store: dict, uid: int):
    task = store.get(uid)
    if task and not task.done():
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
    store.pop(uid, None)


# ============================================================
# SUBSCRIPTION
# ============================================================
async def check_subscription(client, uid: int) -> list:
    not_joined = []
    for chat_id, info in required_channels.items():
        refs = []
        username = (info.get("username") or "").lstrip("@")
        if username:
            refs.append(f"@{username}")
        refs.append(chat_id)

        member = None
        for ref in refs:
            try:
                member = await client.get_chat_member(ref, uid)
                break
            except Exception:
                continue

        if member is None or member.status in (enums.ChatMemberStatus.BANNED, enums.ChatMemberStatus.LEFT):
            not_joined.append((chat_id, info))
    return not_joined


async def gate_check(client, uid: int, chat_id: int, lang: str) -> bool:
    if not required_channels:
        return True
    not_joined = await check_subscription(client, uid)
    if not not_joined:
        return True

    texts = TEXTS.get(lang, TEXTS["uz"])
    buttons = []
    for _, info in not_joined:
        username = (info.get("username") or "").lstrip("@")
        invite_link = info.get("invite_link") or ""
        title = info.get("title") or "Kanal"
        if username:
            buttons.append([InlineKeyboardButton(f"📢 @{username}", url=f"https://t.me/{username}")])
        elif invite_link:
            buttons.append([InlineKeyboardButton(f"📢 {title}", url=invite_link)])

    buttons.append([InlineKeyboardButton(texts["join_check_btn"], callback_data="check_join")])

    old_join_msg = user_join_msg.pop(uid, None)
    await safe_delete(old_join_msg)

    sent = await client.send_message(
        chat_id,
        texts["join_required"],
        parse_mode=enums.ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup(buttons),
    )
    user_join_msg[uid] = sent
    return False


# ============================================================
# STATUS / DEBOUNCE
# ============================================================
async def _send_status(client, chat_id: int, uid: int):
    await asyncio.sleep(DEBOUNCE_SEC)
    count_now = file_count(uid)
    downloading = user_downloading.get(uid, 0)
    sm = user_status_msg.get(uid)
    text = tx(uid, "receiving", count=count_now + downloading) if downloading > 0 else tx(uid, "files_saved", count=count_now)
    markup = None
    if downloading == 0:
        markup = InlineKeyboardMarkup(
            [[InlineKeyboardButton(tx(uid, "ready_btn"), callback_data="zip_now")]]
        )
    try:
        if sm is None:
            sent = await client.send_message(
                chat_id,
                text,
                parse_mode=enums.ParseMode.MARKDOWN,
                reply_markup=markup,
            )
            user_status_msg[uid] = sent
        else:
            await sm.edit_text(text, parse_mode=enums.ParseMode.MARKDOWN, reply_markup=markup)
    except Exception:
        pass


def restart_debounce(client, chat_id: int, uid: int):
    schedule_task(user_debounce, uid, _send_status(client, chat_id, uid))


async def _send_daily_limit_msg(client, chat_id: int, uid: int):
    await asyncio.sleep(1.5)
    sm = user_status_msg.pop(uid, None)
    await safe_delete(sm)
    await client.send_message(
        chat_id,
        tx(uid, "daily_limit"),
        parse_mode=enums.ParseMode.MARKDOWN,
        reply_markup=main_menu(uid),
    )


def schedule_limit_msg(client, chat_id: int, uid: int):
    schedule_task(user_limit_debounce, uid, _send_daily_limit_msg(client, chat_id, uid))


async def _send_excess_msg(client, chat_id: int, uid: int):
    await asyncio.sleep(DEBOUNCE_SEC)
    accepted = file_count(uid)
    rejected = user_excess.pop(uid, 0)
    if accepted == 0:
        return
    limits = get_limits(uid)
    text = tx(
        uid,
        "files_limit",
        accepted=accepted,
        rejected=rejected,
        max_files=limits["files"],
    )
    markup = InlineKeyboardMarkup(
        [[InlineKeyboardButton(tx(uid, "ready_btn"), callback_data="zip_now")]]
    )
    sm = user_status_msg.get(uid)
    try:
        if sm is None:
            user_status_msg[uid] = await client.send_message(
                chat_id,
                text,
                parse_mode=enums.ParseMode.MARKDOWN,
                reply_markup=markup,
            )
        else:
            await sm.edit_text(text, parse_mode=enums.ParseMode.MARKDOWN, reply_markup=markup)
    except Exception:
        pass


# ============================================================
# PREMIUM / PAYMENT UI
# ============================================================
async def show_premium_menu(client, chat_id: int, uid: int):
    expiry = get_premium_expiry(uid)
    status = (
        tx(uid, "premium_active_status", expiry=expiry)
        if is_premium(uid)
        else tx(uid, "premium_free_status")
    )
    buttons = [
        [
            InlineKeyboardButton("💳 Uzcard / Humo", callback_data="premium_method_card"),
            InlineKeyboardButton("💳 Visa", callback_data="premium_method_visa"),
        ],
        [InlineKeyboardButton("💎 Crypto (USDT)", callback_data="premium_crypto_menu")],
    ]
    await client.send_message(
        chat_id,
        tx(uid, "premium_choose_method", status=status),
        parse_mode=enums.ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup(buttons),
    )


async def show_payment_details(client, chat_id: int, uid: int, method: str, message_to_edit=None):
    setting_key = PAYMENT_SETTINGS[method]
    value = get_setting(setting_key)
    if not value:
        await client.send_message(chat_id, tx(uid, "payment_not_configured"), reply_markup=main_menu(uid))
        return
    buttons = InlineKeyboardMarkup(
        [[InlineKeyboardButton(tx(uid, "payment_done_btn"), callback_data=f"premium_paid_{method}")]]
    )
    text = tx(uid, "payment_details", label=payment_method_label(method), value=value)
    if message_to_edit is not None:
        await message_to_edit.edit_text(text, parse_mode=enums.ParseMode.MARKDOWN, reply_markup=buttons)
    else:
        await client.send_message(chat_id, text, parse_mode=enums.ParseMode.MARKDOWN, reply_markup=buttons)


async def ask_for_payment_screenshot(client, chat_id: int, uid: int, method: str):
    waiting_for_payment_screenshot[uid] = {"method": method}
    await client.send_message(
        chat_id,
        tx(uid, "payment_screenshot_ask"),
        parse_mode=enums.ParseMode.MARKDOWN,
        reply_markup=main_menu(uid),
    )


async def handle_payment_screenshot(client, message: Message):
    uid = message.from_user.id
    payload = waiting_for_payment_screenshot.pop(uid, None)
    if not payload:
        return False

    method = payload["method"]
    amount = (message.caption or "").strip() or "Ko'rsatilmagan"

    file_id = ""
    send_fn = None
    send_arg = None
    if message.photo:
        file_id = message.photo.file_id
        send_fn = client.send_photo
        send_arg = message.photo.file_id
    elif message.document:
        file_id = message.document.file_id
        send_fn = client.send_document
        send_arg = message.document.file_id
    else:
        waiting_for_payment_screenshot[uid] = payload
        await client.send_message(
            message.chat.id,
            "📸 Iltimos, skrinshotni rasm yoki document ko'rinishida yuboring.",
            reply_markup=main_menu(uid),
        )
        return True

    payment_id = create_payment(uid, method, file_id, amount)
    caption = (
        f"💳 *Yangi Premium to'lov arizasi*\n\n"
        f"🆔 To'lov ID: `{payment_id}`\n"
        f"👤 Foydalanuvchi: `{uid}`\n"
        f"💠 Usul: *{payment_method_label(method)}*\n"
        f"💵 Summa: *{amount}*\n"
        f"🕐 {now_str()}"
    )
    markup = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("✅ Tasdiqlash", callback_data=f"pay_approve_{payment_id}"),
                InlineKeyboardButton("❌ Bekor qilish", callback_data=f"pay_reject_{payment_id}"),
            ]
        ]
    )
    admin_msg = await send_fn(
        ADMIN_ID,
        send_arg,
        caption=caption,
        parse_mode=enums.ParseMode.MARKDOWN,
        reply_markup=markup,
    )
    set_payment_admin_message(payment_id, admin_msg.chat.id, admin_msg.id)
    await safe_delete(message)
    await client.send_message(
        message.chat.id,
        tx(uid, "payment_submitted"),
        parse_mode=enums.ParseMode.MARKDOWN,
        reply_markup=main_menu(uid),
    )
    return True


# ============================================================
# BROADCAST
# ============================================================
async def handle_admin_broadcast(client, message: Message):
    uid = message.from_user.id if message.from_user else 0
    target = admin_broadcast_target.get(uid)
    if uid != ADMIN_ID or not target:
        return False

    admin_broadcast_target.pop(uid, None)
    recipients = get_broadcast_recipients(target)
    ok = 0
    fail = 0
    progress = await client.send_message(message.chat.id, "📨 Broadcast boshlandi...")
    for target_uid in recipients:
        try:
            await client.copy_message(target_uid, message.chat.id, message.id)
            ok += 1
        except Exception:
            fail += 1
    await safe_delete(progress)
    await client.send_message(
        message.chat.id,
        f"📨 *Broadcast tugadi!*\n\n✅ *{ok}*\n❌ *{fail}*",
        parse_mode=enums.ParseMode.MARKDOWN,
    )
    try:
        await safe_delete(message)
    except Exception:
        pass
    return True


# ============================================================
# ZIP CORE
# ============================================================
async def _auto_zip_runner(client, chat_id: int, uid: int, delay: int, user_obj=None):
    await asyncio.sleep(delay)
    while user_downloading.get(uid, 0) > 0:
        await asyncio.sleep(3)
    if file_count(uid) == 0:
        return
    sm = user_status_msg.pop(uid, None)
    await safe_delete(sm)
    auto_name = make_zip_name(user_obj) if user_obj else f"auto_{datetime.now():%Y%m%d_%H%M%S}"
    await create_and_send_zip(client, chat_id, uid, auto_name, auto=True, priority=is_premium(uid))


def start_auto_zip(client, chat_id: int, uid: int, delay: int = AUTO_ZIP_DELAY, user_obj=None):
    schedule_task(user_auto_zip, uid, _auto_zip_runner(client, chat_id, uid, delay, user_obj))


async def create_and_send_zip(client, chat_id: int, uid: int, zip_name_raw: str, auto: bool = False, priority: bool = False):
    global ZIP_SEMAPHORE
    if ZIP_SEMAPHORE is None:
        ZIP_SEMAPHORE = asyncio.Semaphore(2)

    folder = user_dir(uid)
    files = [f for f in os.listdir(folder) if os.path.isfile(os.path.join(folder, f))]
    if not files:
        return

    zip_name = f"{os.path.splitext(zip_name_raw)[0]}.zip"
    zip_path = os.path.join(folder, zip_name)
    existing_sm = user_status_msg.get(uid)
    progress = None

    try:
        if existing_sm:
            try:
                await existing_sm.edit_text(tx(uid, "creating_zip"), parse_mode=enums.ParseMode.MARKDOWN)
            except Exception:
                existing_sm = None
        if not existing_sm:
            progress = await client.send_message(
                chat_id,
                tx(uid, "creating_zip"),
                parse_mode=enums.ParseMode.MARKDOWN,
                reply_markup=main_menu(uid),
            )

        queue_msg = None
        if not priority and ZIP_SEMAPHORE.locked():
            queue_msg = await client.send_message(chat_id, tx(uid, "zip_queue"), parse_mode=enums.ParseMode.MARKDOWN)

        if priority:
            await _run_zip_job(client, chat_id, uid, zip_name, zip_path, files, folder, auto)
        else:
            async with ZIP_SEMAPHORE:
                if queue_msg:
                    await safe_delete(queue_msg)
                await _run_zip_job(client, chat_id, uid, zip_name, zip_path, files, folder, auto)
    except Exception as e:
        await client.send_message(chat_id, tx(uid, "zip_error"), parse_mode=enums.ParseMode.MARKDOWN)
        await error_to_admin(client, "create_and_send_zip", uid, e)
    finally:
        await safe_delete(progress)
        sm = user_status_msg.pop(uid, None)
        await safe_delete(sm)
        waiting_for_zip_name.pop(uid, None)
        user_auto_zip.pop(uid, None)


async def _run_zip_job(client, chat_id: int, uid: int, zip_name: str, zip_path: str, files: list, folder: str, auto: bool):
    fcount = len(files)
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_STORED) as zf:
        for fname in files:
            fpath = os.path.join(folder, fname)
            if os.path.isfile(fpath) and fname != zip_name:
                zf.write(fpath, arcname=fname)

    zip_size = os.path.getsize(zip_path) if os.path.exists(zip_path) else 0
    caption = tx(uid, "zip_caption")
    if auto:
        caption = f"{tx(uid, 'auto_zip_done')}\n\n{caption}"

    await client.send_document(
        chat_id,
        zip_path,
        caption=caption,
        file_name=zip_name,
        parse_mode=enums.ParseMode.MARKDOWN,
    )
    add_zip_stat(uid, zip_size / 1024 / 1024, fcount)

    try:
        shutil.rmtree(folder)
        os.makedirs(folder, exist_ok=True)
    except Exception as e:
        print(f"[cleanup] {e}")


async def prompt_premium_zip_name(client, chat_id: int, uid: int, user):
    waiting_for_zip_name[uid] = {"chat_id": chat_id, "user": user}
    await client.send_message(
        chat_id,
        tx(uid, "premium_name_prompt"),
        parse_mode=enums.ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup(
            [
                [InlineKeyboardButton(tx(uid, "premium_name_default"), callback_data="zip_name_default")],
                [InlineKeyboardButton(tx(uid, "premium_name_cancel"), callback_data="zip_name_cancel")],
            ]
        ),
    )


# ============================================================
# FILE RECEIVING
# ============================================================
async def receive_file(client, message: Message, obj, filename: str):
    uid = message.from_user.id

    if is_banned(uid):
        await safe_delete(message)
        return

    await maybe_send_premium_expiry_warning(client, uid, message.chat.id)

    if uid in waiting_for_payment_screenshot:
        await safe_delete(message)
        await client.send_message(
            message.chat.id,
            "📸 Avval to'lov skrinshotini rasm yoki document ko'rinishida yuboring.",
            reply_markup=main_menu(uid),
        )
        return

    lang = get_lang(uid) or "uz"
    if not await gate_check(client, uid, message.chat.id, lang):
        await safe_delete(message)
        return

    limits = get_limits(uid)
    if get_daily_zip_count(uid) >= limits["daily_zips"]:
        await safe_delete(message)
        schedule_limit_msg(client, message.chat.id, uid)
        return

    fsize = getattr(obj, "file_size", 0) or 0
    used_now = disk_used(uid) + user_reserved_bytes.get(uid, 0)
    current_count = file_count(uid) + user_downloading.get(uid, 0)

    if current_count >= limits["files"]:
        await safe_delete(message)
        user_excess[uid] = user_excess.get(uid, 0) + 1
        schedule_task(user_debounce, uid, _send_excess_msg(client, message.chat.id, uid))
        return

    if used_now + fsize > limits["storage"]:
        await safe_delete(message)
        user_storage_rej[uid] = user_storage_rej.get(uid, 0) + 1

        async def _send_storage_full_msg(chat_id: int, target_uid: int):
            await asyncio.sleep(DEBOUNCE_SEC)
            rejected = user_storage_rej.pop(target_uid, 0)
            accepted = file_count(target_uid)
            msg_text = tx(
                target_uid,
                "storage_full",
                accepted=accepted,
                rejected=rejected,
                used=fmt_size(disk_used(target_uid)),
                max_size=fmt_size(limits["storage"]),
            )
            sm = user_status_msg.pop(target_uid, None)
            await safe_delete(sm)
            user_status_msg[target_uid] = await client.send_message(
                chat_id,
                msg_text,
                parse_mode=enums.ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup(
                    [[InlineKeyboardButton(tx(target_uid, "ready_btn"), callback_data="zip_now")]]
                ),
            )

        schedule_task(user_debounce, uid, _send_storage_full_msg(message.chat.id, uid))
        return

    user_reserved_bytes[uid] = user_reserved_bytes.get(uid, 0) + fsize
    user_downloading[uid] = user_downloading.get(uid, 0) + 1
    restart_debounce(client, message.chat.id, uid)

    folder = user_dir(uid)
    safe_name = sanitize_filename(filename)
    save_path = unique_path(folder, safe_name)
    try:
        await message.download(file_name=save_path)
    except Exception as e:
        await error_to_admin(client, "receive_file.download", uid, e)
    finally:
        user_downloading[uid] = max(0, user_downloading.get(uid, 1) - 1)
        user_reserved_bytes[uid] = max(0, user_reserved_bytes.get(uid, fsize) - fsize)

    await safe_delete(message)
    restart_debounce(client, message.chat.id, uid)
    await cancel_task(user_auto_zip, uid)
    start_auto_zip(client, message.chat.id, uid, user_obj=message.from_user)


# ============================================================
# APP
# ============================================================
app = Client("zip_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)


def _is_admin(_, __, query):
    return query.from_user.id == ADMIN_ID


admin_filter = filters.create(_is_admin)


# ============================================================
# START / LANGUAGE / JOIN
# ============================================================
@app.on_message(filters.command("start"))
async def cmd_start(client, message):
    uid = message.from_user.id
    await safe_delete(message)
    if is_banned(uid):
        return

    await maybe_send_premium_expiry_warning(client, uid, message.chat.id)

    lang = get_lang(uid)
    if lang is None:
        upsert_user(message.from_user, "uz")
        sent = await client.send_message(
            message.chat.id,
            TEXTS["uz"]["choose_lang"],
            reply_markup=InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton("🇺🇿 O'zbek", callback_data="setlang_uz"),
                        InlineKeyboardButton("🇬🇧 English", callback_data="setlang_en"),
                    ]
                ]
            ),
        )
        user_welcome_msg[uid] = sent
        return

    upsert_user(message.from_user, lang)

    old_welcome = user_welcome_msg.pop(uid, None)
    await safe_delete(old_welcome)

    welcome = await client.send_message(
        message.chat.id,
        tx(uid, "welcome", name=message.from_user.first_name or "User"),
        parse_mode=enums.ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup(
            [[InlineKeyboardButton(tx(uid, "change_lang"), callback_data="change_lang")]]
        ),
    )
    user_welcome_msg[uid] = welcome

    await client.send_message(
        message.chat.id,
        f"⭐ {tx(uid, 'premium_btn')}",
        reply_markup=main_menu(uid),
    )

    if required_channels:
        await gate_check(client, uid, message.chat.id, lang)


@app.on_callback_query(filters.create(lambda _, __, q: q.data.startswith("setlang_")))
async def cb_set_lang(client, call):
    uid = call.from_user.id
    lang = call.data.split("_", 1)[1]
    upsert_user(call.from_user, lang)
    await safe_delete(call.message)
    user_welcome_msg.pop(uid, None)
    welcome = await client.send_message(
        call.message.chat.id,
        tx(uid, "welcome", name=call.from_user.first_name or "User"),
        parse_mode=enums.ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup(
            [[InlineKeyboardButton(tx(uid, "change_lang"), callback_data="change_lang")]]
        ),
    )
    user_welcome_msg[uid] = welcome
    await client.send_message(
        call.message.chat.id,
        f"⭐ {tx(uid, 'premium_btn')}",
        reply_markup=main_menu(uid),
    )
    await send_sticker(client, call.message.chat.id, "start")
    await call.answer(tx(uid, "lang_set"))
    if required_channels:
        await gate_check(client, uid, call.message.chat.id, lang)


@app.on_callback_query(filters.create(lambda _, __, q: q.data == "change_lang"))
async def cb_change_lang(client, call):
    uid = call.from_user.id
    await safe_delete(call.message)
    sent = await client.send_message(
        call.message.chat.id,
        TEXTS["uz"]["choose_lang"],
        reply_markup=InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton("🇺🇿 O'zbek", callback_data="setlang_uz"),
                    InlineKeyboardButton("🇬🇧 English", callback_data="setlang_en"),
                ]
            ]
        ),
    )
    user_welcome_msg[uid] = sent
    await call.answer()


@app.on_callback_query(filters.create(lambda _, __, q: q.data == "check_join"))
async def cb_check_join(client, call):
    uid = call.from_user.id
    lang = get_lang(uid) or "uz"
    await maybe_send_premium_expiry_warning(client, uid, call.message.chat.id)
    missing = await check_subscription(client, uid)
    if missing:
        await call.answer(TEXTS[lang]["join_fail"], show_alert=True)
    else:
        user_join_msg.pop(uid, None)
        await safe_delete(call.message)
        await call.answer(TEXTS[lang]["join_ok"], show_alert=True)


# ============================================================
# PREMIUM CALLBACKS
# ============================================================
@app.on_callback_query(filters.create(lambda _, __, q: q.data == "premium_crypto_menu"))
async def cb_premium_crypto_menu(client, call):
    uid = call.from_user.id
    await call.message.edit_text(
        tx(uid, "premium_choose_crypto"),
        parse_mode=enums.ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup(
            [
                [InlineKeyboardButton("USDT (BEP20)", callback_data="premium_method_usdt_bep20")],
                [InlineKeyboardButton("USDT (TRC20)", callback_data="premium_method_usdt_trc20")],
                [InlineKeyboardButton("USDT (Plasma/Polygon)", callback_data="premium_method_usdt_polygon")],
                [InlineKeyboardButton("⬅️ Orqaga", callback_data="premium_back")],
            ]
        ),
    )
    await call.answer()


@app.on_callback_query(filters.create(lambda _, __, q: q.data == "premium_back"))
async def cb_premium_back(client, call):
    await show_premium_menu(client, call.message.chat.id, call.from_user.id)
    await safe_delete(call.message)
    await call.answer()


@app.on_callback_query(filters.create(lambda _, __, q: q.data.startswith("premium_method_")))
async def cb_premium_method(client, call):
    method = call.data.replace("premium_method_", "", 1)
    await show_payment_details(client, call.message.chat.id, call.from_user.id, method, message_to_edit=call.message)
    await call.answer()


@app.on_callback_query(filters.create(lambda _, __, q: q.data.startswith("premium_paid_")))
async def cb_premium_paid(client, call):
    method = call.data.replace("premium_paid_", "", 1)
    await ask_for_payment_screenshot(client, call.message.chat.id, call.from_user.id, method)
    await call.answer()


# ============================================================
# ZIP CALLBACKS
# ============================================================
@app.on_callback_query(filters.create(lambda _, __, q: q.data == "zip_now"))
async def cb_zip_now(client, call):
    uid = call.from_user.id
    user = call.from_user
    await maybe_send_premium_expiry_warning(client, uid, call.message.chat.id)

    if file_count(uid) == 0:
        await call.answer(tx(uid, "no_files"), show_alert=True)
        return

    limits = get_limits(uid)
    if get_daily_zip_count(uid) >= limits["daily_zips"]:
        sm = user_status_msg.pop(uid, None)
        await safe_delete(sm)
        await client.send_message(
            call.message.chat.id,
            tx(uid, "daily_limit"),
            parse_mode=enums.ParseMode.MARKDOWN,
            reply_markup=main_menu(uid),
        )
        await call.answer()
        return

    if user_downloading.get(uid, 0) > 0:
        await call.answer(tx(uid, "zip_wait"), show_alert=True)
        return

    await cancel_task(user_auto_zip, uid)
    await cancel_task(user_debounce, uid)

    sm = user_status_msg.pop(uid, None)
    await safe_delete(sm)

    if is_premium(uid):
        await client.send_message(
            call.message.chat.id,
            tx(uid, "premium_priority_started"),
            parse_mode=enums.ParseMode.MARKDOWN,
            reply_markup=main_menu(uid),
        )
        await prompt_premium_zip_name(client, call.message.chat.id, uid, user)
    else:
        await create_and_send_zip(
            client,
            call.message.chat.id,
            uid,
            make_zip_name(user),
            priority=False,
        )
    await call.answer()


@app.on_callback_query(filters.create(lambda _, __, q: q.data == "zip_name_default"))
async def cb_zip_name_default(client, call):
    uid = call.from_user.id
    payload = waiting_for_zip_name.get(uid)
    if not payload:
        await call.answer()
        return
    await safe_delete(call.message)
    await create_and_send_zip(
        client,
        payload["chat_id"],
        uid,
        make_zip_name(payload["user"]),
        priority=True,
    )
    await call.answer()


@app.on_callback_query(filters.create(lambda _, __, q: q.data == "zip_name_cancel"))
async def cb_zip_name_cancel(client, call):
    uid = call.from_user.id
    waiting_for_zip_name.pop(uid, None)
    await safe_delete(call.message)
    await client.send_message(call.message.chat.id, tx(uid, "premium_name_cancelled"), reply_markup=main_menu(uid))
    await call.answer()


# ============================================================
# PAYMENT ADMIN CALLBACKS
# ============================================================
@app.on_callback_query(admin_filter & filters.create(lambda _, __, q: q.data.startswith("pay_approve_")))
async def cb_payment_approve(client, call):
    payment_id = int(call.data.replace("pay_approve_", "", 1))
    payment = get_payment(payment_id)
    if not payment or payment[3] != "pending":
        await call.answer("Bu to'lov allaqachon ko'rib chiqilgan.", show_alert=True)
        return
    expiry = grant_premium(payment[1], PREMIUM_DAYS)
    approve_payment(payment_id)
    try:
        await call.message.edit_caption(
            f"{call.message.caption}\n\n✅ *Tasdiqlandi*\n⏳ Premium muddati: *{expiry.strftime('%Y-%m-%d %H:%M:%S')}*",
            parse_mode=enums.ParseMode.MARKDOWN,
            reply_markup=None,
        )
    except Exception:
        pass
    try:
        await client.send_message(
            payment[1],
            tx(payment[1], "payment_approved"),
            parse_mode=enums.ParseMode.MARKDOWN,
            reply_markup=main_menu(payment[1]),
        )
    except Exception:
        pass
    await call.answer("Premium berildi.")


@app.on_callback_query(admin_filter & filters.create(lambda _, __, q: q.data.startswith("pay_reject_")))
async def cb_payment_reject(client, call):
    payment_id = int(call.data.replace("pay_reject_", "", 1))
    payment = get_payment(payment_id)
    if not payment or payment[3] != "pending":
        await call.answer("Bu to'lov allaqachon ko'rib chiqilgan.", show_alert=True)
        return
    waiting_for_admin_input[ADMIN_ID] = {"action": "reject_payment", "payment_id": payment_id}
    await client.send_message(
        call.message.chat.id,
        f"❌ To'lov #{payment_id} uchun rad etish sababini yozing.",
    )
    await call.answer()


# ============================================================
# MEDIA / FILE HANDLERS
# ============================================================
@app.on_message(filters.document)
async def on_document(client, message):
    if await handle_admin_broadcast(client, message):
        return
    if await handle_payment_screenshot(client, message):
        return
    doc = message.document
    await receive_file(client, message, doc, doc.file_name or f"file_{datetime.now():%Y%m%d_%H%M%S}")


@app.on_message(filters.photo)
async def on_photo(client, message):
    if await handle_admin_broadcast(client, message):
        return
    if await handle_payment_screenshot(client, message):
        return
    await receive_file(client, message, message.photo, f"photo_{datetime.now():%Y%m%d_%H%M%S}.jpg")


@app.on_message(filters.video)
async def on_video(client, message):
    if await handle_admin_broadcast(client, message):
        return
    video = message.video
    await receive_file(client, message, video, video.file_name or f"video_{datetime.now():%Y%m%d_%H%M%S}.mp4")


@app.on_message(filters.audio)
async def on_audio(client, message):
    if await handle_admin_broadcast(client, message):
        return
    audio = message.audio
    await receive_file(client, message, audio, audio.file_name or f"audio_{datetime.now():%Y%m%d_%H%M%S}.mp3")


@app.on_message(filters.voice)
async def on_voice(client, message):
    if await handle_admin_broadcast(client, message):
        return
    await receive_file(client, message, message.voice, f"voice_{datetime.now():%Y%m%d_%H%M%S}.ogg")


@app.on_message(filters.video_note)
async def on_video_note(client, message):
    if await handle_admin_broadcast(client, message):
        return
    await receive_file(client, message, message.video_note, f"videonote_{datetime.now():%Y%m%d_%H%M%S}.mp4")


@app.on_message(filters.sticker)
async def on_sticker(client, message):
    if await handle_admin_broadcast(client, message):
        return
    await receive_file(client, message, message.sticker, f"sticker_{datetime.now():%Y%m%d_%H%M%S}.webp")


@app.on_message(filters.animation)
async def on_animation(client, message):
    if await handle_admin_broadcast(client, message):
        return
    animation = message.animation
    await receive_file(client, message, animation, animation.file_name or f"gif_{datetime.now():%Y%m%d_%H%M%S}.gif")


# ============================================================
# TEXT HANDLER
# ============================================================
@app.on_message(filters.text & ~filters.command(["start", "admin"]))
async def on_text(client, message):
    uid = message.from_user.id

    if is_banned(uid):
        await safe_delete(message)
        return

    await maybe_send_premium_expiry_warning(client, uid, message.chat.id)

    if get_lang(uid) is None:
        upsert_user(message.from_user, "uz")
        await safe_delete(message)
        await client.send_message(
            message.chat.id,
            TEXTS["uz"]["choose_lang"],
            reply_markup=InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton("🇺🇿 O'zbek", callback_data="setlang_uz"),
                        InlineKeyboardButton("🇬🇧 English", callback_data="setlang_en"),
                    ]
                ]
            ),
        )
        return

    admin_payload = waiting_for_admin_input.get(uid)
    if uid == ADMIN_ID and admin_payload:
        waiting_for_admin_input.pop(uid, None)
        raw = message.text.strip()
        action = admin_payload["action"]

        if action == "add_channel":
            normalized = raw.replace("https://t.me/", "@").replace("http://t.me/", "@").replace("t.me/", "@")
            try:
                chat = await client.get_chat(normalized)
                username = (getattr(chat, "username", None) or "").lstrip("@")
                invite_link = ""
                if not username:
                    try:
                        invite_link = await client.export_chat_invite_link(chat.id)
                    except Exception:
                        pass
                if not username and not invite_link:
                    await message.reply("❌ Kanal public emas va invite link olinmadi.")
                    return
                add_channel(chat.id, chat.title or normalized, username=username, invite_link=invite_link)
                ref = f"@{username}" if username else invite_link
                await message.reply(
                    f"✅ Kanal qo'shildi: *{chat.title}*\n🔗 `{ref}`\n🆔 `{chat.id}`",
                    parse_mode=enums.ParseMode.MARKDOWN,
                )
            except Exception:
                await message.reply("❌ Kanal topilmadi.")
            return

        if action == "ban":
            try:
                target_id = int(re.search(r"\d+", raw).group())
            except Exception:
                await message.reply("❌ Noto'g'ri ID.")
                return
            data = get_user_by_id(target_id)
            if not data:
                await message.reply("❌ Foydalanuvchi topilmadi.")
                return
            ban_user(target_id)
            await message.reply(f"⛔ `{target_id}` bloklandi.", parse_mode=enums.ParseMode.MARKDOWN)
            try:
                await client.send_message(target_id, tx(target_id, "banned"))
            except Exception:
                pass
            return

        if action == "unban":
            try:
                target_id = int(re.search(r"\d+", raw).group())
            except Exception:
                await message.reply("❌ Noto'g'ri ID.")
                return
            data = get_user_by_id(target_id)
            if not data:
                await message.reply("❌ Foydalanuvchi topilmadi.")
                return
            unban_user(target_id)
            await message.reply(f"✅ `{target_id}` blokdan chiqarildi.", parse_mode=enums.ParseMode.MARKDOWN)
            return

        if action == "info":
            try:
                target_id = int(re.search(r"\d+", raw).group())
            except Exception:
                await message.reply("❌ Noto'g'ri ID.")
                return
            data = get_user_by_id(target_id)
            if not data:
                await message.reply("❌ Foydalanuvchi topilmadi.")
                return
            tid, fn, ln, un, lg, jd, banned, premium, expiry, daily_count = data
            limits = PREMIUM_LIMITS if premium else FREE_LIMITS
            premium_status = "Ha" if premium else "Yoq"
            await message.reply(
                f"👤 *Foydalanuvchi*\n\n"
                f"🆔 `{tid}`\n"
                f"📛 {fn} {ln}\n"
                f"🔗 @{un if un else 'yoq'}\n"
                f"🌍 {lg.upper()} | 📅 {jd[:16]}\n"
                f"⭐ Premium: *{premium_status}*\n"
                f"⏳ Expiry: `{expiry or '-'}`\n"
                f"📦 Bugungi ZIP: *{daily_count}/{limits['daily_zips']}*\n"
                f"💾 Disk: *{fmt_size(disk_used(tid))}*",
                parse_mode=enums.ParseMode.MARKDOWN,
            )
            return

        if action == "clear":
            try:
                target_id = int(re.search(r"\d+", raw).group())
            except Exception:
                await message.reply("❌ Noto'g'ri ID.")
                return
            folder = os.path.join(BASE_DIR, str(target_id))
            if os.path.exists(folder):
                shutil.rmtree(folder)
                os.makedirs(folder, exist_ok=True)
            await message.reply(f"🗑️ `{target_id}` fayllari tozalandi.", parse_mode=enums.ParseMode.MARKDOWN)
            return

        if action.startswith("set_setting:"):
            setting_key = action.split(":", 1)[1]
            set_setting(setting_key, raw)
            await message.reply(tx(uid, "settings_saved"), reply_markup=main_menu(uid))
            return

        if action == "reject_payment":
            payment_id = admin_payload["payment_id"]
            payment = get_payment(payment_id)
            if not payment or payment[3] != "pending":
                await message.reply("❌ Bu to'lov allaqachon ko'rib chiqilgan.")
                return
            reject_payment(payment_id, raw)
            try:
                await client.send_message(
                    payment[1],
                    tx(payment[1], "payment_rejected", reason=raw),
                    parse_mode=enums.ParseMode.MARKDOWN,
                    reply_markup=main_menu(payment[1]),
                )
            except Exception:
                pass
            if payment[6] and payment[7]:
                try:
                    await client.edit_message_caption(
                        payment[6],
                        payment[7],
                        caption=(
                            f"💳 *Premium to'lov arizasi*\n\n"
                            f"🆔 To'lov ID: `{payment_id}`\n"
                            f"👤 Foydalanuvchi: `{payment[1]}`\n"
                            f"❌ *Rad etildi*\n"
                            f"Sabab: {raw}"
                        ),
                        parse_mode=enums.ParseMode.MARKDOWN,
                        reply_markup=None,
                    )
                except Exception:
                    pass
            await message.reply("✅ Rad etish sababi yuborildi.")
            return

    if uid == ADMIN_ID and await handle_admin_broadcast(client, message):
        return

    if uid in waiting_for_zip_name:
        payload = waiting_for_zip_name.pop(uid)
        custom = message.text.strip()
        await safe_delete(message)
        await create_and_send_zip(
            client,
            payload["chat_id"],
            uid,
            make_zip_name(payload["user"], custom_name=custom),
            priority=True,
        )
        return

    if message.text == tx(uid, "premium_btn"):
        lang = get_lang(uid) or "uz"
        if not await gate_check(client, uid, message.chat.id, lang):
            await safe_delete(message)
            return
        await safe_delete(message)
        await show_premium_menu(client, message.chat.id, uid)
        return

    await safe_delete(message)


# ============================================================
# ADMIN PANEL
# ============================================================
@app.on_message(filters.command("admin") & filters.user(ADMIN_ID))
async def cmd_admin(client, message):
    stats = get_global_stats()
    disk = fmt_size(total_disk_all())
    await send_sticker(client, message.chat.id, "admin")
    await message.reply(
        f"🔐 *Admin Panel*\n\n"
        f"👥 Jami: *{user_count()}* | 📅 Bugun: *{today_count()}*\n"
        f"⭐ Oddiy: *{stats['free_users']}* | Premium: *{stats['premium_users']}*\n"
        f"💾 Disk: *{disk}*\n\n"
        f"📦 Jami ZIP: *{stats['total_zips']}* (bugun: *{stats['today_zips']}*)\n"
        f"📊 Jami MB: *{stats['total_mb']:.1f}* (bugun: *{stats['today_mb']:.1f}*)\n"
        f"📎 Jami fayl: *{stats['total_files']}*",
        parse_mode=enums.ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton("👥 Foydalanuvchilar", callback_data="adm_users"),
                    InlineKeyboardButton("📊 Statistika", callback_data="adm_stats"),
                ],
                [
                    InlineKeyboardButton("📨 Broadcast", callback_data="adm_broadcast"),
                    InlineKeyboardButton("🔍 Foydalanuvchi", callback_data="adm_search"),
                ],
                [
                    InlineKeyboardButton("⛔ Ban", callback_data="adm_ban"),
                    InlineKeyboardButton("✅ Unban", callback_data="adm_unban"),
                ],
                [
                    InlineKeyboardButton("🗑️ Tozalash", callback_data="adm_clear"),
                    InlineKeyboardButton("💾 Disk", callback_data="adm_disk"),
                ],
                [
                    InlineKeyboardButton("📢 Kanallar", callback_data="adm_channels"),
                    InlineKeyboardButton("💳 Premium to'lovlar", callback_data="adm_payments"),
                ],
                [
                    InlineKeyboardButton("🧾 Rekvizitlar", callback_data="adm_settings"),
                    InlineKeyboardButton("🔁 DB", callback_data="adm_volume"),
                ],
            ]
        ),
    )


@app.on_callback_query(admin_filter & filters.create(lambda _, __, q: q.data == "adm_users"))
async def adm_users(client, call):
    rows = all_users()
    if not rows:
        await call.message.reply("Foydalanuvchilar yo'q.")
        await call.answer()
        return
    lines = ["👥 *Oxirgi foydalanuvchilar*:\n"]
    for index, row in enumerate(rows[:30], 1):
        tid, fn, ln, un, lg, jd, banned, premium, expiry, daily_count = row
        full = f"{fn} {ln}".strip() or "-"
        uname = f"@{un}" if un else "-"
        badge = " ⭐" if premium else ""
        if banned:
            badge += " 🚫"
        lines.append(f"`{index}.` {full}{badge} | {uname}\n   🆔 `{tid}` | {lg.upper()} | {jd[:10]}")
    if len(rows) > 30:
        lines.append(f"\n... va yana *{len(rows) - 30}* ta")
    text = "\n".join(lines)
    for chunk in [text[i : i + 4000] for i in range(0, len(text), 4000)]:
        await call.message.reply(chunk, parse_mode=enums.ParseMode.MARKDOWN)
    await call.answer()


@app.on_callback_query(admin_filter & filters.create(lambda _, __, q: q.data == "adm_stats"))
async def adm_stats(client, call):
    from datetime import timedelta as td

    users = all_users()
    stats = get_global_stats()
    today_value = today_str()
    today_new = sum(1 for row in users if (row[5] or "").startswith(today_value))
    uz_count = sum(1 for row in users if row[4] == "uz")
    en_count = sum(1 for row in users if row[4] == "en")
    week = []
    for offset in range(6, -1, -1):
        day = (datetime.now() - td(days=offset)).strftime("%Y-%m-%d")
        joined = sum(1 for row in users if (row[5] or "").startswith(day))
        zip_row = get_db().execute(
            "SELECT COALESCE(SUM(zip_count),0), COALESCE(SUM(total_mb),0) FROM zip_stats WHERE date=?",
            (day,),
        ).fetchone()
        bar = "█" * min(joined, 15)
        week.append(f"`{day[5:]}` {bar} *{joined}* foyda | *{zip_row[0]}* zip | *{zip_row[1]:.1f}* MB")
    await call.message.reply(
        f"📊 *Statistika*\n\n"
        f"👥 Jami: *{len(users)}* | 📅 Bugun: *{today_new}*\n"
        f"⭐ Oddiy: *{stats['free_users']}* | Premium: *{stats['premium_users']}*\n"
        f"🇺🇿 *{uz_count}* | 🇬🇧 *{en_count}*\n\n"
        f"📦 Jami ZIP: *{stats['total_zips']}* | Bugun: *{stats['today_zips']}*\n"
        f"📊 Jami MB: *{stats['total_mb']:.1f}* | Bugun: *{stats['today_mb']:.1f}*\n"
        f"📎 Jami fayl: *{stats['total_files']}*\n\n"
        f"📈 *Oxirgi 7 kun:*\n" + "\n".join(week),
        parse_mode=enums.ParseMode.MARKDOWN,
    )
    await call.answer()


@app.on_callback_query(admin_filter & filters.create(lambda _, __, q: q.data == "adm_disk"))
async def adm_disk(client, call):
    rows = all_users_disk()
    if not rows:
        await call.message.reply("💾 Disk bo'sh.")
        await call.answer()
        return
    user_map = {row[0]: row for row in all_users()}
    total_used = sum(item[1] for item in rows)
    lines = [f"💾 *Disk statistikasi*\nUmumiy: *{fmt_size(total_used)}*\n"]
    for idx, (uid, used) in enumerate(rows[:30], 1):
        user = user_map.get(uid)
        name = f"{user[1]} {user[2]}".strip() if user else "Noma'lum"
        username = f"@{user[3]}" if user and user[3] else "-"
        max_size = PREMIUM_LIMITS["storage"] if user and user[7] else FREE_LIMITS["storage"]
        pct = used / max_size * 100 if max_size else 0
        lines.append(f"`{idx}.` {name} ({username})\n   🆔 `{uid}` | {fmt_size(used)} ({pct:.1f}%)")
    text = "\n".join(lines)
    for chunk in [text[i : i + 4000] for i in range(0, len(text), 4000)]:
        await call.message.reply(chunk, parse_mode=enums.ParseMode.MARKDOWN)
    await call.answer()


@app.on_callback_query(admin_filter & filters.create(lambda _, __, q: q.data == "adm_broadcast"))
async def adm_broadcast(client, call):
    await call.message.reply(
        "📨 Broadcast targetni tanlang:",
        reply_markup=InlineKeyboardMarkup(
            [
                [InlineKeyboardButton("👥 Hammaga", callback_data="broadcast_target_all")],
                [InlineKeyboardButton("🙂 Faqat oddiy foydalanuvchilarga", callback_data="broadcast_target_free")],
                [InlineKeyboardButton("⭐ Faqat Premium foydalanuvchilarga", callback_data="broadcast_target_premium")],
            ]
        ),
    )
    await call.answer()


@app.on_callback_query(admin_filter & filters.create(lambda _, __, q: q.data.startswith("broadcast_target_")))
async def adm_broadcast_target(client, call):
    target = call.data.replace("broadcast_target_", "", 1)
    admin_broadcast_target[ADMIN_ID] = target
    await call.message.reply(
        "📨 Endi yubormoqchi bo'lgan text yoki media xabaringizni yuboring.\n"
        "Bot uni formatini buzmasdan copy qiladi."
    )
    await call.answer()


@app.on_callback_query(admin_filter & filters.create(lambda _, __, q: q.data == "adm_search"))
async def adm_search(client, call):
    waiting_for_admin_input[ADMIN_ID] = {"action": "info"}
    await call.message.reply("🔍 Foydalanuvchi ID sini yuboring:")
    await call.answer()


@app.on_callback_query(admin_filter & filters.create(lambda _, __, q: q.data == "adm_ban"))
async def adm_ban(client, call):
    waiting_for_admin_input[ADMIN_ID] = {"action": "ban"}
    await call.message.reply("⛔ Ban qilinadigan foydalanuvchi ID sini yuboring:")
    await call.answer()


@app.on_callback_query(admin_filter & filters.create(lambda _, __, q: q.data == "adm_unban"))
async def adm_unban(client, call):
    waiting_for_admin_input[ADMIN_ID] = {"action": "unban"}
    await call.message.reply("✅ Unban qilinadigan foydalanuvchi ID sini yuboring:")
    await call.answer()


@app.on_callback_query(admin_filter & filters.create(lambda _, __, q: q.data == "adm_clear"))
async def adm_clear(client, call):
    waiting_for_admin_input[ADMIN_ID] = {"action": "clear"}
    await call.message.reply("🗑️ Fayllari tozalanadigan foydalanuvchi ID sini yuboring:")
    await call.answer()


@app.on_callback_query(admin_filter & filters.create(lambda _, __, q: q.data == "adm_channels"))
async def adm_channels(client, call):
    channels = get_channels()
    if channels:
        text = "📢 *Majburiy kanallar:*\n\n" + "\n".join(
            f"• {info['title']} — `{('@' + info['username']) if info.get('username') else (info.get('invite_link') or 'link yoq')}` (`{cid}`)"
            for cid, info in channels.items()
        )
    else:
        text = "📢 Hozircha kanal qo'shilmagan."
    buttons = [
        [InlineKeyboardButton(f"🗑 {info['title']} o'chirish", callback_data=f"adm_rmchan_{cid}")]
        for cid, info in channels.items()
    ]
    buttons.append([InlineKeyboardButton("➕ Kanal qo'shish", callback_data="adm_addchan")])
    await call.message.reply(text, parse_mode=enums.ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(buttons))
    await call.answer()


@app.on_callback_query(admin_filter & filters.create(lambda _, __, q: q.data == "adm_addchan"))
async def adm_addchan(client, call):
    waiting_for_admin_input[ADMIN_ID] = {"action": "add_channel"}
    await call.message.reply("📢 Kanal username yoki ID sini yuboring:\n`@kanal` yoki `-1001234567890`", parse_mode=enums.ParseMode.MARKDOWN)
    await call.answer()


@app.on_callback_query(admin_filter & filters.create(lambda _, __, q: q.data.startswith("adm_rmchan_")))
async def adm_rmchan(client, call):
    try:
        cid = int(call.data.replace("adm_rmchan_", "", 1))
        title = required_channels.get(cid, {}).get("title", str(cid))
        remove_channel(cid)
        await call.message.reply(f"✅ *{title}* o'chirildi.", parse_mode=enums.ParseMode.MARKDOWN)
    except Exception:
        await call.answer("Xato", show_alert=True)
        return
    await call.answer()


@app.on_callback_query(admin_filter & filters.create(lambda _, __, q: q.data == "adm_payments"))
async def adm_payments(client, call):
    payments = list_pending_payments()
    if not payments:
        await call.message.reply("💳 Kutilayotgan Premium to'lovlar yo'q.")
        await call.answer()
        return
    lines = ["💳 *Kutilayotgan Premium to'lovlar:*\n"]
    for payment_id, user_id, method, amount, created_at in payments:
        lines.append(
            f"ID: `{payment_id}` | 👤 `{user_id}`\n"
            f"   💠 {payment_method_label(method)} | 💵 {amount or '-'} | 🕐 {created_at[:16]}"
        )
    lines.append("\nTasdiqlash/rad etish skrinshot ostidagi tugmalar orqali bajariladi.")
    await call.message.reply("\n".join(lines), parse_mode=enums.ParseMode.MARKDOWN)
    await call.answer()


@app.on_callback_query(admin_filter & filters.create(lambda _, __, q: q.data == "adm_settings"))
async def adm_settings(client, call):
    settings_map = get_all_payment_settings()
    text = (
        "🧾 *To'lov rekvizitlari*\n\n"
        f"💳 Uzcard / Humo:\n`{settings_map['payment_card'] or '-'}`\n\n"
        f"💳 Visa:\n`{settings_map['payment_visa'] or '-'}`\n\n"
        f"💎 USDT (BEP20):\n`{settings_map['payment_usdt_bep20'] or '-'}`\n\n"
        f"💎 USDT (TRC20):\n`{settings_map['payment_usdt_trc20'] or '-'}`\n\n"
        f"💎 USDT (Plasma/Polygon):\n`{settings_map['payment_usdt_polygon'] or '-'}`"
    )
    buttons = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("✏️ Uzcard / Humo", callback_data="adm_set_payment_card")],
            [InlineKeyboardButton("✏️ Visa", callback_data="adm_set_payment_visa")],
            [InlineKeyboardButton("✏️ USDT (BEP20)", callback_data="adm_set_payment_usdt_bep20")],
            [InlineKeyboardButton("✏️ USDT (TRC20)", callback_data="adm_set_payment_usdt_trc20")],
            [InlineKeyboardButton("✏️ USDT (Plasma/Polygon)", callback_data="adm_set_payment_usdt_polygon")],
        ]
    )
    await call.message.reply(text, parse_mode=enums.ParseMode.MARKDOWN, reply_markup=buttons)
    await call.answer()


@app.on_callback_query(admin_filter & filters.create(lambda _, __, q: q.data.startswith("adm_set_")))
async def adm_set_setting(client, call):
    key = call.data.replace("adm_set_", "", 1)
    waiting_for_admin_input[ADMIN_ID] = {"action": f"set_setting:{key}"}
    await call.message.reply(f"✍️ `{key}` uchun yangi qiymatni yuboring:", parse_mode=enums.ParseMode.MARKDOWN)
    await call.answer()


@app.on_callback_query(admin_filter & filters.create(lambda _, __, q: q.data == "adm_volume"))
async def adm_volume(client, call):
    await call.message.reply(
        "\n".join(
            [
                "🗄️ *Turso DB*",
                f"URL: `{TURSO_URL[:50]}...`" if TURSO_URL else "❌ Ulanmagan",
                f"Lokal DB: `{LOCAL_DB}`",
                f"Foydalanuvchilar: `{user_count()}`",
            ]
        ),
        parse_mode=enums.ParseMode.MARKDOWN,
    )
    await call.answer()


# ============================================================
# KEEP ALIVE / BACKGROUND
# ============================================================
def keep_alive():
    flask_app = Flask(__name__)

    @flask_app.route("/")
    def home():
        stats = get_global_stats()
        return (
            f"Bot ishlayapti | Users: {user_count()} | Premium: {stats['premium_users']} | "
            f"ZIP: {stats['total_zips']} | Disk: {fmt_size(total_disk_all())}"
        )

    port = int(os.environ.get("PORT", 5000))
    flask_app.run(host="0.0.0.0", port=port)


async def maybe_send_premium_expiry_warning(client, uid: int, chat_id: int):
    cleanup_expired_premium_for_user(uid)
    row = get_db().execute(
        "SELECT is_premium, premium_expiry, premium_warned FROM users WHERE telegram_id=?",
        (uid,),
    ).fetchone()
    if not row:
        return
    if not row[0] or row[2]:
        return

    expiry = row[1] or ""
    expiry_dt = parse_dt(expiry)
    if not expiry_dt:
        return

    now = datetime.now()
    if now < expiry_dt <= now + timedelta(days=1):
        try:
            await client.send_message(
                chat_id,
                tx(uid, "premium_expiry_warn", expiry=expiry),
                parse_mode=enums.ParseMode.MARKDOWN,
                reply_markup=main_menu(uid),
            )
            c = get_db()
            c.execute("UPDATE users SET premium_warned=1 WHERE telegram_id=?", (uid,))
            c.commit()
            db_sync()
        except Exception:
            pass


# ============================================================
# MAIN
# ============================================================
def main():
    global ZIP_SEMAPHORE
    if not all([os.environ.get("API_ID"), os.environ.get("API_HASH"), os.environ.get("BOT_TOKEN")]):
        raise RuntimeError("API_ID, API_HASH, BOT_TOKEN to'ldirilmagan!")

    get_db()
    init_db()
    _load_channels()
    os.makedirs(BASE_DIR, exist_ok=True)
    os.makedirs(STICKER_DIR, exist_ok=True)
    ZIP_SEMAPHORE = asyncio.Semaphore(2)

    print(f"[BOT] Tayyorlanmoqda... Kanallar: {len(required_channels)}")
    threading.Thread(target=keep_alive, daemon=True).start()
    print("[BOT] Ishga tushdi!")
    app.run()


if __name__ == "__main__":
    main()
