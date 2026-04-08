import os
import re
import shutil
import zipfile
import asyncio
import threading
import sqlite3
from datetime import datetime
from flask import Flask
from pyrogram import Client, filters, enums
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, Message

# ════════════════════════════════════════════════════════════
#  CONFIG
# ════════════════════════════════════════════════════════════
API_ID    = int(os.environ.get("API_ID",    29517932))
API_HASH  = os.environ.get("API_HASH",  "572b177f48692c0cbd88664120fb87f4")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "7579799414:AAFubjp6EdJySpv8tQHxvkpgO1i3fM45kKg")

BASE_DIR       = "user_files"
STICKER_DIR    = "stickers"
ADMIN_ID       = 1663567950
MAX_STORAGE    = 500 * 1024 * 1024   # 500 MB
AUTO_ZIP_DELAY = 180                  # 3 daqiqa

VOLUME_PATH = os.environ.get("VOLUME_PATH", "/app/data")
DB_PATH     = os.path.join(VOLUME_PATH, "bot.db")

# ════════════════════════════════════════════════════════════
#  IN-MEMORY STATE
# ════════════════════════════════════════════════════════════
broadcast_mode:      set  = set()
waiting_for_user_id: dict = {}   # {admin_id: action}
user_status_msg:     dict = {}   # {uid: Message}   — bitta "qabul qilinmoqda" xabari
user_auto_zip:       dict = {}   # {uid: Task}

# ════════════════════════════════════════════════════════════
#  VOLUME CHECK
# ════════════════════════════════════════════════════════════
def check_volume():
    print(f"[VOLUME] DB: {DB_PATH} | exists: {os.path.exists(VOLUME_PATH)}")
    if os.path.exists(VOLUME_PATH):
        files = os.listdir(VOLUME_PATH)
        if "bot.db" in files:
            print(f"[VOLUME] bot.db OK — {os.path.getsize(DB_PATH)} bytes")
        else:
            print("[VOLUME] bot.db topilmadi — yangi yaratiladi")
    else:
        print(f"[VOLUME] ❌ Volume mavjud emas: {VOLUME_PATH}")

# ════════════════════════════════════════════════════════════
#  DATABASE
# ════════════════════════════════════════════════════════════
def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
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
        """)
        # Fayllar jadvali — file_id saqlanadi, ZIP vaqtida yuklanadi
        conn.execute("""
            CREATE TABLE IF NOT EXISTS user_files (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_id INTEGER NOT NULL,
                file_id     TEXT    NOT NULL,
                file_type   TEXT    NOT NULL,
                filename    TEXT    NOT NULL,
                file_size   INTEGER DEFAULT 0,
                added_at    TEXT    NOT NULL
            )
        """)
        for col, dfn in [("waiting_zip","INTEGER DEFAULT 0"),("is_banned","INTEGER DEFAULT 0")]:
            try:
                conn.execute(f"ALTER TABLE users ADD COLUMN {col} {dfn}")
            except Exception:
                pass
        conn.commit()
    print(f"[DB] tayyor: {DB_PATH}")


# ── File record funksiyalari ─────────────────────────────
def add_file_record(uid: int, file_id: str, file_type: str,
                    filename: str, file_size: int):
    with sqlite3.connect(DB_PATH) as c:
        c.execute(
            "INSERT INTO user_files(telegram_id,file_id,file_type,filename,file_size,added_at)"
            " VALUES(?,?,?,?,?,?)",
            (uid, file_id, file_type, filename, file_size,
             datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        )
        c.commit()

def get_user_files(uid: int) -> list:
    """[(id, file_id, file_type, filename, file_size), ...]"""
    with sqlite3.connect(DB_PATH) as c:
        return c.execute(
            "SELECT id,file_id,file_type,filename,file_size "
            "FROM user_files WHERE telegram_id=? ORDER BY id",
            (uid,)
        ).fetchall()

def clear_user_files(uid: int):
    with sqlite3.connect(DB_PATH) as c:
        c.execute("DELETE FROM user_files WHERE telegram_id=?", (uid,))
        c.commit()

def user_file_count(uid: int) -> int:
    with sqlite3.connect(DB_PATH) as c:
        r = c.execute(
            "SELECT COUNT(*) FROM user_files WHERE telegram_id=?", (uid,)
        ).fetchone()
    return r[0] if r else 0

def user_pending_size(uid: int) -> int:
    """DB dagi fayllarning umumiy taxminiy hajmi (bytes)"""
    with sqlite3.connect(DB_PATH) as c:
        r = c.execute(
            "SELECT COALESCE(SUM(file_size),0) FROM user_files WHERE telegram_id=?", (uid,)
        ).fetchone()
    return r[0] if r else 0

def all_users_pending() -> list:
    """[(uid, file_count, total_size), ...] — fayllari bor foydalanuvchilar"""
    with sqlite3.connect(DB_PATH) as c:
        return c.execute(
            "SELECT telegram_id, COUNT(*), COALESCE(SUM(file_size),0) "
            "FROM user_files GROUP BY telegram_id ORDER BY 3 DESC"
        ).fetchall()


def set_waiting(uid: int, val: bool):
    with sqlite3.connect(DB_PATH) as c:
        c.execute("UPDATE users SET waiting_zip=? WHERE telegram_id=?", (int(val), uid))
        c.commit()

def is_waiting(uid: int) -> bool:
    with sqlite3.connect(DB_PATH) as c:
        r = c.execute("SELECT waiting_zip FROM users WHERE telegram_id=?", (uid,)).fetchone()
    return bool(r[0]) if r else False

def upsert_user(user, lang=None):
    with sqlite3.connect(DB_PATH) as c:
        c.execute("""
            INSERT INTO users(telegram_id,first_name,last_name,username,language,joined_at)
            VALUES(?,?,?,?,?,?)
            ON CONFLICT(telegram_id) DO UPDATE SET
                first_name=excluded.first_name, last_name=excluded.last_name,
                username=excluded.username, language=COALESCE(?,language)
        """, (user.id, user.first_name or "", user.last_name or "",
              user.username or "", lang or "uz",
              datetime.now().strftime("%Y-%m-%d %H:%M:%S"), lang))
        c.commit()

def get_lang(uid: int):
    with sqlite3.connect(DB_PATH) as c:
        r = c.execute("SELECT language FROM users WHERE telegram_id=?", (uid,)).fetchone()
    return r[0] if r else None

def is_banned(uid: int) -> bool:
    with sqlite3.connect(DB_PATH) as c:
        r = c.execute("SELECT is_banned FROM users WHERE telegram_id=?", (uid,)).fetchone()
    return bool(r[0]) if r else False

def ban_user(uid: int):
    with sqlite3.connect(DB_PATH) as c:
        c.execute("UPDATE users SET is_banned=1 WHERE telegram_id=?", (uid,)); c.commit()

def unban_user(uid: int):
    with sqlite3.connect(DB_PATH) as c:
        c.execute("UPDATE users SET is_banned=0 WHERE telegram_id=?", (uid,)); c.commit()

def all_users() -> list:
    with sqlite3.connect(DB_PATH) as c:
        return c.execute(
            "SELECT telegram_id,first_name,last_name,username,language,joined_at,is_banned "
            "FROM users ORDER BY id DESC"
        ).fetchall()

def user_count() -> int:
    with sqlite3.connect(DB_PATH) as c:
        return c.execute("SELECT COUNT(*) FROM users").fetchone()[0]

def today_count() -> int:
    t = datetime.now().strftime("%Y-%m-%d")
    with sqlite3.connect(DB_PATH) as c:
        return c.execute("SELECT COUNT(*) FROM users WHERE joined_at LIKE ?", (f"{t}%",)).fetchone()[0]

def get_user_by_id(tid: int):
    with sqlite3.connect(DB_PATH) as c:
        return c.execute(
            "SELECT telegram_id,first_name,last_name,username,language,joined_at,is_banned "
            "FROM users WHERE telegram_id=?", (tid,)
        ).fetchone()

# ════════════════════════════════════════════════════════════
#  TEXTS  (i18n)
# ════════════════════════════════════════════════════════════
TEXTS = {
    "uz": {
        "choose_lang": "🌍 Tilni tanlang:",
        "welcome": (
            "✅ Til saqlandi!\n\n"
            "👋 Salom, *{name}*!\n\n"
            "📦 Men fayllaringizni *ZIP arxivga* yig'ib beraman.\n\n"
            "━━━━━━━━━━━━━━━\n"
            "📎 *Qanday ishlaydi:*\n"
            "① Istalgan fayl yuboring\n"
            "② Barcha fayllar yuklanib bo'lgach tugmani bosing\n"
            "③ ZIP nomini yozing — tayyor!\n\n"
            "⏱ *Diqqat:* 3 daqiqa ichida tugma bosilmasa,\n"
            "fayllaringiz *avtomatik* ZIP lanadi.\n\n"
            "💾 Har bir foydalanuvchiga: max *500 MB*"
        ),
        "receiving":    "📥 *Fayllar qabul qilinmoqda...* kutib turing",
        "files_saved": (
            "✅ *{count} ta fayl* qabul qilindi!\n\n"
            "👇 Hammasi tayyor bo'lsa ZIP yasash tugmasini bosing:"
        ),
        "storage_full": (
            "❌ *Xotira to'lib qoldi!*\n\n"
            "💾 Ishlatilgan: *{used}* / *{max}*\n\n"
            "📦 Avval «ZIP yasash» tugmasini bosib fayllarni oling,\n"
            "so'ng yangi fayl yuboring."
        ),
        "ready_btn":    "📦 ZIP yasash",
        "ask_zip_name": (
            "✏️ *ZIP fayl nomini yozing:*\n\n"
            "• Harf, raqam, ` - ` va ` _ ` ishlating\n"
            "• Bo'sh joy ham bo'lsa — `_` ga aylantiriladi\n\n"
            "📌 Misol: `mening_fayllar` yoki `mening fayllar`"
        ),
        "zip_caption":   "📦 *ZIP tayyor!*\n\n🤖 @Zipla_bot — Hayotni Ziplab o't!",
        "no_files":      "⚠️ *Fayl topilmadi.* Avval fayl yuboring.",
        "zip_error":     "❌ *ZIP yaratishda xato.* Qaytadan urining.",
        "bad_name":      "❌ *Noto'g'ri nom!*\n\nFaqat harf, raqam, bo'sh joy, `-` va `_` ishlating.\n\n📌 Misol: `mening fayllar`",
        "lang_set":      "✅ Til saqlandi!",
        "change_lang":   "🌍 Tilni o'zgartirish",
        "download_err": (
            "⚠️ *Fayl qabul qilinmadi!*\n\n"
            "😔 Kechirasiz, faylni serverga yuklashda xatolik yuz berdi.\n"
            "Bu muammo tez orada bartaraf etiladi.\n\n"
            "🔄 *Iltimos, faylni qaytadan yuboring.*\n"
            "Agar muammo davom etsa, boshqa turdagi fayl yuborib ko'ring."
        ),
        "creating_zip":  "⚙️ *ZIP yaratilmoqda...* iltimos kuting",
        "banned":        "🚫 Siz tizimdan bloklangansiz.",
        "auto_zip_warn": (
            "⏰ *3 daqiqa o'tdi!*\n\n"
            "🤖 Fayllaringizdan avtomatik ZIP yaratilmoqda..."
        ),
        "auto_zip_done": (
            "🤖 *Avtomatik ZIP yaratildi!*\n\n"
            "3 daqiqa ichida tugma bosilmagani uchun\n"
            "fayllaringiz avtomatik arxivlandi."
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
            "① Send any files you want to zip\n"
            "② Once all uploaded, press the button\n"
            "③ Give it a name — done!\n\n"
            "⏱ *Note:* If button not pressed within 3 min,\n"
            "files are *auto-zipped*.\n\n"
            "💾 Storage limit per user: *500 MB*"
        ),
        "receiving":    "📥 *Receiving files...* please wait",
        "files_saved": (
            "✅ *{count} file(s)* received!\n\n"
            "👇 When all files are sent, press Create ZIP:"
        ),
        "storage_full": (
            "❌ *Storage full!*\n\n"
            "💾 Used: *{used}* of *{max}*\n\n"
            "📦 Press «Create ZIP» to download your files first,\n"
            "then send new ones."
        ),
        "ready_btn":    "📦 Create ZIP",
        "ask_zip_name": (
            "✏️ *Enter ZIP file name:*\n\n"
            "• Use letters, numbers, ` - ` and ` _ `\n"
            "• Spaces are allowed — auto-converted to `_`\n\n"
            "📌 Example: `my_files` or `my files`"
        ),
        "zip_caption":   "📦 *ZIP is ready!*\n\n🤖 @Zipla\\_bot — Zip your life!",
        "no_files":      "⚠️ *No files found.* Please send files first.",
        "zip_error":     "❌ *ZIP creation failed.* Please try again.",
        "bad_name":      "❌ *Invalid name!*\n\nUse letters, numbers, spaces, `-` and `_` only.\n\n📌 Example: `my files`",
        "lang_set":      "✅ Language saved!",
        "change_lang":   "🌍 Change language",
        "download_err": (
            "⚠️ *File not received!*\n\n"
            "😔 Sorry, there was an error uploading the file to the server.\n"
            "This issue will be resolved shortly.\n\n"
            "🔄 *Please resend the file.*\n"
            "If the problem persists, try a different file type."
        ),
        "creating_zip":  "⚙️ *Creating ZIP...* please wait",
        "banned":        "🚫 You are blocked from this system.",
        "auto_zip_warn": (
            "⏰ *3 minutes passed!*\n\n"
            "🤖 Auto-creating ZIP from your files..."
        ),
        "auto_zip_done": (
            "🤖 *Auto ZIP created!*\n\n"
            "Since the button wasn't pressed within 3 minutes,\n"
            "your files were automatically archived."
        ),
    },
}

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

def storage_used(uid: int) -> int:
    """Foydalanuvchining DB dagi pending fayllar hajmi"""
    return user_pending_size(uid)

def file_count(uid: int) -> int:
    """Foydalanuvchining DB dagi pending fayllar soni"""
    return user_file_count(uid)

def total_storage_all() -> int:
    """Barcha pending fayllarning umumiy taxminiy hajmi"""
    with sqlite3.connect(DB_PATH) as c:
        r = c.execute("SELECT COALESCE(SUM(file_size),0) FROM user_files").fetchone()
    return r[0] if r else 0

def all_users_storage() -> list:
    """(uid, used_bytes) — pending fayllari bo'yicha tartiblangan"""
    rows = all_users_pending()
    return [(r[0], r[2]) for r in rows if r[2] > 0]

def fmt_size(b: int) -> str:
    if b < 1024 ** 2:
        return f"{b/1024:.1f} KB"
    return f"{b/1024**2:.1f} MB"

def unique_path(directory: str, filename: str) -> str:
    full = os.path.join(directory, filename)
    if not os.path.exists(full):
        return full
    base, ext = os.path.splitext(filename)
    stamp = datetime.now().strftime("%H%M%S_%f")[:9]
    return os.path.join(directory, f"{base}_{stamp}{ext}")

async def send_sticker(client, chat_id: int, name: str):
    path = os.path.join(STICKER_DIR, f"{name}.webp")
    if os.path.exists(path):
        try:
            await client.send_sticker(chat_id, path)
        except Exception:
            pass

async def error_to_admin(client, context: str, uid: int, err: Exception):
    """Faqat xatoliklarni adminga yuborish"""
    try:
        await client.send_message(
            ADMIN_ID,
            f"🚨 *XATOLIK*\n\n"
            f"📍 Joy: `{context}`\n"
            f"👤 Foydalanuvchi ID: `{uid}`\n"
            f"❗ Xato: `{type(err).__name__}: {err}`\n"
            f"🕐 Vaqt: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            parse_mode=enums.ParseMode.MARKDOWN,
        )
    except Exception as e:
        print(f"[error_to_admin failed] {e}")

# ════════════════════════════════════════════════════════════
#  AUTO-ZIP TIMER
# ════════════════════════════════════════════════════════════
async def cancel_auto_zip(uid: int):
    task = user_auto_zip.get(uid)
    if task and not task.done():
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
    user_auto_zip.pop(uid, None)

async def auto_zip_runner(client, chat_id: int, uid: int):
    await asyncio.sleep(AUTO_ZIP_DELAY)
    if user_file_count(uid) == 0 or is_waiting(uid):
        return
    try:
        await client.send_message(
            chat_id, tx(uid, "auto_zip_warn"),
            parse_mode=enums.ParseMode.MARKDOWN,
        )
    except Exception:
        pass
    auto_name = f"auto_{datetime.now():%Y%m%d_%H%M%S}"
    await create_and_send_zip(client, chat_id, uid, auto_name, auto=True)

def start_auto_zip(client, chat_id: int, uid: int):
    loop = asyncio.get_event_loop()
    old  = user_auto_zip.get(uid)
    if old and not old.done():
        old.cancel()
    user_auto_zip[uid] = loop.create_task(auto_zip_runner(client, chat_id, uid))

# ════════════════════════════════════════════════════════════
#  ZIP YARATISH
# ════════════════════════════════════════════════════════════
async def create_and_send_zip(client, chat_id: int, uid: int,
                               zip_name_raw: str, auto: bool = False):
    file_records = get_user_files(uid)
    if not file_records:
        await client.send_message(chat_id, tx(uid, "no_files"),
                                   parse_mode=enums.ParseMode.MARKDOWN)
        return

    udir     = user_dir(uid)
    zip_name = f"{zip_name_raw}.zip"
    zip_path = os.path.join(udir, zip_name)

    progress = await client.send_message(
        chat_id, tx(uid, "creating_zip"),
        parse_mode=enums.ParseMode.MARKDOWN,
    )
    try:
        # 1) Har bir file_id bo'yicha faylni yuklab olish
        downloaded = []
        seen_names = set()
        for _, file_id, file_type, filename, _ in file_records:
            # Takrorlanmasin deb noyob nom
            base, ext = os.path.splitext(filename)
            uname = filename
            counter = 1
            while uname in seen_names:
                uname = f"{base}_{counter}{ext}"
                counter += 1
            seen_names.add(uname)
            save_path = os.path.join(udir, uname)
            try:
                await client.download_media(file_id, file_name=save_path)
                downloaded.append((save_path, uname))
            except Exception as e:
                await error_to_admin(client, f"create_zip → download {file_type}", uid, e)
                # Yuklab bo'lmagan faylni o'tkazib yuboramiz, davom etamiz

        if not downloaded:
            raise RuntimeError("Hech bir fayl yuklab olinmadi")

        # 2) ZIP yaratish
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for fpath, arcname in downloaded:
                if os.path.isfile(fpath):
                    zf.write(fpath, arcname=arcname)

        # 3) ZIP yuborish
        caption = tx(uid, "zip_caption")
        if auto:
            caption = tx(uid, "auto_zip_done") + "\n\n" + caption

        await client.send_document(
            chat_id, zip_path,
            caption=caption,
            file_name=zip_name,
            parse_mode=enums.ParseMode.MARKDOWN,
        )
    except Exception as e:
        await client.send_message(chat_id, tx(uid, "zip_error"),
                                   parse_mode=enums.ParseMode.MARKDOWN)
        await error_to_admin(client, "create_and_send_zip", uid, e)
        return
    finally:
        try:
            await progress.delete()
        except Exception:
            pass
        sm = user_status_msg.pop(uid, None)
        if sm:
            try:
                await sm.delete()
            except Exception:
                pass

    # 4) Tozalash — papka + DB yozuvlari
    try:
        shutil.rmtree(udir)
        os.makedirs(udir, exist_ok=True)
    except Exception as e:
        print(f"[cleanup error] {e}")

    clear_user_files(uid)
    set_waiting(uid, False)
    user_auto_zip.pop(uid, None)

# ════════════════════════════════════════════════════════════
#  FAYL QABUL QILISH  (markaziy funksiya)
# ════════════════════════════════════════════════════════════
async def receive_file(client, message: Message, obj, filename: str):
    uid = message.from_user.id

    if is_banned(uid):
        await message.reply(tx(uid, "banned"))
        return

    # Taxminiy hajm tekshiruvi (file_size metadata'dan)
    fsize       = getattr(obj, "file_size", 0) or 0
    pending_now = user_pending_size(uid)
    if pending_now + fsize > MAX_STORAGE:
        await message.reply(
            tx(uid, "storage_full",
               used=fmt_size(pending_now), max=fmt_size(MAX_STORAGE)),
            parse_mode=enums.ParseMode.MARKDOWN,
        )
        return

    # file_id ni aniqlash — har fayl turida har xil
    file_id = getattr(obj, "file_id", None)
    if not file_id:
        # Rasm uchun eng katta o'lcham
        if message.photo:
            file_id = message.photo.file_id
        else:
            return

    # file_type
    if   message.document:   ftype = "document"
    elif message.photo:      ftype = "photo"
    elif message.video:      ftype = "video"
    elif message.audio:      ftype = "audio"
    elif message.voice:      ftype = "voice"
    elif message.video_note: ftype = "video_note"
    elif message.sticker:    ftype = "sticker"
    elif message.animation:  ftype = "animation"
    else:                    ftype = "file"

    # DB ga yoz
    add_file_record(uid, file_id, ftype, filename, fsize)

    # Foydalanuvchi xabarini o'chirish
    try:
        await message.delete()
    except Exception:
        pass

    new_cnt = user_file_count(uid)

    # Bitta status xabar — yangi bo'lsa yuborish, bor bo'lsa yangilash
    sm = user_status_msg.get(uid)
    if sm is None:
        try:
            sm = await client.send_message(
                message.chat.id,
                tx(uid, "files_saved", count=new_cnt),
                parse_mode=enums.ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton(tx(uid, "ready_btn"), callback_data="zip_now")
                ]])
            )
            user_status_msg[uid] = sm
        except Exception:
            pass
    else:
        try:
            await sm.edit_text(
                tx(uid, "files_saved", count=new_cnt),
                parse_mode=enums.ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton(tx(uid, "ready_btn"), callback_data="zip_now")
                ]])
            )
        except Exception:
            pass

    # Auto-ZIP taymerni qayta boshlash
    start_auto_zip(client, message.chat.id, uid)

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
    if is_banned(uid):
        await message.reply(TEXTS["uz"]["banned"])
        return
    if get_lang(uid) is None:
        upsert_user(message.from_user, "uz")
    await message.reply(
        TEXTS["uz"]["choose_lang"],
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("🇺🇿 O'zbek",  callback_data="setlang_uz"),
            InlineKeyboardButton("🇬🇧 English", callback_data="setlang_en"),
        ]])
    )

# ════════════════════════════════════════════════════════════
#  TIL TANLASH
# ════════════════════════════════════════════════════════════
@app.on_callback_query(filters.create(lambda _, __, q: q.data.startswith("setlang_")))
async def cb_set_lang(client, call):
    lang = call.data.split("_")[1]
    upsert_user(call.from_user, lang)
    try:
        await call.message.delete()
    except Exception:
        pass
    name  = call.from_user.first_name or "Foydalanuvchi"
    texts = TEXTS[lang]
    await client.send_message(
        call.message.chat.id,
        texts["welcome"].format(name=name),
        parse_mode=enums.ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton(texts["change_lang"], callback_data="change_lang")
        ]])
    )
    await send_sticker(client, call.message.chat.id, "start")
    await call.answer(texts["lang_set"])


@app.on_callback_query(filters.create(lambda _, __, q: q.data == "change_lang"))
async def cb_change_lang(client, call):
    await call.message.reply(
        TEXTS["uz"]["choose_lang"],
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("🇺🇿 O'zbek",  callback_data="setlang_uz"),
            InlineKeyboardButton("🇬🇧 English", callback_data="setlang_en"),
        ]])
    )
    await call.answer()

# ════════════════════════════════════════════════════════════
#  FAYL HANDLERLARI — barcha tur qabul qilinadi
# ════════════════════════════════════════════════════════════
@app.on_message(filters.document)
async def on_document(client, message):
    doc = message.document
    await receive_file(client, message, doc,
                       doc.file_name or f"file_{datetime.now():%Y%m%d_%H%M%S}")

@app.on_message(filters.photo)
async def on_photo(client, message):
    await receive_file(client, message, message.photo,
                       f"photo_{datetime.now():%Y%m%d_%H%M%S}.jpg")

@app.on_message(filters.video)
async def on_video(client, message):
    v = message.video
    await receive_file(client, message, v,
                       v.file_name or f"video_{datetime.now():%Y%m%d_%H%M%S}.mp4")

@app.on_message(filters.audio)
async def on_audio(client, message):
    a = message.audio
    await receive_file(client, message, a,
                       a.file_name or f"audio_{datetime.now():%Y%m%d_%H%M%S}.mp3")

@app.on_message(filters.voice)
async def on_voice(client, message):
    await receive_file(client, message, message.voice,
                       f"voice_{datetime.now():%Y%m%d_%H%M%S}.ogg")

@app.on_message(filters.video_note)
async def on_video_note(client, message):
    await receive_file(client, message, message.video_note,
                       f"videonote_{datetime.now():%Y%m%d_%H%M%S}.mp4")

@app.on_message(filters.sticker)
async def on_sticker_msg(client, message):
    await receive_file(client, message, message.sticker,
                       f"sticker_{datetime.now():%Y%m%d_%H%M%S}.webp")

@app.on_message(filters.animation)
async def on_animation(client, message):
    g = message.animation
    await receive_file(client, message, g,
                       g.file_name or f"gif_{datetime.now():%Y%m%d_%H%M%S}.gif")

@app.on_message(filters.contact)
async def on_contact(client, message):
    # Kontaktni vCard sifatida saqlash
    c   = message.contact
    fn  = f"contact_{c.first_name or 'contact'}_{datetime.now():%Y%m%d_%H%M%S}.vcf"
    uid = message.from_user.id
    udir = user_dir(uid)
    try:
        await message.delete()
    except Exception:
        pass
    save_path = unique_path(udir, fn)
    vcard = (
        f"BEGIN:VCARD\nVERSION:3.0\n"
        f"FN:{c.first_name or ''} {c.last_name or ''}\n"
        f"TEL:{c.phone_number}\n"
        f"END:VCARD\n"
    )
    with open(save_path, "w", encoding="utf-8") as f:
        f.write(vcard)
    new_cnt  = file_count(uid)
    new_used = storage_used(uid)
    sm = user_status_msg.get(uid)
    if sm:
        try:
            await sm.edit_text(
                tx(uid, "files_saved", count=new_cnt, size=fmt_size(new_used)),
                parse_mode=enums.ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton(tx(uid, "ready_btn"), callback_data="zip_now")
                ]])
            )
        except Exception:
            pass
    else:
        sm2 = await client.send_message(
            message.chat.id,
            tx(uid, "files_saved", count=new_cnt, size=fmt_size(new_used)),
            parse_mode=enums.ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton(tx(uid, "ready_btn"), callback_data="zip_now")
            ]])
        )
        user_status_msg[uid] = sm2
    start_auto_zip(client, message.chat.id, uid)

# ════════════════════════════════════════════════════════════
#  ZIP YASASH TUGMASI
# ════════════════════════════════════════════════════════════
@app.on_callback_query(filters.create(lambda _, __, q: q.data == "zip_now"))
async def cb_zip_now(client, call):
    uid = call.from_user.id
    if user_file_count(uid) == 0:
        await call.message.reply(tx(uid, "no_files"), parse_mode=enums.ParseMode.MARKDOWN)
        await call.answer()
        return
    await cancel_auto_zip(uid)
    set_waiting(uid, True)
    await call.message.reply(
        tx(uid, "ask_zip_name"),
        parse_mode=enums.ParseMode.MARKDOWN,
    )
    await call.answer()

# ════════════════════════════════════════════════════════════
#  MATN HANDLERI
# ════════════════════════════════════════════════════════════
ZIP_NAME_RE = re.compile(r'^[\w\- ]{1,64}$')


@app.on_message(filters.text & ~filters.command(["start", "admin"]))
async def on_text(client, message):
    uid = message.from_user.id

    if get_lang(uid) is None:
        upsert_user(message.from_user, "uz")
        await message.reply(
            TEXTS["uz"]["choose_lang"],
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🇺🇿 O'zbek",  callback_data="setlang_uz"),
                InlineKeyboardButton("🇬🇧 English", callback_data="setlang_en"),
            ]])
        )
        return

    # ── Admin broadcast ──
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
        try:
            await prog.delete()
        except Exception:
            pass
        await message.reply(
            f"📨 *Broadcast tugadi!*\n\n✅ Yuborildi: *{ok}*\n❌ Yuborilmadi: *{fail}*",
            parse_mode=enums.ParseMode.MARKDOWN,
        )
        return

    # ── Admin: foydalanuvchi ID kutilmoqda ──
    if uid == ADMIN_ID and uid in waiting_for_user_id:
        action = waiting_for_user_id.pop(uid)
        raw    = message.text.strip()
        try:
            target_id = int(re.search(r'\d+', raw).group())
        except Exception:
            await message.reply("❌ Noto'g'ri ID. Faqat raqam yuboring.")
            return
        data = get_user_by_id(target_id)

        if action == "ban":
            if not data:
                await message.reply(f"❌ ID `{target_id}` topilmadi.",
                                    parse_mode=enums.ParseMode.MARKDOWN); return
            ban_user(target_id)
            await message.reply(
                f"⛔ *Bloklandi:* {data[1]} {data[2]} (`{target_id}`)",
                parse_mode=enums.ParseMode.MARKDOWN,
            )
            try:
                await client.send_message(target_id, tx(target_id, "banned"))
            except Exception:
                pass

        elif action == "unban":
            if not data:
                await message.reply(f"❌ ID `{target_id}` topilmadi.",
                                    parse_mode=enums.ParseMode.MARKDOWN); return
            unban_user(target_id)
            await message.reply(
                f"✅ *Blokdan chiqarildi:* {data[1]} {data[2]} (`{target_id}`)",
                parse_mode=enums.ParseMode.MARKDOWN,
            )

        elif action == "info":
            if not data:
                await message.reply(f"❌ ID `{target_id}` topilmadi.",
                                    parse_mode=enums.ParseMode.MARKDOWN); return
            tid, fn, ln, un, lg, jd, bnnd = data
            fcnt       = user_file_count(tid)
            used       = user_pending_size(tid)
            ban_status = "✅ Yoq" if not bnnd else "🚫 Ha"
            uname      = f"@{un}" if un else "—"
            await message.reply(
                f"👤 *Foydalanuvchi ma'lumoti*\n\n"
                f"🆔 ID: `{tid}`\n"
                f"📛 Ism: {fn} {ln}\n"
                f"🔗 Username: {uname}\n"
                f"🌍 Til: {lg.upper()}\n"
                f"📅 Qo'shilgan: {jd[:16]}\n"
                f"📁 Pending fayllar: {fcnt} ta\n"
                f"💾 Taxminiy hajm: {fmt_size(used)}\n"
                f"🚫 Bloklangan: {ban_status}",
                parse_mode=enums.ParseMode.MARKDOWN,
            )

        elif action == "clear":
            if not data:
                await message.reply(f"❌ ID `{target_id}` topilmadi.",
                                    parse_mode=enums.ParseMode.MARKDOWN); return
            ud = os.path.join(BASE_DIR, str(target_id))
            if os.path.exists(ud):
                shutil.rmtree(ud); os.makedirs(ud, exist_ok=True)
            clear_user_files(target_id)
            await message.reply(
                f"🗑️ ID `{target_id}` — fayllar tozalandi (disk + DB).",
                parse_mode=enums.ParseMode.MARKDOWN,
            )
        return

    # ── Oddiy foydalanuvchi: ZIP nomi ──
    if not is_waiting(uid):
        return

    zip_name_raw = message.text.strip()
    if not ZIP_NAME_RE.match(zip_name_raw):
        await message.reply(tx(uid, "bad_name"), parse_mode=enums.ParseMode.MARKDOWN)
        return

    zip_name_clean = re.sub(r'\s+', '_', zip_name_raw)
    set_waiting(uid, False)
    await cancel_auto_zip(uid)
    # Foydalanuvchi matnini o'chirish
    try:
        await message.delete()
    except Exception:
        pass
    await create_and_send_zip(client, message.chat.id, uid, zip_name_clean)

# ════════════════════════════════════════════════════════════
#  ADMIN PANEL
# ════════════════════════════════════════════════════════════
def _is_admin(_, __, q): return q.from_user.id == ADMIN_ID
admin_filter = filters.create(_is_admin)


@app.on_message(filters.command("admin") & filters.user(ADMIN_ID))
async def cmd_admin(client, message):
    cnt   = user_count()
    today = today_count()
    disk  = fmt_size(total_storage_all())
    await send_sticker(client, message.chat.id, "admin")
    await message.reply(
        f"🔐 *Admin Panel*\n\n"
        f"👥 Jami foydalanuvchi : *{cnt}*\n"
        f"📅 Bugun qo'shilgan   : *{today}*\n"
        f"💾 Umumiy disk hajmi  : *{disk}*\n"
        f"🗄️ DB : `{DB_PATH}`",
        parse_mode=enums.ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("👥 Foydalanuvchilar",     callback_data="adm_users"),
             InlineKeyboardButton("📊 Statistika",            callback_data="adm_stats")],
            [InlineKeyboardButton("📨 Broadcast",             callback_data="adm_broadcast"),
             InlineKeyboardButton("🔍 Foydalanuvchi izlash",  callback_data="adm_search")],
            [InlineKeyboardButton("⛔ Ban",                   callback_data="adm_ban"),
             InlineKeyboardButton("✅ Unban",                 callback_data="adm_unban")],
            [InlineKeyboardButton("🗑️ Fayllarni tozalash",   callback_data="adm_clear"),
             InlineKeyboardButton("💾 Disk statistika",      callback_data="adm_disk")],
            [InlineKeyboardButton("🔁 Volume tekshirish",    callback_data="adm_volume")],
        ]),
    )


@app.on_callback_query(admin_filter & filters.create(lambda _, __, q: q.data == "adm_users"))
async def adm_users(client, call):
    users = all_users()
    if not users:
        await call.message.reply("Hech qanday foydalanuvchi yo'q.")
        await call.answer(); return

    lines = ["👥 *Foydalanuvchilar* (oxirgi 30):\n"]
    for i, (tid, fn, ln, un, lg, jd, bnnd) in enumerate(users[:30], 1):
        full  = f"{fn} {ln}".strip() or "—"
        ustr  = f"@{un}" if un else "username yo'q"
        bmark = " 🚫" if bnnd else ""
        lines.append(
            f"`{i}.` {full}{bmark} | {ustr}\n"
            f"   🆔 `{tid}` | {lg.upper()} | {jd[:10]}"
        )
    if len(users) > 30:
        lines.append(f"\n… va yana *{len(users)-30}* ta")

    text = "\n".join(lines)
    for chunk in [text[i:i+4000] for i in range(0, len(text), 4000)]:
        await call.message.reply(chunk, parse_mode=enums.ParseMode.MARKDOWN)
    await call.answer()


@app.on_callback_query(admin_filter & filters.create(lambda _, __, q: q.data == "adm_stats"))
async def adm_stats(client, call):
    from datetime import timedelta
    users     = all_users()
    total     = len(users)
    today_str = datetime.now().strftime("%Y-%m-%d")
    today_cnt = sum(1 for u in users if (u[5] or "").startswith(today_str))
    uz_cnt    = sum(1 for u in users if u[4] == "uz")
    en_cnt    = sum(1 for u in users if u[4] == "en")
    ban_cnt   = sum(1 for u in users if u[6])
    disk      = fmt_size(total_storage_all())

    week = []
    for i in range(6, -1, -1):
        d     = (datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d")
        cnt_d = sum(1 for u in users if (u[5] or "").startswith(d))
        bar   = "█" * min(cnt_d, 15)
        week.append(f"`{d[5:]}` {bar} *{cnt_d}*")

    await call.message.reply(
        f"📊 *Statistika*\n\n"
        f"👥 Jami: *{total}*  |  📅 Bugun: *{today_cnt}*\n"
        f"🇺🇿 O'zbek: *{uz_cnt}*  |  🇬🇧 English: *{en_cnt}*\n"
        f"🚫 Bloklangan: *{ban_cnt}*  |  💾 Disk: *{disk}*\n\n"
        f"📈 *Oxirgi 7 kun:*\n" + "\n".join(week),
        parse_mode=enums.ParseMode.MARKDOWN,
    )
    await call.answer()


@app.on_callback_query(admin_filter & filters.create(lambda _, __, q: q.data == "adm_disk"))
async def adm_disk(client, call):
    """Har bir foydalanuvchi uchun pending fayllar statistikasi"""
    rows = all_users_pending()   # [(uid, file_count, total_size), ...]
    if not rows:
        await call.message.reply("💾 Hozircha hech kimning fayli yo'q.")
        await call.answer(); return

    db_users = {u[0]: (u[1], u[2], u[3]) for u in all_users()}
    total_sz  = sum(r[2] for r in rows)
    total_cnt = sum(r[1] for r in rows)
    lines     = [
        f"💾 *Disk statistikasi* (pending fayllar)\n"
        f"Jami: *{total_cnt} ta fayl* | *{fmt_size(total_sz)}*\n"
    ]
    for i, (uid, fcnt, used) in enumerate(rows[:30], 1):
        info = db_users.get(uid)
        name = f"{info[1]} {info[2]}".strip() if info else "Noma'lum"
        ustr = f"@{info[3]}" if (info and info[3]) else "—"
        pct  = used / MAX_STORAGE * 100 if MAX_STORAGE else 0
        bar  = "█" * min(int(pct / 5), 20)
        lines.append(
            f"`{i}.` {name} ({ustr})\n"
            f"   🆔 `{uid}` | {fcnt} fayl | {fmt_size(used)} ({pct:.1f}%) {bar}"
        )
    if len(rows) > 30:
        lines.append(f"\n… va yana *{len(rows)-30}* ta")

    text = "\n".join(lines)
    for chunk in [text[i:i+4000] for i in range(0, len(text), 4000)]:
        await call.message.reply(chunk, parse_mode=enums.ParseMode.MARKDOWN)
    await call.answer()


@app.on_callback_query(admin_filter & filters.create(lambda _, __, q: q.data == "adm_broadcast"))
async def adm_broadcast(client, call):
    broadcast_mode.add(ADMIN_ID)
    await call.message.reply(
        "📨 Xabarni yozing:\n_(Bloklanganlarga yuborilmaydi. Bekor: /admin)_",
        parse_mode=enums.ParseMode.MARKDOWN,
    )
    await call.answer()


@app.on_callback_query(admin_filter & filters.create(lambda _, __, q: q.data == "adm_search"))
async def adm_search(client, call):
    waiting_for_user_id[ADMIN_ID] = "info"
    await call.message.reply("🔍 Foydalanuvchi ID sini yuboring:")
    await call.answer()


@app.on_callback_query(admin_filter & filters.create(lambda _, __, q: q.data == "adm_ban"))
async def adm_ban(client, call):
    waiting_for_user_id[ADMIN_ID] = "ban"
    await call.message.reply("⛔ Ban qilmoqchi bo'lgan foydalanuvchi *ID* sini yuboring:",
                              parse_mode=enums.ParseMode.MARKDOWN)
    await call.answer()


@app.on_callback_query(admin_filter & filters.create(lambda _, __, q: q.data == "adm_unban"))
async def adm_unban(client, call):
    waiting_for_user_id[ADMIN_ID] = "unban"
    await call.message.reply("✅ Blokdan chiqarmoqchi bo'lgan foydalanuvchi *ID* sini yuboring:",
                              parse_mode=enums.ParseMode.MARKDOWN)
    await call.answer()


@app.on_callback_query(admin_filter & filters.create(lambda _, __, q: q.data == "adm_clear"))
async def adm_clear(client, call):
    waiting_for_user_id[ADMIN_ID] = "clear"
    await call.message.reply("🗑️ Fayllarini tozalamoqchi bo'lgan foydalanuvchi *ID* sini yuboring:",
                              parse_mode=enums.ParseMode.MARKDOWN)
    await call.answer()


@app.on_callback_query(admin_filter & filters.create(lambda _, __, q: q.data == "adm_volume"))
async def adm_volume_check(client, call):
    exists = os.path.exists(VOLUME_PATH)
    lines  = [f"🔁 *Volume tekshiruv*\n",
               f"📁 Path: `{VOLUME_PATH}`",
               f"Mavjud: `{exists}`"]
    if exists:
        files = os.listdir(VOLUME_PATH)
        lines.append(f"Fayllar: `{files}`")
        if "bot.db" in files:
            size = os.path.getsize(DB_PATH)
            lines.append(f"bot.db: `{fmt_size(size)}`")
            lines.append(f"Foydalanuvchilar: `{user_count()}`")
        else:
            lines.append("⚠️ bot.db topilmadi!")
    else:
        lines.append("❌ Volume mount qilinmagan!")
    await call.message.reply("\n".join(lines), parse_mode=enums.ParseMode.MARKDOWN)
    await call.answer()

# ════════════════════════════════════════════════════════════
#  FLASK — keep-alive
# ════════════════════════════════════════════════════════════
def keep_alive():
    flask_app = Flask(__name__)

    @flask_app.route("/")
    def home():
        return (
            f"✅ Bot ishlayapti! | "
            f"👥 {user_count()} foydalanuvchi | "
            f"💾 {fmt_size(total_storage_all())} disk"
        )

    port = int(os.environ.get("PORT", 5000))
    flask_app.run(host="0.0.0.0", port=port)

# ════════════════════════════════════════════════════════════
#  MAIN
# ════════════════════════════════════════════════════════════
if __name__ == "__main__":
    check_volume()
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    init_db()
    os.makedirs(BASE_DIR,    exist_ok=True)
    os.makedirs(STICKER_DIR, exist_ok=True)
    threading.Thread(target=keep_alive, daemon=True).start()
    print("✅ Bot ishga tushdi!")
    app.run()
