import os
import shutil
import zipfile
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton

TOKEN = '7579799414:AAFubjp6EdJySpv8tQHxvkpgO1i3fM45kKg'
bot = telebot.TeleBot(TOKEN)

BASE_DIR = 'user_files'
STICKER_DIR = 'stickers'

# --- Foydalanuvchi papkasi ---
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
        with open(path, 'rb') as f:
            bot.send_sticker(chat_id, f)

@bot.message_handler(content_types=['document'])
def handle_files(message):
    user_id = message.from_user.id
    user_dir = get_user_dir(user_id)

    file_info = bot.get_file(message.document.file_id)
    file_path = file_info.file_path
    downloaded_file = bot.download_file(file_path)

    file_name = message.document.file_name
    save_path = os.path.join(user_dir, file_name)

    with open(save_path, 'wb') as f:
        f.write(downloaded_file)

    file_count = count_user_files(user_id)
    send_sticker(message.chat.id, 'ok')
    bot.reply_to(message, f"Fayl saqlandi ✅\nJami {file_count} ta fayl bor.")
    send_options(message.chat.id)

def send_options(chat_id):
    markup = InlineKeyboardMarkup()
    markup.add(
        InlineKeyboardButton("📤 Yana fayl yuboraman", callback_data="send_file"),
        InlineKeyboardButton("📦 ZIP nomini kiritaman", callback_data="zip_now"),
        InlineKeyboardButton("🗑 Tozalash", callback_data="clear_files")
    )
    bot.send_message(chat_id, "Nima qilamiz?", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: True)
def handle_callback(call):
    user_id = call.from_user.id
    user_dir = get_user_dir(user_id)

    if call.data == "send_file":
        bot.send_message(call.message.chat.id, "Yana fayl yuboring 📎")

    elif call.data == "zip_now":
        bot.send_message(call.message.chat.id, "ZIP fayl nomini yozing:")

    elif call.data == "clear_files":
        if os.path.exists(user_dir):
            shutil.rmtree(user_dir)
        bot.send_message(call.message.chat.id, "Barcha fayllar o‘chirildi.")
        send_sticker(call.message.chat.id, 'trash')

@bot.message_handler(func=lambda message: message.text and not message.text.startswith('/'))
def handle_zip_name(message):
    user_id = message.from_user.id
    user_dir = get_user_dir(user_id)
    zip_name = message.text.strip()

    if not os.listdir(user_dir):
        bot.reply_to(message, "Siz hech qanday fayl yubormagansiz.")
        return

    zip_path = os.path.join(BASE_DIR, f"{zip_name}.zip")
    with zipfile.ZipFile(zip_path, 'w') as zipf:
        for root, dirs, files in os.walk(user_dir):
            for file in files:
                zipf.write(os.path.join(root, file), arcname=file)

    with open(zip_path, 'rb') as f:
        bot.send_document(message.chat.id, f, caption="📦 ZIP tayyor!")

    send_sticker(message.chat.id, 'done')
    shutil.rmtree(user_dir)
    os.remove(zip_path)

@bot.message_handler(commands=['start'])
def start_handler(message):
    bot.send_message(message.chat.id, "👋 Salom! Men fayllarni ZIP qilib qaytaraman.")
    send_sticker(message.chat.id, 'start')
    send_options(message.chat.id)

# --- Run ---
if __name__ == '__main__':
    os.makedirs(BASE_DIR, exist_ok=True)
    os.makedirs(STICKER_DIR, exist_ok=True)
    print("Bot ishga tushdi...")
    bot.polling()
