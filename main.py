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
BOT_TOKEN = os.environ.get("BOT_TOKEN", "7579799414:AAGDyXOzKEWKtk4D4N6Vsi3X5qngmPr0uiE")

BASE_DIR       = "user_files"
STICKER_DIR    = "stickers"
ADMIN_ID       = 1663567950
MAX_STORAGE    = 300 * 1024 * 1024   # 300 MB
AUTO_ZIP_DELAY = 60                   # 1 daqiqa
DEBOUNCE_SEC   = 1.5                  # batch kutish

VOLUME_PATH = os.environ.get("VOLUME_PATH", "/app/data")
DB_PATH     = os.path.join(VOLUME_PATH, "bot.db")

# ════════════════════════════════════════════════════════════
#  IN-MEMORY STATE
# ════════════════════════════════════════════════════════════
broadcast_mode:      set  = set()
waiting_for_user_id: dict = {}  # {admin_id: action}
user_status_msg:     dict = {}  # {uid: Message}  — "X fayl qabul qilindi" xabari
user_welcome_msg:    dict = {}  # {uid: Message}  — welcome/til tanlash xabari
user_auto_zip:       dict = {}  # {uid: Task}
user_debounce:       dict = {}  # {uid: Task}
# Yuklanayotgan fayllar soni (debounce uchun)
user_downloading:    dict = {}  # {uid: int}  — hozir yuklanayotgan fayllar soni

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
        print(f"[VOLUME] Volume mavjud emas: {VOLUME_PATH}")

# ════════════════════════════════════════════════════════════
#  DATABASE  (faqat users jadvali)
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
        for col, dfn in [
            ("waiting_zip", "INTEGER DEFAULT 0"),
            ("is_banned",   "INTEGER DEFAULT 0"),
        ]:
            try:
                conn.execute(f"ALTER TABLE users ADD COLUMN {col} {dfn}")
            except Exception:
                pass
        conn.commit()
    print(f"[DB] tayyor: {DB_PATH}")


def upsert_user(user, lang=None):
    with sqlite3.connect(DB_PATH) as c:
        c.execute("""
            INSERT INTO users(telegram_id,first_name,last_name,username,language,joined_at)
            VALUES(?,?,?,?,?,?)
            ON CONFLICT(telegram_id) DO UPDATE SET
                first_name=excluded.first_name,
                last_name=excluded.last_name,
                username=excluded.username,
                language=COALESCE(?,language)
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
        c.execute("UPDATE users SET is_banned=1 WHERE telegram_id=?", (uid,))
        c.commit()

def unban_user(uid: int):
    with sqlite3.connect(DB_PATH) as c:
        c.execute("UPDATE users SET is_banned=0 WHERE telegram_id=?", (uid,))
        c.commit()

def set_waiting(uid: int, val: bool):
    with sqlite3.connect(DB_PATH) as c:
        c.execute("UPDATE users SET waiting_zip=? WHERE telegram_id=?", (int(val), uid))
        c.commit()

def is_waiting(uid: int) -> bool:
    with sqlite3.connect(DB_PATH) as c:
        r = c.execute("SELECT waiting_zip FROM users WHERE telegram_id=?", (uid,)).fetchone()
    return bool(r[0]) if r else False

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
        return c.execute(
            "SELECT COUNT(*) FROM users WHERE joined_at LIKE ?", (f"{t}%",)
        ).fetchone()[0]

def get_user_by_id(tid: int):
    with sqlite3.connect(DB_PATH) as c:
        return c.execute(
            "SELECT telegram_id,first_name,last_name,username,language,joined_at,is_banned "
            "FROM users WHERE telegram_id=?", (tid,)
        ).fetchone()

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
            "③ ZIP nomini yozing — tayyor!\n\n"
            "⏱ *Eslatma:* 1 daqiqa ichida tugma bosilmasa,\n"
            "fayllaringiz *avtomatik* arxivlanadi.\n\n"
            "💾 Har bir foydalanuvchi uchun: max *300 MB*"
        ),
        "files_saved": (
            "✅ *{count} ta fayl* qabul qilindi!\n\n"
            "👇 Hammasi tayyor bo'lsa ZIP yasash tugmasini bosing:"
        ),
        "receiving": "📥 *{count} ta fayl qabul qilinmoqda...* kutib turing",
        "storage_full": (
            "⚠️ *Xotira to'lib qoldi!*\n\n"
            "📄 Oxirgi fayl: `{last_file}`\n"
            "💾 Band: *{used}* / *{max}*\n\n"
            "✏️ ZIP nomini yozing — fayllar arxivlanadi:\n"
            "_(40 soniyada avtomatik ZIP yaratiladi)_"
        ),
        "ready_btn":   "📦 ZIP yasash",
        "ask_zip_name": (
            "✏️ *ZIP fayl nomini yozing:*\n\n"
            "• Harf, raqam, ` - ` va ` _ ` ishlating\n"
            "• Bo'sh joy ham bo'lsa — `_` ga aylantiriladi\n\n"
            "📌 Misol: `mening_fayllar` yoki `mening fayllar`"
        ),
        "zip_wait": (
            "⏳ *Fayllar hali yuklanmoqda...*\n\n"
            "Iltimos bir oz kuting, keyin nom yuboring."
        ),
        "zip_caption":  "📦 *ZIP tayyor!*\n\n🤖 @Zipla_bot — Hayotni Ziplab o't!",
        "no_files":     "⚠️ Avval fayl yuboring.",
        "zip_error":    "❌ ZIP yaratishda xato. Qaytadan urining.",
        "bad_name":     "❌ *Noto'g'ri nom!* Harf, raqam, bo'sh joy, `-` va `_` ishlating.",
        "lang_set":     "✅ Til saqlandi!",
        "change_lang":  "🌍 Tilni o'zgartirish",
        "creating_zip": "⚙️ *ZIP yaratilmoqda...* iltimos kuting",
        "banned":       "🚫 Bloklangansiz.",
        "auto_zip_done": "🤖 *Avtomatik ZIP:* 1 daqiqa o'tgani uchun fayllaringiz arxivlandi.",
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
            "③ Give it a name — done!\n\n"
            "⏱ *Note:* Files are *auto-zipped* after 1 minute.\n\n"
            "💾 Storage limit per user: *300 MB*"
        ),
        "files_saved": (
            "✅ *{count} file(s)* received!\n\n"
            "👇 Press Create ZIP when ready:"
        ),
        "receiving": "📥 *Receiving {count} file(s)...* please wait",
        "storage_full": (
            "⚠️ *Storage full!*\n\n"
            "📄 Last file: `{last_file}`\n"
            "💾 Used: *{used}* of *{max}*\n\n"
            "✏️ Enter a ZIP name to archive current files:\n"
            "_(Auto-ZIP in 40 seconds)_"
        ),
        "ready_btn":   "📦 Create ZIP",
        "ask_zip_name": (
            "✏️ *Enter ZIP file name:*\n\n"
            "• Use letters, numbers, ` - ` and ` _ `\n"
            "• Spaces allowed — auto-converted to `_`\n\n"
            "📌 Example: `my_files` or `my files`"
        ),
        "zip_wait": (
            "⏳ *Files are still uploading...*\n\n"
            "Please wait a moment, then send the name."
        ),
        "zip_caption":  "📦 *ZIP is ready!*\n\n🤖 @Zipla_bot — Zip your life!",
        "no_files":     "⚠️ Please send files first.",
        "zip_error":    "❌ ZIP creation failed. Please try again.",
        "bad_name":     "❌ *Invalid name!* Use letters, numbers, spaces, `-` and `_`.",
        "lang_set":     "✅ Language saved!",
        "change_lang":  "🌍 Change language",
        "creating_zip": "⚙️ *Creating ZIP...* please wait",
        "banned":       "🚫 You are blocked.",
        "auto_zip_done": "🤖 *Auto ZIP:* files archived after 1 minute of inactivity.",
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

def disk_used(uid: int) -> int:
    d = user_dir(uid)
    return sum(
        os.path.getsize(os.path.join(d, f))
        for f in os.listdir(d)
        if os.path.isfile(os.path.join(d, f))
    )

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
    """[(uid, used_bytes), ...] — disk ishlatayotgan foydalanuvchilar"""
    result = []
    if not os.path.exists(BASE_DIR):
        return result
    for folder in os.listdir(BASE_DIR):
        try:
            uid  = int(folder)
            used = disk_used(uid)
            if used > 0:
                result.append((uid, used))
        except ValueError:
            pass
    result.sort(key=lambda x: x[1], reverse=True)
    return result

def unique_path(directory: str, filename: str) -> str:
    full = os.path.join(directory, filename)
    if not os.path.exists(full):
        return full
    base, ext = os.path.splitext(filename)
    stamp = datetime.now().strftime("%H%M%S_%f")[:9]
    return os.path.join(directory, f"{base}_{stamp}{ext}")

def fmt_size(b: int) -> str:
    if b < 1024 ** 2:
        return f"{b/1024:.1f} KB"
    return f"{b/1024**2:.1f} MB"

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
            f"🚨 *XATOLIK*\n\n"
            f"📍 `{context}`\n"
            f"👤 ID: `{uid}`\n"
            f"❗ `{type(err).__name__}: {err}`\n"
            f"🕐 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            parse_mode=enums.ParseMode.MARKDOWN,
        )
    except Exception as e:
        print(f"[error_to_admin] {e}")

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
    old  = d.get(uid)
    if old and not old.done():
        old.cancel()
    d[uid] = loop.create_task(coro)

# ════════════════════════════════════════════════════════════
#  STATUS XABAR — debounce orqali yangilanadi
# ════════════════════════════════════════════════════════════
async def _send_status(client, chat_id: int, uid: int):
    """
    DEBOUNCE_SEC o'tgach — fayllar soni bo'yicha status xabar
    yuboradi yoki yangilaydi. Yuklanayotgan fayllar bo'lsa
    "qabul qilinmoqda", bo'lmasa "saqlandi + ZIP tugmasi".
    """
    await asyncio.sleep(DEBOUNCE_SEC)

    cnt        = file_count(uid)
    dl_cnt     = user_downloading.get(uid, 0)
    sm         = user_status_msg.get(uid)
    markup     = InlineKeyboardMarkup([[
        InlineKeyboardButton(tx(uid, "ready_btn"), callback_data="zip_now")
    ]])

    if dl_cnt > 0:
        # Hali yuklanayotganlar bor
        text   = tx(uid, "receiving", count=cnt + dl_cnt)
        markup = None   # Tugma yo'q — yuklanish tugasin
    else:
        # Hammasi yuklanib bo'ldi
        text = tx(uid, "files_saved", count=cnt)

    if sm is None:
        try:
            sent = await client.send_message(
                chat_id, text,
                parse_mode=enums.ParseMode.MARKDOWN,
                reply_markup=markup,
            )
            user_status_msg[uid] = sent
        except Exception:
            pass
    else:
        try:
            await sm.edit_text(
                text,
                parse_mode=enums.ParseMode.MARKDOWN,
                reply_markup=markup,
            )
        except Exception:
            pass

def restart_debounce(client, chat_id: int, uid: int):
    schedule_task(user_debounce, uid, _send_status(client, chat_id, uid))

# ════════════════════════════════════════════════════════════
#  AUTO-ZIP TIMER
# ════════════════════════════════════════════════════════════
async def _auto_zip_runner(client, chat_id: int, uid: int, delay: int):
    await asyncio.sleep(delay)
    if file_count(uid) == 0 or is_waiting(uid):
        return
    auto_name = f"auto_{datetime.now():%Y%m%d_%H%M%S}"
    await create_and_send_zip(client, chat_id, uid, auto_name, auto=True)

def start_auto_zip(client, chat_id: int, uid: int, delay: int = AUTO_ZIP_DELAY):
    schedule_task(
        user_auto_zip, uid,
        _auto_zip_runner(client, chat_id, uid, delay)
    )

# ════════════════════════════════════════════════════════════
#  ZIP YARATISH VA YUBORISH
# ════════════════════════════════════════════════════════════
async def create_and_send_zip(client, chat_id: int, uid: int,
                               zip_name_raw: str, auto: bool = False):
    udir = user_dir(uid)
    files = [f for f in os.listdir(udir) if os.path.isfile(os.path.join(udir, f))]
    if not files:
        return

    zip_name = f"{zip_name_raw}.zip"
    zip_path = os.path.join(udir, zip_name)

    progress = await client.send_message(
        chat_id, tx(uid, "creating_zip"),
        parse_mode=enums.ParseMode.MARKDOWN,
    )
    try:
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for fname in files:
                fpath = os.path.join(udir, fname)
                if os.path.isfile(fpath) and fname != zip_name:
                    zf.write(fpath, arcname=fname)

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
        await client.send_message(
            chat_id, tx(uid, "zip_error"),
            parse_mode=enums.ParseMode.MARKDOWN,
        )
        await error_to_admin(client, "create_and_send_zip", uid, e)
        return
    finally:
        await safe_delete(progress)
        sm = user_status_msg.pop(uid, None)
        await safe_delete(sm)
        wm = user_welcome_msg.pop(uid, None)
        await safe_delete(wm)

    # Tozalash
    try:
        shutil.rmtree(udir)
        os.makedirs(udir, exist_ok=True)
    except Exception as e:
        print(f"[cleanup] {e}")

    set_waiting(uid, False)
    user_auto_zip.pop(uid, None)

# ════════════════════════════════════════════════════════════
#  FAYL QABUL QILISH
# ════════════════════════════════════════════════════════════
async def receive_file(client, message: Message, obj, filename: str):
    uid = message.from_user.id

    if is_banned(uid):
        await safe_delete(message)
        return

    fsize    = getattr(obj, "file_size", 0) or 0
    used_now = disk_used(uid)

    # Xotira to'lib qoldi
    if used_now + fsize > MAX_STORAGE:
        await safe_delete(message)
        udir  = user_dir(uid)
        files = [f for f in os.listdir(udir) if os.path.isfile(os.path.join(udir, f))]
        last_fn = files[-1] if files else "—"

        sm = user_status_msg.pop(uid, None)
        await safe_delete(sm)

        sfm = await client.send_message(
            message.chat.id,
            tx(uid, "storage_full",
               last_file=last_fn,
               used=fmt_size(used_now),
               max=fmt_size(MAX_STORAGE)),
            parse_mode=enums.ParseMode.MARKDOWN,
        )
        user_status_msg[uid] = sfm
        set_waiting(uid, True)
        await cancel_task(user_auto_zip, uid)
        start_auto_zip(client, message.chat.id, uid, delay=40)
        return

    # Foydalanuvchi xabarini darhol o'chirish
    await safe_delete(message)

    # Yuklanayotganlar sonini oshirish
    user_downloading[uid] = user_downloading.get(uid, 0) + 1

    # Debounce — "qabul qilinmoqda" xabari
    restart_debounce(client, message.chat.id, uid)

    # Faylni serverga yuklash
    udir      = user_dir(uid)
    save_path = unique_path(udir, filename)
    try:
        await message.download(file_name=save_path)
    except Exception as e:
        await error_to_admin(client, "receive_file→download", uid, e)
    finally:
        # Yuklandi yoki xato — yuklanayotganlar sonini kamaytir
        user_downloading[uid] = max(0, user_downloading.get(uid, 1) - 1)

    # Yuklanib bo'ldi — statusni yangilash uchun debounce qayta ishga tush
    restart_debounce(client, message.chat.id, uid)

    # Auto-zip taymerni qayta boshlash
    await cancel_task(user_auto_zip, uid)
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
    await safe_delete(message)

    if is_banned(uid):
        return

    if get_lang(uid) is None:
        upsert_user(message.from_user, "uz")

    sent = await client.send_message(
        message.chat.id,
        TEXTS["uz"]["choose_lang"],
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("🇺🇿 O'zbek",  callback_data="setlang_uz"),
            InlineKeyboardButton("🇬🇧 English", callback_data="setlang_en"),
        ]])
    )
    user_welcome_msg[uid] = sent
# ════════════════════════════════════════════════════════════
#  BAZANI QUTQARISH FUNKSIYALARI (ADMIN UCHUN)
# ════════════════════════════════════════════════════════════

@app.on_message(filters.command("getdb") & filters.user(ADMIN_ID))
async def emergency_db_send(client, message):
    """Bazani to'g'ridan-to'g'ri yuborish"""
    await message.reply_text("Baza qidirilmoqda...")
    if os.path.exists(DB_PATH):
        try:
            await message.reply_document(
                document=DB_PATH,
                caption=f"Baza topildi!\nYo'l: {DB_PATH}\nVaqt: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
            )
        except Exception as e:
            await message.reply_text(f"Faylni yuborishda xatolik: {e}")
    else:
        await message.reply_text(f"Afsus, baza topilmadi. Yo'lni tekshiring: {DB_PATH}")

@app.on_message(filters.command("ls") & filters.user(ADMIN_ID))
async def list_volume_files(client, message):
    """Volume ichida nima borligini ko'rish (yo'lni aniqlash uchun)"""
    try:
        if os.path.exists(VOLUME_PATH):
            files = os.listdir(VOLUME_PATH)
            files_str = "\n".join(files) if files else "Papka bo'sh"
            await message.reply_text(f"Volume ichidagi fayllar ({VOLUME_PATH}):\n\n{files_str}")
        else:
            await message.reply_text(f"Volume yo'li topilmadi: {VOLUME_PATH}")
    except Exception as e:
        await message.reply_text(f"Xatolik: {e}")

# ════════════════════════════════════════════════════════════
#  TIL TANLASH
# ════════════════════════════════════════════════════════════
@app.on_callback_query(filters.create(lambda _, __, q: q.data.startswith("setlang_")))
async def cb_set_lang(client, call):
    uid  = call.from_user.id
    lang = call.data.split("_")[1]
    upsert_user(call.from_user, lang)

    await safe_delete(call.message)
    user_welcome_msg.pop(uid, None)

    name  = call.from_user.first_name or "Foydalanuvchi"
    sent  = await client.send_message(
        call.message.chat.id,
        TEXTS[lang]["welcome"].format(name=name),
        parse_mode=enums.ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton(TEXTS[lang]["change_lang"], callback_data="change_lang")
        ]])
    )
    user_welcome_msg[uid] = sent
    await send_sticker(client, call.message.chat.id, "start")
    await call.answer(TEXTS[lang]["lang_set"])


@app.on_callback_query(filters.create(lambda _, __, q: q.data == "change_lang"))
async def cb_change_lang(client, call):
    uid = call.from_user.id
    await safe_delete(call.message)
    sent = await client.send_message(
        call.message.chat.id,
        TEXTS["uz"]["choose_lang"],
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("🇺🇿 O'zbek",  callback_data="setlang_uz"),
            InlineKeyboardButton("🇬🇧 English", callback_data="setlang_en"),
        ]])
    )
    user_welcome_msg[uid] = sent
    await call.answer()

# ════════════════════════════════════════════════════════════
#  FAYL HANDLERLARI — matndan tashqari hamma narsa
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

# ════════════════════════════════════════════════════════════
#  ZIP YASASH TUGMASI
# ════════════════════════════════════════════════════════════
@app.on_callback_query(filters.create(lambda _, __, q: q.data == "zip_now"))
async def cb_zip_now(client, call):
    uid = call.from_user.id

    if file_count(uid) == 0:
        await call.answer(tx(uid, "no_files"), show_alert=True)
        return

    await cancel_task(user_auto_zip, uid)
    await cancel_task(user_debounce, uid)
    set_waiting(uid, True)

    sm = user_status_msg.pop(uid, None)
    await safe_delete(sm)

    sent = await call.message.reply(
        tx(uid, "ask_zip_name"),
        parse_mode=enums.ParseMode.MARKDOWN,
    )
    user_status_msg[uid] = sent
    await call.answer()

# ════════════════════════════════════════════════════════════
#  MATN HANDLERI
# ════════════════════════════════════════════════════════════
ZIP_NAME_RE = re.compile(r'^[\w\- ]{1,64}$')


@app.on_message(filters.text & ~filters.command(["start", "admin"]))
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
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🇺🇿 O'zbek",  callback_data="setlang_uz"),
                InlineKeyboardButton("🇬🇧 English", callback_data="setlang_en"),
            ]])
        )
        user_welcome_msg[uid] = sent
        return

    # ── Admin broadcast ──────────────────────────────────
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

    # ── Admin: foydalanuvchi ID ──────────────────────────
    if uid == ADMIN_ID and uid in waiting_for_user_id:
        action = waiting_for_user_id.pop(uid)
        raw    = message.text.strip()
        try:
            target_id = int(re.search(r'\d+', raw).group())
        except Exception:
            await message.reply("❌ Noto'g'ri ID.")
            return
        data = get_user_by_id(target_id)

        if action == "ban":
            if not data:
                await message.reply(f"❌ `{target_id}` topilmadi.",
                                    parse_mode=enums.ParseMode.MARKDOWN)
                return
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
                await message.reply(f"❌ `{target_id}` topilmadi.",
                                    parse_mode=enums.ParseMode.MARKDOWN)
                return
            unban_user(target_id)
            await message.reply(
                f"✅ *Blokdan chiqarildi:* {data[1]} {data[2]} (`{target_id}`)",
                parse_mode=enums.ParseMode.MARKDOWN,
            )

        elif action == "info":
            if not data:
                await message.reply(f"❌ `{target_id}` topilmadi.",
                                    parse_mode=enums.ParseMode.MARKDOWN)
                return
            tid, fn, ln, un, lg, jd, bnnd = data
            fcnt       = file_count(tid)
            used       = disk_used(tid)
            ban_status = "🚫 Ha" if bnnd else "✅ Yoq"
            uname      = f"@{un}" if un else "—"
            await message.reply(
                f"👤 *Foydalanuvchi*\n\n"
                f"🆔 `{tid}`\n"
                f"📛 {fn} {ln}\n"
                f"🔗 {uname}\n"
                f"🌍 {lg.upper()} | 📅 {jd[:16]}\n"
                f"📁 {fcnt} ta fayl | 💾 {fmt_size(used)}\n"
                f"🚫 Ban: {ban_status}",
                parse_mode=enums.ParseMode.MARKDOWN,
            )

        elif action == "clear":
            if not data:
                await message.reply(f"❌ `{target_id}` topilmadi.",
                                    parse_mode=enums.ParseMode.MARKDOWN)
                return
            ud = os.path.join(BASE_DIR, str(target_id))
            if os.path.exists(ud):
                shutil.rmtree(ud)
                os.makedirs(ud, exist_ok=True)
            await message.reply(
                f"🗑️ `{target_id}` — tozalandi.",
                parse_mode=enums.ParseMode.MARKDOWN,
            )
        return

    # ── Oddiy foydalanuvchi: ZIP nomi ────────────────────
    if not is_waiting(uid):
        await safe_delete(message)
        return

    zip_name_raw = message.text.strip()
    await safe_delete(message)

    # Hali fayllar yuklanayotgan bo'lsa — kutish xabari
    if user_downloading.get(uid, 0) > 0:
        sm = user_status_msg.get(uid)
        if sm:
            try:
                await sm.edit_text(
                    tx(uid, "zip_wait"),
                    parse_mode=enums.ParseMode.MARKDOWN,
                )
            except Exception:
                pass
        # Waiting holatida qolsin, qayta nom yuboring
        return

    # Noto'g'ri nom
    if not ZIP_NAME_RE.match(zip_name_raw):
        sm = user_status_msg.get(uid)
        if sm:
            try:
                await sm.edit_text(
                    tx(uid, "bad_name") + "\n\n" + tx(uid, "ask_zip_name"),
                    parse_mode=enums.ParseMode.MARKDOWN,
                )
            except Exception:
                pass
        return

    # To'g'ri nom — ZIP yasash
    zip_name_clean = re.sub(r'\s+', '_', zip_name_raw)
    set_waiting(uid, False)
    await cancel_task(user_auto_zip, uid)

    sm = user_status_msg.pop(uid, None)
    await safe_delete(sm)

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
    disk  = fmt_size(total_disk_all())
    await send_sticker(client, message.chat.id, "admin")
    await message.reply(
        f"🔐 *Admin Panel*\n\n"
        f"👥 Jami: *{cnt}* | 📅 Bugun: *{today}*\n"
        f"💾 Disk: *{disk}*\n"
        f"🗄️ `{DB_PATH}`",
        parse_mode=enums.ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("👥 Foydalanuvchilar",    callback_data="adm_users"),
             InlineKeyboardButton("📊 Statistika",           callback_data="adm_stats")],
            [InlineKeyboardButton("📨 Broadcast",            callback_data="adm_broadcast"),
             InlineKeyboardButton("🔍 Foydalanuvchi izlash", callback_data="adm_search")],
            [InlineKeyboardButton("⛔ Ban",                  callback_data="adm_ban"),
             InlineKeyboardButton("✅ Unban",                callback_data="adm_unban")],
            [InlineKeyboardButton("🗑️ Fayllarni tozalash",  callback_data="adm_clear"),
             InlineKeyboardButton("💾 Disk statistika",     callback_data="adm_disk")],
            [InlineKeyboardButton("🔁 Volume tekshirish",   callback_data="adm_volume")],
        ]),
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
        full  = f"{fn} {ln}".strip() or "—"
        ustr  = f"@{un}" if un else "—"
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
    disk      = fmt_size(total_disk_all())
    week      = []
    for i in range(6, -1, -1):
        d     = (datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d")
        cnt_d = sum(1 for u in users if (u[5] or "").startswith(d))
        bar   = "█" * min(cnt_d, 15)
        week.append(f"`{d[5:]}` {bar} *{cnt_d}*")
    await call.message.reply(
        f"📊 *Statistika*\n\n"
        f"👥 *{total}* | 📅 Bugun: *{today_cnt}*\n"
        f"🇺🇿 *{uz_cnt}* | 🇬🇧 *{en_cnt}*\n"
        f"🚫 Ban: *{ban_cnt}* | 💾 *{disk}*\n\n"
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
    db_map    = {u[0]: (u[1], u[2], u[3]) for u in all_users()}
    total_sz  = sum(r[1] for r in rows)
    lines     = [f"💾 *Disk statistikasi*\nUmumiy: *{fmt_size(total_sz)}*\n"]
    for i, (uid, used) in enumerate(rows[:30], 1):
        info  = db_map.get(uid)
        name  = f"{info[0]} {info[1]}".strip() if info else "Noma'lum"
        ustr  = f"@{info[2]}" if (info and info[2]) else "—"
        pct   = used / MAX_STORAGE * 100
        bar   = "█" * min(int(pct / 5), 20)
        lines.append(
            f"`{i}.` {name} ({ustr})\n"
            f"   🆔 `{uid}` | {fmt_size(used)} ({pct:.1f}%) {bar}"
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
    lines  = [f"🔁 *Volume*\nPath: `{VOLUME_PATH}` | Mavjud: `{exists}`"]
    if exists:
        vfiles = os.listdir(VOLUME_PATH)
        lines.append(f"Fayllar: `{vfiles}`")
        if "bot.db" in vfiles:
            lines.append(f"bot.db: `{fmt_size(os.path.getsize(DB_PATH))}`")
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
            f"Bot ishlayapti! "
            f"Foydalanuvchilar: {user_count()} | "
            f"Disk: {fmt_size(total_disk_all())}"
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
    print("Bot ishga tushdi!")
    app.run()
