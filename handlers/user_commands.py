from datetime import datetime
import asyncio

from pyrogram import Client, filters, enums
from pyrogram.types import Message, ChatJoinRequest, InlineKeyboardMarkup, InlineKeyboardButton

import database
import state
from config import ADMIN_ID
from bot_instance import app
from texts import TEXTS, tx
from keyboards import main_keyboard
from helpers import safe_delete, send_sticker
from subscription import gate_check, check_subscription

# ════════════════════════════════════════════════════════════
#  /start buyrug'i
# ════════════════════════════════════════════════════════════
@app.on_message(filters.command("start"))
async def cmd_start(client, message):
    uid = message.from_user.id
    await safe_delete(message)

    if database.is_banned(uid):
        return

    lang = database.get_lang(uid)

    if lang is not None:
        # 1. AGAR TIL OLDIN TANLANGAN BO'LSA: To'g'ridan-to'g'ri Welcome xabarini chiqaramiz
        name = message.from_user.first_name or "Foydalanuvchi"

        # Eski welcome xabarini tozalaymiz
        old_wm = state.user_welcome_msg.pop(uid, None)
        await safe_delete(old_wm)

        sent = await client.send_message(
            message.chat.id,
            tx(uid, "welcome", name=name),
            parse_mode=enums.ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton(TEXTS[lang]["change_lang"], callback_data="change_lang")
            ]]),
        )
        state.user_welcome_msg[uid] = sent
        await send_sticker(client, message.chat.id, "start")

        # Pastdagi asosiy menyu klaviaturasini chiqarish
        await client.send_message(
            message.chat.id, "👇",
            reply_markup=main_keyboard(uid),
        )

        # Kanallarni tekshirish (majburiy obuna)
        if state.required_channels:
            await gate_check(client, uid, message.chat.id, lang)

    else:
        # 2. AGAR TIL TANLANMAGAN BO'LSA (Birinchi marta kirganda): Til tanlash tugmalari chiqadi
        sent = await client.send_message(
            message.chat.id,
            "🌐 Tilni tanlang / Choose language:",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🇺🇿 O'zbek", callback_data="setlang_uz"),
                InlineKeyboardButton("🇬🇧 English", callback_data="setlang_en"),
            ]]),
        )
        state.user_welcome_msg[uid] = sent

# ════════════════════════════════════════════════════════════
#  /language buyrug'i (Tilni xohlagan paytda o'zgartirish)
# ════════════════════════════════════════════════════════════
@app.on_message(filters.command(["language", "lang"]) & filters.private)
async def cmd_change_lang(client, message: Message):
    uid = message.from_user.id
    await safe_delete(message)

    if database.is_banned(uid):
        return

    await client.send_message(
        message.chat.id,
        "🌐 Yangi tilni tanlang / Choose a new language:",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("🇺🇿 O'zbek", callback_data="setlang_uz"),
            InlineKeyboardButton("🇬🇧 English", callback_data="setlang_en"),
        ]]),
    )

@app.on_message(filters.forwarded & filters.user(ADMIN_ID))
async def on_forwarded(client, message):
    # Faqat kanaldan forward qilingan bo'lsa
    if message.forward_from_chat and message.forward_from_chat.type == enums.ChatType.CHANNEL:
        chat = message.forward_from_chat
        title = chat.title or str(chat.id)
        username = chat.username or ""
        chat_id = chat.id

        # Agar allaqachon qo'shilgan bo'lsa
        if chat_id in state.required_channels:
            await message.reply("Bu kanal allaqachon qo‘shilgan.")
            return

        if not username:
            # Maxfiy kanal (username yo'q)
            database.add_channel(chat_id, title, is_private=1)
            state.awaiting_invite_link[chat_id] = ADMIN_ID
            await message.reply(
                f"✅ Maxfiy kanal qo‘shildi: *{title}*\n"
                f"Endi menga foydalanuvchilarga ko‘rinadigan **taklif havolasini** yuboring (masalan, `https://t.me/+xxx`).",
                parse_mode=enums.ParseMode.MARKDOWN
            )
        else:
            # Publik kanal (username bor) – avtomatik qo‘shamiz
            database.add_channel(chat_id, title, username=username)
            await message.reply(
                f"✅ Publik kanal qo‘shildi: *{title}*\n"
                f"🔗 @{username}",
                parse_mode=enums.ParseMode.MARKDOWN
            )
    else:
        await message.reply("Iltimos, faqat kanaldan forward qilingan post yuboring.")

@app.on_chat_join_request()
async def handle_join_request(client: Client, join_request: ChatJoinRequest):
    # Ma'lumotlar bazasiga ulanish
    c = database.get_db()

    c.execute("""
        INSERT OR IGNORE INTO join_requests(telegram_id, chat_id, created_at)
        VALUES(?,?,?)
    """, (
        join_request.from_user.id,
        join_request.chat.id,
        datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    ))
    c.commit()
    database.db_sync()
# ════════════════════════════════════════════════════════════
#  TIL TANLASH
# ════════════════════════════════════════════════════════════
@app.on_callback_query(filters.create(lambda _, __, q: q.data.startswith("setlang_")))
async def cb_set_lang(client, call):
    uid  = call.from_user.id
    lang = call.data.split("_")[1]
    database.upsert_user(call.from_user, lang)
    await safe_delete(call.message)
    state.user_welcome_msg.pop(uid, None)
    name = call.from_user.first_name or "Foydalanuvchi"
    sent = await client.send_message(
        call.message.chat.id,
        tx(uid, "welcome", name=name),
        parse_mode=enums.ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton(TEXTS[lang]["change_lang"], callback_data="change_lang")
        ]]),
    )
    state.user_welcome_msg[uid] = sent
    await send_sticker(client, call.message.chat.id, "start")
    await call.answer(TEXTS[lang]["lang_set"])
    # Send main keyboard
    await client.send_message(
        call.message.chat.id, "👇",
        reply_markup=main_keyboard(uid),
    )
    if state.required_channels:
        await gate_check(client, uid, call.message.chat.id, lang)



@app.on_callback_query(filters.create(lambda _, __, q: q.data == "change_lang"))
async def cb_change_lang(client, call):
    uid = call.from_user.id
    await safe_delete(call.message)
    sent = await client.send_message(
        call.message.chat.id,
        TEXTS["uz"]["choose_lang"],
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("🇺🇿 O'zbek", callback_data="setlang_uz"),
            InlineKeyboardButton("🇬🇧 English", callback_data="setlang_en"),
        ]]),
    )
    state.user_welcome_msg[uid] = sent
    await call.answer()

# ════════════════════════════════════════════════════════════
#  OBUNA TEKSHIRISH
# ════════════════════════════════════════════════════════════
@app.on_callback_query(filters.create(lambda _, __, q: q.data == "check_join"))
async def cb_check_join(client, call):
    uid  = call.from_user.id
    lang = database.get_lang(uid) or "uz"
    not_joined = await check_subscription(client, uid)
    if not not_joined:
        await call.answer(TEXTS[lang]["join_ok"], show_alert=True)
        await safe_delete(call.message)
    else:
        await call.answer(TEXTS[lang]["join_fail"], show_alert=True)

# ════════════════════════════════════════════════════════════
#  "📦 ZIP YASASH" TUGMASI (qo'lda zip yasash)
# ════════════════════════════════════════════════════════════
@app.on_callback_query(filters.create(lambda _, __, q: q.data == "zip_now"))
async def cb_zip_now(client, call):
    uid     = call.from_user.id
    chat_id = call.message.chat.id
    await call.answer()

    from fs_utils import file_count, make_zip_name
    from batch import cancel_task
    from zip_ops import create_and_send_zip

    if file_count(uid) == 0:
        return

    # Pending avto-zip taymerini bekor qilamiz -- qo'lda bosilgani uchun
    await cancel_task(state.user_auto_zip, uid)

    sm = state.user_status_msg.pop(uid, None)
    await safe_delete(sm)

    default_name = make_zip_name(call.from_user)
    ask = await client.send_message(
        chat_id,
        tx(uid, "ask_zip_name", default=default_name)
        if "ask_zip_name" in TEXTS.get(database.get_lang(uid) or "uz", {})
        else f"📝 ZIP uchun nom yuboring (30 soniya)\n_Yubormasangiz: `{default_name}`_",
        parse_mode=enums.ParseMode.MARKDOWN,
    )
    state.user_zip_naming[uid] = {"chat_id": chat_id, "default_name": default_name, "ask_msg": ask}

    async def _zip_naming_timeout():
        await asyncio.sleep(30)
        info = state.user_zip_naming.get(uid)
        if info is None:
            return  # foydalanuvchi allaqachon nom yubordi (text_router hal qildi)
        state.user_zip_naming.pop(uid, None)
        await safe_delete(info.get("ask_msg", ask))
        if file_count(uid) > 0:
            await create_and_send_zip(client, info["chat_id"], uid, info["default_name"])

    asyncio.ensure_future(_zip_naming_timeout())
