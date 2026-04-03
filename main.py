import os
import re
import shutil
import zipfile
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

BASE_DIR    = "user_files"
STICKER_DIR = "stickers"
ADMIN_ID    = 1663567950
MAX_STORAGE = 500 * 1024 * 1024   # ✅ 500 MB per user (avval 200 edi)

# ============================================================
#  RAILWAY VOLUME FIX
#  Railway da volume mount path ni to'g'ri aniqlash
#  Volume settings da mount path nima qo'ygan bo'lsangiz, shu bo'lishi kerak
#  Odatda: /app/data  yoki  /data
# ============================================================
VOLUME_PATH = os.environ.get("VOLUME_PATH", "/app/data")   # Railway environment variable qo'shing
DB_PATH     = os.path.join(VOLUME_PATH, "bot.db")

def check_volume():
    """Volume to'g'ri mount bo'lganini tekshirish"""
    print(f"[VOLUME] DB path: {DB_PATH}")
    print(f"[VOLUME] Path exists: {os.path.exists(VOLUME_PATH)}")
    if os.path.exists(VOLUME_PATH):
        files = os.listdir(VOLUME_PATH)
        print(f"[VOLUME] Files in volume: {files}")
        if "bot.db" in files:
            size = os.path.getsize(DB_PATH)
            print(f"[VOLUME] ✅ bot.db topildi! Hajmi: {size} bytes")
        else:
            print(f"[VOLUME] ⚠️  bot.db yo'q — yangi DB yaratiladi")
    else:
        print(f"[VOLUME] ❌ Volume path mavjud emas! Railway da volume mount qiling: {VOLUME_PATH}")
        print(f"[VOLUME] Railway Dashboard → Service → Volumes → Mount Path: {VOLUME_PATH}")

# ============================================================
#  IN-MEMORY STATE
# ============================================================
broadcast_mode: set = set()

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
        # Eski DB bo'lsa ustunlarni qo'shib qo'y
        for col, definition in [
            ("waiting_zip", "INTEGER DEFAULT 0"),
            ("is_banned",   "INTEGER DEFAULT 0"),
        ]:
            try:
                conn.execute(f"ALTER TABLE users ADD COLUMN {col} {definition}")
            except Exception:
                pass
        conn.commit()
    print(f"[DB] ✅ Database tayyor: {DB_PATH}")


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


def upsert_user(user, lang: str | None = None):
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
            user.first_name  or "",
            user.last_name   or "",
            user.username    or "",
            lang or "uz",
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            lang,
        ))
        conn.commit()


def get_lang(user_id: int) -> str | None:
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


def get_user_by_id(telegram_id: int) -> tuple | None:
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
        "choose_lang"   : "🌐 Tilni tanlang / Choose language:",
        "welcome"       : (
            "👋 Salom, {name}!\n\n"
            "Men fayllarni ZIP arxivga yig'ib beraman.\n\n"
            "📎 Istalgan fayl yuboring:\n"
            "   • Rasm, screenshot, PNG/JPG\n"
            "   • Video — MP4, MKV, WebM\n"
            "   • Audio — MP3, OGG\n"
            "   • Hujjat, arxiv va boshqalar\n\n"
            "📦 Keyin «Tayyor» tugmasini bosing va ZIP nomini yozing.\n"
            "💾 Har bir foydalanuvchiga: max 500 MB joy."
        ),
        "file_saved"    : "✅ Fayl saqlandi!\n📁 Jami: {count} ta fayl\n💾 Ishlatilgan: {size}",
        "storage_full"  : (
            "❌ Xotira to'lib qoldi!\n\n"
            "💾 Siz {used} dan {max} ni ishlatdingiz.\n"
            "Avval ZIP qilib oling, keyin yangi fayl yuboring."
        ),
        "ready_btn"     : "📦 Tayyor — ZIP yasash",
        "ask_zip_name"  : (
            "✏️ ZIP fayl nomini yozing\n\n"
            "⚠️ Qoidalar:\n"
            "   • Faqat harf, raqam, — _ belgilari\n"
            "   • Bo'sh joy qolmasin!\n\n"
            "✅ To'g'ri: ali_zip  yoki  ali-zip\n"
            "❌ Noto'g'ri: ali zip"
        ),
        "zip_caption"   : "📦 ZIP tayyor!\n\n😄 @Zipla_bot — Hayotni Ziplab o't!",
        "no_files"      : "⚠️ Hech qanday fayl yo'q. Avval fayl yuboring.",
        "zip_error"     : "❌ ZIP yaratishda xato yuz berdi. Qaytadan urining.",
        "bad_name"      : "❌ Noto'g'ri nom!\n\nFaqat harf, raqam, — _ belgilari:\n✅ ali_zip\n❌ ali zip",
        "lang_set"      : "✅ Til saqlandi!",
        "change_lang"   : "🌐 Tilni o'zgartirish",
        "download_err"  : "❌ Faylni yuklashda xato. Qaytadan yuboring.",
        "creating_zip"  : "⏳ ZIP yaratilmoqda...",
        "banned"        : "⛔ Siz bloklangansiz. Admin bilan bog'laning.",
    },
    "en": {
        "choose_lang"   : "🌐 Tilni tanlang / Choose language:",
        "welcome"       : (
            "👋 Hello, {name}!\n\n"
            "I pack your files into a ZIP archive.\n\n"
            "📎 Send any file:\n"
            "   • Photos, screenshots, PNG/JPG\n"
            "   • Videos — MP4, MKV, WebM\n"
            "   • Audio — MP3, OGG\n"
            "   • Documents, archives, etc.\n\n"
            "📦 Then press «Ready» and type a ZIP name.\n"
            "💾 Per user storage limit: 500 MB."
        ),
        "file_saved"    : "✅ File saved!\n📁 Total: {count} files\n💾 Used: {size}",
        "storage_full"  : (
            "❌ Storage limit reached!\n\n"
            "💾 You used {used} of {max}.\n"
            "Create a ZIP first, then send new files."
        ),
        "ready_btn"     : "📦 Ready — Create ZIP",
        "ask_zip_name"  : "✏️ Enter ZIP file name (letters, numbers, — _ only, no spaces):",
        "zip_caption"   : "📦 ZIP is ready!\n\n😄 @Zipla_bot — Zip your life!",
        "no_files"      : "⚠️ No files found. Please send files first.",
        "zip_error"     : "❌ Error creating ZIP. Please try again.",
        "bad_name"      : "❌ Invalid name!\n\nUse letters, numbers, _ and - only (no spaces):\n✅ ali_zip\n❌ ali zip",
        "lang_set"      : "✅ Language saved!",
        "change_lang"   : "🌐 Change language",
        "download_err"  : "❌ Download error. Please resend the file.",
        "creating_zip"  : "⏳ Creating ZIP...",
        "banned"        : "⛔ You are banned. Contact admin.",
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
    """Barcha foydalanuvchilarning umumiy disk hajmi"""
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


async def log_admin(label: str, user, text: str):
    try:
        safe = lambda s: (s or "").encode("utf-16", "surrogatepass").decode("utf-16", "replace")
        await app.send_message(
            ADMIN_ID,
            f"[LOG] {label}\n👤 {safe(user.first_name)} (ID: {user.id})\n💬 {safe(text)}"
        )
    except Exception as e:
        print(f"[log_admin error] {e}")

# ============================================================
#  CORE: fayl qabul qilish
# ============================================================
async def receive_file(client, message, obj, filename: str):
    uid   = message.from_user.id

    # Ban tekshiruvi
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
               max=fmt_size(MAX_STORAGE))
        )
        return

    save_path = unique_path(udir, filename)

    try:
        await message.download(file_name=save_path)
    except Exception as e:
        await message.reply(tx(uid, "download_err"))
        print(f"[download error] {e}")
        return

    cnt  = file_count(uid)
    used = storage_used(uid)
    await send_sticker(client, message.chat.id, "ok")
    await message.reply(
        tx(uid, "file_saved", count=cnt, size=fmt_size(used)),
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton(tx(uid, "ready_btn"), callback_data="zip_now")]
        ])
    )
    await log_admin("📎 Fayl yuborildi", message.from_user, filename)

# ============================================================
#  /start
# ============================================================
app = Client("zip_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)


@app.on_message(filters.command("start"))
async def cmd_start(client, message):
    uid  = message.from_user.id
    lang = get_lang(uid)

    if is_banned(uid):
        await message.reply(TEXTS["uz"]["banned"])
        return

    if lang is None:
        upsert_user(message.from_user, "uz")
        lang = get_lang(uid)

    if lang is None:
        await message.reply(
            TEXTS["uz"]["choose_lang"],
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🇺🇿 O'zbek",  callback_data="setlang_uz"),
                InlineKeyboardButton("🇬🇧 English", callback_data="setlang_en"),
            ]])
        )
    else:
        await show_welcome(client, message.chat.id, message.from_user)

    await log_admin("▶️ /start", message.from_user, "/start")


async def show_welcome(client, chat_id: int, user):
    lang  = get_lang(user.id) or "uz"
    name  = user.first_name or "Foydalanuvchi"
    texts = TEXTS[lang]
    await client.send_message(
        chat_id,
        texts["welcome"].format(name=name),
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton(f"🌐 {texts['change_lang']}", callback_data="change_lang")
        ]])
    )
    await send_sticker(client, chat_id, "start")

# ============================================================
#  Til tanlash
# ============================================================
@app.on_callback_query(filters.create(lambda _, __, q: q.data.startswith("setlang_")))
async def cb_set_lang(client, call):
    lang = call.data.split("_")[1]
    upsert_user(call.from_user, lang)
    try:
        await call.message.delete()
    except Exception:
        pass
    await show_welcome(client, call.message.chat.id, call.from_user)
    await call.answer(TEXTS[lang]["lang_set"])


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
    ph = message.photo
    await receive_file(client, message, ph,
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
    vo = message.voice
    await receive_file(client, message, vo,
                       f"voice_{datetime.now():%Y%m%d_%H%M%S}.ogg")


@app.on_message(filters.video_note)
async def on_video_note(client, message):
    vn = message.video_note
    await receive_file(client, message, vn,
                       f"videonote_{datetime.now():%Y%m%d_%H%M%S}.mp4")


@app.on_message(filters.sticker)
async def on_sticker(client, message):
    s = message.sticker
    await receive_file(client, message, s,
                       f"sticker_{datetime.now():%Y%m%d_%H%M%S}.webp")

# ============================================================
#  "Tayyor" tugmasi
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

    set_waiting(uid, True)
    await call.message.reply(tx(uid, "ask_zip_name"))
    await call.answer()

# ============================================================
#  Matn handleri
# ============================================================
ZIP_NAME_RE = re.compile(r'^[\w\-]{1,64}$')

# Admin: foydalanuvchi ID kutish holati
waiting_for_user_id: dict = {}   # {admin_id: "ban" | "unban" | "info" | "clear"}


@app.on_message(filters.text & ~filters.command(["start", "admin"]))
async def on_text(client, message):
    uid = message.from_user.id

    if get_lang(uid) is None:
        upsert_user(message.from_user, "uz")
        await show_welcome(client, message.chat.id, message.from_user)
        return

    # Admin broadcast
    if uid == ADMIN_ID and uid in broadcast_mode:
        broadcast_mode.discard(uid)
        users = all_users()
        ok = fail = 0
        progress_msg = await message.reply("📨 Yuborilmoqda...")
        for row in users:
            if row[6]:  # is_banned
                continue
            try:
                await client.send_message(row[0], f"📢 {message.text}")
                ok += 1
            except Exception:
                fail += 1
        try:
            await progress_msg.delete()
        except Exception:
            pass
        await message.reply(
            f"✅ Broadcast tugadi!\n✔️ Yuborildi: **{ok}**\n❌ Yuborilmadi: **{fail}**",
            parse_mode=enums.ParseMode.MARKDOWN,
        )
        return

    # Admin: foydalanuvchi ID kutilmoqda
    if uid == ADMIN_ID and uid in waiting_for_user_id:
        action = waiting_for_user_id.pop(uid)
        text   = message.text.strip()

        # ID raqamini ajratib olish
        try:
            target_id = int(re.search(r'\d+', text).group())
        except Exception:
            await message.reply("❌ Noto'g'ri ID formati. Faqat raqam yuboring.")
            return

        if action == "ban":
            user_data = get_user_by_id(target_id)
            if not user_data:
                await message.reply(f"❌ ID `{target_id}` topilmadi.", parse_mode=enums.ParseMode.MARKDOWN)
                return
            ban_user(target_id)
            await message.reply(
                f"⛔ Foydalanuvchi **bloklandi**!\n"
                f"👤 {user_data[1]} {user_data[2]} (ID: `{target_id}`)",
                parse_mode=enums.ParseMode.MARKDOWN,
            )
            try:
                await client.send_message(target_id, tx(target_id, "banned"))
            except Exception:
                pass

        elif action == "unban":
            user_data = get_user_by_id(target_id)
            if not user_data:
                await message.reply(f"❌ ID `{target_id}` topilmadi.", parse_mode=enums.ParseMode.MARKDOWN)
                return
            unban_user(target_id)
            await message.reply(
                f"✅ Foydalanuvchi **blokdan chiqarildi**!\n"
                f"👤 {user_data[1]} {user_data[2]} (ID: `{target_id}`)",
                parse_mode=enums.ParseMode.MARKDOWN,
            )

        elif action == "info":
            user_data = get_user_by_id(target_id)
            if not user_data:
                await message.reply(f"❌ ID `{target_id}` topilmadi.", parse_mode=enums.ParseMode.MARKDOWN)
                return
            tid, fn, ln, un, lg, jd, banned = user_data
            used       = storage_used(tid)
            fcnt       = file_count(tid)
            ban_status = "Ha" if banned else "Yoq"
            username   = ("@" + un) if un else "—"
            await message.reply(
                f"👤 **Foydalanuvchi ma'lumoti**\n\n"
                f"🆔 ID: `{tid}`\n"
                f"📛 Ism: {fn} {ln}\n"
                f"🔗 Username: {username}\n"
                f"🌐 Til: {lg.upper()}\n"
                f"📅 Qo'shilgan: {jd[:16]}\n"
                f"📁 Fayllar: {fcnt} ta\n"
                f"💾 Disk: {fmt_size(used)}\n"
                f"🚫 Bloklangan: {ban_status}",
                parse_mode=enums.ParseMode.MARKDOWN,
            )

        elif action == "clear":
            user_data = get_user_by_id(target_id)
            if not user_data:
                await message.reply(f"❌ ID `{target_id}` topilmadi.", parse_mode=enums.ParseMode.MARKDOWN)
                return
            udir = os.path.join(BASE_DIR, str(target_id))
            if os.path.exists(udir):
                shutil.rmtree(udir)
                os.makedirs(udir, exist_ok=True)
            await message.reply(
                f"🗑️ ID `{target_id}` ning barcha fayllari o'chirildi.",
                parse_mode=enums.ParseMode.MARKDOWN,
            )
        return

    # ZIP nomi kutilmayapti
    if not is_waiting(uid):
        return

    zip_name_raw = message.text.strip()

    if not ZIP_NAME_RE.match(zip_name_raw):
        await message.reply(tx(uid, "bad_name"))
        return

    set_waiting(uid, False)

    udir     = user_dir(uid)
    zip_name = f"{zip_name_raw}.zip"
    zip_path = os.path.join(udir, zip_name)

    progress_msg = await message.reply(tx(uid, "creating_zip"))

    try:
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for fname in os.listdir(udir):
                fpath = os.path.join(udir, fname)
                if os.path.isfile(fpath) and fname != zip_name:
                    zf.write(fpath, arcname=fname)

        await client.send_document(
            message.chat.id,
            zip_path,
            caption=tx(uid, "zip_caption"),
            file_name=zip_name,
        )
        await log_admin("📦 ZIP yaratildi", message.from_user, zip_name)

    except Exception as e:
        await message.reply(tx(uid, "zip_error"))
        print(f"[zip error] {e}")
        return

    finally:
        try:
            await progress_msg.delete()
        except Exception:
            pass

    try:
        shutil.rmtree(udir)
        os.makedirs(udir, exist_ok=True)
    except Exception as e:
        print(f"[cleanup error] {e}")

# ============================================================
#  ADMIN PANEL
# ============================================================
def _is_admin(_, __, q):
    return q.from_user.id == ADMIN_ID

admin_filter = filters.create(_is_admin)


@app.on_message(filters.command("admin") & filters.user(ADMIN_ID))
async def cmd_admin(client, message):
    cnt       = user_count()
    today_cnt = today_count()
    disk      = fmt_size(total_storage_all_users())
    await message.reply(
        f"🔐 **Admin Panel**\n\n"
        f"👥 Jami foydalanuvchilar : **{cnt}**\n"
        f"📅 Bugun qo'shilganlar   : **{today_cnt}**\n"
        f"💾 Umumiy disk           : **{disk}**\n"
        f"🗄️ DB path               : `{DB_PATH}`",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("👥 Foydalanuvchilar",    callback_data="adm_users"),
             InlineKeyboardButton("📊 Statistika",           callback_data="adm_stats")],
            [InlineKeyboardButton("📨 Broadcast",            callback_data="adm_broadcast"),
             InlineKeyboardButton("🔍 Foydalanuvchi izlash", callback_data="adm_search")],
            [InlineKeyboardButton("⛔ Ban",                  callback_data="adm_ban"),
             InlineKeyboardButton("✅ Unban",                callback_data="adm_unban")],
            [InlineKeyboardButton("🗑️ Fayllarni tozalash",  callback_data="adm_clear"),
             InlineKeyboardButton("🔁 Volume tekshirish",   callback_data="adm_volume")],
        ]),
        parse_mode=enums.ParseMode.MARKDOWN,
    )


@app.on_callback_query(admin_filter & filters.create(lambda _, __, q: q.data == "adm_users"))
async def adm_users(client, call):
    users = all_users()
    if not users:
        await call.message.reply("Hech qanday foydalanuvchi yo'q.")
        await call.answer()
        return

    lines = ["👥 **Foydalanuvchilar ro'yxati** (oxirgi 30 ta):\n"]
    for i, (tid, fn, ln, un, lg, jd, banned) in enumerate(users[:30], 1):
        full  = f"{fn} {ln}".strip() or "—"
        ustr  = f"@{un}" if un else "username yo'q"
        bmark = " ⛔" if banned else ""
        lines.append(
            f"`{i}.` {full}{bmark} | {ustr}\n"
            f"    ID: `{tid}` | Til: {lg.upper()} | {jd[:10]}"
        )

    if len(users) > 30:
        lines.append(f"\n… va yana **{len(users) - 30}** ta foydalanuvchi")

    text = "\n".join(lines)
    for chunk in [text[i:i+4000] for i in range(0, len(text), 4000)]:
        await call.message.reply(chunk, parse_mode=enums.ParseMode.MARKDOWN)
    await call.answer()


@app.on_callback_query(admin_filter & filters.create(lambda _, __, q: q.data == "adm_stats"))
async def adm_stats(client, call):
    users     = all_users()
    total     = len(users)
    today     = datetime.now().strftime("%Y-%m-%d")
    today_cnt = sum(1 for u in users if (u[5] or "").startswith(today))
    uz_cnt    = sum(1 for u in users if u[4] == "uz")
    en_cnt    = sum(1 for u in users if u[4] == "en")
    ban_cnt   = sum(1 for u in users if u[6])
    disk      = fmt_size(total_storage_all_users())

    # Oxirgi 7 kunlik statistika
    week_lines = []
    from datetime import timedelta
    for i in range(6, -1, -1):
        d     = (datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d")
        cnt_d = sum(1 for u in users if (u[5] or "").startswith(d))
        bar   = "█" * min(cnt_d, 20)
        week_lines.append(f"`{d[5:]}` {bar} {cnt_d}")

    await call.message.reply(
        f"📊 **Statistika**\n\n"
        f"👥 Jami foydalanuvchilar : **{total}**\n"
        f"📅 Bugun qo'shilganlar   : **{today_cnt}**\n"
        f"🇺🇿 O'zbek tili           : **{uz_cnt}**\n"
        f"🇬🇧 Ingliz tili           : **{en_cnt}**\n"
        f"⛔ Bloklangan            : **{ban_cnt}**\n"
        f"💾 Umumiy disk foydalanish: **{disk}**\n\n"
        f"📈 **Oxirgi 7 kun:**\n" + "\n".join(week_lines),
        parse_mode=enums.ParseMode.MARKDOWN,
    )
    await call.answer()


@app.on_callback_query(admin_filter & filters.create(lambda _, __, q: q.data == "adm_broadcast"))
async def adm_broadcast(client, call):
    broadcast_mode.add(ADMIN_ID)
    await call.message.reply(
        "📨 Barcha foydalanuvchilarga yuboriladigan xabarni yozing:\n"
        "_(Bloklangan foydalanuvchilarga yuborilmaydi)_\n"
        "_(Bekor qilish uchun /admin bosing)_",
        parse_mode=enums.ParseMode.MARKDOWN,
    )
    await call.answer()


@app.on_callback_query(admin_filter & filters.create(lambda _, __, q: q.data == "adm_search"))
async def adm_search(client, call):
    waiting_for_user_id[ADMIN_ID] = "info"
    await call.message.reply(
        "🔍 Foydalanuvchi ID sini yuboring:",
        parse_mode=enums.ParseMode.MARKDOWN,
    )
    await call.answer()


@app.on_callback_query(admin_filter & filters.create(lambda _, __, q: q.data == "adm_ban"))
async def adm_ban(client, call):
    waiting_for_user_id[ADMIN_ID] = "ban"
    await call.message.reply(
        "⛔ Ban qilmoqchi bo'lgan foydalanuvchi **ID** sini yuboring:",
        parse_mode=enums.ParseMode.MARKDOWN,
    )
    await call.answer()


@app.on_callback_query(admin_filter & filters.create(lambda _, __, q: q.data == "adm_unban"))
async def adm_unban(client, call):
    waiting_for_user_id[ADMIN_ID] = "unban"
    await call.message.reply(
        "✅ Blokdan chiqarmoqchi bo'lgan foydalanuvchi **ID** sini yuboring:",
        parse_mode=enums.ParseMode.MARKDOWN,
    )
    await call.answer()


@app.on_callback_query(admin_filter & filters.create(lambda _, __, q: q.data == "adm_clear"))
async def adm_clear(client, call):
    waiting_for_user_id[ADMIN_ID] = "clear"
    await call.message.reply(
        "🗑️ Fayllarini tozalamoqchi bo'lgan foydalanuvchi **ID** sini yuboring:",
        parse_mode=enums.ParseMode.MARKDOWN,
    )
    await call.answer()


@app.on_callback_query(admin_filter & filters.create(lambda _, __, q: q.data == "adm_volume"))
async def adm_volume_check(client, call):
    lines = [
        f"🗄️ **Volume tekshiruv**\n",
        f"📁 Path: `{VOLUME_PATH}`",
        f"✅ Mavjud: `{os.path.exists(VOLUME_PATH)}`",
    ]
    if os.path.exists(VOLUME_PATH):
        files = os.listdir(VOLUME_PATH)
        lines.append(f"📂 Fayllar: `{files}`")
        if "bot.db" in files:
            size = os.path.getsize(DB_PATH)
            lines.append(f"🗃️ bot.db hajmi: `{fmt_size(size)}`")
            lines.append(f"👥 Bazadagi foydalanuvchilar: `{user_count()}`")
        else:
            lines.append("⚠️ bot.db topilmadi!")
    else:
        lines.append(
            "\n❌ **Volume mount qilinmagan!**\n\n"
            "Railway Dashboard:\n"
            "1. Service → Settings → Volumes\n"
            f"2. Mount Path: `{VOLUME_PATH}`\n"
            "3. Environment var qo'shing:\n"
            f"   `VOLUME_PATH={VOLUME_PATH}`"
        )
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
            f"✅ Bot is running!<br>"
            f"👥 Users: {user_count()}<br>"
            f"🗄️ DB: {DB_PATH}<br>"
            f"💾 Volume OK: {os.path.exists(VOLUME_PATH)}"
        )

    port = int(os.environ.get("PORT", 5000))
    flask_app.run(host="0.0.0.0", port=port)

# ============================================================
#  MAIN
# ============================================================
if __name__ == "__main__":
    check_volume()                                      # Volume holatini log qilish
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    init_db()
    os.makedirs(BASE_DIR,    exist_ok=True)
    os.makedirs(STICKER_DIR, exist_ok=True)
    threading.Thread(target=keep_alive, daemon=True).start()
    print("✅ Bot ishga tushdi!")
    app.run()
