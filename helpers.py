import os
import asyncio

from pyrogram import enums
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, Message

import database
import state
from config import STICKER_DIR, ADMIN_ID
from texts import TEXTS


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


async def show_donate(client, chat_id: int, uid: int):
    lang    = database.get_lang(uid) or "uz"
    donors  = database.get_top_donors()
    medals  = ["🥇","🥈","🥉"] + ["⭐"]*10
    if donors:
        lines = []
        for i, (tid, fn, amounts, cnt) in enumerate(donors):
            medal = medals[i] if i < len(medals) else "⭐"
            lines.append(f"{medal} *{fn}* — {amounts}")
        top_text = TEXTS[lang]["top_donors"].format(list="\n".join(lines))
    else:
        top_text = TEXTS[lang]["no_donors"]

    await client.send_message(
        chat_id, top_text,
        parse_mode=enums.ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton(TEXTS[lang]["donate_btn"], callback_data="donate_show_form")
        ]]),
    )


async def _handle_admin_reply_media(client, message: Message):
    target_uid = state.admin_reply_to.pop(ADMIN_ID, None)
    if not target_uid:
        return
    lang = database.get_lang(target_uid) or "uz"
    caption = TEXTS[lang]["reply_from_admin"]
    try:
        if message.photo:
            await client.send_photo(target_uid, message.photo.file_id,
                                    caption=caption, parse_mode=enums.ParseMode.MARKDOWN)
        elif message.video:
            await client.send_video(target_uid, message.video.file_id,
                                    caption=caption, parse_mode=enums.ParseMode.MARKDOWN)
        await message.reply(TEXTS["uz"]["admin_reply_sent"])
    except Exception as e:
        await message.reply(f"❌ Yuborishda xato: {e}")

# ── Per-user file lock (race condition fix) ───────────────
def get_user_file_lock(uid: int) -> asyncio.Lock:
    if uid not in state._user_file_locks:
        state._user_file_locks[uid] = asyncio.Lock()
    return state._user_file_locks[uid]
