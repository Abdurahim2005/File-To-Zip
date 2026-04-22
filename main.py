import os
import re
import shutil
import zipfile
import asyncio
import threading
import libsql_experimental as libsql
from datetime import datetime, date
from flask import Flask
from pyrogram import Client, filters, enums
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, Message

# ════════════════════════════════════════════════════════════
#  CONFIG
# ════════════════════════════════════════════════════════════
API_ID = int(os.environ["API_ID"])
API_HASH = os.environ["API_HASH"]
BOT_TOKEN = os.environ["BOT_TOKEN"]

TURSO_URL = os.environ.get("TURSO_URL", "")
TURSO_TOKEN = os.environ.get("TURSO_TOKEN", "")
LOCAL_DB = "/tmp/bot_replica.db"

BASE_DIR = "user_files"
STICKER_DIR = "stickers"
ADMIN_ID = int(os.environ.get("ADMIN_ID", "1663567950"))
MAX_STORAGE = 300 * 1024 * 1024
MAX_FILES = 25
MAX_ZIPS_DAY = 3
AUTO_ZIP_DELAY = 60
DEBOUNCE_SEC = 1.5

# ════════════════════════════════════════════════════════════
#  IN-MEMORY STATE
# ════════════════════════════════════════════════════════════
broadcast_mode: set = set()
waiting_for_user_id: dict = {}
user_status_msg: dict = {}
user_welcome_msg: dict = {}
user_auto_zip: dict = {}
user_debounce: dict = {}
user_downloading: dict = {}
user_reserved_bytes: dict = {}
user_excess: dict = {}
user_limit_debounce: dict = {}
user_storage_rej: dict = {}
required_channels: dict = {}

# ZIP navbat semafori — bir vaqtda max 2 ta ZIP jarayoni
ZIP_SEMAPHORE: asyncio.Semaphore = None

# ════════════════════════════════════════════════════════════
#  TURSO DB
# ════════════════════════════════════════════════════════════
_db_conn = None


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


# ════════════════════════════════════════════════════════════
#  DATABASE INIT
# ════════════════════════════════════════════════════════════
def init_db():
    c = get_db()
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            telegram_id INTEGER UNIQUE NOT NULL,
            first_name  TEXT    DEFAULT '',
            last_name   TEXT    DEFAULT '',
            username    TEXT    DEFAULT '',
            language    TEXT    DEFAULT 'uz',
            waiting_zip INTEGER DEFAULT 0,
            is_banned   INTEGER DEFAULT 0,
            joined_at   TEXT    NOT NULL
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
        CREATE TABLE IF NOT EXISTS zip_stats (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            date        TEXT NOT NULL,
            telegram_id INTEGER NOT NULL,
            zip_count   INTEGER DEFAULT 0,
            total_mb    REAL    DEFAULT 0.0,
            file_count  INTEGER DEFAULT 0
        )
    """
    )
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS donations (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            telegram_id  INTEGER NOT NULL,
            first_name   TEXT    DEFAULT '',
            amount       TEXT    DEFAULT '',
            currency     TEXT    DEFAULT '',
            confirmed    INTEGER DEFAULT 0,
            created_at   TEXT    NOT NULL,
            confirmed_at TEXT    DEFAULT ''
        )
    """
    )

    for col, dfn in [("waiting_zip", "INTEGER DEFAULT 0"), ("is_banned", "INTEGER DEFAULT 0")]:
        try:
            c.execute(f"ALTER TABLE users ADD COLUMN {col} {dfn}")
        except Exception:
            pass

    for col, dfn in [("username", "TEXT DEFAULT ''"), ("invite_link", "TEXT DEFAULT ''")]:
        try:
            c.execute(f"ALTER TABLE channels ADD COLUMN {col} {dfn}")
        except Exception:
            pass

    c.commit()
    db_sync()


# ── Users ────────────────────────────────────────────────
def upsert_user(user, lang=None):
    c = get_db()
    c.execute(
        """
        INSERT INTO users(telegram_id,first_name,last_name,username,language,joined_at)
        VALUES(?,?,?,?,?,?)
        ON CONFLICT(telegram_id) DO UPDATE SET
            first_name=excluded.first_name, last_name=excluded.last_name,
            username=excluded.username, language=COALESCE(?,language)
    """,
        (
            user.id,
            user.first_name or "",
            user.last_name or "",
            user.username or "",
            lang or "uz",
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            lang,
        ),
    )
    c.commit()
    db_sync()


def get_lang(uid: int):
    r = get_db().execute("SELECT language FROM users WHERE telegram_id=?", (uid,)).fetchone()
    return r[0] if r else None


def is_banned(uid: int) -> bool:
    r = get_db().execute("SELECT is_banned FROM users WHERE telegram_id=?", (uid,)).fetchone()
    return bool(r[0]) if r else False


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


def all_users() -> list:
    return get_db().execute(
        "SELECT telegram_id,first_name,last_name,username,language,joined_at,is_banned "
        "FROM users ORDER BY id DESC"
    ).fetchall()


def user_count() -> int:
    return get_db().execute("SELECT COUNT(*) FROM users").fetchone()[0]


def today_count() -> int:
    t = datetime.now().strftime("%Y-%m-%d")
    return get_db().execute("SELECT COUNT(*) FROM users WHERE joined_at LIKE ?", (f"{t}%",)).fetchone()[0]


def get_user_by_id(tid: int):
    return get_db().execute(
        "SELECT telegram_id,first_name,last_name,username,language,joined_at,is_banned "
        "FROM users WHERE telegram_id=?",
        (tid,),
    ).fetchone()


# ── Channels ─────────────────────────────────────────────
def _load_channels():
    global required_channels
    rows = get_db().execute("SELECT chat_id, title, username, invite_link FROM channels").fetchall()
    required_channels = {
        r[0]: {
            "title": r[1] or "",
            "username": (r[2] or "").lstrip("@"),
            "invite_link": r[3] or "",
        }
        for r in rows
    }


def add_channel(chat_id: int, title: str, username: str = "", invite_link: str = ""):
    username = (username or "").lstrip("@")
    c = get_db()
    c.execute(
        "INSERT OR REPLACE INTO channels(chat_id,title,username,invite_link) VALUES(?,?,?,?)",
        (chat_id, title, username, invite_link),
    )
    c.commit()
    db_sync()
    required_channels[chat_id] = {
        "title": title,
        "username": username,
        "invite_link": invite_link or "",
    }


def remove_channel(chat_id: int):
    c = get_db()
    c.execute("DELETE FROM channels WHERE chat_id=?", (chat_id,))
    c.commit()
    db_sync()
    required_channels.pop(chat_id, None)


def get_channels() -> dict:
    return {cid: data.copy() for cid, data in required_channels.items()}


# ── ZIP statistikasi ─────────────────────────────────────
def today_str() -> str:
    return date.today().isoformat()


def get_daily_zip_count(uid: int) -> int:
    r = get_db().execute(
        "SELECT zip_count FROM zip_stats WHERE date=? AND telegram_id=?",
        (today_str(), uid),
    ).fetchone()
    return r[0] if r else 0


def add_zip_stat(uid: int, mb: float, fcount: int):
    c = get_db()
    d = today_str()
    existing = c.execute(
        "SELECT id,zip_count,total_mb,file_count FROM zip_stats WHERE date=? AND telegram_id=?",
        (d, uid),
    ).fetchone()
    if existing:
        c.execute(
            "UPDATE zip_stats SET zip_count=zip_count+1, total_mb=total_mb+?, file_count=file_count+? "
            "WHERE id=?",
            (mb, fcount, existing[0]),
        )
    else:
        c.execute(
            "INSERT INTO zip_stats(date,telegram_id,zip_count,total_mb,file_count) VALUES(?,?,1,?,?)",
            (d, uid, mb, fcount),
        )
    c.commit()
    db_sync()


def get_global_stats() -> dict:
    c = get_db()
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
    }


# ── Donations ────────────────────────────────────────────
def add_donation(uid: int, first_name: str, amount: str, currency: str) -> int:
    c = get_db()
    c.execute(
        "INSERT INTO donations(telegram_id,first_name,amount,currency,created_at) VALUES(?,?,?,?,?)",
        (uid, first_name, amount, currency, datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
    )
    c.commit()
    db_sync()
    return c.execute("SELECT last_insert_rowid()").fetchone()[0]


def confirm_donation(donation_id: int):
    c = get_db()
    c.execute(
        "UPDATE donations SET confirmed=1, confirmed_at=? WHERE id=?",
        (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), donation_id),
    )
    c.commit()
    db_sync()


def get_top_donors(limit: int = 10) -> list:
    return get_db().execute(
        "SELECT telegram_id, first_name, GROUP_CONCAT(amount||' '||currency, ', '), COUNT(*) "
        "FROM donations WHERE confirmed=1 "
        "GROUP BY telegram_id ORDER BY COUNT(*) DESC LIMIT ?",
        (limit,),
    ).fetchall()


def get_pending_donations() -> list:
    return get_db().execute(
        "SELECT id, telegram_id, first_name, amount, currency, created_at "
        "FROM donations WHERE confirmed=0 ORDER BY id DESC LIMIT 20"
    ).fetchall()


# ════════════════════════════════════════════════════════════
#  TEXTS
# ════════════════════════════════════════════════════════════
TEXTS = {
    "uz": {
        "choose_lang": "🌍 Tilni tanlang:",
        "welcome": (
            "✅ Til saqlandi!\n\n"
            "👋 Salom, *{name}*!\n\n"
            "📦 Fayllaringizni *ZIP arxivga* yig'ib beraman.\n\n"
            "━━━━━━━━━━━━━━━\n"
            "📎 *Qanday ishlaydi:*\n"
            "① Istalgan fayl yuboring\n"
            "② «📦 ZIP yasash» tugmasini bosing\n"
            "③ Tayyor! ZIP avtomatik yaratiladi.\n\n"
            "⏱ *1 daqiqa* ichida tugma bosilmasa — avtozip.\n\n"
            "📋 *Cheklovlar:*\n"
            "• Max *25 ta fayl* (bir ZIP uchun)\n"
            "• Max *300 MB* umumiy hajm\n"
            "• Kuniga *3 ta ZIP*"
        ),
        "files_saved": "✅ *{count} ta fayl* qabul qilindi!\n\n👇 ZIP yasash tugmasini bosing:",
        "receiving": "📥 *{count} ta fayl qabul qilinmoqda...* kutib turing",
        "max_files": (
            "⛔ *Fayl cheklovi!*\n\nBir ZIP uchun maksimal *25 ta fayl*.\n"
            "Hozirgi fayllarni avval ziplab oling."
        ),
        "daily_limit": (
            "⛔ *Kunlik limit!*\n\nBugun *3 ta ZIP* limitingiz tugadi.\n"
            "Ertaga yana foydalanishingiz mumkin! 😊"
        ),
        "join_required": (
            "👋 Botdan foydalanish uchun\n"
            "quyidagi kanal(lar)ga obuna bo'ling:\n\n"
            "✅ Obuna bo'lgach «Tekshirish» tugmasini bosing."
        ),
        "join_check_btn": "✅ Tekshirish",
        "join_ok": "✅ Obuna tasdiqlandi!",
        "join_fail": "❌ Hali obuna bo'lmadingiz.",
        "storage_full": (
            "⚠️ *Xotira to'lib qoldi!*\n\n"
            "📄 Oxirgi fayl: `{last_file}`\n"
            "💾 Band: *{used}* / *{max}*\n\n"
            "ZIP yasash tugmasini bosing — 40 soniyada avto-zip."
        ),
        "ready_btn": "📦 ZIP yasash",
        "zip_wait": "⏳ *Fayllar hali yuklanmoqda...* biroz kuting.",
        "zip_queue": "⏳ *Navbatda...* ZIP jarayoni band, kuting.",
        "zip_caption": "📦 *ZIP tayyor!*\n\n🤖 @Zipla_bot — Hayotni Ziplab o't!",
        "no_files": "⚠️ Avval fayl yuboring.",
        "zip_error": "❌ ZIP yaratishda xato. Qaytadan urining.",
        "lang_set": "✅ Til saqlandi!",
        "change_lang": "🌍 Tilni o'zgartirish",
        "creating_zip": "⚙️ *ZIP yaratilmoqda...* iltimos kuting",
        "banned": "🚫 Bloklangansiz.",
        "auto_zip_done": "🤖 *Avtomatik ZIP* yaratildi.",
        "donate_text": (
            "☕ *Kofe sotib oling!*\n\n"
            "Botni rivojlantirish uchun istalgan miqdorda yordam bering.\n\n"
            "━━━━━━━━━━━━━━━\n"
            "🇺🇿 *Uzcard:* `5614684903726220`\n"
            "💳 *Visa:* `4916990318718514`\n\n"
            "🪙 *USDT (TRC20):*\n`TAs1YHxyz8tgYYTsDYPFqdtu9VxMjWPbKw`\n\n"
            "🪙 *USDT (BEP20 / PLASMA):*\n`0x10355140b54a53188c056a29e5973a40181b21ef`\n\n"
            "━━━━━━━━━━━━━━━\n"
            "To'lov qilgach miqdor va valyutani yozing,\n"
            "«✅ Donat qildim» tugmasini bosing."
        ),
        "donate_btn": "☕ Donat qilish",
        "donate_done_btn": "✅ Donat qildim",
        "donate_ask": "💬 Donat miqdori va valyutasini yozing:\nMisol: `50000 UZS` yoki `5 USDT`",
        "donate_sent": "✅ So'rovingiz qabul qilindi! Admin tez orada tasdiqlaydi. 🙏",
        "top_donors": "🏆 *Top Donorlar*\n\n{list}",
        "no_donors": "Hali hech kim donat qilmagan. Birinchi bo'ling! ☕",
        "premium_text": (
            "⭐ *Premium haqida*\n\n"
            "Premium funksiyalar hozircha ishlab chiqilmoqda.\n\n"
            "📋 *Rejalashtirilgan imkoniyatlar:*\n"
            "• Kunlik ZIP limiti yo'q\n"
            "• Max 1 GB fayl hajmi\n"
            "• Max 100 ta fayl per ZIP\n"
            "• Ustuvor navbat\n\n"
            "Qiziqasizmi? Adminga yozing!"
        ),
    },
    "en": {
        "choose_lang": "🌍 Choose language:",
        "welcome": (
            "✅ Language saved!\n\n"
            "👋 Hello, *{name}*!\n\n"
            "📦 I pack your files into a *ZIP archive*.\n\n"
            "━━━━━━━━━━━━━━━\n"
            "📎 *How it works:*\n"
            "① Send any files\n"
            "② Press «📦 Create ZIP»\n"
            "③ Done! ZIP is created automatically.\n\n"
            "⏱ *Auto-zipped* after 1 minute.\n\n"
            "📋 *Limits:*\n"
            "• Max *25 files* per ZIP\n"
            "• Max *300 MB* total size\n"
            "• *3 ZIPs* per day"
        ),
        "files_saved": "✅ *{count} file(s)* received!\n\n👇 Press Create ZIP when ready:",
        "receiving": "📥 *Receiving {count} file(s)...* please wait",
        "max_files": (
            "⛔ *File limit reached!*\n\nMaximum *25 files* per ZIP.\n"
            "Please ZIP current files first."
        ),
        "daily_limit": (
            "⛔ *Daily limit reached!*\n\nYou've used *3 ZIPs* today.\n"
            "Come back tomorrow! 😊"
        ),
        "join_required": (
            "👋 To use this bot, please join\n"
            "the following channel(s):\n\n"
            "✅ After joining, press «Check» button."
        ),
        "join_check_btn": "✅ Check",
        "join_ok": "✅ Subscription confirmed!",
        "join_fail": "❌ You haven't joined yet.",
        "storage_full": (
            "⚠️ *Storage full!*\n\n"
            "📄 Last file: `{last_file}`\n"
            "💾 Used: *{used}* of *{max}*\n\n"
            "Press Create ZIP — auto-zip in 40 seconds."
        ),
        "ready_btn": "📦 Create ZIP",
        "zip_wait": "⏳ *Files still uploading...* please wait.",
        "zip_queue": "⏳ *In queue...* ZIP process is busy, please wait.",
        "zip_caption": "📦 *ZIP is ready!*\n\n🤖 @Zipla_bot — Zip your life!",
        "no_files": "⚠️ Please send files first.",
        "zip_error": "❌ ZIP creation failed. Please try again.",
        "lang_set": "✅ Language saved!",
        "change_lang": "🌍 Change language",
        "creating_zip": "⚙️ *Creating ZIP...* please wait",
        "banned": "🚫 You are blocked.",
        "auto_zip_done": "🤖 *Auto ZIP* created.",
        "donate_text": (
            "☕ *Buy me a coffee!*\n\n"
            "Support bot development with any amount.\n\n"
            "━━━━━━━━━━━━━━━\n"
            "🇺🇿 *Uzcard:* `5614684903726220`\n"
            "💳 *Visa:* `4916990318718514`\n\n"
            "🪙 *USDT (TRC20):*\n`TAs1YHxyz8tgYYTsDYPFqdtu9VxMjWPbKw`\n\n"
            "🪙 *USDT (BEP20 / PLASMA):*\n`0x10355140b54a53188c056a29e5973a40181b21ef`\n\n"
            "━━━━━━━━━━━━━━━\n"
            "After payment, type the amount and currency,\n"
            "then press «✅ I donated»."
        ),
        "donate_btn": "☕ Donate",
        "donate_done_btn": "✅ I donated",
        "donate_ask": "💬 Type the amount and currency:\nExample: `5 USDT` or `50000 UZS`",
        "donate_sent": "✅ Request received! Admin will confirm soon. 🙏",
        "top_donors": "🏆 *Top Donors*\n\n{list}",
        "no_donors": "No donors yet. Be the first! ☕",
        "premium_text": (
            "⭐ *Premium Info*\n\n"
            "Premium features are coming soon.\n\n"
            "📋 *Planned features:*\n"
            "• Unlimited daily ZIPs\n"
            "• Up to 1 GB file size\n"
            "• Up to 100 files per ZIP\n"
            "• Priority queue\n\n"
            "Interested? Contact admin!"
        ),
    },
}

# Donat so'rash holati  {uid: True}
user_donating: dict = {}


def tx(uid: int, key: str, **kw) -> str:
    lang = get_lang(uid) or "uz"
    text = TEXTS.get(lang, TEXTS["uz"]).get(key, key)
    return text.format(**kw) if kw else text


# ════════════════════════════════════════════════════════════
#  FILE UTILITIES
# ════════════════════════════════════════════════════════════
def user_dir(uid: int) -> str:
    p = os.path.join(BASE_DIR, str(uid))
    os.makedirs(p, exist_ok=True)
    return p


def disk_used(uid: int) -> int:
    d = user_dir(uid)
    return sum(os.path.getsize(os.path.join(d, f)) for f in os.listdir(d) if os.path.isfile(os.path.join(d, f)))


def file_count(uid: int) -> int:
    d = user_dir(uid)
    return len([f for f in os.listdir(d) if os.path.isfile(os.path.join(d, f))])


def total_disk_all() -> int:
    total = 0
    if not os.path.exists(BASE_DIR):
        return 0
    for folder in os.listdir(BASE_DIR):
        fp = os.path.join(BASE_DIR, folder)
        if os.path.isdir(fp):
            for f in os.listdir(fp):
                fpath = os.path.join(fp, f)
                if os.path.isfile(fpath):
                    total += os.path.getsize(fpath)
    return total


def all_users_disk() -> list:
    result = []
    if not os.path.exists(BASE_DIR):
        return result
    for folder in os.listdir(BASE_DIR):
        try:
            uid = int(folder)
            used = disk_used(uid)
            if used > 0:
                result.append((uid, used))
        except ValueError:
            pass
    result.sort(key=lambda x: x[1], reverse=True)
    return result


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


def fmt_size(b: int) -> str:
    if b < 1024**2:
        return f"{b / 1024:.1f} KB"
    return f"{b / 1024**2:.1f} MB"


def sanitize_filename(filename: str) -> str:
    name = re.sub(r'[\\/:*?"<>|]', "_", filename)
    name = re.sub(r"\s+", "_", name)
    name = name.strip("._")
    return name if name else f"file_{datetime.now():%Y%m%d_%H%M%S}"


def make_zip_name(user) -> str:
    name = (user.first_name or "") + ("_" + user.last_name if user.last_name else "")
    name = re.sub(r"\s+", "_", name.strip())
    name = re.sub(r"[^\w\-]", "", name)
    if not name:
        name = f"user_{user.id}"
    stamp = datetime.now().strftime("%d%m%y_%H%M")
    return f"{name}_{stamp}"


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
            f"🕐 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            parse_mode=enums.ParseMode.MARKDOWN,
        )
    except Exception as e:
        print(f"[error_to_admin] {e}")


# ════════════════════════════════════════════════════════════
#  SUBSCRIPTION CHECK
# ════════════════════════════════════════════════════════════
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
            buttons.append(
                [InlineKeyboardButton(f"📢 @{username}", url=f"https://t.me/{username}")]
            )
        elif invite_link:
            buttons.append([InlineKeyboardButton(f"📢 {title}", url=invite_link)])

    buttons.append([InlineKeyboardButton(texts["join_check_btn"], callback_data="check_join")])

    await client.send_message(
        chat_id,
        texts["join_required"],
        parse_mode=enums.ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup(buttons),
        disable_web_page_preview=True,
    )
    return False


# ════════════════════════════════════════════════════════════
#  TASK HELPERS
# ════════════════════════════════════════════════════════════
async def cancel_task(d: dict, uid: int):
    task = d.get(uid)
    if task and not task.done():
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
    d.pop(uid, None)


def schedule_task(d: dict, uid: int, coro):
    loop = asyncio.get_event_loop()
    old = d.get(uid)
    if old and not old.done():
        old.cancel()
    d[uid] = loop.create_task(coro)


# ════════════════════════════════════════════════════════════
#  STATUS XABAR — debounce
# ════════════════════════════════════════════════════════════
async def _send_status(client, chat_id: int, uid: int):
    await asyncio.sleep(DEBOUNCE_SEC)
    cnt = file_count(uid)
    dl_cnt = user_downloading.get(uid, 0)
    sm = user_status_msg.get(uid)
    markup = InlineKeyboardMarkup(
        [[InlineKeyboardButton(tx(uid, "ready_btn"), callback_data="zip_now")]]
    )
    text = tx(uid, "receiving", count=cnt + dl_cnt) if dl_cnt > 0 else tx(uid, "files_saved", count=cnt)
    mup = None if dl_cnt > 0 else markup
    if sm is None:
        try:
            sent = await client.send_message(chat_id, text, parse_mode=enums.ParseMode.MARKDOWN, reply_markup=mup)
            user_status_msg[uid] = sent
        except Exception:
            pass
    else:
        try:
            await sm.edit_text(text, parse_mode=enums.ParseMode.MARKDOWN, reply_markup=mup)
        except Exception:
            pass


def restart_debounce(client, chat_id: int, uid: int):
    schedule_task(user_debounce, uid, _send_status(client, chat_id, uid))


# ── Kunlik limit xabari debounce ─────────────────────────
async def _send_daily_limit_msg(client, chat_id: int, uid: int):
    await asyncio.sleep(2.0)
    sm = user_status_msg.pop(uid, None)
    await safe_delete(sm)
    await client.send_message(chat_id, tx(uid, "daily_limit"), parse_mode=enums.ParseMode.MARKDOWN)


def schedule_limit_msg(client, chat_id: int, uid: int):
    schedule_task(user_limit_debounce, uid, _send_daily_limit_msg(client, chat_id, uid))


# ── Oshiqcha fayl xabari debounce ────────────────────────
async def _send_excess_msg(client, chat_id: int, uid: int):
    await asyncio.sleep(DEBOUNCE_SEC)
    accepted = file_count(uid)
    rejected = user_excess.pop(uid, 0)
    if accepted == 0:
        return
    sm = user_status_msg.get(uid)
    lang = get_lang(uid) or "uz"
    if lang == "uz":
        text = (
            f"✅ *{accepted} ta fayl* qabul qilindi!\n"
            f"❌ *{rejected} ta fayl* qabul qilinmadi (25 ta limit).\n\n"
            f"👇 ZIP yasash tugmasini bosing:"
        )
    else:
        text = (
            f"✅ *{accepted} file(s)* received!\n"
            f"❌ *{rejected} file(s)* rejected (25 file limit).\n\n"
            f"👇 Press Create ZIP when ready:"
        )
    markup = InlineKeyboardMarkup(
        [[InlineKeyboardButton(tx(uid, "ready_btn"), callback_data="zip_now")]]
    )
    if sm is None:
        try:
            sent = await client.send_message(chat_id, text, parse_mode=enums.ParseMode.MARKDOWN, reply_markup=markup)
            user_status_msg[uid] = sent
        except Exception:
            pass
    else:
        try:
            await sm.edit_text(text, parse_mode=enums.ParseMode.MARKDOWN, reply_markup=markup)
        except Exception:
            pass


# ════════════════════════════════════════════════════════════
#  AUTO-ZIP TIMER
# ════════════════════════════════════════════════════════════
async def _auto_zip_runner(client, chat_id: int, uid: int, delay: int, user_obj=None):
    await asyncio.sleep(delay)
    if file_count(uid) == 0:
        return
    sm = user_status_msg.pop(uid, None)
    await safe_delete(sm)
    auto_name = make_zip_name(user_obj) if user_obj else f"auto_{datetime.now():%Y%m%d_%H%M%S}"
    await create_and_send_zip(client, chat_id, uid, auto_name, auto=True)


def start_auto_zip(client, chat_id: int, uid: int, delay: int = AUTO_ZIP_DELAY, user_obj=None):
    schedule_task(user_auto_zip, uid, _auto_zip_runner(client, chat_id, uid, delay, user_obj))


# ════════════════════════════════════════════════════════════
#  ZIP YARATISH  (Queue + STORED compression)
# ════════════════════════════════════════════════════════════
async def create_and_send_zip(client, chat_id: int, uid: int, zip_name_raw: str, auto: bool = False):
    global ZIP_SEMAPHORE
    if ZIP_SEMAPHORE is None:
        ZIP_SEMAPHORE = asyncio.Semaphore(2)

    udir = user_dir(uid)
    files = [f for f in os.listdir(udir) if os.path.isfile(os.path.join(udir, f))]
    if not files:
        return

    zip_name = f"{zip_name_raw}.zip"
    zip_path = os.path.join(udir, zip_name)

    existing_sm = user_status_msg.get(uid)
    if existing_sm:
        try:
            await existing_sm.edit_text(tx(uid, "creating_zip"), parse_mode=enums.ParseMode.MARKDOWN)
        except Exception:
            existing_sm = None

    if not existing_sm:
        progress = await client.send_message(chat_id, tx(uid, "creating_zip"), parse_mode=enums.ParseMode.MARKDOWN)
    else:
        progress = None

    queue_msg = None
    if ZIP_SEMAPHORE.locked():
        queue_msg = await client.send_message(chat_id, tx(uid, "zip_queue"), parse_mode=enums.ParseMode.MARKDOWN)

    async with ZIP_SEMAPHORE:
        if queue_msg:
            await safe_delete(queue_msg)

        fcount = len(files)
        try:
            with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_STORED) as zf:
                for fname in files:
                    fpath = os.path.join(udir, fname)
                    if os.path.isfile(fpath) and fname != zip_name:
                        zf.write(fpath, arcname=fname)

            zip_size = os.path.getsize(zip_path) if os.path.exists(zip_path) else 0
            caption = tx(uid, "zip_caption")
            if auto:
                caption = tx(uid, "auto_zip_done") + "\n\n" + caption

            await client.send_document(
                chat_id,
                zip_path,
                caption=caption,
                file_name=zip_name,
                parse_mode=enums.ParseMode.MARKDOWN,
            )
            add_zip_stat(uid, zip_size / 1024 / 1024, fcount)

        except Exception as e:
            await client.send_message(chat_id, tx(uid, "zip_error"), parse_mode=enums.ParseMode.MARKDOWN)
            await error_to_admin(client, "create_and_send_zip", uid, e)
            return
        finally:
            await safe_delete(progress)
            sm = user_status_msg.pop(uid, None)
            await safe_delete(sm)
            wm = user_welcome_msg.pop(uid, None)
            await safe_delete(wm)

    try:
        if os.path.exists(udir):
            shutil.rmtree(udir)
            os.makedirs(udir, exist_ok=True)
    except Exception as e:
        print(f"[cleanup] {e}")

    user_auto_zip.pop(uid, None)


# ════════════════════════════════════════════════════════════
#  FAYL QABUL QILISH
# ════════════════════════════════════════════════════════════
async def receive_file(client, message: Message, obj, filename: str):
    uid = message.from_user.id

    if is_banned(uid):
        await safe_delete(message)
        return

    lang = get_lang(uid) or "uz"
    if not await gate_check(client, uid, message.chat.id, lang):
        await safe_delete(message)
        return

    if get_daily_zip_count(uid) >= MAX_ZIPS_DAY:
        await safe_delete(message)
        schedule_limit_msg(client, message.chat.id, uid)
        return

    fsize = getattr(obj, "file_size", 0) or 0
    used_now = disk_used(uid) + user_reserved_bytes.get(uid, 0)
    cur_cnt = file_count(uid) + user_downloading.get(uid, 0)

    if cur_cnt >= MAX_FILES:
        await safe_delete(message)
        user_excess[uid] = user_excess.get(uid, 0) + 1
        schedule_task(user_debounce, uid, _send_excess_msg(client, message.chat.id, uid))
        return

    if used_now + fsize > MAX_STORAGE:
        await safe_delete(message)
        user_storage_rej[uid] = user_storage_rej.get(uid, 0) + 1

        async def _send_storage_full_msg(chat_id, u):
            await asyncio.sleep(DEBOUNCE_SEC)
            rej_cnt = user_storage_rej.pop(u, 0)
            udir = user_dir(u)
            flist = [f for f in os.listdir(udir) if os.path.isfile(os.path.join(udir, f))]
            acc_cnt = len(flist)
            lang_u = get_lang(u) or "uz"
            if lang_u == "uz":
                text = (
                    f"⚠️ *Xotira to'lib qoldi!*\n\n"
                    f"✅ Qabul qilindi: *{acc_cnt} ta fayl*\n"
                    f"❌ Qabul qilinmadi: *{rej_cnt} ta fayl*\n"
                    f"💾 Band: *{fmt_size(used_now)}* / *{fmt_size(MAX_STORAGE)}*\n\n"
                    f"ZIP yasash tugmasini bosing — 40 soniyada avto-zip."
                )
            else:
                text = (
                    f"⚠️ *Storage full!*\n\n"
                    f"✅ Accepted: *{acc_cnt} file(s)*\n"
                    f"❌ Rejected: *{rej_cnt} file(s)*\n"
                    f"💾 Used: *{fmt_size(used_now)}* of *{fmt_size(MAX_STORAGE)}*\n\n"
                    f"Press Create ZIP — auto-zip in 40 seconds."
                )
            sm = user_status_msg.pop(u, None)
            await safe_delete(sm)
            sfm = await client.send_message(
                chat_id,
                text,
                parse_mode=enums.ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup(
                    [[InlineKeyboardButton(tx(u, "ready_btn"), callback_data="zip_now")]]
                ),
            )
            user_status_msg[u] = sfm
            await cancel_task(user_auto_zip, u)
            start_auto_zip(client, chat_id, u, delay=40, user_obj=None)

        schedule_task(user_debounce, uid, _send_storage_full_msg(message.chat.id, uid))
        return

    user_reserved_bytes[uid] = user_reserved_bytes.get(uid, 0) + fsize
    user_downloading[uid] = user_downloading.get(uid, 0) + 1
    restart_debounce(client, message.chat.id, uid)

    udir = user_dir(uid)
    safe_name = sanitize_filename(filename)
    save_path = unique_path(udir, safe_name)
    try:
        await message.download(file_name=save_path)
    except Exception as e:
        await error_to_admin(client, "receive_file→download", uid, e)
    finally:
        user_downloading[uid] = max(0, user_downloading.get(uid, 1) - 1)
        user_reserved_bytes[uid] = max(0, user_reserved_bytes.get(uid, fsize) - fsize)

    await safe_delete(message)
    restart_debounce(client, message.chat.id, uid)

    await cancel_task(user_auto_zip, uid)
    start_auto_zip(client, message.chat.id, uid, user_obj=message.from_user)


# ════════════════════════════════════════════════════════════
#  BOT
# ════════════════════════════════════════════════════════════
app = Client("zip_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)


# ════════════════════════════════════════════════════════════
#  /start
# ════════════════════════════════════════════════════════════
@app.on_message(filters.command("start"))
async def cmd_start(client, message):
    uid = message.from_user.id
    await safe_delete(message)
    if is_banned(uid):
        return
    if get_lang(uid) is None:
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


# ════════════════════════════════════════════════════════════
#  TIL TANLASH
# ════════════════════════════════════════════════════════════
@app.on_callback_query(filters.create(lambda _, __, q: q.data.startswith("setlang_")))
async def cb_set_lang(client, call):
    uid = call.from_user.id
    lang = call.data.split("_")[1]
    upsert_user(call.from_user, lang)
    await safe_delete(call.message)
    user_welcome_msg.pop(uid, None)
    name = call.from_user.first_name or "Foydalanuvchi"
    sent = await client.send_message(
        call.message.chat.id,
        TEXTS[lang]["welcome"].format(name=name),
        parse_mode=enums.ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup(
            [[InlineKeyboardButton(TEXTS[lang]["change_lang"], callback_data="change_lang")]]
        ),
    )
    user_welcome_msg[uid] = sent
    await send_sticker(client, call.message.chat.id, "start")
    await call.answer(TEXTS[lang]["lang_set"])
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


# ════════════════════════════════════════════════════════════
#  OBUNA TEKSHIRISH
# ════════════════════════════════════════════════════════════
@app.on_callback_query(filters.create(lambda _, __, q: q.data == "check_join"))
async def cb_check_join(client, call):
    uid = call.from_user.id
    lang = get_lang(uid) or "uz"
    not_joined = await check_subscription(client, uid)
    if not not_joined:
        await call.answer(TEXTS[lang]["join_ok"], show_alert=True)
    else:
        await call.answer(TEXTS[lang]["join_fail"], show_alert=True)


# ════════════════════════════════════════════════════════════
#  FAYL HANDLERLARI
# ════════════════════════════════════════════════════════════
@app.on_message(filters.document)
async def on_document(client, message):
    doc = message.document
    await receive_file(client, message, doc, doc.file_name or f"file_{datetime.now():%Y%m%d_%H%M%S}")


@app.on_message(filters.photo)
async def on_photo(client, message):
    await receive_file(client, message, message.photo, f"photo_{datetime.now():%Y%m%d_%H%M%S}.jpg")


@app.on_message(filters.video)
async def on_video(client, message):
    v = message.video
    await receive_file(client, message, v, v.file_name or f"video_{datetime.now():%Y%m%d_%H%M%S}.mp4")


@app.on_message(filters.audio)
async def on_audio(client, message):
    a = message.audio
    await receive_file(client, message, a, a.file_name or f"audio_{datetime.now():%Y%m%d_%H%M%S}.mp3")


@app.on_message(filters.voice)
async def on_voice(client, message):
    await receive_file(client, message, message.voice, f"voice_{datetime.now():%Y%m%d_%H%M%S}.ogg")


@app.on_message(filters.video_note)
async def on_video_note(client, message):
    await receive_file(client, message, message.video_note, f"videonote_{datetime.now():%Y%m%d_%H%M%S}.mp4")


@app.on_message(filters.sticker)
async def on_sticker_msg(client, message):
    await receive_file(client, message, message.sticker, f"sticker_{datetime.now():%Y%m%d_%H%M%S}.webp")


@app.on_message(filters.animation)
async def on_animation(client, message):
    g = message.animation
    await receive_file(client, message, g, g.file_name or f"gif_{datetime.now():%Y%m%d_%H%M%S}.gif")


# ════════════════════════════════════════════════════════════
#  ZIP YASASH TUGMASI
# ════════════════════════════════════════════════════════════
@app.on_callback_query(filters.create(lambda _, __, q: q.data == "zip_now"))
async def cb_zip_now(client, call):
    uid = call.from_user.id
    user = call.from_user

    if file_count(uid) == 0:
        await call.answer(tx(uid, "no_files"), show_alert=True)
        return

    if get_daily_zip_count(uid) >= MAX_ZIPS_DAY:
        sm = user_status_msg.pop(uid, None)
        await safe_delete(sm)
        await client.send_message(call.message.chat.id, tx(uid, "daily_limit"), parse_mode=enums.ParseMode.MARKDOWN)
        await call.answer()
        return

    if user_downloading.get(uid, 0) > 0:
        await call.answer(tx(uid, "zip_wait"), show_alert=True)
        return

    await cancel_task(user_auto_zip, uid)
    await cancel_task(user_debounce, uid)

    sm = user_status_msg.pop(uid, None)
    await safe_delete(sm)

    zip_name = make_zip_name(user)
    await call.answer()
    await create_and_send_zip(client, call.message.chat.id, uid, zip_name)


# ════════════════════════════════════════════════════════════
#  DONATE
# ════════════════════════════════════════════════════════════
@app.on_message(filters.command("donate"))
async def cmd_donate(client, message):
    uid = message.from_user.id
    await safe_delete(message)
    lang = get_lang(uid) or "uz"
    await client.send_message(
        message.chat.id,
        TEXTS[lang]["donate_text"],
        parse_mode=enums.ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup(
            [
                [InlineKeyboardButton(TEXTS[lang]["donate_done_btn"], callback_data="donate_done")],
                [InlineKeyboardButton("🏆 Top donorlar", callback_data="top_donors")],
            ]
        ),
    )


@app.on_callback_query(filters.create(lambda _, __, q: q.data == "donate_done"))
async def cb_donate_done(client, call):
    uid = call.from_user.id
    lang = get_lang(uid) or "uz"
    user_donating[uid] = True
    await call.message.reply(TEXTS[lang]["donate_ask"], parse_mode=enums.ParseMode.MARKDOWN)
    await call.answer()


@app.on_callback_query(filters.create(lambda _, __, q: q.data == "top_donors"))
async def cb_top_donors(client, call):
    uid = call.from_user.id
    lang = get_lang(uid) or "uz"
    donors = get_top_donors()
    if not donors:
        await call.answer(TEXTS[lang]["no_donors"], show_alert=True)
        return
    lines = []
    medals = ["🥇", "🥈", "🥉"] + ["⭐"] * 10
    for i, (tid, fn, amounts, cnt) in enumerate(donors):
        medal = medals[i] if i < len(medals) else "⭐"
        lines.append(f"{medal} *{fn}* — {amounts}")
    await call.message.reply(TEXTS[lang]["top_donors"].format(list="\n".join(lines)), parse_mode=enums.ParseMode.MARKDOWN)
    await call.answer()


# ════════════════════════════════════════════════════════════
#  PREMIUM
# ════════════════════════════════════════════════════════════
@app.on_message(filters.command("premium"))
async def cmd_premium(client, message):
    uid = message.from_user.id
    lang = get_lang(uid) or "uz"
    await safe_delete(message)
    await client.send_message(message.chat.id, TEXTS[lang]["premium_text"], parse_mode=enums.ParseMode.MARKDOWN)


# ════════════════════════════════════════════════════════════
#  MATN HANDLERI
# ════════════════════════════════════════════════════════════
@app.on_message(filters.text & ~filters.command(["start", "admin", "donate", "premium"]))
async def on_text(client, message):
    uid = message.from_user.id

    if is_banned(uid):
        await safe_delete(message)
        return

    if get_lang(uid) is None:
        upsert_user(message.from_user, "uz")
        await safe_delete(message)
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

    if uid == ADMIN_ID and uid in broadcast_mode:
        broadcast_mode.discard(uid)
        users = all_users()
        ok = fail = 0
        prog = await message.reply("📨 Yuborilmoqda...")
        for row in users:
            if row[6]:
                continue
            try:
                await client.send_message(row[0], f"📢 {message.text}")
                ok += 1
            except Exception:
                fail += 1
        await safe_delete(prog)
        await message.reply(
            f"📨 *Broadcast tugadi!*\n\n✅ *{ok}*\n❌ *{fail}*",
            parse_mode=enums.ParseMode.MARKDOWN,
        )
        return

    if uid == ADMIN_ID and uid in waiting_for_user_id:
        action = waiting_for_user_id.pop(uid)
        raw = message.text.strip()

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
                    await message.reply(
                        "❌ Kanal public emas va invite link ham olinmadi.\n"
                        "Botni kanalga admin qiling yoki public @username ishlating."
                    )
                    return

                add_channel(chat.id, chat.title or normalized, username=username, invite_link=invite_link)

                warn = ""
                try:
                    me = await client.get_me()
                    await client.get_chat_member(chat.id, me.id)
                except Exception:
                    warn = "\n\n⚠️ Obuna tekshiruvi barqaror ishlashi uchun botni shu kanalga admin qiling."

                ref = f"@{username}" if username else invite_link
                await message.reply(
                    f"✅ Kanal qo'shildi: *{chat.title}*\n"
                    f"🔗 `{ref}`\n"
                    f"🆔 `{chat.id}`{warn}",
                    parse_mode=enums.ParseMode.MARKDOWN,
                )
            except Exception:
                await message.reply(
                    "❌ Kanal topilmadi.\n"
                    "Username yuboring (`@kanal`) yoki botni kanalga admin qilib qayta urinib ko'ring.",
                    parse_mode=enums.ParseMode.MARKDOWN,
                )
            return

        if action == "confirm_donation":
            try:
                don_id = int(re.search(r"\d+", raw).group())
                confirm_donation(don_id)
                pend = get_db().execute(
                    "SELECT telegram_id, first_name, amount, currency FROM donations WHERE id=?",
                    (don_id,),
                ).fetchone()
                if pend:
                    try:
                        await client.send_message(
                            pend[0],
                            f"🎉 Donatlingiz tasdiqlandi! Rahmat, *{pend[1]}*!\n"
                            f"💰 *{pend[2]} {pend[3]}*\n\n☕ @Zipla_bot",
                            parse_mode=enums.ParseMode.MARKDOWN,
                        )
                    except Exception:
                        pass
                await message.reply(f"✅ Donat #{don_id} tasdiqlandi.")
            except Exception:
                await message.reply("❌ ID xato.")
            return

        try:
            target_id = int(re.search(r"\d+", raw).group())
        except Exception:
            await message.reply("❌ Noto'g'ri ID.")
            return
        data = get_user_by_id(target_id)

        if action == "ban":
            if not data:
                await message.reply(f"❌ `{target_id}` topilmadi.", parse_mode=enums.ParseMode.MARKDOWN)
                return
            ban_user(target_id)
            await message.reply(
                f"⛔ *Bloklandi:* {data[1]} (`{target_id}`)",
                parse_mode=enums.ParseMode.MARKDOWN,
            )
            try:
                await client.send_message(target_id, tx(target_id, "banned"))
            except Exception:
                pass
        elif action == "unban":
            if not data:
                await message.reply(f"❌ `{target_id}` topilmadi.", parse_mode=enums.ParseMode.MARKDOWN)
                return
            unban_user(target_id)
            await message.reply(
                f"✅ *Blokdan chiqarildi:* {data[1]} (`{target_id}`)",
                parse_mode=enums.ParseMode.MARKDOWN,
            )
        elif action == "info":
            if not data:
                await message.reply(f"❌ `{target_id}` topilmadi.", parse_mode=enums.ParseMode.MARKDOWN)
                return
            tid, fn, ln, un, lg, jd, bnnd = data
            fcnt = file_count(tid)
            used = disk_used(tid)
            today_zips = get_daily_zip_count(tid)
            ban_status = "🚫 Ha" if bnnd else "✅ Yoq"
            uname = f"@{un}" if un else "—"
            await message.reply(
                f"👤 *Foydalanuvchi*\n\n🆔 `{tid}`\n📛 {fn} {ln}\n🔗 {uname}\n"
                f"🌍 {lg.upper()} | 📅 {jd[:16]}\n📁 {fcnt} fayl | 💾 {fmt_size(used)}\n"
                f"📦 Bugungi ZIP: {today_zips}/{MAX_ZIPS_DAY}\n🚫 Ban: {ban_status}",
                parse_mode=enums.ParseMode.MARKDOWN,
            )
        elif action == "clear":
            if not data:
                await message.reply(f"❌ `{target_id}` topilmadi.", parse_mode=enums.ParseMode.MARKDOWN)
                return
            ud = os.path.join(BASE_DIR, str(target_id))
            if os.path.exists(ud):
                shutil.rmtree(ud)
                os.makedirs(ud, exist_ok=True)
            await message.reply(f"🗑️ `{target_id}` — tozalandi.", parse_mode=enums.ParseMode.MARKDOWN)
        return

    if uid in user_donating:
        user_donating.pop(uid)
        text = message.text.strip()
        lang = get_lang(uid) or "uz"
        parts = text.split(maxsplit=1)
        amount = parts[0] if parts else text
        currency = parts[1].upper() if len(parts) > 1 else "?"
        fn = message.from_user.first_name or "Foydalanuvchi"
        don_id = add_donation(uid, fn, amount, currency)
        await safe_delete(message)
        await client.send_message(message.chat.id, TEXTS[lang]["donate_sent"], parse_mode=enums.ParseMode.MARKDOWN)
        try:
            await client.send_message(
                ADMIN_ID,
                f"💰 *Yangi donat so'rovi!*\n\n"
                f"🆔 Don ID: `{don_id}`\n"
                f"👤 {fn} (`{uid}`)\n"
                f"💵 *{amount} {currency}*\n\n"
                f"Tasdiqlash uchun Don ID ni yuboring: `/admin` → Donat tasdiqlash",
                parse_mode=enums.ParseMode.MARKDOWN,
            )
        except Exception:
            pass
        return

    await safe_delete(message)


# ════════════════════════════════════════════════════════════
#  ADMIN PANEL
# ════════════════════════════════════════════════════════════
def _is_admin(_, __, q):
    return q.from_user.id == ADMIN_ID


admin_filter = filters.create(_is_admin)


@app.on_message(filters.command("admin") & filters.user(ADMIN_ID))
async def cmd_admin(client, message):
    s = get_global_stats()
    cnt = user_count()
    today = today_count()
    disk = fmt_size(total_disk_all())
    await send_sticker(client, message.chat.id, "admin")
    await message.reply(
        f"🔐 *Admin Panel*\n\n"
        f"👥 Jami: *{cnt}* | 📅 Bugun: *{today}*\n"
        f"💾 Disk: *{disk}* | 🗄️ `Turso`\n\n"
        f"📦 Jami ZIP: *{s['total_zips']}* (bugun: *{s['today_zips']}*)\n"
        f"📊 Jami MB: *{s['total_mb']:.1f}* (bugun: *{s['today_mb']:.1f}*)\n"
        f"📎 Jami fayl: *{s['total_files']}*",
        parse_mode=enums.ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton("👥 Foydalanuvchilar", callback_data="adm_users"),
                    InlineKeyboardButton("📊 Statistika", callback_data="adm_stats"),
                ],
                [
                    InlineKeyboardButton("📨 Broadcast", callback_data="adm_broadcast"),
                    InlineKeyboardButton("🔍 Foydalanuvchi izlash", callback_data="adm_search"),
                ],
                [
                    InlineKeyboardButton("⛔ Ban", callback_data="adm_ban"),
                    InlineKeyboardButton("✅ Unban", callback_data="adm_unban"),
                ],
                [
                    InlineKeyboardButton("🗑️ Fayllarni tozalash", callback_data="adm_clear"),
                    InlineKeyboardButton("💾 Disk statistika", callback_data="adm_disk"),
                ],
                [
                    InlineKeyboardButton("📢 Kanallar", callback_data="adm_channels"),
                    InlineKeyboardButton("💰 Donat so'rovlar", callback_data="adm_donations"),
                ],
                [InlineKeyboardButton("🔁 DB tekshirish", callback_data="adm_volume")],
            ]
        ),
    )


@app.on_callback_query(admin_filter & filters.create(lambda _, __, q: q.data == "adm_users"))
async def adm_users(client, call):
    users = all_users()
    if not users:
        await call.message.reply("Hech qanday foydalanuvchi yo'q.")
        await call.answer()
        return
    lines = ["👥 *Foydalanuvchilar* (oxirgi 30):\n"]
    for i, (tid, fn, ln, un, lg, jd, bnnd) in enumerate(users[:30], 1):
        full = f"{fn} {ln}".strip() or "—"
        ustr = f"@{un}" if un else "—"
        bmark = " 🚫" if bnnd else ""
        lines.append(f"`{i}.` {full}{bmark} | {ustr}\n   🆔 `{tid}` | {lg.upper()} | {jd[:10]}")
    if len(users) > 30:
        lines.append(f"\n… va yana *{len(users) - 30}* ta")
    text = "\n".join(lines)
    for chunk in [text[i : i + 4000] for i in range(0, len(text), 4000)]:
        await call.message.reply(chunk, parse_mode=enums.ParseMode.MARKDOWN)
    await call.answer()


@app.on_callback_query(admin_filter & filters.create(lambda _, __, q: q.data == "adm_stats"))
async def adm_stats(client, call):
    from datetime import timedelta

    users = all_users()
    total = len(users)
    today_str_val = datetime.now().strftime("%Y-%m-%d")
    today_cnt = sum(1 for u in users if (u[5] or "").startswith(today_str_val))
    uz_cnt = sum(1 for u in users if u[4] == "uz")
    en_cnt = sum(1 for u in users if u[4] == "en")
    ban_cnt = sum(1 for u in users if u[6])
    s = get_global_stats()
    week = []
    for i in range(6, -1, -1):
        d = (datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d")
        cnt_d = sum(1 for u in users if (u[5] or "").startswith(d))
        zr = get_db().execute(
            "SELECT COALESCE(SUM(zip_count),0), COALESCE(SUM(total_mb),0) "
            "FROM zip_stats WHERE date=?",
            (d,),
        ).fetchone()
        bar = "█" * min(cnt_d, 15)
        week.append(f"`{d[5:]}` {bar} *{cnt_d}* foyda | *{zr[0]}* zip | *{zr[1]:.1f}* MB")
    await call.message.reply(
        f"📊 *Statistika*\n\n"
        f"👥 *{total}* | 📅 Bugun: *{today_cnt}*\n"
        f"🇺🇿 *{uz_cnt}* | 🇬🇧 *{en_cnt}* | 🚫 Ban: *{ban_cnt}*\n\n"
        f"📦 Jami ZIP: *{s['total_zips']}* | Bugun: *{s['today_zips']}*\n"
        f"📊 Jami MB: *{s['total_mb']:.1f}* | Bugun: *{s['today_mb']:.1f}*\n"
        f"📎 Jami fayl: *{s['total_files']}*\n\n"
        f"📈 *Oxirgi 7 kun:*\n" + "\n".join(week),
        parse_mode=enums.ParseMode.MARKDOWN,
    )
    await call.answer()


@app.on_callback_query(admin_filter & filters.create(lambda _, __, q: q.data == "adm_disk"))
async def adm_disk(client, call):
    rows = all_users_disk()
    if not rows:
        await call.message.reply("💾 Diskda hech narsa yo'q.")
        await call.answer()
        return
    db_map = {u[0]: (u[1], u[2], u[3]) for u in all_users()}
    total_sz = sum(r[1] for r in rows)
    lines = [f"💾 *Disk statistikasi*\nUmumiy: *{fmt_size(total_sz)}*\n"]
    for i, (uid, used) in enumerate(rows[:30], 1):
        info = db_map.get(uid)
        name = f"{info[0]} {info[1]}".strip() if info else "Noma'lum"
        ustr = f"@{info[2]}" if (info and info[2]) else "—"
        pct = used / MAX_STORAGE * 100
        bar = "█" * min(int(pct / 5), 20)
        lines.append(f"`{i}.` {name} ({ustr})\n   🆔 `{uid}` | {fmt_size(used)} ({pct:.1f}%) {bar}")
    if len(rows) > 30:
        lines.append(f"\n… va yana *{len(rows) - 30}* ta")
    text = "\n".join(lines)
    for chunk in [text[i : i + 4000] for i in range(0, len(text), 4000)]:
        await call.message.reply(chunk, parse_mode=enums.ParseMode.MARKDOWN)
    await call.answer()


@app.on_callback_query(admin_filter & filters.create(lambda _, __, q: q.data == "adm_broadcast"))
async def adm_broadcast(client, call):
    broadcast_mode.add(ADMIN_ID)
    await call.message.reply("📨 Xabarni yozing:\n_(Bekor: /admin)_", parse_mode=enums.ParseMode.MARKDOWN)
    await call.answer()


@app.on_callback_query(admin_filter & filters.create(lambda _, __, q: q.data == "adm_search"))
async def adm_search(client, call):
    waiting_for_user_id[ADMIN_ID] = "info"
    await call.message.reply("🔍 Foydalanuvchi ID sini yuboring:")
    await call.answer()


@app.on_callback_query(admin_filter & filters.create(lambda _, __, q: q.data == "adm_ban"))
async def adm_ban(client, call):
    waiting_for_user_id[ADMIN_ID] = "ban"
    await call.message.reply(
        "⛔ Ban qilmoqchi bo'lgan foydalanuvchi *ID* sini yuboring:",
        parse_mode=enums.ParseMode.MARKDOWN,
    )
    await call.answer()


@app.on_callback_query(admin_filter & filters.create(lambda _, __, q: q.data == "adm_unban"))
async def adm_unban(client, call):
    waiting_for_user_id[ADMIN_ID] = "unban"
    await call.message.reply(
        "✅ Blokdan chiqarmoqchi bo'lgan foydalanuvchi *ID* sini yuboring:",
        parse_mode=enums.ParseMode.MARKDOWN,
    )
    await call.answer()


@app.on_callback_query(admin_filter & filters.create(lambda _, __, q: q.data == "adm_clear"))
async def adm_clear(client, call):
    waiting_for_user_id[ADMIN_ID] = "clear"
    await call.message.reply(
        "🗑️ Fayllarini tozalamoqchi bo'lgan foydalanuvchi *ID* sini yuboring:",
        parse_mode=enums.ParseMode.MARKDOWN,
    )
    await call.answer()


@app.on_callback_query(admin_filter & filters.create(lambda _, __, q: q.data == "adm_channels"))
async def adm_channels(client, call):
    channels = get_channels()
    if channels:
        lines = []
        for cid, info in channels.items():
            ref = f"@{info['username']}" if info.get("username") else (info.get("invite_link") or "link yo'q")
            lines.append(f"• {info['title']} — `{ref}` (`{cid}`)")
        text = "📢 *Majburiy kanallar:*\n\n" + "\n".join(lines)
    else:
        text = "📢 Hozircha kanal qo'shilmagan."

    btns = [
        [InlineKeyboardButton(f"🗑 {info['title']} o'chirish", callback_data=f"adm_rmchan_{cid}")]
        for cid, info in channels.items()
    ]
    btns.append([InlineKeyboardButton("➕ Kanal qo'shish", callback_data="adm_addchan")])
    await call.message.reply(
        text,
        parse_mode=enums.ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup(btns),
    )
    await call.answer()


@app.on_callback_query(admin_filter & filters.create(lambda _, __, q: q.data == "adm_addchan"))
async def adm_addchan(client, call):
    waiting_for_user_id[ADMIN_ID] = "add_channel"
    await call.message.reply(
        "📢 Kanal username yoki ID sini yuboring:\n`@kanal` yoki `-1001234567890`",
        parse_mode=enums.ParseMode.MARKDOWN,
    )
    await call.answer()


@app.on_callback_query(admin_filter & filters.create(lambda _, __, q: q.data.startswith("adm_rmchan_")))
async def adm_rmchan(client, call):
    try:
        cid = int(call.data.split("adm_rmchan_")[1])
        info = required_channels.get(cid, {})
        title = info.get("title", str(cid)) if isinstance(info, dict) else str(info)
        remove_channel(cid)
        await call.message.reply(f"✅ *{title}* o'chirildi.", parse_mode=enums.ParseMode.MARKDOWN)
    except Exception:
        await call.answer("Xato", show_alert=True)
    await call.answer()


@app.on_callback_query(admin_filter & filters.create(lambda _, __, q: q.data == "adm_donations"))
async def adm_donations(client, call):
    pend = get_pending_donations()
    if not pend:
        await call.message.reply("💰 Kutilayotgan donat so'rovlar yo'q.")
        await call.answer()
        return
    lines = ["💰 *Kutilayotgan donatlar:*\n"]
    for don_id, tid, fn, amount, currency, created in pend:
        lines.append(f"ID: `{don_id}` | {fn} (`{tid}`)\n   💵 *{amount} {currency}* | {created[:16]}")
    lines.append("\nTasdiqlash uchun `/admin` → son ID yuboring.")
    await call.message.reply(
        "\n".join(lines),
        parse_mode=enums.ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("✅ Tasdiqlash", callback_data="adm_confirm_don")]]),
    )
    await call.answer()


@app.on_callback_query(admin_filter & filters.create(lambda _, __, q: q.data == "adm_confirm_don"))
async def adm_confirm_don(client, call):
    waiting_for_user_id[ADMIN_ID] = "confirm_donation"
    await call.message.reply("✅ Tasdiqlash uchun Don ID sini yuboring (raqam):")
    await call.answer()


@app.on_callback_query(admin_filter & filters.create(lambda _, __, q: q.data == "adm_volume"))
async def adm_volume_check(client, call):
    lines = [
        "🗄️ *Turso DB*\n",
        f"URL: `{TURSO_URL[:40]}...`" if TURSO_URL else "❌ Ulanmagan!",
        f"Lokal: `{LOCAL_DB}` | Mavjud: `{os.path.exists(LOCAL_DB)}`",
        f"Foydalanuvchilar: `{user_count()}`",
    ]
    await call.message.reply("\n".join(lines), parse_mode=enums.ParseMode.MARKDOWN)
    await call.answer()


# ════════════════════════════════════════════════════════════
#  FLASK — keep-alive
# ════════════════════════════════════════════════════════════
def keep_alive():
    flask_app = Flask(__name__)

    @flask_app.route("/")
    def home():
        s = get_global_stats()
        return f"Bot ishlayapti! Foydalanuvchilar: {user_count()} | Jami ZIP: {s['total_zips']} | {fmt_size(total_disk_all())} disk"

    port = int(os.environ.get("PORT", 5000))
    flask_app.run(host="0.0.0.0", port=port)


# ════════════════════════════════════════════════════════════
#  MAIN
# ════════════════════════════════════════════════════════════
if __name__ == "__main__":
    if not all([os.environ.get("API_ID"), os.environ.get("API_HASH"), os.environ.get("BOT_TOKEN")]):
        raise RuntimeError("API_ID, API_HASH, BOT_TOKEN to'ldirilmagan!")

    get_db()
    init_db()
    _load_channels()

    os.makedirs(BASE_DIR, exist_ok=True)
    os.makedirs(STICKER_DIR, exist_ok=True)

    print(f"[BOT] Tayyorlanmoqda... Kanallar: {len(required_channels)}")

    threading.Thread(target=keep_alive, daemon=True).start()

    print("[BOT] Ishga tushdi!")
    app.run()
