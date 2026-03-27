import os
import shutil
import zipfile
import threading
from flask import Flask
from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton

# ==== BOT CONFIG (.env dan o'qish tavsiya etiladi) ====
API_ID = int(os.environ.get("API_ID", 29517932))
API_HASH = os.environ.get("API_HASH", "572b177f48692c0cbd88664120fb87f4")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "7579799414:AAFubjp6EdJySpv8tQHxvkpgO1i3fM45kKg")

BASE_DIR = 'user_files'
STICKER_DIR = 'stickers'
ADMIN_ID = 1663567950

app = Client("zip_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

# ✅ State: kim ZIP nomi kutmoqda
waiting_for_zip_name = set()

def get_user_dir(user_id):
    user_dir = os.path.join(BASE_DIR, str(user_id))
    os.makedirs(user_dir, exist_ok=True)
    return user_dir

def count_user_files(user_id):
    return len(os.listdir(get_user_dir(user_id)))

# ✅ Async sticker funksiyasi
async def send_sticker(client, chat_id, name):
    path = os.path.join(STICKER_DIR, f"{name}.webp")
    if os.path.exists(path):
        await client.send_sticker(chat_id, path)

async def log_to_admin(sender_type, user, text):
    try:
        safe_name = user.first_name.encode('utf-16', 'surrogatepass').decode('utf-16', 'replace')
        safe_text = str(text).encode('utf-16', 'surrogatepass').decode('utf-16', 'replace')
        log_msg = f"[LOG] {sender_type}\n👤 {safe_name} (ID: {user.id})\n💬 {safe_text}"
        await app.send_message(ADMIN_ID, log_msg)
    except Exception as e:
        print(f"Log xatosi: {e}")

@app.on_message(filters.command("start"))
async def start_handler(client, message):
    await message.reply("👋 Salom! Men fayllarni ZIP qilib qaytaraman.")
    await send_sticker(client, message.chat.id, 'start')
    await log_to_admin("Foydalanuvchi yubordi", message.from_user, "/start")

@app.on_message(filters.document)
async def handle_files(client, message):
    user_id = message.from_user.id
    user_dir = get_user_dir(user_id)
    file_name = message.document.file_name
    save_path = os.path.join(user_dir, file_name)

    # ✅ Fayl hajmini tekshirish (50MB limit)
    if message.document.file_size > 50 * 1024 * 1024:
        await message.reply("⚠️ Fayl hajmi 50MB dan oshmasligi kerak.")
        return

    if os.path.exists(save_path):
        msg = f"⚠️ Fayl '{file_name}' allaqachon saqlangan."
        await message.reply(msg)
        await send_sticker(client, message.chat.id, 'warning')
        await log_to_admin("Bot ogohlantirdi", message.from_user, msg)
        return

    try:
        await message.download(file_name=save_path)
    except Exception as e:
        await message.reply("❌ Faylni saqlashda xato yuz berdi.")
        print(f"Download xato: {e}")
        return

    file_count = count_user_files(user_id)
    await send_sticker(client, message.chat.id, 'ok')
    reply_msg = f"Fayl saqlandi ✅\nJami {file_count} ta fayl bor."
    await message.reply(reply_msg, reply_markup=InlineKeyboardMarkup(
        [[InlineKeyboardButton("📦 Tayyor", callback_data="zip_now")]]))

    await log_to_admin("Foydalanuvchi yubordi", message.from_user, file_name)

@app.on_callback_query(filters.create(lambda _, __, q: q.data == "zip_now"))
async def handle_callback(client, call):
    user_id = call.from_user.id
    user_dir = get_user_dir(user_id)

    if not os.listdir(user_dir):
        await call.message.reply("⚠️ Avval fayl yuboring.")
        return

    # ✅ Foydalanuvchini kutish holatiga qo'shish
    waiting_for_zip_name.add(user_id)
    await call.message.reply("📝 ZIP fayl nomini yozing:")
    await call.answer()

@app.on_message(filters.text & ~filters.command(["start"]))
async def handle_zip_name(client, message):
    user_id = message.from_user.id

    # ✅ Faqat tugma bosgan foydalanuvchilar uchun ishlaydi
    if user_id not in waiting_for_zip_name:
        await message.reply("📎 Fayl yuboring yoki /start bosing.")
        return

    user_dir = get_user_dir(user_id)
    zip_name = message.text.strip()

    # ✅ Fayl nomini xavfsiz qilish
    zip_name = "".join(c for c in zip_name if c.isalnum() or c in (' ', '-', '_')).strip()
    if not zip_name:
        await message.reply("❌ Noto'g'ri fayl nomi. Qaytadan yozing:")
        return

    # ✅ User ID qo'shib to'qnashuvni oldini olish
    zip_path = os.path.join(BASE_DIR, f"{user_id}_{zip_name}.zip")

    try:
        with zipfile.ZipFile(zip_path, 'w') as zipf:
            for root, _, files in os.walk(user_dir):
                for file in files:
                    zipf.write(os.path.join(root, file), arcname=file)

        await app.send_document(
            message.chat.id, zip_path,
            caption="📦 ZIP tayyor!\n\n😅@Zipla_bot Hayotni Ziplab o't."
        )
        await send_sticker(client, message.chat.id, 'done')

    except Exception as e:
        await message.reply("❌ ZIP yaratishda xato yuz berdi.")
        print(f"ZIP xato: {e}")
    finally:
        # ✅ Tozalash
        waiting_for_zip_name.discard(user_id)
        shutil.rmtree(user_dir, ignore_errors=True)
        if os.path.exists(zip_path):
            os.remove(zip_path)

    await log_to_admin("Foydalanuvchi yubordi", message.from_user, message.text)
    await log_to_admin("Bot yubordi", message.from_user, f"ZIP '{zip_name}.zip' yuborildi")

# == Flask server (Render uchun) ==
def keep_alive():
    flask_app = Flask('')

    @flask_app.route('/')
    def home():
        return "Bot is running!"

    port = int(os.environ.get("PORT", 5000))
    flask_app.run(host='0.0.0.0', port=port)

if __name__ == '__main__':
    os.makedirs(BASE_DIR, exist_ok=True)
    os.makedirs(STICKER_DIR, exist_ok=True)
    threading.Thread(target=keep_alive, daemon=True).start()  # ✅ daemon=True qo'shildi
    print("Bot ishga tushdi...")
    app.run()
