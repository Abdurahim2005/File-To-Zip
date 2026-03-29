import os
import re
import shutil
import zipfile
import threading
import sqlite3
from datetime import datetime
from flask import Flask
from pyrogram import Client, filters, enums          # FIX 1: enums import
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
MAX_STORAGE = 200 * 1024 * 1024   # 200 MB per user
DB_PATH     = "/app/data/bot.db"

app = Client("zip_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

# ============================================================
#  IN-MEMORY STATE
# ============================================================
waiting_for_zip_name : set = set()
broadcast_mode       : set = set()

# ============================================================
#  DATABASE
# ============================================================
def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)  # FIX 2: /app/data/ papka yaratish
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_id INTEGER UNIQUE NOT NULL,
                first_name  TEXT    DEFAULT '',
                last_name   TEXT    DEFAULT '',
                username    TEXT    DEFAULT '',
                language    TEXT    DEFAULT 'uz',
                joined_at   TEXT    NOT NULL
            )
        """)
        conn.commit()


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


def all_users() -> list:
    with sqlite3.connect(DB_PATH) as conn:
        return conn.execute(
            "SELECT telegram_id, first_name, last_name, username, language, joined_at FROM users ORDER BY id DESC"
        ).fetchall()


def user_count() -> int:
    with sqlite3.connect(DB_PATH) as conn:
        return conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]

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
            "💾 Har bir foydalanuvchiga: max 200 MB joy."
        ),
        "file_saved"    : "✅ Fayl saqlandi!\n📁 Jami: {count} ta fayl\n💾 Ishlatilgan: {size}",
        "storage_full"  : (
            "❌ Xotira to'lib qoldi!\n\n"
            "💾 Siz {used} dan {max} ni ishlatdingiz.\n"
            "Avval ZIP qilib oling, keyin yangi fayl yuboring."
        ),
        "ready_btn"     : "📦 Tayyor — ZIP yasash",
        "ask_zip_name"  : "✏️ ZIP fayl nomini yozing (faqat harf, raqam, — _ belgilari):",
        "zip_caption"   : "📦 ZIP tayyor!\n\n😄 @Zipla_bot — Hayotni Ziplab o't!",
        "no_files"      : "⚠️ Hech qanday fayl yo'q. Avval fayl yuboring.",
        "zip_error"     : "❌ ZIP yaratishda xato yuz berdi. Qaytadan urining.",
        "bad_name"      : "❌ Noto'g'ri nom. Faqat harf, raqam, — _ belgilari:",
        "lang_set"      : "✅ Til saqlandi!",
        "change_lang"   : "🌐 Tilni o'zgartirish",
        "download_err"  : "❌ Faylni yuklashda xato. Qaytadan yuboring.",
        "creating_zip"  : "⏳ ZIP yaratilmoqda...",
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
            "💾 Per user storage limit: 200 MB."
        ),
        "file_saved"    : "✅ File saved!\n📁 Total: {count} files\n💾 Used: {size}",
        "storage_full"  : (
            "❌ Storage limit reached!\n\n"
            "💾 You used {used} of {max}.\n"
            "Create a ZIP first, then send new files."
        ),
        "ready_btn"     : "📦 Ready — Create ZIP",
        "ask_zip_name"  : "✏️ Enter ZIP file name (letters, numbers, — _ only):",
        "zip_caption"   : "📦 ZIP is ready!\n\n😄 @Zipla_bot — Zip your life!",
        "no_files"      : "⚠️ No files found. Please send files first.",
        "zip_error"     : "❌ Error creating ZIP. Please try again.",
        "bad_name"      : "❌ Invalid name. Use only letters, numbers, — _ characters:",
        "lang_set"      : "✅ Language saved!",
        "change_lang"   : "🌐 Change language",
        "download_err"  : "❌ Download error. Please resend the file.",
        "creating_zip"  : "⏳ Creating ZIP...",
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
@app.on_message(filters.command("start"))
async def cmd_start(client, message):
    uid  = message.from_user.id
    lang = get_lang(uid)

    if lang is None:
        upsert_user(message.from_user, "uz")
        lang = get_lang(uid)

    if lang is None:
        # DB muammo bo'lsa — til tanlash ko'rsat
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
#  Til tanlash callbacklari
# ============================================================
@app.on_callback_query(filters.create(lambda _, __, q: q.data.startswith("setlang_")))
async def cb_set_lang(client, call):
    lang = call.data.split("_")[1]   # "uz" yoki "en"
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
#  "Tayyor" tugmasi → ZIP nomi so'rash
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

    waiting_for_zip_name.add(uid)
    await call.message.reply(tx(uid, "ask_zip_name"))
    await call.answer()

# ============================================================
#  Matn handleri — ZIP nomi yoki broadcast
# ============================================================
# Ruxsat etilgan belgilar: harf, raqam, _ va - ; max 64 ta
ZIP_NAME_RE = re.compile(r'^[\w\-]{1,64}$')


@app.on_message(filters.text & ~filters.command(["start", "admin"]))
async def on_text(client, message):
    uid = message.from_user.id

    # Tilni tanlamagan foydalanuvchi — til tanlashni ko'rsat
    if get_lang(uid) is None:
        await message.reply(
            TEXTS["uz"]["choose_lang"],
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🇺🇿 O'zbek",  callback_data="setlang_uz"),
                InlineKeyboardButton("🇬🇧 English", callback_data="setlang_en"),
            ]])
        )
        return

    # Admin broadcast rejimi
    if uid == ADMIN_ID and uid in broadcast_mode:
        broadcast_mode.discard(uid)
        users = all_users()
        ok = fail = 0
        for row in users:
            try:
                await client.send_message(row[0], f"📢 {message.text}")
                ok += 1
            except Exception:
                fail += 1
        await message.reply(
            f"✅ Broadcast tugadi!\n✔️ Yuborildi: {ok}\n❌ Yuborilmadi: {fail}"
        )
        return

    # ZIP nomi kutilmayapti — e'tiborsiz qoldur
    if uid not in waiting_for_zip_name:
        return

    # ============================================================
    #  FIX 3: ZIP YARATISH KODI (avval yo'q edi!)
    # ============================================================
    zip_name_raw = message.text.strip()

    # Nom validatsiyasi
    if not ZIP_NAME_RE.match(zip_name_raw):
        await message.reply(tx(uid, "bad_name"))
        return  # waiting_for_zip_name da qoladi → qaytadan nom so'raydi

    # Nomni to'g'ri qabul qildik
    waiting_for_zip_name.discard(uid)

    udir     = user_dir(uid)
    zip_name = f"{zip_name_raw}.zip"
    zip_path = os.path.join(udir, zip_name)

    # Jarayon xabari
    progress_msg = await message.reply(tx(uid, "creating_zip"))

    try:
        # ZIP arxiv yaratish
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for fname in os.listdir(udir):
                fpath = os.path.join(udir, fname)
                if os.path.isfile(fpath) and fname != zip_name:
                    zf.write(fpath, arcname=fname)

        # ZIP ni foydalanuvchiga yuborish
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
        # Progress xabarni o'chirish
        try:
            await progress_msg.delete()
        except Exception:
            pass

    # Foydalanuvchi papkasini tozalash (ZIP yuborilgandan keyin)
    try:
        shutil.rmtree(udir)
        os.makedirs(udir, exist_ok=True)
    except Exception as e:
        print(f"[cleanup error] {e}")

# ============================================================
#  ADMIN PANEL
# ============================================================
@app.on_message(filters.command("admin") & filters.user(ADMIN_ID))
async def cmd_admin(client, message):
    cnt = user_count()
    await message.reply(
        f"🔐 **Admin Panel**\n👥 Jami foydalanuvchilar: **{cnt}**",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("👥 Foydalanuvchilar ro'yxati", callback_data="adm_users")],
            [InlineKeyboardButton("📊 Statistika",               callback_data="adm_stats")],
            [InlineKeyboardButton("📨 Broadcast (xabar yuborish)", callback_data="adm_broadcast")],
        ]),
        parse_mode=enums.ParseMode.MARKDOWN,  # FIX 1: to'g'ri parse_mode
    )


def _is_admin(_, __, q):
    return q.from_user.id == ADMIN_ID

admin_filter = filters.create(_is_admin)


@app.on_callback_query(admin_filter & filters.create(lambda _, __, q: q.data == "adm_users"))
async def adm_users(client, call):
    users = all_users()
    if not users:
        await call.message.reply("Hech qanday foydalanuvchi yo'q.")
        await call.answer()
        return

    lines = ["👥 **Foydalanuvchilar ro'yxati** (oxirgi 30 ta):\n"]
    for i, (tid, fn, ln, un, lg, jd) in enumerate(users[:30], 1):
        full = f"{fn} {ln}".strip() or "—"
        ustr = f"@{un}" if un else "username yo'q"
        lines.append(f"`{i}.` {full} | {ustr}\n    ID: `{tid}` | Til: {lg.upper()} | {jd[:10]}")

    if len(users) > 30:
        lines.append(f"\n… va yana **{len(users) - 30}** ta foydalanuvchi")

    text = "\n".join(lines)
    if len(text) > 4000:
        for chunk in [text[i:i+4000] for i in range(0, len(text), 4000)]:
            await call.message.reply(chunk, parse_mode=enums.ParseMode.MARKDOWN)
    else:
        await call.message.reply(text, parse_mode=enums.ParseMode.MARKDOWN)

    await call.answer()


@app.on_callback_query(admin_filter & filters.create(lambda _, __, q: q.data == "adm_stats"))
async def adm_stats(client, call):
    users     = all_users()
    total     = len(users)
    uz_cnt    = sum(1 for u in users if u[4] == "uz")
    en_cnt    = sum(1 for u in users if u[4] == "en")
    today     = datetime.now().strftime("%Y-%m-%d")
    today_cnt = sum(1 for u in users if (u[5] or "").startswith(today))

    await call.message.reply(
        f"📊 **Statistika**\n\n"
        f"👥 Jami foydalanuvchilar : **{total}**\n"
        f"📅 Bugun qo'shilganlar   : **{today_cnt}**\n"
        f"🇺🇿 O'zbek tili           : **{uz_cnt}**\n"
        f"🇬🇧 Ingliz tili           : **{en_cnt}**",
        parse_mode=enums.ParseMode.MARKDOWN,
    )
    await call.answer()


@app.on_callback_query(admin_filter & filters.create(lambda _, __, q: q.data == "adm_broadcast"))
async def adm_broadcast(client, call):
    broadcast_mode.add(ADMIN_ID)
    await call.message.reply(
        "📨 Barcha foydalanuvchilarga yuboriladigan xabarni yozing:\n"
        "_(Bekor qilish uchun /admin bosing)_",
        parse_mode=enums.ParseMode.MARKDOWN,
    )
    await call.answer()

# ============================================================
#  FLASK — Railway/Render uchun keep-alive
# ============================================================
def keep_alive():
    flask_app = Flask(__name__)

    @flask_app.route("/")
    def home():
        return f"✅ Bot is running! Users: {user_count()}"

    port = int(os.environ.get("PORT", 5000))
    flask_app.run(host="0.0.0.0", port=port)

# ============================================================
#  MAIN
# ============================================================
if __name__ == "__main__":
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)  # FIX 2: papkani oldin yaratish
    init_db()
    os.makedirs(BASE_DIR,    exist_ok=True)
    os.makedirs(STICKER_DIR, exist_ok=True)
    threading.Thread(target=keep_alive, daemon=True).start()
    print("✅ Bot ishga tushdi!")
    app.run()
