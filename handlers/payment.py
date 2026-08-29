"""
════════════════════════════════════════════════════════════
 PREMIUM TO'LOV OQIMI (karta / kripto)
 Foydalanuvchi: "💳 30 kunlik Premium olish" -> usul tanlash ->
 karta yoki kripto tafsilotlari -> "To'ladim" -> chek yuborish ->
 admin ko'rib chiqadi -> tasdiqlasa Premium avtomatik yoqiladi.
════════════════════════════════════════════════════════════
"""
import asyncio

from pyrogram import filters, enums, ContinuePropagation
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton

import database
import state
from config import ADMIN_ID, PREMIUM_PRICE_UZS, PREMIUM_PRICE_USDT
from bot_instance import app, admin_filter
from texts import tx
from helpers import safe_delete


def _cancel_kb(uid: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton(tx(uid, "btn_cancel"), callback_data="pay_cancel")]])


# ════════════════════════════════════════════════════════════
#  BOSHLASH
# ════════════════════════════════════════════════════════════
@app.on_callback_query(filters.create(lambda _, __, q: q.data == "topup:start"))
async def start_topup(client, call):
    uid = call.from_user.id
    await call.answer()
    markup = InlineKeyboardMarkup([
        [InlineKeyboardButton(tx(uid, "btn_card"), callback_data="pay_method:card")],
        [InlineKeyboardButton(tx(uid, "btn_crypto"), callback_data="pay_method:crypto")],
        [InlineKeyboardButton(tx(uid, "btn_cancel"), callback_data="pay_cancel")],
    ])
    await client.send_message(call.message.chat.id, tx(uid, "choose_payment_method"), reply_markup=markup)


@app.on_callback_query(filters.create(lambda _, __, q: q.data == "pay_cancel"))
async def cancel_payment(client, call):
    uid = call.from_user.id
    state.user_payment_flow.pop(uid, None)
    await call.answer()
    await safe_delete(call.message)


# ════════════════════════════════════════════════════════════
#  KARTA ORQALI
# ════════════════════════════════════════════════════════════
@app.on_callback_query(filters.create(lambda _, __, q: q.data == "pay_method:card"))
async def choose_card_method(client, call):
    uid = call.from_user.id
    cards = database.list_active_cards()
    await call.answer()
    if not cards:
        await call.message.edit_text(tx(uid, "no_active_cards"))
        return
    state.user_payment_flow[uid] = {"method": "card"}
    buttons = [[InlineKeyboardButton(f"{c[1]} •• {c[2][-4:]}", callback_data=f"pay_card:{c[0]}")] for c in cards]
    buttons.append([InlineKeyboardButton(tx(uid, "btn_cancel"), callback_data="pay_cancel")])
    await call.message.edit_text(tx(uid, "choose_card"), reply_markup=InlineKeyboardMarkup(buttons))


@app.on_callback_query(filters.create(lambda _, __, q: q.data.startswith("pay_card:")))
async def choose_specific_card(client, call):
    uid = call.from_user.id
    card_id = int(call.data.split(":")[1])
    card = database.get_card(card_id)
    await call.answer()
    if not card:
        return

    _id, bank, number, owner = card
    method_detail = f"{bank} •• {number[-4:]}"
    state.user_payment_flow[uid] = {
        "method": "card", "method_detail": method_detail,
        "amount": str(PREMIUM_PRICE_UZS), "currency": "so'm",
    }
    await call.message.edit_text(
        tx(uid, "card_details", bank=bank, number=number, owner=owner, amount=PREMIUM_PRICE_UZS),
        parse_mode=enums.ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton(tx(uid, "btn_i_paid"), callback_data="i_paid")],
            [InlineKeyboardButton(tx(uid, "btn_cancel"), callback_data="pay_cancel")],
        ]),
    )


# ════════════════════════════════════════════════════════════
#  KRIPTO ORQALI
# ════════════════════════════════════════════════════════════
@app.on_callback_query(filters.create(lambda _, __, q: q.data == "pay_method:crypto"))
async def choose_crypto_method(client, call):
    uid = call.from_user.id
    tokens = database.list_active_tokens()
    await call.answer()
    if not tokens:
        await call.message.edit_text(tx(uid, "no_active_tokens"))
        return
    state.user_payment_flow[uid] = {"method": "crypto"}
    buttons = [[InlineKeyboardButton(t[1], callback_data=f"pay_token:{t[0]}")] for t in tokens]
    buttons.append([InlineKeyboardButton(tx(uid, "btn_cancel"), callback_data="pay_cancel")])
    await call.message.edit_text(tx(uid, "choose_token"), reply_markup=InlineKeyboardMarkup(buttons))


@app.on_callback_query(filters.create(lambda _, __, q: q.data.startswith("pay_token:")))
async def choose_specific_token(client, call):
    uid = call.from_user.id
    token_id = int(call.data.split(":")[1])
    token = database.get_token(token_id)
    await call.answer()
    if not token:
        return

    networks = database.list_networks_for_token(token_id)
    if not networks:
        await call.message.edit_text(tx(uid, "no_active_networks"))
        return

    flow = state.user_payment_flow.get(uid, {})
    flow["token_name"] = token[1]
    state.user_payment_flow[uid] = flow

    buttons = [[InlineKeyboardButton(n[2], callback_data=f"pay_network:{n[0]}")] for n in networks]
    buttons.append([InlineKeyboardButton(tx(uid, "btn_cancel"), callback_data="pay_cancel")])
    await call.message.edit_text(
        tx(uid, "choose_network", token=token[1]),
        parse_mode=enums.ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup(buttons),
    )


@app.on_callback_query(filters.create(lambda _, __, q: q.data.startswith("pay_network:")))
async def choose_specific_network(client, call):
    uid = call.from_user.id
    network_id = int(call.data.split(":")[1])
    network = database.get_network(network_id)
    await call.answer()
    if not network:
        return

    _id, token_id, net_name, address = network
    flow = state.user_payment_flow.get(uid, {})
    token_name = flow.get("token_name", "")
    method_detail = f"{token_name} / {net_name}"
    flow.update({
        "method": "crypto", "method_detail": method_detail,
        "amount": str(PREMIUM_PRICE_USDT), "currency": "USDT",
    })
    state.user_payment_flow[uid] = flow

    text_key = "network_details_usdt" if token_name.strip().upper() == "USDT" else "network_details_other"
    await call.message.edit_text(
        tx(uid, text_key, token=token_name, network=net_name, address=address, amount=PREMIUM_PRICE_USDT),
        parse_mode=enums.ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton(tx(uid, "btn_i_paid"), callback_data="i_paid")],
            [InlineKeyboardButton(tx(uid, "btn_cancel"), callback_data="pay_cancel")],
        ]),
    )


# ════════════════════════════════════════════════════════════
#  "TO'LADIM" -> CHEK SO'RASH
# ════════════════════════════════════════════════════════════
@app.on_callback_query(filters.create(lambda _, __, q: q.data == "i_paid"))
async def request_receipt(client, call):
    uid = call.from_user.id
    await call.answer()
    if uid not in state.user_payment_flow or "method_detail" not in state.user_payment_flow[uid]:
        return
    ask = await client.send_message(call.message.chat.id, tx(uid, "upload_receipt"), reply_markup=_cancel_kb(uid))
    flow = state.user_payment_flow[uid]
    flow["awaiting_receipt"] = True
    flow["chat_id"] = call.message.chat.id
    flow["ask_msg"] = ask


# Chek qabul qilish -- rasm yoki PDF (media.py dagi umumiy fayl-qabul qiluvchi
# handlerlardan OLDIN ishlashi shart, shuning uchun group=-1 -- past raqam ustuvor)
@app.on_message((filters.photo | filters.document) & filters.private, group=-1)
async def receive_receipt(client, message):
    uid = message.from_user.id
    flow = state.user_payment_flow.get(uid)
    if not flow or not flow.get("awaiting_receipt"):
        raise ContinuePropagation  # to'lov jarayonida emas -- keyingi handlerlarga o'tkazish

    if message.photo:
        file_id = message.photo.file_id
        receipt_type = "photo"
    elif message.document and (
        (message.document.mime_type == "application/pdf")
        or (message.document.file_name or "").lower().endswith(".pdf")
    ):
        file_id = message.document.file_id
        receipt_type = "document"
    else:
        await message.reply(tx(uid, "invalid_receipt"))
        message.stop_propagation()
        return

    await safe_delete(flow.get("ask_msg"))

    payment_id = database.create_pending_payment(
        user_id=uid,
        method=flow["method"],
        method_detail=flow["method_detail"],
        amount=flow["amount"],
        currency=flow["currency"],
        receipt_file_id=file_id,
        receipt_type=receipt_type,
    )

    state.user_payment_flow.pop(uid, None)
    await client.send_message(message.chat.id, tx(uid, "payment_submitted", payment_id=payment_id))

    await _notify_admin_of_payment(client, payment_id, message.from_user)

    # Chek muvaffaqiyatli qabul qilindi -- xabar bu yerda TO'XTASHI kerak.
    # group=-1 faqat TARTIBni belgilaydi (bu handler boshqalardan oldin
    # ishlaydi), lekin funksiya oddiy tugasa pyrogram xabarni baribir
    # keyingi guruhlarga (masalan media.py dagi umumiy fayl-qabul qiluvchi
    # handlerlarga) uzatishda davom etadi -- shuning uchun chek fayli
    # "yangi yuklangan fayl" sifatida ham qabul qilinib, ZIP navbatiga
    # tushib qolgan edi. stop_propagation() aynan shuni oldini oladi.
    message.stop_propagation()


async def _notify_admin_of_payment(client, payment_id: int, from_user):
    payment = database.get_payment(payment_id)
    if not payment:
        return
    _id, user_id, method, method_detail, amount, currency, receipt_file_id, receipt_type, status, created_at, _, _ = payment

    user_label = f"@{from_user.username}" if from_user.username else (from_user.first_name or str(user_id))
    caption = (
        f"🆕 *Yangi to'lov so'rovi* №{payment_id}\n\n"
        f"👤 {user_label} (`{user_id}`)\n"
        f"💳 Usul: {method_detail}\n"
        f"💰 Summa: {amount} {currency}\n"
        f"🕒 {created_at}"
    )
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Tasdiqlash", callback_data=f"adm_pay:approve:{payment_id}"),
        InlineKeyboardButton("❌ Bekor qilish", callback_data=f"adm_pay:reject:{payment_id}"),
    ]])
    try:
        if receipt_type == "photo":
            await client.send_photo(ADMIN_ID, receipt_file_id, caption=caption, reply_markup=kb, parse_mode=enums.ParseMode.MARKDOWN)
        else:
            await client.send_document(ADMIN_ID, receipt_file_id, caption=caption, reply_markup=kb, parse_mode=enums.ParseMode.MARKDOWN)
    except Exception:
        pass


# ════════════════════════════════════════════════════════════
#  ADMIN: TASDIQLASH / BEKOR QILISH
# ════════════════════════════════════════════════════════════
@app.on_callback_query(filters.create(lambda _, __, q: q.data.startswith("adm_pay:")))
async def resolve_payment_callback(client, call):
    if call.from_user.id != ADMIN_ID:
        return
    _, action, payment_id_str = call.data.split(":")
    payment_id = int(payment_id_str)
    approve = action == "approve"

    payment = database.resolve_payment(payment_id, approve, call.from_user.id)
    if not payment:
        await call.answer("Bu so'rov allaqachon ko'rib chiqilgan.", show_alert=True)
        return

    _id, user_id, method, method_detail, amount, currency, receipt_file_id, receipt_type, status, created_at, _, _ = payment

    result_text = (
        f"✅ To'lov №{payment_id} tasdiqlandi. Foydalanuvchiga Premium yoqildi."
        if approve else f"❌ To'lov №{payment_id} bekor qilindi."
    )
    try:
        if call.message.caption is not None:
            await call.message.edit_caption(result_text)
        else:
            await call.message.edit_text(result_text)
    except Exception:
        pass

    user_lang = database.get_lang(user_id) or "uz"
    try:
        if approve:
            database.apply_premium(user_id)
            await client.send_message(user_id, tx(user_id, "payment_approved_user"), parse_mode=enums.ParseMode.MARKDOWN)
        else:
            await client.send_message(user_id, tx(user_id, "payment_rejected_user", payment_id=payment_id), parse_mode=enums.ParseMode.MARKDOWN)
    except Exception:
        pass

    await call.answer()


# ════════════════════════════════════════════════════════════
#  ADMIN: TO'LOVLAR MENYUSI (kartalar, kripto, kutilayotgan so'rovlar)
# ════════════════════════════════════════════════════════════
def _payments_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("💳 Kartalar", callback_data="adm_cards_menu"),
         InlineKeyboardButton("🪙 Kripto", callback_data="adm_crypto_menu")],
        [InlineKeyboardButton("📥 Kutilayotgan to'lovlar", callback_data="adm_payments_queue")],
    ])


@app.on_callback_query(admin_filter & filters.create(lambda _, __, q: q.data == "adm_payments_menu"))
async def adm_payments_menu(client, call):
    pending = database.count_pending_payments()
    await call.message.reply(
        f"💳 *To'lovlar boshqaruvi*\n\n📥 Kutilayotgan so'rovlar: *{pending}*",
        parse_mode=enums.ParseMode.MARKDOWN,
        reply_markup=_payments_menu_kb(),
    )
    await call.answer()


# ── Kutilayotgan to'lovlar navbati ──
@app.on_callback_query(admin_filter & filters.create(lambda _, __, q: q.data == "adm_payments_queue"))
async def adm_payments_queue(client, call):
    await call.answer()
    await _show_next_payment(client, call.message.chat.id)


async def _show_next_payment(client, chat_id: int):
    payments = database.list_pending_payments(limit=1)
    if not payments:
        await client.send_message(chat_id, "📭 Hozircha kutilayotgan to'lov yo'q.")
        return
    payment = payments[0]
    _id, user_id, method, method_detail, amount, currency, receipt_file_id, receipt_type, status, created_at, _, _ = payment

    lang = database.get_lang(user_id) or "uz"
    name = None
    caption = (
        f"🆕 *To'lov so'rovi* №{_id}\n\n"
        f"👤 ID: `{user_id}`\n"
        f"💳 Usul: {method_detail}\n"
        f"💰 Summa: {amount} {currency}\n"
        f"🕒 {created_at}"
    )
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Tasdiqlash", callback_data=f"adm_pay:approve:{_id}"),
        InlineKeyboardButton("❌ Bekor qilish", callback_data=f"adm_pay:reject:{_id}"),
    ]])
    if receipt_type == "photo":
        await client.send_photo(chat_id, receipt_file_id, caption=caption, reply_markup=kb, parse_mode=enums.ParseMode.MARKDOWN)
    else:
        await client.send_document(chat_id, receipt_file_id, caption=caption, reply_markup=kb, parse_mode=enums.ParseMode.MARKDOWN)


# ── Kartalar boshqaruvi ──
def _cards_manage_kb(cards: list) -> InlineKeyboardMarkup:
    buttons = [[InlineKeyboardButton(f"{c[1]} •• {c[2][-4:]}  🗑", callback_data=f"adm_card_del:{c[0]}")] for c in cards]
    buttons.append([InlineKeyboardButton("➕ Karta qo'shish", callback_data="adm_card_add")])
    return InlineKeyboardMarkup(buttons)


@app.on_callback_query(admin_filter & filters.create(lambda _, __, q: q.data == "adm_cards_menu"))
async def adm_cards_menu(client, call):
    cards = database.list_all_cards()
    text = "💳 *Kartalar ro'yxati*\n\nO'chirish uchun kartaga bosing." if cards else "💳 Hozircha karta yo'q."
    await call.message.reply(text, parse_mode=enums.ParseMode.MARKDOWN, reply_markup=_cards_manage_kb(cards))
    await call.answer()


@app.on_callback_query(admin_filter & filters.create(lambda _, __, q: q.data == "adm_card_add"))
async def add_card_start(client, call):
    admin_id = call.from_user.id
    state.user_admin_flow[admin_id] = {"flow": "add_card", "step": "bank"}
    await call.message.reply("🏦 Bank nomini kiriting:")
    await call.answer()


@app.on_callback_query(admin_filter & filters.create(lambda _, __, q: q.data.startswith("adm_card_del:")))
async def delete_card_cb(client, call):
    card_id = int(call.data.split(":")[1])
    database.delete_card(card_id)
    await call.answer("Karta o'chirildi.")
    cards = database.list_all_cards()
    text = "💳 *Kartalar ro'yxati*\n\nO'chirish uchun kartaga bosing." if cards else "💳 Hozircha karta yo'q."
    await call.message.edit_text(text, parse_mode=enums.ParseMode.MARKDOWN, reply_markup=_cards_manage_kb(cards))


# ── Kripto boshqaruvi ──
def _tokens_manage_kb(tokens: list) -> InlineKeyboardMarkup:
    buttons = [[InlineKeyboardButton(f"{tkn[1]}  🗑", callback_data=f"adm_token_del:{tkn[0]}"),
                InlineKeyboardButton("🌐 Tarmoqlar", callback_data=f"adm_token_manage:{tkn[0]}")] for tkn in tokens]
    buttons.append([InlineKeyboardButton("➕ Token qo'shish", callback_data="adm_token_add")])
    return InlineKeyboardMarkup(buttons)


@app.on_callback_query(admin_filter & filters.create(lambda _, __, q: q.data == "adm_crypto_menu"))
async def adm_crypto_menu(client, call):
    tokens = database.list_all_tokens()
    text = "🪙 *Kripto tokenlar*" if tokens else "🪙 Hozircha token yo'q."
    await call.message.reply(text, parse_mode=enums.ParseMode.MARKDOWN, reply_markup=_tokens_manage_kb(tokens))
    await call.answer()


@app.on_callback_query(admin_filter & filters.create(lambda _, __, q: q.data == "adm_token_add"))
async def add_token_start(client, call):
    admin_id = call.from_user.id
    state.user_admin_flow[admin_id] = {"flow": "add_token"}
    await call.message.reply("🪙 Token nomini kiriting (masalan: USDT):")
    await call.answer()


@app.on_callback_query(admin_filter & filters.create(lambda _, __, q: q.data.startswith("adm_token_del:")))
async def delete_token_cb(client, call):
    token_id = int(call.data.split(":")[1])
    database.delete_token(token_id)
    await call.answer("Token o'chirildi.")
    tokens = database.list_all_tokens()
    text = "🪙 *Kripto tokenlar*" if tokens else "🪙 Hozircha token yo'q."
    await call.message.edit_text(text, parse_mode=enums.ParseMode.MARKDOWN, reply_markup=_tokens_manage_kb(tokens))


def _token_detail_kb(token_id: int, networks: list) -> InlineKeyboardMarkup:
    buttons = [[InlineKeyboardButton(f"{n[2]}  🗑", callback_data=f"adm_net_del:{n[0]}")] for n in networks]
    buttons.append([InlineKeyboardButton("➕ Tarmoq qo'shish", callback_data=f"adm_net_add:{token_id}")])
    return InlineKeyboardMarkup(buttons)


@app.on_callback_query(admin_filter & filters.create(lambda _, __, q: q.data.startswith("adm_token_manage:")))
async def manage_token(client, call):
    token_id = int(call.data.split(":")[1])
    token = database.get_token(token_id)
    if not token:
        await call.answer()
        return
    networks = database.list_all_networks_for_token(token_id)
    text = f"🪙 *{token[1]}* tarmoqlari" + ("" if networks else "\n\nHozircha tarmoq yo'q.")
    await call.message.reply(text, parse_mode=enums.ParseMode.MARKDOWN, reply_markup=_token_detail_kb(token_id, networks))
    await call.answer()


@app.on_callback_query(admin_filter & filters.create(lambda _, __, q: q.data.startswith("adm_net_add:")))
async def add_network_start(client, call):
    admin_id = call.from_user.id
    token_id = int(call.data.split(":")[1])
    state.user_admin_flow[admin_id] = {"flow": "add_network", "token_id": token_id, "step": "name"}
    await call.message.reply("🌐 Tarmoq nomini kiriting (masalan: TRC20):")
    await call.answer()


@app.on_callback_query(admin_filter & filters.create(lambda _, __, q: q.data.startswith("adm_net_del:")))
async def delete_network_cb(client, call):
    network_id = int(call.data.split(":")[1])
    database.delete_network(network_id)
    await call.answer("Tarmoq o'chirildi.")


# Admin matn-kiritish oqimi (karta/token/tarmoq qo'shish) endi
# handlers/text_router.py da state.user_admin_flow orqali boshqariladi
# (bitta markazlashgan matn-router bilan to'qnashuvning oldini olish uchun).
async def handle_admin_payment_flow(message) -> bool:
    """text_router.py dan chaqiriladi. True qaytarsa, xabar ishlangan hisoblanadi."""
    admin_id = message.from_user.id
    flow = state.user_admin_flow.get(admin_id)
    if not flow:
        return False
    raw = (message.text or "").strip()

    if flow["flow"] == "add_card":
        if flow["step"] == "bank":
            flow["bank_name"] = raw
            flow["step"] = "number"
            await message.reply("💳 Karta raqamini kiriting:")
            return True
        if flow["step"] == "number":
            flow["card_number"] = raw
            flow["step"] = "owner"
            await message.reply("👤 Karta egasining ismini kiriting:")
            return True
        if flow["step"] == "owner":
            database.add_card(flow["bank_name"], flow["card_number"], raw)
            state.user_admin_flow.pop(admin_id, None)
            await message.reply("✅ Karta qo'shildi.")
            return True

    if flow["flow"] == "add_token":
        database.add_crypto_token(raw)
        state.user_admin_flow.pop(admin_id, None)
        await message.reply(f"✅ Token qo'shildi: {raw.upper()}")
        return True

    if flow["flow"] == "add_network":
        if flow["step"] == "name":
            flow["network_name"] = raw
            flow["step"] = "address"
            await message.reply("📮 Tarmoq manzilini (wallet address) kiriting:")
            return True
        if flow["step"] == "address":
            database.add_network(flow["token_id"], flow["network_name"], raw)
            state.user_admin_flow.pop(admin_id, None)
            await message.reply("✅ Tarmoq qo'shildi.")
            return True

    return False
