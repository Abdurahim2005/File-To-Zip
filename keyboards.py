from pyrogram.types import ReplyKeyboardMarkup, KeyboardButton

import database
from texts import TEXTS


def main_keyboard(uid: int):
    lang = database.get_lang(uid) or "uz"
    t = TEXTS.get(lang, TEXTS["uz"])
    return ReplyKeyboardMarkup(
        [[KeyboardButton("⭐ Premium"), KeyboardButton(t["btn_stats"])],
         [KeyboardButton(t["btn_contact"]), KeyboardButton(t["btn_feedback"])]],
        resize_keyboard=True
    )
