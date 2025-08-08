import os
import shutil
import zipfile
import threading
from flask import Flask
from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton

# ==== BOT CONFIG ====
API_ID = 29517932
API_HASH = "572b177f48692c0cbd88664120fb87f4"
BOT_TOKEN = "7579799414:AAFubjp6EdJySpv8tQHxvkpgO1i3fM45kKg"

BASE_DIR = 'user_files'
STICKER_DIR = 'stickers'
ADMIN_ID = 1663567950

app = Client("zip_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

def get_user_dir(user_id):
    user_dir = os.path.join(BASE_DIR, str(user_id))
    os.makedirs(user_dir, exist_ok=True)
    return user_dir

def count_user_files(user_id):
    user_dir = get_user_dir(user_id)
    return len(os.listdir(user_dir))

def send_sticker(chat_id, name):
    path = os.path.join(STICKER_DIR, f"{name}.webp")
    if os.path.exists(path):
        app.send_sticker(chat_id, path)

def log_to_admin(sender_type, user, text):
    safe_name = user.first_name.encode('utf-16', 'surrogatepass').decode('utf-16', 'replace')
    safe_text = text.encode('utf-16', 'surrogatepass').decode('utf-16', 'replace')
    log_msg = f"[LOG] {sender_type}\n\U0001F464 {safe_name} (ID: {user.id})\n\U0001F4AC {safe_text}"
    app.send_message(ADMIN_ID, log_msg)

@app.on_message(filters.document)
async def handle_files(client, message):
    user_id = message.from_user.id
    user_dir = get_user_dir(user_id)
    file_name = message.document.file_name
    save_path = os.path.join(user_dir, file_name)

    if os.path.exists(save_path):
        msg = f"\u26A0\uFE0F Fayl '{file_name}' allaqachon saqlangan."
        await message.reply(msg)
        send_sticker(message.chat.id, 'warning')
        log_to_admin("Bot ogohlantirdi", message.from_user, msg)
        return

    await message.download(file_name=save_path)

    file_count = count_user_files(user_id)
    send_sticker(message.chat.id, 'ok')
    reply_msg = f"Fayl saqlandi \u2705\nJami {file_count} ta fayl bor."
    await message.reply(reply_msg, reply_markup=InlineKeyboardMarkup(
        [[InlineKeyboardButton("\U0001F4E6 Tayyor", callback_data="zip_now")]]))

    log_to_admin("Foydalanuvchi yubordi", message.from_user, file_name)
    log_to_admin("Bot yubordi", message.from_user, reply_msg)

@app.on_callback_query(filters.create(lambda _, __, query: query.data == "zip_now"))
async def handle_callback(client, call):
    await call.message.reply("ZIP fayl nomini yozing:")
    log_to_admin("Bot yubordi", call.from_user, "ZIP fayl nomini yozing:")

@app.on_message(filters.text & ~filters.command(["start"]))
async def handle_zip_name(client, message):
    user_id = message.from_user.id
    user_dir = get_user_dir(user_id)
    zip_name = message.text.strip()

    if not os.listdir(user_dir):
        msg = "Siz hech qanday fayl yubormagansiz."
        await message.reply(msg)
        log_to_admin("Bot yubordi", message.from_user, msg)
        return

    zip_path = os.path.join(BASE_DIR, f"{zip_name}.zip")
    with zipfile.ZipFile(zip_path, 'w') as zipf:
        for root, _, files in os.walk(user_dir):
            for file in files:
                zipf.write(os.path.join(root, file), arcname=file)

    await app.send_document(message.chat.id, zip_path, caption="\U0001F4E6 ZIP tayyor!\n\n\U0001F605@Zipla_bot Hayotni Ziplab o't.")
    send_sticker(message.chat.id, 'done')

    shutil.rmtree(user_dir)
    os.remove(zip_path)

    log_to_admin("Foydalanuvchi yubordi", message.from_user, message.text)
    log_to_admin("Bot yubordi", message.from_user, f"ZIP fayl '{zip_name}.zip' yuborildi")

@app.on_message(filters.command("start"))
async def start_handler(client, message):
    await message.reply("\U0001F44B Salom! Men fayllarni ZIP qilib qaytaraman.")
    send_sticker(message.chat.id, 'start')
    log_to_admin("Foydalanuvchi yubordi", message.from_user, "/start")
    log_to_admin("Bot yubordi", message.from_user, "\U0001F44B Salom va tugmalar yuborilmadi")

# == Flask "fake" server to trick Render ==
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
    threading.Thread(target=keep_alive).start()
    print("Bot ishga tushdi...")
    app.run()
    
