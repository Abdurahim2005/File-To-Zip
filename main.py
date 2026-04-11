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

BASE_DIR        = "user_files"
STICKER_DIR     = "stickers"
ADMIN_ID        = 1663567950
MAX_STORAGE     = 400 * 1024 * 1024   # 400 MB
AUTO_ZIP_DELAY  = 60                   # 1 daqiqa — oddiy taymer
OVERFLOW_DELAY  = 40                   # 40 soniya — xotira to'lganda
DEBOUNCE_DELAY  = 1.5                  # 1.5s — batch fayllarni kutish

VOLUME_PATH = os.environ.get("VOLUME_PATH", "/app/data")
DB_PATH     = os.path.join(VOLUME_PATH, "bot.db")

# ════════════════════════════════════════════════════════════
#  IN-MEMORY STATE
# ════════════════════════════════════════════════════════════
broadcast_mode:      set  = set()
waiting_for_user_id: dict = {}   # {admin_id: action}

# Foydalanuvchi holat ob'ektlari
user_status_msg:     dict = {}   # {uid: Message}   — bitta status xabar
user_welcome_msg:    dict = {}   # {uid: Message}   — welcome xabari (zip ketgach o'chadi)
user_auto_zip:       dict = {}   # {uid: Task}       — auto-zip taymer
user_debounce:       dict = {}   # {uid: Task}       — batch debounce
user_download_task:  dict = {}   # {uid: Task}       — parallel download (ZIP tugmasi bossaganda)

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


# ── Users ────────────────────────────────────────────────
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
        c.execute("UPDATE users SET is_banned=1 WHERE telegram_id=?", (uid,)); c.commit()

def unban_user(uid: int):
    with sqlite3.connect(DB_PATH) as c:
        c.execute("UPDATE users SET is_banned=0 WHERE telegram_id=?", (uid,)); c.commit()

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


# ── File records ─────────────────────────────────────────
def add_file_record(uid: int, file_id: str, file_type: str,
                    filename: str, file_size: int):
    with sqlite3.connect(DB_PATH) as c:
        c.execute(
            "INSERT INTO user_files"
            "(telegram_id,file_id,file_type,filename,file_size,added_at)"
            " VALUES(?,?,?,?,?,?)",
            (uid, file_id, file_type, filename, file_size,
             datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        )
        c.commit()

def get_user_files(uid: int) -> list:
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
    with sqlite3.connect(DB_PATH) as c:
        r = c.execute(
            "SELECT COALESCE(SUM(file_size),0) FROM user_files WHERE telegram_id=?", (uid,)
        ).fetchone()
    return r[0] if r else 0

def all_users_pending() -> list:
    """[(uid, file_count, total_size), ...]"""
    with sqlite3.connect(DB_PATH) as c:
        return c.execute(
            "SELECT telegram_id, COUNT(*), COALESCE(SUM(file_size),0) "
            "FROM user_files GROUP BY telegram_id ORDER BY 3 DESC"
        ).fetchall()

def total_storage_all() -> int:
    with sqlite3.connect(DB_PATH) as c:
        r = c.execute(
            "SELECT COALESCE(SUM(file_size),0) FROM user_files"
        ).fetchone()
    return r[0] if r else 0

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
            "💾 Har bir foydalanuvchi uchun: max *400 MB*"
        ),
        "files_saved": (
            "✅ *{count} ta fayl* qabul qilindi!\n\n"
            "👇 Hammasi tayyor bo'lsa ZIP yasash tugmasini bosing:"
        ),
        "storage_full": (
            "⚠️ *Xotira to'lib qoldi!*\n\n"
            "📄 Oxirgi qabul qilingan fayl: `{last_file}`\n"
            "💾 Band qilingan joy: *{used}* / *{max}*\n\n"
            "✏️ Hozirgi fayllar uchun *ZIP nomini yozing:*\n"
            "_(40 soniyada avtomatik ZIP yaratiladi)_"
        ),
        "ready_btn":    "📦 ZIP yasash",
        "ask_zip_name": (
            "✏️ *ZIP fayl nomini yozing:*\n\n"
            "• Harf, raqam, ` - ` va ` _ ` ishlating\n"
            "• Bo'sh joy ham bo'lsa — `_` ga aylantiriladi\n\n"
            "📌 Misol: `mening_fayllar` yoki `mening fayllar`"
        ),
        "zip_caption":   "📦 *ZIP tayyor!*\n\n🤖 @Zipla_bot — Hayotni Ziplab o't!",
        "no_files":      "⚠️ Avval fayl yuboring.",
        "zip_error":     "❌ ZIP yaratishda xato. Qaytadan urining.",
        "bad_name":      "❌ *Noto'g'ri nom!* Harf, raqam, bo'sh joy, `-` va `_` ishlating.",
        "lang_set":      "✅ Til saqlandi!",
        "change_lang":   "🌍 Tilni o'zgartirish",
        "creating_zip":  "⚙️ *ZIP yaratilmoqda...* iltimos kuting",
        "banned":        "🚫 Bloklangansiz.",
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
            "💾 Storage limit per user: *400 MB*"
        ),
        "files_saved": (
            "✅ *{count} file(s)* received!\n\n"
            "👇 Press Create ZIP when ready:"
        ),
        "storage_full": (
            "⚠️ *Storage full!*\n\n"
            "📄 Last received file: `{last_file}`\n"
            "💾 Used: *{used}* of *{max}*\n\n"
            "✏️ Enter a *ZIP name* for current files:\n"
            "_(Auto-ZIP in 40 seconds)_"
        ),
        "ready_btn":    "📦 Create ZIP",
        "ask_zip_name": (
            "✏️ *Enter ZIP file name:*\n\n"
            "• Use letters, numbers, ` - ` and ` _ `\n"
            "• Spaces allowed — auto-converted to `_`\n\n"
            "📌 Example: `my_files` or `my files`"
        ),
        "zip_caption":   "📦 *ZIP is ready!*\n\n🤖 @Zipla_bot — Zip your life!",
        "no_files":      "⚠️ Please send files first.",
        "zip_error":     "❌ ZIP creation failed. Please try again.",
        "bad_name":      "❌ *Invalid name!* Use letters, numbers, spaces, `-` and `_`.",
        "lang_set":      "✅ Language saved!",
        "change_lang":   "🌍 Change language",
        "creating_zip":  "⚙️ *Creating ZIP...* please wait",
        "banned":        "🚫 You are blocked.",
        "auto_zip_done": "🤖 *Auto ZIP:* files archived after 1 minute of inactivity.",
    },
}

def tx(uid: int, key: str, **kw) -> str:
    lang = get_lang(uid) or "uz"
    text = TEXTS.get(lang, TEXTS["uz"]).get(key, key)
    return text.format(**kw) if kw else text

# ════════════════════════════════════════════════════════════
#  UTILITIES
# ════════════════════════════════════════════════════════════
def user_dir(uid: int) -> str:
    p = os.path.join(BASE_DIR, str(uid))
    os.makedirs(p, exist_ok=True)
    return p

def fmt_size(b: int) -> str:
    if b < 1024 ** 2:
        return f"{b/1024:.1f} KB"
    return f"{b/1024**2:.1f} MB"

async def safe_delete(msg):
    """Xabolarni xatosiz o'chirish"""
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
            f"📍 Joy: `{context}`\n"
            f"👤 ID: `{uid}`\n"
            f"❗ `{type(err).__name__}: {err}`\n"
            f"🕐 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            parse_mode=enums.ParseMode.MARKDOWN,
        )
    except Exception as e:
        print(f"[error_to_admin] {e}")

async def cleanup_user(uid: int):
    """Foydalanuvchi papkasini va DB yozuvlarini tozalash"""
    udir = user_dir(uid)
    try:
        shutil.rmtree(udir)
        os.makedirs(udir, exist_ok=True)
    except Exception as e:
        print(f"[cleanup error] {e}")
    clear_user_files(uid)
    set_waiting(uid, False)

# ════════════════════════════════════════════════════════════
#  TASK HELPERS — bekor qilish
# ════════════════════════════════════════════════════════════
async def cancel_task(task_dict: dict, uid: int):
    task = task_dict.get(uid)
    if task and not task.done():
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
    task_dict.pop(uid, None)

def schedule_task(task_dict: dict, uid: int, coro):
    loop = asyncio.get_event_loop()
    old  = task_dict.get(uid)
    if old and not old.done():
        old.cancel()
    task_dict[uid] = loop.create_task(coro)

# ════════════════════════════════════════════════════════════
#  PARALLEL DOWNLOAD (ZIP tugmasi bosilganda boshladi)
# ════════════════════════════════════════════════════════════
async def _download_one(client, file_id: str, save_path: str) -> tuple:
    """Bitta faylni yuklab olish — (file_id, save_path, ok)"""
    try:
        await client.download_media(file_id, file_name=save_path)
        return (file_id, save_path, True)
    except Exception as e:
        return (file_id, save_path, False)


async def predownload_files(client, uid: int) -> dict:
    """
    Barcha fayllarni PARALLEL yuklab olish.
    Qaytaradi: {file_id: (local_path, arcname)}
    """
    file_records = get_user_files(uid)
    udir         = user_dir(uid)
    seen_names   : set  = set()
    tasks        : list = []
    file_id_map  : dict = {}   # save_path → (file_id, arcname)

    for _, file_id, _, filename, _ in file_records:
        base, ext = os.path.splitext(filename)
        arcname   = filename
        counter   = 1
        while arcname in seen_names:
            arcname = f"{base}_{counter}{ext}"
            counter += 1
        seen_names.add(arcname)
        save_path = os.path.join(udir, arcname)
        file_id_map[save_path] = (file_id, arcname)
        tasks.append(_download_one(client, file_id, save_path))

    # Barchasi bir vaqtda parallel
    results = await asyncio.gather(*tasks, return_exceptions=True)

    output: dict = {}
    for res in results:
        if isinstance(res, tuple) and res[2]:   # ok=True
            fid, spath, _ = res
            _, arcname    = file_id_map[spath]
            output[fid]   = (spath, arcname)

    return output

# ════════════════════════════════════════════════════════════
#  AUTO-ZIP TIMERS
# ════════════════════════════════════════════════════════════
async def auto_zip_runner(client, chat_id: int, uid: int, delay: int, auto_name: str):
    await asyncio.sleep(delay)
    if user_file_count(uid) == 0 or is_waiting(uid):
        return
    await create_and_send_zip(client, chat_id, uid, auto_name, auto=True)

def start_auto_zip(client, chat_id: int, uid: int,
                   delay: int = AUTO_ZIP_DELAY):
    auto_name = f"auto_{datetime.now():%Y%m%d_%H%M%S}"
    schedule_task(
        user_auto_zip, uid,
        auto_zip_runner(client, chat_id, uid, delay, auto_name)
    )

# ════════════════════════════════════════════════════════════
#  DEBOUNCE — batch fayllarni kutish
# ════════════════════════════════════════════════════════════
async def debounce_runner(client, chat_id: int, uid: int):
    """
    DEBOUNCE_DELAY sekund yangi fayl kelmasa —
    bitta "X ta fayl qabul qilindi" xabari yuborish/yangilash
    """
    await asyncio.sleep(DEBOUNCE_DELAY)
    cnt = user_file_count(uid)
    if cnt == 0:
        return

    sm = user_status_msg.get(uid)
    markup = InlineKeyboardMarkup([[
        InlineKeyboardButton(tx(uid, "ready_btn"), callback_data="zip_now")
    ]])
    text = tx(uid, "files_saved", count=cnt)

    if sm is None:
        try:
            sm = await client.send_message(
                chat_id, text,
                parse_mode=enums.ParseMode.MARKDOWN,
                reply_markup=markup,
            )
            user_status_msg[uid] = sm
        except Exception:
            pass
    else:
        try:
            await sm.edit_text(text,
                               parse_mode=enums.ParseMode.MARKDOWN,
                               reply_markup=markup)
        except Exception:
            pass

def restart_debounce(client, chat_id: int, uid: int):
    schedule_task(
        user_debounce, uid,
        debounce_runner(client, chat_id, uid)
    )

# ════════════════════════════════════════════════════════════
#  ZIP YARATISH
# ════════════════════════════════════════════════════════════
async def create_and_send_zip(client, chat_id: int, uid: int,
                               zip_name_raw: str, auto: bool = False):
    file_records = get_user_files(uid)
    if not file_records:
        return

    udir     = user_dir(uid)
    zip_name = f"{zip_name_raw}.zip"
    zip_path = os.path.join(udir, zip_name)

    progress = await client.send_message(
        chat_id, tx(uid, "creating_zip"),
        parse_mode=enums.ParseMode.MARKDOWN,
    )
    try:
        # ① Preload task ni kutish yoki parallel yuklab olish
        preloaded: dict = {}
        dl_task = user_download_task.get(uid)
        if dl_task is not None and not dl_task.done():
            # ZIP tugmasi bosib boshlangan parallel yuklov hali tugamagan — kutamiz
            try:
                preloaded = await asyncio.wait_for(
                    asyncio.shield(dl_task), timeout=120
                )
            except Exception:
                preloaded = {}
        elif dl_task is not None and dl_task.done():
            try:
                preloaded = dl_task.result() or {}
            except Exception:
                preloaded = {}

        # Preload yo'q (auto-zip yoki xato) — parallel yuklaymiz
        if not preloaded:
            preloaded = await predownload_files(client, uid)

        if not preloaded:
            raise RuntimeError("Hech bir fayl yuklab olinmadi")

        # ② ZIP yaratish (preloaded fayllardan)
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for fid, (fpath, arcname) in preloaded.items():
                if os.path.isfile(fpath):
                    zf.write(fpath, arcname=arcname)

        # ③ ZIP yuborish
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
        await safe_delete(progress)
        # Status xabarni o'chirish
        sm = user_status_msg.pop(uid, None)
        await safe_delete(sm)
        # Welcome xabarni o'chirish (chat toza qolsin)
        wm = user_welcome_msg.pop(uid, None)
        await safe_delete(wm)

    # ④ Tozalash
    await cleanup_user(uid)
    user_auto_zip.pop(uid, None)
    user_download_task.pop(uid, None)

# ════════════════════════════════════════════════════════════
#  FAYL QABUL QILISH
# ════════════════════════════════════════════════════════════
async def receive_file(client, message: Message, obj, filename: str):
    uid = message.from_user.id

    # Bloklangan — xabalni o'chir, hech nima yuborma
    if is_banned(uid):
        await safe_delete(message)
        return

    fsize       = getattr(obj, "file_size", 0) or 0
    pending_now = user_pending_size(uid)

    # Xotira to'lib qoldi
    if pending_now + fsize > MAX_STORAGE:
        await safe_delete(message)
        # Oxirgi qabul qilingan fayl nomini topish
        files = get_user_files(uid)
        last_fn = files[-1][3] if files else "—"

        # Status xabarni o'chirish, o'rniga storage_full xabari
        sm = user_status_msg.pop(uid, None)
        await safe_delete(sm)

        sfm = await client.send_message(
            message.chat.id,
            tx(uid, "storage_full",
               last_file=last_fn,
               used=fmt_size(pending_now),
               max=fmt_size(MAX_STORAGE)),
            parse_mode=enums.ParseMode.MARKDOWN,
        )
        user_status_msg[uid] = sfm

        # Waiting holatiga o'tkazish va 40s overflow timer
        set_waiting(uid, True)
        await cancel_task(user_auto_zip, uid)
        start_auto_zip(client, message.chat.id, uid, delay=OVERFLOW_DELAY)
        return

    # file_id aniqlash
    file_id = getattr(obj, "file_id", None)
    if not file_id and message.photo:
        file_id = message.photo.file_id
    if not file_id:
        await safe_delete(message)
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
    await safe_delete(message)

    # Debounce — batch fayllar uchun
    restart_debounce(client, message.chat.id, uid)

    # Auto-zip taymerni qayta boshlash (60s)
    await cancel_task(user_auto_zip, uid)
    start_auto_zip(client, message.chat.id, uid, delay=AUTO_ZIP_DELAY)

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
    await safe_delete(message)  # /start xabarini o'chir

    if is_banned(uid):
        return   # bloklangan — hech nima yuborma

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
    # Til tanlash xabarini ham keyinchalik o'chirish uchun saqla
    user_welcome_msg[uid] = sent

# ════════════════════════════════════════════════════════════
#  TIL TANLASH
# ════════════════════════════════════════════════════════════
@app.on_callback_query(filters.create(lambda _, __, q: q.data.startswith("setlang_")))
async def cb_set_lang(client, call):
    uid  = call.from_user.id
    lang = call.data.split("_")[1]
    upsert_user(call.from_user, lang)

    # Til tanlash xabarini o'chirish
    await safe_delete(call.message)
    user_welcome_msg.pop(uid, None)

    name  = call.from_user.first_name or "Foydalanuvchi"
    texts = TEXTS[lang]
    sent  = await client.send_message(
        call.message.chat.id,
        texts["welcome"].format(name=name),
        parse_mode=enums.ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton(texts["change_lang"], callback_data="change_lang")
        ]])
    )
    # Welcome xabarini saqla — ZIP ketgach o'chiriladi
    user_welcome_msg[uid] = sent
    await send_sticker(client, call.message.chat.id, "start")
    await call.answer(texts["lang_set"])


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
#  FAYL HANDLERLARI
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
    if user_file_count(uid) == 0:
        await call.answer(tx(uid, "no_files"), show_alert=True)
        return

    # Auto-zip taymerni to'xtatish
    await cancel_task(user_auto_zip, uid)
    await cancel_task(user_debounce, uid)

    # ★ Parallel download — foydalanuvchi nom yozayotganda yuklab turamiz
    loop = asyncio.get_event_loop()
    user_download_task[uid] = loop.create_task(predownload_files(client, uid))

    set_waiting(uid, True)

    # Status xabarni o'chirish, nom so'rash xabari yuborish
    sm = user_status_msg.pop(uid, None)
    await safe_delete(sm)

    sent = await call.message.reply(
        tx(uid, "ask_zip_name"),
        parse_mode=enums.ParseMode.MARKDOWN,
    )
    # Bu xabarni ham keyinchalik o'chirish uchun status_msg sifatida saqlaymiz
    user_status_msg[uid] = sent
    await call.answer()

# ════════════════════════════════════════════════════════════
#  MATN HANDLERI
# ════════════════════════════════════════════════════════════
ZIP_NAME_RE = re.compile(r'^[\w\- ]{1,64}$')


@app.on_message(filters.text & ~filters.command(["start", "admin"]))
async def on_text(client, message):
    uid = message.from_user.id

    # Bloklangan — o'chir
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
            await message.reply("❌ Noto'g'ri ID."); return

        data = get_user_by_id(target_id)

        if action == "ban":
            if not data:
                await message.reply(f"❌ `{target_id}` topilmadi.",
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
                await message.reply(f"❌ `{target_id}` topilmadi.",
                                    parse_mode=enums.ParseMode.MARKDOWN); return
            unban_user(target_id)
            await message.reply(
                f"✅ *Blokdan chiqarildi:* {data[1]} {data[2]} (`{target_id}`)",
                parse_mode=enums.ParseMode.MARKDOWN,
            )

        elif action == "info":
            if not data:
                await message.reply(f"❌ `{target_id}` topilmadi.",
                                    parse_mode=enums.ParseMode.MARKDOWN); return
            tid, fn, ln, un, lg, jd, bnnd = data
            fcnt       = user_file_count(tid)
            used       = user_pending_size(tid)
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
                                    parse_mode=enums.ParseMode.MARKDOWN); return
            await cleanup_user(target_id)
            await message.reply(
                f"🗑️ `{target_id}` — tozalandi.",
                parse_mode=enums.ParseMode.MARKDOWN,
            )
        return

    # ── Oddiy foydalanuvchi: ZIP nomi ────────────────────
    if not is_waiting(uid):
        # Kutilmagan matn — o'chir, jim
        await safe_delete(message)
        return

    zip_name_raw = message.text.strip()

    # Noto'g'ri nom — xabarni o'chir, qisqa alert
    if not ZIP_NAME_RE.match(zip_name_raw):
        await safe_delete(message)
        # Oldingi "nom so'rash" xabarini yangilash
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

    # To'g'ri nom
    zip_name_clean = re.sub(r'\s+', '_', zip_name_raw)
    await safe_delete(message)

    set_waiting(uid, False)
    await cancel_task(user_auto_zip, uid)

    # "Nom so'rash" xabarini o'chirish
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
    disk  = fmt_size(total_storage_all())
    await send_sticker(client, message.chat.id, "admin")
    await message.reply(
        f"🔐 *Admin Panel*\n\n"
        f"👥 Jami: *{cnt}* | 📅 Bugun: *{today}*\n"
        f"💾 Pending disk: *{disk}*\n"
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
        await call.answer(); return

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
    disk      = fmt_size(total_storage_all())

    week = []
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
    rows = all_users_pending()   # [(uid, file_count, total_size), ...]
    if not rows:
        await call.message.reply("💾 Hozircha hech kimning pending fayli yo'q.")
        await call.answer(); return

    # {tid: (fn, ln, un)} mapping — indekslar to'g'ri
    db_map    = {u[0]: (u[1], u[2], u[3]) for u in all_users()}
    total_sz  = sum(r[2] for r in rows)
    total_cnt = sum(r[1] for r in rows)
    lines     = [
        f"💾 *Disk statistikasi*\n"
        f"Jami: *{total_cnt} ta fayl* | *{fmt_size(total_sz)}*\n"
    ]
    for i, (uid, fcnt, used) in enumerate(rows[:30], 1):
        info  = db_map.get(uid)
        # info = (fn, ln, un)  — indeks 0=fn, 1=ln, 2=un
        fn    = info[0] if info else ""
        ln    = info[1] if info else ""
        un    = info[2] if info else ""
        name  = f"{fn} {ln}".strip() or "Noma'lum"
        ustr  = f"@{un}" if un else "—"
        pct   = used / MAX_STORAGE * 100 if MAX_STORAGE else 0
        bar   = "█" * min(int(pct / 5), 20)
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
    lines  = [f"🔁 *Volume*\nPath: `{VOLUME_PATH}` | Mavjud: `{exists}`"]
    if exists:
        files = os.listdir(VOLUME_PATH)
        lines.append(f"Fayllar: `{files}`")
        if "bot.db" in files:
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
            f"Disk: {fmt_size(total_storage_all())}"
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
