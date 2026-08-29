from pyrogram.types import ReplyKeyboardMarkup, KeyboardButton

import database
from config import ADMIN_ID
from texts import TEXTS


def main_keyboard(uid: int):
    lang = database.get_lang(uid) or "uz"
    t = TEXTS.get(lang, TEXTS["uz"])
    rows = [
        [KeyboardButton("⭐ Premium"), KeyboardButton(t["btn_stats"])],
        [KeyboardButton(t["btn_contact"]), KeyboardButton(t["btn_feedback"])],
    ]
    if uid == ADMIN_ID:
        rows.append([KeyboardButton("🔐 Admin panel")])
    return ReplyKeyboardMarkup(rows, resize_keyboard=True)
