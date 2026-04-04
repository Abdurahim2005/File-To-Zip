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
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton

# ============================================================
#  CONFIG
# ============================================================
API_ID    = int(os.environ.get("API_ID",    29517932))
API_HASH  = os.environ.get("API_HASH",  "572b177f48692c0cbd88664120fb87f4")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "7579799414:AAFubjp6EdJySpv8tQHxvkpgO1i3fM45kKg")

BASE_DIR       = "user_files"
STICKER_DIR    = "stickers"
ADMIN_ID       = 1663567950
MAX_STORAGE    = 500 * 1024 * 1024   # 500 MB per user
AUTO_ZIP_DELAY = 180                  # 3 daqiqa (sekund)

VOLUME_PATH = os.environ.get("VOLUME_PATH", "/app/data")
DB_PATH     = os.path.join(VOLUME_PATH, "bot.db")

# ============================================================
#  IN-MEMORY STATE
# ============================================================
broadcast_mode:      set  = set()
waiting_for_user_id: dict = {}    # {admin_id: action}
user_status_msg:     dict = {}    # {uid: Message}  — bitta umumiy status xabar
user_auto_zip:       dict = {}    # {uid: asyncio.Task}

# ============================================================
#  VOLUME CHECK
# ============================================================
def check_volume():
    print(f"[VOLUME] DB path: {DB_PATH}")
    print(f"[VOLUME] Path exists: {os.path.exists(VOLUME_PATH)}")
    if os.path.exists(VOLUME_PATH):
        files = os.listdir(VOLUME_PATH)
        print(f"[VOLUME] Files in volume: {files}")
        if "bot.db" in files:
            size = os.path.getsize(DB_PATH)
            print(f"[VOLUME] bot.db topildi! Hajmi: {size} bytes")
        else:
            print("[VOLUME] bot.db yoq — yangi DB yaratiladi")
    else:
        print(f"[VOLUME] Volume path mavjud emas: {VOLUME_PATH}")

# ============================================================
#  DATABASE
# ============================================================
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
        for col, definition in [
            ("waiting_zip", "INTEGER DEFAULT 0"),
            ("is_banned",   "INTEGER DEFAULT 0"),
        ]:
            try:
                conn.execute(f"ALTER TABLE users ADD COLUMN {col} {definition}")
            except Exception:
                pass
        conn.commit()
    print(f"[DB] Database tayyor: {DB_PATH}")


def set_waiting(user_id: int, val: bool):
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            "UPDATE users SET waiting_zip=? WHERE telegram_id=?",
            (1 if val else 0, user_id)
        )
        conn.commit()


def is_waiting(user_id: int) -> bool:
    with sqlite3.connect(DB_PATH) as conn:
        row = conn.execute(
            "SELECT waiting_zip FROM users WHERE telegram_id=?", (user_id,)
        ).fetchone()
    return bool(row[0]) if row else False


def upsert_user(user, lang=None):
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            INSERT INTO users (telegram_id, first_name, last_name, username, language, joined_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(telegram_id) DO UPDATE SET
                first_name = excluded.first_name,
                last_name  = excluded.last_name,
                username   = excluded.username,
                language   = COALESCE(?, language)
        """, (
            user.id,
            user.first_name or "",
            user.last_name  or "",
            user.username   or "",
            lang or "uz",
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            lang,
        ))
        conn.commit()


def get_lang(user_id: int):
    with sqlite3.connect(DB_PATH) as conn:
        row = conn.execute(
            "SELECT language FROM users WHERE telegram_id=?", (user_id,)
        ).fetchone()
    return row[0] if row else None


def is_banned(user_id: int) -> bool:
    with sqlite3.connect(DB_PATH) as conn:
        row = conn.execute(
            "SELECT is_banned FROM users WHERE telegram_id=?", (user_id,)
        ).fetchone()
    return bool(row[0]) if row else False


def ban_user(user_id: int):
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("UPDATE users SET is_banned=1 WHERE telegram_id=?", (user_id,))
        conn.commit()


def unban_user(user_id: int):
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("UPDATE users SET is_banned=0 WHERE telegram_id=?", (user_id,))
        conn.commit()


def all_users() -> list:
    with sqlite3.connect(DB_PATH) as conn:
        return conn.execute(
            "SELECT telegram_id, first_name, last_name, username, language, joined_at, is_banned "
            "FROM users ORDER BY id DESC"
        ).fetchall()


def user_count() -> int:
    with sqlite3.connect(DB_PATH) as conn:
        return conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]


def today_count() -> int:
    today = datetime.now().strftime("%Y-%m-%d")
    with sqlite3.connect(DB_PATH) as conn:
        return conn.execute(
            "SELECT COUNT(*) FROM users WHERE joined_at LIKE ?", (f"{today}%",)
        ).fetchone()[0]


def get_user_by_id(telegram_id: int):
    with sqlite3.connect(DB_PATH) as conn:
        return conn.execute(
            "SELECT telegram_id, first_name, last_name, username, language, joined_at, is_banned "
            "FROM users WHERE telegram_id=?", (telegram_id,)
        ).fetchone()

# ============================================================
#  TEXTS  (i18n)
# ============================================================
TEXTS = {
    "uz": {
        "choose_lang": (
            "👋 Salom!\n\n"
            "Botdan foydalanish uchun avval tilni tanlang:"
        ),
        "welcome": (
            "✅ Til saqlandi!\n\n"
            "👋 Salom, {name}!\n\n"
            "Men fayllaringizni ZIP arxivga yig'ib beraman.\n\n"
            "📎 *Qanday foydalanish:*\n"
            "1️⃣ Menga istalgan fayl yuboring\n"
            "2️⃣ Barcha fayllar yuklanib bo'lgach «📦 ZIP yasash» tugmasini bosing\n"
            "3️⃣ ZIP faylingizga nom bering va tayyor!\n\n"
            "⚠️ *Diqqat:* 3 daqiqa ichida tugma bosilmasa, ZIP avtomatik yaratiladi.\n\n"
            "💾 Har bir foydalanuvchi uchun: max *500 MB* joy."
        ),
        "receiving":   "⏳ Qabul qilinmoqda... ({count} ta fayl yuklanmoqda)",
        "files_saved": (
            "✅ *{count} ta fayl* muvaffaqiyatli saqlandi!\n"
            "💾 Umumiy hajmi: {size}\n\n"
            "📦 ZIP yaratishga tayyor bo'lsangiz tugmani bosing.\n"
            "⏱️ Aks holda 3 daqiqadan keyin avtomatik ZIP yaratiladi."
        ),
        "storage_full": (
            "❌ *Xotira to'lib qoldi!*\n\n"
            "💾 Ishlatilgan: {used} / {max}\n\n"
            "Avval «📦 ZIP yasash» tugmasini bosib fayllarni oling,\n"
            "so'ng yangi fayl yuboring."
        ),
        "ready_btn":    "📦 ZIP yasash",
        "ask_zip_name": (
            "✏️ *ZIP fayl nomini yozing:*\n\n"
            "• Harf, raqam, tire ( - ) va pastki chiziq ( _ ) ishlating\n"
            "• Bo'sh joy ham bo'lsa — avtomatik _ ga aylantiriladi\n\n"
            "Misol: `mening_fayllar` yoki `mening fayllar`"
        ),
        "zip_caption":   "📦 ZIP tayyor!\n\n😄 @Zipla_bot — Hayotni Ziplab ot!",
        "no_files":      "⚠️ Hech qanday fayl topilmadi. Avval fayl yuboring.",
        "zip_error":     "❌ ZIP yaratishda xato yuz berdi. Qaytadan urining.",
        "bad_name":      "❌ Noto'g'ri nom!\n\nFaqat harf, raqam, bo'sh joy, - va _ ishlating.\n\nMisol: `mening fayllar`",
        "lang_set":      "Til saqlandi!",
        "change_lang":   "🌐 Tilni o'zgartirish",
        "download_err":  "❌ Yuklab olishda xato. Faylni qaytadan yuboring.",
        "creating_zip":  "⏳ ZIP yaratilmoqda, iltimos kuting...",
        "banned":        "Siz bloklangansiz.",
        "auto_zip_warn": (
            "⏰ *3 daqiqa o'tdi!*\n\n"
            "Fayllaringizdan avtomatik ZIP yaratilmoqda..."
        ),
        "auto_zip_done": (
            "📦 Avtomatik ZIP yaratildi!\n\n"
            "3 daqiqa ichida tugma bosilmagani uchun\n"
            "fayllaringiz avtomatik arxivlandi."
        ),
    },
    "en": {
        "choose_lang": (
            "👋 Hello!\n\n"
            "Please choose your language to get started:"
        ),
        "welcome": (
            "✅ Language saved!\n\n"
            "👋 Hello, {name}!\n\n"
            "I pack your files into a ZIP archive.\n\n"
            "📎 *How to use:*\n"
            "1️⃣ Send me any files you want to zip\n"
            "2️⃣ Once all files are uploaded, press «📦 Create ZIP»\n"
            "3️⃣ Give your ZIP a name and it's ready!\n\n"
            "⚠️ *Note:* If you don't press the button within 3 minutes, ZIP is created automatically.\n\n"
            "💾 Storage limit per user: *500 MB*."
        ),
        "receiving":   "⏳ Receiving... ({count} file(s) uploading)",
        "files_saved": (
            "✅ *{count} file(s)* saved successfully!\n"
            "💾 Total size: {size}\n\n"
            "📦 Press the button when ready to create ZIP.\n"
            "⏱️ Otherwise, ZIP will be created automatically in 3 minutes."
        ),
        "storage_full": (
            "❌ *Storage limit reached!*\n\n"
            "💾 Used: {used} of {max}\n\n"
            "Press «📦 Create ZIP» to get your files first,\n"
            "then you can send new ones."
        ),
        "ready_btn":    "📦 Create ZIP",
        "ask_zip_name": (
            "✏️ *Enter a name for your ZIP file:*\n\n"
            "• Use letters, numbers, hyphens ( - ) and underscores ( _ )\n"
            "• Spaces are allowed — auto-converted to _\n\n"
            "Example: `my_files` or `my files`"
        ),
        "zip_caption":   "📦 Your ZIP is ready!\n\n😄 @Zipla_bot — Zip your life!",
        "no_files":      "⚠️ No files found. Please send files first.",
        "zip_error":     "❌ Error creating ZIP. Please try again.",
        "bad_name":      "❌ Invalid name!\n\nUse letters, numbers, spaces, - and _ only.\n\nExample: `my files`",
        "lang_set":      "Language saved!",
        "change_lang":   "🌐 Change language",
        "download_err":  "❌ Download failed. Please resend the file.",
        "creating_zip":  "⏳ Creating ZIP, please wait...",
        "banned":        "You are banned.",
        "auto_zip_warn": (
            "⏰ *3 minutes passed!*\n\n"
            "Auto-creating ZIP from your files..."
        ),
        "auto_zip_done": (
            "📦 Auto ZIP created!\n\n"
            "Since the button was not pressed within 3 minutes,\n"
            "your files were automatically archived."
        ),
    },
}


def tx(user_id: int, key: str, **kw) -> str:
    lang = get_lang(user_id) or "uz"
    text = TEXTS.get(lang, TEXTS["uz"]).get(key, key)
    return text.format(**kw) if kw else text

# ============================================================
#  FILE UTILITIES
# ============================================================
def user_dir(user_id: int) -> str:
    path = os.path.join(BASE_DIR, str(user_id))
    os.makedirs(path, exist_ok=True)
    return path


def storage_used(user_id: int) -> int:
    d = user_dir(user_id)
    return sum(
        os.path.getsize(os.path.join(d, f))
        for f in os.listdir(d)
        if os.path.isfile(os.path.join(d, f))
    )


def file_count(user_id: int) -> int:
    d = user_dir(user_id)
    return len([f for f in os.listdir(d) if os.path.isfile(os.path.join(d, f))])


def total_storage_all_users() -> int:
    total = 0
    if not os.path.exists(BASE_DIR):
        return 0
    for uid_folder in os.listdir(BASE_DIR):
        folder_path = os.path.join(BASE_DIR, uid_folder)
        if os.path.isdir(folder_path):
            for f in os.listdir(folder_path):
                fp = os.path.join(folder_path, f)
                if os.path.isfile(fp):
                    total += os.path.getsize(fp)
    return total


def fmt_size(b: int) -> str:
    if b < 1024 ** 2:
        return f"{b / 1024:.1f} KB"
    return f"{b / 1024 ** 2:.1f} MB"


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


async def log_admin(app_client, label: str, uid: int, text: str):
    try:
        await app_client.send_message(
            ADMIN_ID,
            f"[LOG] {label}\nID: {uid}\n{text}"
        )
    except Exception as e:
        print(f"[log_admin error] {e}")

# ============================================================
#  AUTO-ZIP TIMER
# ============================================================
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

    udir  = user_dir(uid)
    files = [f for f in os.listdir(udir) if os.path.isfile(os.path.join(udir, f))]
    if not files:
        return
    if is_waiting(uid):
        return

    try:
        await client.send_message(
            chat_id,
            tx(uid, "auto_zip_warn"),
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
    task = loop.create_task(auto_zip_runner(client, chat_id, uid))
    user_auto_zip[uid] = task

# ============================================================
#  ZIP YARATISH  (markaziy funksiya)
# ============================================================
async def create_and_send_zip(client, chat_id: int, uid: int,
                               zip_name_raw: str, auto: bool = False):
    udir     = user_dir(uid)
    zip_name = f"{zip_name_raw}.zip"
    zip_path = os.path.join(udir, zip_name)

    progress = await client.send_message(chat_id, tx(uid, "creating_zip"))

    try:
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for fname in os.listdir(udir):
                fpath = os.path.join(udir, fname)
                if os.path.isfile(fpath) and fname != zip_name:
                    zf.write(fpath, arcname=fname)

        caption = tx(uid, "zip_caption")
        if auto:
            caption = tx(uid, "auto_zip_done") + "\n\n" + caption

        await client.send_document(
            chat_id,
            zip_path,
            caption=caption,
            file_name=zip_name,
        )
        await log_admin(client, "ZIP yaratildi" + (" (auto)" if auto else ""), uid, zip_name)

    except Exception as e:
        await client.send_message(chat_id, tx(uid, "zip_error"))
        print(f"[zip error] {e}")
        return
    finally:
        try:
            await progress.delete()
        except Exception:
            pass
        # Status xabarni ham o'chirish
        sm = user_status_msg.pop(uid, None)
        if sm:
            try:
                await sm.delete()
            except Exception:
                pass

    # Fayllarni tozalash
    try:
        shutil.rmtree(udir)
        os.makedirs(udir, exist_ok=True)
    except Exception as e:
        print(f"[cleanup error] {e}")

    set_waiting(uid, False)
    user_auto_zip.pop(uid, None)

# ============================================================
#  FAYL QABUL QILISH
# ============================================================
async def receive_file(client, message, obj, filename: str):
    uid = message.from_user.id

    if is_banned(uid):
        await message.reply(tx(uid, "banned"))
        return

    fsize = getattr(obj, "file_size", 0) or 0
    udir  = user_dir(uid)
    used  = storage_used(uid)

    if used + fsize > MAX_STORAGE:
        await message.reply(
            tx(uid, "storage_full",
               used=fmt_size(used),
               max=fmt_size(MAX_STORAGE)),
            parse_mode=enums.ParseMode.MARKDOWN,
        )
        return

    # Bitta umumiy status xabar
    cur_cnt = file_count(uid)
    prev_sm = user_status_msg.get(uid)

    if prev_sm is None:
        try:
            sm = await message.reply(tx(uid, "receiving", count=cur_cnt + 1))
            user_status_msg[uid] = sm
        except Exception:
            pass
    else:
        try:
            await prev_sm.edit_text(tx(uid, "receiving", count=cur_cnt + 1))
        except Exception:
            pass

    # Faylni yuklash
    save_path = unique_path(udir, filename)
    try:
        await message.download(file_name=save_path)
    except Exception as e:
        await message.reply(tx(uid, "download_err"))
        print(f"[download error] {e}")
        return

    new_cnt  = file_count(uid)
    new_used = storage_used(uid)

    # Status xabarni yangilash — "saqlandi" holati + tugma
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

    # Auto-ZIP taymerni qayta boshlash
    start_auto_zip(client, message.chat.id, uid)

    await log_admin(client, "Fayl yuborildi", uid, filename)

# ============================================================
#  BOT
# ============================================================
app = Client("zip_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

# ============================================================
#  /start  — til tanlash tugmalari bilan (1-talab)
# ============================================================
@app.on_message(filters.command("start"))
async def cmd_start(client, message):
    uid = message.from_user.id

    if is_banned(uid):
        await message.reply(TEXTS["uz"]["banned"])
        return

    if get_lang(uid) is None:
        upsert_user(message.from_user, "uz")

    # Har doim til tanlash tugmalari bilan ochiladi
    await message.reply(
        TEXTS["uz"]["choose_lang"],
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("🇺🇿 O'zbek",  callback_data="setlang_uz"),
            InlineKeyboardButton("🇬🇧 English", callback_data="setlang_en"),
        ]])
    )

# ============================================================
#  Til tanlash callbacklari
# ============================================================
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

# ============================================================
#  FAYL HANDLERLARI
# ============================================================
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

# ============================================================
#  ZIP yasash tugmasi
# ============================================================
@app.on_callback_query(filters.create(lambda _, __, q: q.data == "zip_now"))
async def cb_zip_now(client, call):
    uid  = call.from_user.id
    udir = user_dir(uid)

    files = [f for f in os.listdir(udir) if os.path.isfile(os.path.join(udir, f))]
    if not files:
        await call.message.reply(tx(uid, "no_files"))
        await call.answer()
        return

    await cancel_auto_zip(uid)
    set_waiting(uid, True)
    await call.message.reply(
        tx(uid, "ask_zip_name"),
        parse_mode=enums.ParseMode.MARKDOWN,
    )
    await call.answer()

# ============================================================
#  Matn handleri
# ============================================================
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

    # Admin broadcast
    if uid == ADMIN_ID and uid in broadcast_mode:
        broadcast_mode.discard(uid)
        users = all_users()
        ok = fail = 0
        progress_msg = await message.reply("Yuborilmoqda...")
        for row in users:
            if row[6]:
                continue
            try:
                await client.send_message(row[0], f"Xabar: {message.text}")
                ok += 1
            except Exception:
                fail += 1
        try:
            await progress_msg.delete()
        except Exception:
            pass
        await message.reply(
            f"Broadcast tugadi!\nYuborildi: **{ok}**\nYuborilmadi: **{fail}**",
            parse_mode=enums.ParseMode.MARKDOWN,
        )
        return

    # Admin: foydalanuvchi ID kutilmoqda
    if uid == ADMIN_ID and uid in waiting_for_user_id:
        action = waiting_for_user_id.pop(uid)
        raw    = message.text.strip()
        try:
            target_id = int(re.search(r'\d+', raw).group())
        except Exception:
            await message.reply("Noto'g'ri ID. Faqat raqam yuboring.")
            return

        data = get_user_by_id(target_id)

        if action == "ban":
            if not data:
                await message.reply(f"ID `{target_id}` topilmadi.",
                                    parse_mode=enums.ParseMode.MARKDOWN)
                return
            ban_user(target_id)
            await message.reply(
                f"Bloklandi: **{data[1]} {data[2]}** (`{target_id}`)",
                parse_mode=enums.ParseMode.MARKDOWN,
            )
            try:
                await client.send_message(target_id, tx(target_id, "banned"))
            except Exception:
                pass

        elif action == "unban":
            if not data:
                await message.reply(f"ID `{target_id}` topilmadi.",
                                    parse_mode=enums.ParseMode.MARKDOWN)
                return
            unban_user(target_id)
            await message.reply(
                f"Blokdan chiqarildi: **{data[1]} {data[2]}** (`{target_id}`)",
                parse_mode=enums.ParseMode.MARKDOWN,
            )

        elif action == "info":
            if not data:
                await message.reply(f"ID `{target_id}` topilmadi.",
                                    parse_mode=enums.ParseMode.MARKDOWN)
                return
            tid, fn, ln, un, lg, jd, bnnd = data
            used       = storage_used(tid)
            fcnt       = file_count(tid)
            ban_status = "Ha" if bnnd else "Yoq"
            uname      = (f"@{un}") if un else "—"
            await message.reply(
                f"Foydalanuvchi\n\n"
                f"ID: `{tid}`\n"
                f"Ism: {fn} {ln}\n"
                f"Username: {uname}\n"
                f"Til: {lg.upper()}\n"
                f"Qoshilgan: {jd[:16]}\n"
                f"Fayllar: {fcnt} ta\n"
                f"Disk: {fmt_size(used)}\n"
                f"Bloklangan: {ban_status}",
                parse_mode=enums.ParseMode.MARKDOWN,
            )

        elif action == "clear":
            if not data:
                await message.reply(f"ID `{target_id}` topilmadi.",
                                    parse_mode=enums.ParseMode.MARKDOWN)
                return
            udir = os.path.join(BASE_DIR, str(target_id))
            if os.path.exists(udir):
                shutil.rmtree(udir)
                os.makedirs(udir, exist_ok=True)
            await message.reply(
                f"ID `{target_id}` fayllar tozalandi.",
                parse_mode=enums.ParseMode.MARKDOWN,
            )
        return

    # Oddiy foydalanuvchi: ZIP nomi
    if not is_waiting(uid):
        return

    zip_name_raw = message.text.strip()

    if not ZIP_NAME_RE.match(zip_name_raw):
        await message.reply(
            tx(uid, "bad_name"),
            parse_mode=enums.ParseMode.MARKDOWN,
        )
        return

    # Bo'sh joylarni _ ga almashtirish (3-talab)
    zip_name_clean = re.sub(r'\s+', '_', zip_name_raw)

    set_waiting(uid, False)
    await cancel_auto_zip(uid)
    await create_and_send_zip(client, message.chat.id, uid, zip_name_clean)

# ============================================================
#  ADMIN PANEL
# ============================================================
def _is_admin(_, __, q):
    return q.from_user.id == ADMIN_ID

admin_filter = filters.create(_is_admin)


@app.on_message(filters.command("admin") & filters.user(ADMIN_ID))
async def cmd_admin(client, message):
    cnt   = user_count()
    today = today_count()
    disk  = fmt_size(total_storage_all_users())
    await message.reply(
        f"Admin Panel\n\n"
        f"Jami: **{cnt}** | Bugun: **{today}**\n"
        f"Disk: **{disk}** | DB: `{DB_PATH}`",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("Foydalanuvchilar",    callback_data="adm_users"),
             InlineKeyboardButton("Statistika",           callback_data="adm_stats")],
            [InlineKeyboardButton("Broadcast",            callback_data="adm_broadcast"),
             InlineKeyboardButton("Foydalanuvchi izlash", callback_data="adm_search")],
            [InlineKeyboardButton("Ban",                  callback_data="adm_ban"),
             InlineKeyboardButton("Unban",                callback_data="adm_unban")],
            [InlineKeyboardButton("Fayllarni tozalash",   callback_data="adm_clear"),
             InlineKeyboardButton("Volume tekshirish",    callback_data="adm_volume")],
        ]),
        parse_mode=enums.ParseMode.MARKDOWN,
    )


@app.on_callback_query(admin_filter & filters.create(lambda _, __, q: q.data == "adm_users"))
async def adm_users(client, call):
    users = all_users()
    if not users:
        await call.message.reply("Hech qanday foydalanuvchi yoq.")
        await call.answer()
        return

    lines = ["Foydalanuvchilar (oxirgi 30):\n"]
    for i, (tid, fn, ln, un, lg, jd, bnnd) in enumerate(users[:30], 1):
        full  = f"{fn} {ln}".strip() or "—"
        ustr  = f"@{un}" if un else "username yoq"
        bmark = " BANNED" if bnnd else ""
        lines.append(
            f"{i}. {full}{bmark} | {ustr}\n"
            f"   ID: `{tid}` | {lg.upper()} | {jd[:10]}"
        )
    if len(users) > 30:
        lines.append(f"\n... va yana **{len(users) - 30}** ta")

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
    disk      = fmt_size(total_storage_all_users())

    week_lines = []
    for i in range(6, -1, -1):
        d     = (datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d")
        cnt_d = sum(1 for u in users if (u[5] or "").startswith(d))
        bar   = "█" * min(cnt_d, 20)
        week_lines.append(f"`{d[5:]}` {bar} {cnt_d}")

    await call.message.reply(
        f"Statistika\n\n"
        f"Jami: **{total}** | Bugun: **{today_cnt}**\n"
        f"Uzbek: **{uz_cnt}** | English: **{en_cnt}**\n"
        f"Bloklangan: **{ban_cnt}** | Disk: **{disk}**\n\n"
        f"Oxirgi 7 kun:\n" + "\n".join(week_lines),
        parse_mode=enums.ParseMode.MARKDOWN,
    )
    await call.answer()


@app.on_callback_query(admin_filter & filters.create(lambda _, __, q: q.data == "adm_broadcast"))
async def adm_broadcast(client, call):
    broadcast_mode.add(ADMIN_ID)
    await call.message.reply(
        "Barcha foydalanuvchilarga yuboriladigan xabarni yozing:\n"
        "(Bloklanganlarga yuborilmaydi. Bekor qilish uchun /admin)",
    )
    await call.answer()


@app.on_callback_query(admin_filter & filters.create(lambda _, __, q: q.data == "adm_search"))
async def adm_search(client, call):
    waiting_for_user_id[ADMIN_ID] = "info"
    await call.message.reply("Foydalanuvchi ID sini yuboring:")
    await call.answer()


@app.on_callback_query(admin_filter & filters.create(lambda _, __, q: q.data == "adm_ban"))
async def adm_ban(client, call):
    waiting_for_user_id[ADMIN_ID] = "ban"
    await call.message.reply("Ban qilmoqchi bolgan foydalanuvchi ID sini yuboring:")
    await call.answer()


@app.on_callback_query(admin_filter & filters.create(lambda _, __, q: q.data == "adm_unban"))
async def adm_unban(client, call):
    waiting_for_user_id[ADMIN_ID] = "unban"
    await call.message.reply("Blokdan chiqarmoqchi bolgan foydalanuvchi ID sini yuboring:")
    await call.answer()


@app.on_callback_query(admin_filter & filters.create(lambda _, __, q: q.data == "adm_clear"))
async def adm_clear(client, call):
    waiting_for_user_id[ADMIN_ID] = "clear"
    await call.message.reply("Fayllarini tozalamoqchi bolgan foydalanuvchi ID sini yuboring:")
    await call.answer()


@app.on_callback_query(admin_filter & filters.create(lambda _, __, q: q.data == "adm_volume"))
async def adm_volume_check(client, call):
    exists = os.path.exists(VOLUME_PATH)
    lines  = [
        f"Volume tekshiruv\n",
        f"Path: `{VOLUME_PATH}`",
        f"Mavjud: `{exists}`",
    ]
    if exists:
        files = os.listdir(VOLUME_PATH)
        lines.append(f"Fayllar: `{files}`")
        if "bot.db" in files:
            size = os.path.getsize(DB_PATH)
            lines.append(f"bot.db: `{fmt_size(size)}`")
            lines.append(f"Foydalanuvchilar: `{user_count()}`")
        else:
            lines.append("bot.db topilmadi!")
    else:
        lines.append("Volume mount qilinmagan!")
    await call.message.reply("\n".join(lines), parse_mode=enums.ParseMode.MARKDOWN)
    await call.answer()

# ============================================================
#  FLASK — keep-alive
# ============================================================
def keep_alive():
    flask_app = Flask(__name__)

    @flask_app.route("/")
    def home():
        return (
            f"Bot ishlayapti! "
            f"Foydalanuvchilar: {user_count()} | "
            f"Volume: {os.path.exists(VOLUME_PATH)}"
        )

    port = int(os.environ.get("PORT", 5000))
    flask_app.run(host="0.0.0.0", port=port)

# ============================================================
#  MAIN
# ============================================================
if __name__ == "__main__":
    check_volume()
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    init_db()
    os.makedirs(BASE_DIR,    exist_ok=True)
    os.makedirs(STICKER_DIR, exist_ok=True)
    threading.Thread(target=keep_alive, daemon=True).start()
    print("Bot ishga tushdi!")
    app.run()
