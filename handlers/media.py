from datetime import datetime

from pyrogram import filters

import state
from config import ADMIN_ID
from bot_instance import app
from helpers import _handle_admin_reply_media
from receiving import receive_file

# ════════════════════════════════════════════════════════════
#  FAYL HANDLERLARI - on_document FILTER TUZATILDI
# ════════════════════════════════════════════════════════════
@app.on_message(filters.document & ~filters.video & ~filters.audio & ~filters.voice &
                ~filters.video_note & ~filters.sticker & ~filters.animation & ~filters.photo)
async def on_document(client, message):
    uid = message.from_user.id
    if state.user_payment_flow.get(uid, {}).get("awaiting_receipt"):
        return  # payment.py o'z handlerida chekni qabul qiladi
    doc = message.document
    await receive_file(client, message, doc, doc.file_name or f"file_{datetime.now():%Y%m%d_%H%M%S}")
@app.on_message(filters.photo)
async def on_photo(client, message):
    # Skip if user is trying to contact admin or admin is replying
    uid = message.from_user.id
    if state.user_payment_flow.get(uid, {}).get("awaiting_receipt"):
        return  # payment.py o'z handlerida chekni qabul qiladi
    if uid == ADMIN_ID and ADMIN_ID in state.admin_reply_to:
        await _handle_admin_reply_media(client, message)
        return
    await receive_file(client, message, message.photo, f"photo_{datetime.now():%Y%m%d_%H%M%S}.jpg")

@app.on_message(filters.video)
async def on_video(client, message):
    uid = message.from_user.id
    if uid == ADMIN_ID and ADMIN_ID in state.admin_reply_to:
        await _handle_admin_reply_media(client, message)
        return
    v = message.video
    await receive_file(client, message, v, v.file_name or f"video_{datetime.now():%Y%m%d_%H%M%S}.mp4")

@app.on_message(filters.audio)
async def on_audio(client, message):
    a = message.audio
    await receive_file(client, message, a, a.file_name or f"audio_{datetime.now():%Y%m%d_%H%M%S}.mp3")

@app.on_message(filters.voice)
async def on_voice(client, message):
    await receive_file(client, message, message.voice, f"voice_{datetime.now():%Y%m%d_%H%M%S}.ogg")

@app.on_message(filters.video_note)
async def on_video_note(client, message):
    await receive_file(client, message, message.video_note, f"videonote_{datetime.now():%Y%m%d_%H%M%S}.mp4")

@app.on_message(filters.sticker)
async def on_sticker_msg(client, message):
    await receive_file(client, message, message.sticker, f"sticker_{datetime.now():%Y%m%d_%H%M%S}.webp")

@app.on_message(filters.animation)
async def on_animation(client, message):
    g = message.animation
    await receive_file(client, message, g, g.file_name or f"gif_{datetime.now():%Y%m%d_%H%M%S}.gif")
# ... qolgan media handlerlar o'zgarishsiz(qo'shdim)
