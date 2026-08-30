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

from pyrogram import filters, enums, ContinuePropagation
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
#  BOSHLASH (text_router.py dan chaqiriladi -- "💬 Fikr-mulohaza" tugmasi
#  bosilganda, umumiy matn-router bilan to'qnashmaslik uchun)
#  Endi avval "Kanalga" / "Adminga" tanlanadi:
#   - Kanalga: eski mantiq (link filtri, kunlik limit, faqat matn)
#   - Adminga: cheklovsiz -- matn, rasm, video, hujjat, silka -- hammasi
#     to'g'ridan-to'g'ri adminga yuboriladi, chunki bu ommaviy post emas,
#     shaxsiy xabar.
# ════════════════════════════════════════════════════════════
async def start_feedback(client, message):
    uid = message.from_user.id
    lang = database.get_lang(uid) or "uz"

    has_channel = bool(database.get_feedback_channel_id())
    if not has_channel and uid == ADMIN_ID:
        # Kanal ulanmagan bo'lsa ham, admin o'ziga o'zi yozmaydi -- tugma sokin
        return

    buttons = []
    if has_channel:
        buttons.append([InlineKeyboardButton(tx(uid, "fb_target_channel"), callback_data="fb_target:channel")])
    buttons.append([InlineKeyboardButton(tx(uid, "fb_target_admin"), callback_data="fb_target:admin")])
    buttons.append([InlineKeyboardButton(tx(uid, "btn_cancel"), callback_data="fb_cancel")])

    ask = await message.reply(tx(uid, "fb_choose_target"), reply_markup=InlineKeyboardMarkup(buttons))
    state.user_feedback_flow[uid] = {"chat_id": message.chat.id, "ask_msg": ask, "stage": "choose_target"}


@app.on_callback_query(filters.create(lambda _, __, q: q.data.startswith("fb_target:")))
async def choose_feedback_target(client, call):
    uid = call.from_user.id
    target = call.data.split(":")[1]  # "channel" yoki "admin"
    lang = database.get_lang(uid) or "uz"

    if target == "channel":
        if uid != ADMIN_ID:
            if database.is_feedback_banned(uid):
                await call.answer()
                await call.message.edit_text(tx(uid, "feedback_banned"))
                return
            allowed, next_allowed = database.check_feedback_slot(uid)
            if not allowed:
                await call.answer()
                await call.message.edit_text(
                    tx(uid, "feedback_rate_limited", when=_format_next_allowed(next_allowed)),
                    parse_mode=enums.ParseMode.MARKDOWN,
                )
                return

    await call.answer()
    ask_text = tx(uid, "feedback_ask") if target == "channel" else tx(uid, "feedback_ask_admin")
    await call.message.edit_text(
        ask_text,
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(tx(uid, "btn_cancel"), callback_data="fb_cancel")]]),
    )
    state.user_feedback_flow[uid] = {
        "chat_id": call.message.chat.id, "ask_msg": call.message,
        "stage": "awaiting_content", "target": target,
    }


@app.on_callback_query(filters.create(lambda _, __, q: q.data == "fb_cancel"))
async def cancel_feedback(client, call):
    uid = call.from_user.id
    state.user_feedback_flow.pop(uid, None)
    await call.answer()
    await safe_delete(call.message)


# Adminga yuborilayotgan xabar matn bo'lmasligi ham mumkin (rasm, video,
# hujjat, silka -- bularning barchasi ochiq). media.py dagi umumiy
# fayl-qabul qiluvchi handlerlardan OLDIN ishlashi shart, shuning uchun
# group=-1 -- xuddi payment.py dagi chek qabul qilish uslubida.
@app.on_message(filters.private & ~filters.text, group=-1)
async def receive_feedback_media(client, message):
    uid = message.from_user.id
    flow = state.user_feedback_flow.get(uid)
    if not flow or flow.get("stage") != "awaiting_content" or flow.get("target") != "admin":
        raise ContinuePropagation  # feedback (admin) jarayonida emas -- keyingi handlerlarga o'tkazish

    await _forward_to_admin(client, message, flow)


# ════════════════════════════════════════════════════════════
#  MATN QABUL QILISH (text_router.py dan chaqiriladi)
# ════════════════════════════════════════════════════════════
async def handle_feedback_text(client, message) -> bool:
    """text_router.py ning umumiy matn handleridan chaqiriladi.
    True qaytarsa, xabar feedback sifatida ishlangan hisoblanadi."""
    uid = message.from_user.id
    flow = state.user_feedback_flow.get(uid)
    if not flow or flow.get("stage") != "awaiting_content":
        return False

    if flow.get("target") == "admin":
        return await _forward_to_admin(client, message, flow)
    return await _post_to_channel(client, message, flow)


async def _forward_to_admin(client, message, flow) -> bool:
    """Adminga cheklovsiz yuborish -- matn, rasm, video, hujjat, silka,
    hammasi ochiq. Kunlik limit va link filtri qo'llanmaydi, chunki bu
    ommaviy post emas, shaxsiy xabar."""
    uid = message.from_user.id
    state.user_feedback_flow.pop(uid, None)

    sender = _sender_label(message.from_user)
    username = f"@{message.from_user.username}" if message.from_user.username else "—"
    header = f"✉️ *Shaxsiy xabar*\n\n👤 {sender} ({username})\n🆔 `{uid}`\n\n"

    try:
        if message.text:
            await client.send_message(ADMIN_ID, header + escape(message.text), parse_mode=enums.ParseMode.MARKDOWN)
        else:
            # Media (rasm/video/hujjat/boshqa) bo'lsa -- forward qilib, ustidan
            # kimdan ekanini yozib qo'yamiz (forward foydalanuvchi ma'lumotini
            # ko'rsatib qo'yishi mumkin bo'lgani uchun, header alohida yuboriladi)
            await client.send_message(ADMIN_ID, header, parse_mode=enums.ParseMode.MARKDOWN)
            await message.forward(ADMIN_ID)
        await message.reply(tx(uid, "feedback_thanks_admin"))
    except Exception:
        await message.reply(tx(uid, "feedback_failed"))

    return True


async def _post_to_channel(client, message, flow) -> bool:
    """Kanalga postlash -- eski mantiq: faqat matn, link filtri, kunlik limit."""
    uid = message.from_user.id
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
