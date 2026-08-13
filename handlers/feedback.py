"""
════════════════════════════════════════════════════════════
 FIKR-MULOHAZA (FEEDBACK)
 Foydalanuvchi "💬 Fikr-mulohaza" tugmasini bosadi -> matn yozadi ->
 (link/reklama bloklanadi) -> admin ulagan kanalga postlanadi,
 👍/👎 tugmalari bilan. Kuniga 1 marta yozish mumkin.
════════════════════════════════════════════════════════════
"""
import re
import asyncio
from html import escape

from pyrogram import filters, enums
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton

import database
import state
from config import ADMIN_ID
from bot_instance import app, admin_filter
from texts import tx
from helpers import safe_delete

# URL (http/https/www.), Telegram t.me/ link va @mentionlarni bloklaydi --
# shu orqali funksiya bepul reklama/spam kanaliga aylanmasin
_LINK_PATTERN = re.compile(
    r"(https?://|www\.|t\.me/|telegram\.me/|@[a-zA-Z0-9_]{4,})",
    re.IGNORECASE,
)


def _contains_link(text: str) -> bool:
    return bool(_LINK_PATTERN.search(text))


def _sender_label(user) -> str:
    """Faqat ism -- @username atayin ko'rsatilmaydi, shunda odamlar
    o'z fikrini erkin yozadi, handle esa hech kimga oshkor bo'lmaydi."""
    name = user.first_name or ""
    if user.last_name:
        name += f" {user.last_name}"
    return escape(name.strip() or "—")


def _format_next_allowed(next_allowed) -> str:
    return next_allowed.strftime("%d.%m.%Y %H:%M")


def _vote_kb(post_id: int, upvotes: int, downvotes: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton(f"👍 {upvotes}", callback_data=f"fbvote:{post_id}:up"),
        InlineKeyboardButton(f"👎 {downvotes}", callback_data=f"fbvote:{post_id}:down"),
    ]])


# ════════════════════════════════════════════════════════════
#  BOSHLASH
# ════════════════════════════════════════════════════════════
# ════════════════════════════════════════════════════════════
#  BOSHLASH (text_router.py dan chaqiriladi -- "💬 Fikr-mulohaza" tugmasi
#  bosilganda, umumiy matn-router bilan to'qnashmaslik uchun)
# ════════════════════════════════════════════════════════════
async def start_feedback(client, message):
    uid = message.from_user.id
    lang = database.get_lang(uid) or "uz"

    if not database.get_feedback_channel_id():
        return  # kanal ulanmagan -- tugma "ishlamaydi" (sokin)

    if uid != ADMIN_ID:
        if database.is_feedback_banned(uid):
            await message.reply(tx(uid, "feedback_banned"))
            return
        allowed, next_allowed = database.check_feedback_slot(uid)
        if not allowed:
            await message.reply(tx(uid, "feedback_rate_limited", when=_format_next_allowed(next_allowed)),
                                 parse_mode=enums.ParseMode.MARKDOWN)
            return

    ask = await message.reply(
        tx(uid, "feedback_ask"),
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(tx(uid, "btn_cancel"), callback_data="fb_cancel")]]),
    )
    state.user_feedback_flow[uid] = {"chat_id": message.chat.id, "ask_msg": ask}


@app.on_callback_query(filters.create(lambda _, __, q: q.data == "fb_cancel"))
async def cancel_feedback(client, call):
    uid = call.from_user.id
    state.user_feedback_flow.pop(uid, None)
    await call.answer()
    await safe_delete(call.message)


# ════════════════════════════════════════════════════════════
#  MATN QABUL QILISH (text_router.py dan chaqiriladi)
# ════════════════════════════════════════════════════════════
async def handle_feedback_text(client, message) -> bool:
    """text_router.py ning umumiy matn handleridan chaqiriladi.
    True qaytarsa, xabar feedback sifatida ishlangan hisoblanadi."""
    uid = message.from_user.id
    if uid not in state.user_feedback_flow:
        return False

    lang = database.get_lang(uid) or "uz"
    text = (message.text or "").strip()

    if not text:
        await message.reply(tx(uid, "feedback_ask"))
        return True

    if _contains_link(text):
        await message.reply(tx(uid, "feedback_link_blocked"))
        return True

    # Yuborishdan oldin qayta tekshiramiz -- shu orada limit tugagan yoki
    # admin ban qilgan bo'lishi mumkin
    if uid != ADMIN_ID:
        if database.is_feedback_banned(uid):
            state.user_feedback_flow.pop(uid, None)
            await message.reply(tx(uid, "feedback_banned"))
            return True
        allowed, next_allowed = database.check_feedback_slot(uid)
        if not allowed:
            state.user_feedback_flow.pop(uid, None)
            await message.reply(tx(uid, "feedback_rate_limited", when=_format_next_allowed(next_allowed)),
                                 parse_mode=enums.ParseMode.MARKDOWN)
            return True

    state.user_feedback_flow.pop(uid, None)

    channel = database.normalize_feedback_channel(database.get_feedback_channel_id())
    posted_message = None
    if channel:
        try:
            channel_text = tx(
                uid, "feedback_channel_post",
                sender=_sender_label(message.from_user), user_id=uid, text=escape(text),
            )
            posted_message = await client.send_message(channel, channel_text, parse_mode=enums.ParseMode.MARKDOWN)
        except Exception:
            posted_message = None

    if posted_message:
        if uid != ADMIN_ID:
            database.mark_feedback_sent(uid)
        post_id = database.create_feedback_post(uid, posted_message.id)
        try:
            await client.edit_message_reply_markup(
                channel, posted_message.id, reply_markup=_vote_kb(post_id, 0, 0),
            )
        except Exception:
            pass
        await message.reply(tx(uid, "feedback_thanks"))
    else:
        # Postlanmadi -- limit ishlatilmaydi, foydalanuvchi jazolanmasin
        await message.reply(tx(uid, "feedback_failed"))

    return True


# ════════════════════════════════════════════════════════════
#  OVOZ BERISH (kanaldagi 👍/👎 tugmalari)
# ════════════════════════════════════════════════════════════
@app.on_callback_query(filters.create(lambda _, __, q: q.data.startswith("fbvote:")))
async def handle_feedback_vote(client, call):
    _, post_id_str, direction = call.data.split(":")
    result = database.apply_feedback_vote(int(post_id_str), call.from_user.id, is_up=(direction == "up"))
    if not result:
        await call.answer()
        return

    _id, author_id, channel_message_id, upvotes, downvotes = result
    await call.answer()
    try:
        await call.message.edit_reply_markup(reply_markup=_vote_kb(_id, upvotes, downvotes))
    except Exception:
        pass  # "message is not modified" -- ovoz o'zgarmagan, muammo emas


# ════════════════════════════════════════════════════════════
#  ADMIN: KANAL SOZLASH, BAN, LIMIT RESET
# ════════════════════════════════════════════════════════════
@app.on_callback_query(admin_filter & filters.create(lambda _, __, q: q.data == "adm_feedback_menu"))
async def adm_feedback_menu(client, call):
    channel = database.get_feedback_channel_id()
    hours = database.get_feedback_cooldown_hours()
    text = (
        f"💬 *Fikr-mulohaza sozlamalari*\n\n"
        f"📡 Kanal: `{channel or 'ulanmagan'}`\n"
        f"⏳ Kunlik limit: *{hours} soatda 1 marta*"
    )
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📡 Kanalni ulash/o'zgartirish", callback_data="adm_fb_set_channel")],
        [InlineKeyboardButton("❌ Kanalni uzish", callback_data="adm_fb_clear_channel")],
        [InlineKeyboardButton("⏳ Limitni o'zgartirish (soat)", callback_data="adm_fb_set_cooldown")],
        [InlineKeyboardButton("🚫 Foydalanuvchini cheklash", callback_data="adm_fb_ban_user"),
         InlineKeyboardButton("✅ Cheklovni olish", callback_data="adm_fb_unban_user")],
        [InlineKeyboardButton("🔄 Limitni reset qilish", callback_data="adm_fb_reset_user")],
    ])
    await call.message.reply(text, parse_mode=enums.ParseMode.MARKDOWN, reply_markup=kb)
    await call.answer()


@app.on_callback_query(admin_filter & filters.create(lambda _, __, q: q.data == "adm_fb_set_channel"))
async def adm_fb_set_channel(client, call):
    state.waiting_for_user_id[ADMIN_ID] = "set_feedback_channel"
    await call.message.reply(
        "📡 *Kanal ID yoki @username yuboring*\n\n"
        "Bot shu kanalda admin bo'lishi shart.\nMisol: `@mening_kanalim` yoki `-1001234567890`",
        parse_mode=enums.ParseMode.MARKDOWN,
    )
    await call.answer()


@app.on_callback_query(admin_filter & filters.create(lambda _, __, q: q.data == "adm_fb_clear_channel"))
async def adm_fb_clear_channel(client, call):
    database.set_feedback_channel_id(None)
    await call.answer("Kanal uzildi.")
    await call.message.reply("❌ Fikr-mulohaza kanali uzildi.")


@app.on_callback_query(admin_filter & filters.create(lambda _, __, q: q.data == "adm_fb_set_cooldown"))
async def adm_fb_set_cooldown(client, call):
    state.waiting_for_user_id[ADMIN_ID] = "set_feedback_cooldown"
    await call.message.reply("⏳ Necha soatda 1 marta yozish mumkin bo'lsin? (masalan: `24`)")
    await call.answer()


@app.on_callback_query(admin_filter & filters.create(lambda _, __, q: q.data == "adm_fb_ban_user"))
async def adm_fb_ban_user(client, call):
    state.waiting_for_user_id[ADMIN_ID] = "feedback_ban"
    await call.message.reply("🚫 Cheklanadigan USER\\_ID yuboring:", parse_mode=enums.ParseMode.MARKDOWN)
    await call.answer()


@app.on_callback_query(admin_filter & filters.create(lambda _, __, q: q.data == "adm_fb_unban_user"))
async def adm_fb_unban_user(client, call):
    state.waiting_for_user_id[ADMIN_ID] = "feedback_unban"
    await call.message.reply("✅ Cheklovi olinadigan USER\\_ID yuboring:", parse_mode=enums.ParseMode.MARKDOWN)
    await call.answer()


@app.on_callback_query(admin_filter & filters.create(lambda _, __, q: q.data == "adm_fb_reset_user"))
async def adm_fb_reset_user(client, call):
    state.waiting_for_user_id[ADMIN_ID] = "feedback_reset"
    await call.message.reply("🔄 Limiti reset qilinadigan USER\\_ID yuboring:", parse_mode=enums.ParseMode.MARKDOWN)
    await call.answer()


# Admin matn-kiritish oqimi: text_router.py dagi waiting_for_user_id
# mexanizmi orqali chaqiriladi (handle_admin_feedback_action)
async def handle_admin_feedback_action(client, message, action: str, raw: str) -> bool:
    if action == "set_feedback_channel":
        channel = database.normalize_feedback_channel(raw)
        if not channel:
            await message.reply("❌ Noto'g'ri format.")
            return True
        try:
            await client.send_message(channel, "✅ Fikr-mulohaza kanali ulandi.")
        except Exception:
            await message.reply("⚠️ Botga shu kanalda yozish huquqi yo'q. Botni admin qiling va qayta urinib ko'ring.")
            return True
        database.set_feedback_channel_id(str(raw).strip())
        await message.reply(f"✅ Kanal ulandi: `{raw}`", parse_mode=enums.ParseMode.MARKDOWN)
        return True

    if action == "set_feedback_cooldown":
        try:
            hours = int(raw)
            database.set_feedback_cooldown_hours(hours)
            await message.reply(f"✅ Limit: {hours} soatda 1 marta.")
        except Exception:
            await message.reply("❌ Butun son yuboring.")
        return True

    if action == "feedback_ban":
        try:
            target_id = int(raw)
            database.set_feedback_banned(target_id, True)
            await message.reply(f"✅ `{target_id}` fikr-mulohaza yozishdan cheklandi.", parse_mode=enums.ParseMode.MARKDOWN)
        except Exception:
            await message.reply("❌ Noto'g'ri ID.")
        return True

    if action == "feedback_unban":
        try:
            target_id = int(raw)
            database.set_feedback_banned(target_id, False)
            await message.reply(f"✅ `{target_id}` cheklovi olib tashlandi.", parse_mode=enums.ParseMode.MARKDOWN)
        except Exception:
            await message.reply("❌ Noto'g'ri ID.")
        return True

    if action == "feedback_reset":
        try:
            target_id = int(raw)
            database.reset_feedback_limit(target_id)
            await message.reply(f"✅ `{target_id}` limiti reset qilindi.", parse_mode=enums.ParseMode.MARKDOWN)
        except Exception:
            await message.reply("❌ Noto'g'ri ID.")
        return True

    return False
