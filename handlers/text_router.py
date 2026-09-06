import os
import re
import shutil
from datetime import datetime

from pyrogram import filters, enums
from pyrogram.errors import UserIsBlocked, InputUserDeactivated
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton

import database
import state
import texts as texts_mod
from config import ADMIN_ID, ADMIN_USERNAME, BASE_DIR, PREMIUM_PRICE_UZS, PREMIUM_PRICE_USDT
from bot_instance import app
from texts import tx
from fs_utils import file_count, disk_used, fmt_size, sanitize_zip_name, make_zip_name
from helpers import safe_delete
from batch import cancel_task
from zip_ops import create_and_send_zip, ask_password_step

# ════════════════════════════════════════════════════════════
#  ADMIN MATN HANDLERI (TO\'LIQ)
# ════════════════════════════════════════════════════════════
@app.on_message(filters.text & ~filters.command(["start","admin","premium"]))
async def on_text(client, message):
    uid  = message.from_user.id
    text = message.text.strip() if message.text else ""

    if database.is_banned(uid):
        await safe_delete(message)
        return
    if text.startswith("/this_private"):
        await safe_delete(message)
        return

    # ── Ensure user in DB ──
    if database.get_lang(uid) is None:
        database.upsert_user(message.from_user, "uz")
        await safe_delete(message)
        sent = await client.send_message(
            message.chat.id, texts_mod.TEXTS["uz"]["choose_lang"],
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🇺🇿 O'zbek", callback_data="setlang_uz"),
                InlineKeyboardButton("🇬🇧 English", callback_data="setlang_en"),
            ]]),
        )
        state.user_welcome_msg[uid] = sent
        return

    lang = database.get_lang(uid) or "uz"
    t    = texts_mod.TEXTS.get(lang, texts_mod.TEXTS["uz"])

    # ── Admin replying to a user (eng ustuvor -- boshqa hech qanday oqim
    # admin javob rejimidagi matnni ushlab qolmasin) ──
    if uid == ADMIN_ID and ADMIN_ID in state.admin_reply_to:
        target_uid = state.admin_reply_to.pop(ADMIN_ID, None)
        if target_uid:
            target_lang = database.get_lang(target_uid) or "uz"
            try:
                await client.send_message(
                    target_uid,
                    f"{texts_mod.TEXTS[target_lang]['reply_from_admin']}\n\n{text}",
                    parse_mode=enums.ParseMode.MARKDOWN,
                )
                await message.reply(texts_mod.TEXTS["uz"]["admin_reply_sent"])
            except Exception as e:
                await message.reply(f"❌ Yuborishda xato: {e}")
        return

    # ── Fikr-mulohaza: matn kiritilishi kutilmoqda ──
    # (agar foydalanuvchi shu payt boshqa menyu tugmasini bossa, feedback
    # holati bekor qilinadi va o'sha tugmaning o'z ishi bajariladi --
    # aks holda tugma nomi ham "feedback matni" sifatida yuborilib qolar edi)
    _menu_buttons = {"⭐ Premium", t.get("btn_stats"), t.get("btn_contact"), t.get("btn_feedback"), t.get("btn_top"), t.get("btn_myid"), "🔐 Admin panel"}
    if uid in state.user_feedback_flow:
        if text in _menu_buttons or text.startswith("/"):
            info = state.user_feedback_flow.pop(uid, None)
            if info:
                await safe_delete(info.get("ask_msg"))
        else:
            from handlers.feedback import handle_feedback_text
            handled = await handle_feedback_text(client, message)
            if handled:
                return

    # ── Keyboard button: Admin panel (faqat adminga ko'rinadi) ──
    if text == "🔐 Admin panel" and uid == ADMIN_ID:
        from handlers.admin import show_admin_panel
        await safe_delete(message)
        await show_admin_panel(client, message)
        return

    # ── Keyboard button: Fikr-mulohaza ──
    if text == t.get("btn_feedback"):
        from handlers.feedback import start_feedback
        await start_feedback(client, message)
        return

    # ── Keyboard button: Top-10 (hammaga ochiq, username ko'rsatilmaydi) ──
    if text == t.get("btn_top"):
        from handlers.admin import build_top_users_text
        await message.reply(build_top_users_text(reveal_username=False), parse_mode=enums.ParseMode.MARKDOWN)
        return

    # ── Admin: karta/token/tarmoq qo'shish oqimi (to'lovlar) ──
    if uid == ADMIN_ID and uid in state.user_admin_flow:
        from handlers.payment import handle_admin_payment_flow
        handled = await handle_admin_payment_flow(message)
        if handled:
            return

        # ── Keyboard button: Premium ──
    if text == "⭐ Premium":
        await safe_delete(message)
        lang = database.get_lang(uid) or "uz"
        reg_zips, reg_storage = state.DEFAULT_ZIPS_DAY, int(state.DEFAULT_STORAGE / 1024 / 1024)
        prem = database.get_premium_settings()
        premium_text = texts_mod.TEXTS[lang]["premium_info"].format(
            reg_zips=reg_zips, reg_storage=reg_storage,
            reg_files=state.MAX_FILES, reg_pw=state.DEFAULT_PW_ZIPS_DAY,
            prem_zips=prem["zips_day"], prem_storage=prem["storage_mb"],
            prem_files=prem["files"], prem_pw=prem["pw_zips_day"],
            price_uzs=PREMIUM_PRICE_UZS, price_usdt=PREMIUM_PRICE_USDT,
        )
        await client.send_message(
            message.chat.id,
            premium_text,
            parse_mode=enums.ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton(tx(uid, "btn_get_premium"), callback_data="topup:start")
            ]]),
            disable_web_page_preview=True,
        )
        return

    # ── Keyboard button: Statistika ──
    if text == t["btn_stats"]:
        await safe_delete(message)
        s = database.get_global_stats()
        await client.send_message(
            message.chat.id,
            t["pub_stats"].format(
                users=database.user_count(), today=database.today_count(),
                total_zips=s["total_zips"], total_mb=s["total_mb"],
                total_files=s["total_files"], today_zips=s["today_zips"],
                today_mb=s["today_mb"],
            ),
            parse_mode=enums.ParseMode.MARKDOWN,
        )
        return

    # ── Keyboard button: Kabinetim ──
    if text == t.get("btn_myid"):
        await safe_delete(message)
        full_name = (message.from_user.first_name or "") + (
            f" {message.from_user.last_name}" if message.from_user.last_name else ""
        )

        is_prem       = database.is_premium(uid)
        level         = "⭐ Premium" if is_prem else "🔹 Oddiy"
        max_zips, max_storage = database.get_user_limits(uid)
        today_zips    = database.get_daily_zip_count(uid)
        max_pw        = database.get_user_pw_zip_limit(uid)
        today_pw      = database.get_pw_zips_used_today(uid)
        total_zips    = database.get_user_zip_total(uid)
        fcount        = file_count(uid)
        used_storage  = disk_used(uid)

        await client.send_message(
            message.chat.id,
            tx(
                uid, "myid_text",
                name=full_name.strip() or "—", id=uid, level=level,
                today_zips=today_zips, max_zips=max_zips,
                today_pw=today_pw, max_pw=max_pw,
                total_zips=total_zips, file_count=fcount,
                used_storage=fmt_size(used_storage), max_storage=fmt_size(max_storage),
            ),
            parse_mode=enums.ParseMode.MARKDOWN,
        )
        return

    # ── Keyboard button: Admin bilan bog'lanish ──
        # ── Keyboard button: Admin bilan bog'lanish ──
    if text == t["btn_contact"]:
        await safe_delete(message)
        contact_text = t.get("contact_text", "📞 Admin bilan bog‘lanish uchun quyidagi tugmani bosing:")
        admin_link = f"https://t.me/{ADMIN_USERNAME}" if ADMIN_USERNAME else f"tg://user?id={ADMIN_ID}"
        await client.send_message(
            message.chat.id,
            contact_text,
            parse_mode=enums.ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("✉️ Admin bilan yozishish", url=admin_link)
            ]])
        )
        return

    # ── ZIP naming input ──
    if uid in state.user_zip_naming:
        info = state.user_zip_naming.pop(uid, None)
        await cancel_task(state.user_auto_zip, uid)
        if info and info.get("ask_msg"):
            await safe_delete(info["ask_msg"])
        zip_name = sanitize_zip_name(text) or (info["default_name"] if info else f"zip_{datetime.now():%Y%m%d_%H%M%S}")
        if not zip_name:
            zip_name = info["default_name"] if info else make_zip_name(message.from_user)
        await safe_delete(message)
        if info and file_count(uid) > 0:
            sm = state.user_status_msg.pop(uid, None)
            await safe_delete(sm)
            await ask_password_step(client, info["chat_id"], uid, zip_name)
        return

    # ── ZIP password input ──
    if uid in state.user_pw_asking and state.user_pw_asking[uid].get("stage") == "password":
        info = state.user_pw_asking.pop(uid, None)
        await safe_delete(message)
        if info and info.get("ask_msg"):
            await safe_delete(info["ask_msg"])
        password = text.strip()
        if not password:
            password = None
        if info and file_count(uid) > 0:
            await create_and_send_zip(client, info["chat_id"], uid, info["zip_name"], password=password)
        return


    # ── Admin broadcast ──
    if uid == ADMIN_ID and uid in state.broadcast_mode:
        state.broadcast_mode.discard(uid)
        users = database.all_users()
        ok = fail = 0
        prog = await message.reply("📨 Yuborilmoqda...")
        for row in users:
            if row[6]:
                continue
            try:
                await client.send_message(row[0], f"📢 {text}")
                ok += 1
            except (UserIsBlocked, InputUserDeactivated):
                # Foydalanuvchi botni bloklagan/akkaunt o'chirilgan --
                # broadcast baribir shu foydalanuvchiga urinib ko'rgani
                # uchun bu ma'lumot "bepul" keladi, alohida so'rov shart
                # emas -- botning umumiy tezligiga ta'sir qilmaydi.
                database.mark_user_left(row[0])
                fail += 1
            except Exception:
                fail += 1
        await safe_delete(prog)
        await message.reply(f"📨 *Broadcast tugadi!*\n\n✅ *{ok}*\n❌ *{fail}*",
                            parse_mode=enums.ParseMode.MARKDOWN)
        return

    # ── Admin waiting for input ──
    if uid == ADMIN_ID and uid in state.waiting_for_user_id:
        action = state.waiting_for_user_id.pop(uid)
        raw    = text

        # ── Fikr-mulohaza admin sozlamalari ──
        from handlers.feedback import handle_admin_feedback_action
        handled = await handle_admin_feedback_action(client, message, action, raw)
        if handled:
            return

        if action == "set_zip_limit":
            parts = raw.split()
            if len(parts) < 2:
                await message.reply("❌ Format: `USER_ID LIMIT`\nMisol: `123456789 10`",
                                    parse_mode=enums.ParseMode.MARKDOWN)
                return
            try:
                target_id = int(parts[0])
                limit_val = int(parts[1])
                if limit_val < 0:
                    raise ValueError
                database.set_user_zip_limit(target_id, limit_val)
                await message.reply(f"✅ `{target_id}` uchun kunlik ZIP limiti: *{limit_val}* ta",
                                    parse_mode=enums.ParseMode.MARKDOWN)
            except Exception:
                await message.reply("❌ Xato. Format: `USER_ID LIMIT`", parse_mode=enums.ParseMode.MARKDOWN)
            return

        if action == "set_storage_limit":
            parts = raw.split()
            if len(parts) < 2:
                await message.reply("❌ Format: `USER_ID MB`\nMisol: `123456789 1024`",
                                    parse_mode=enums.ParseMode.MARKDOWN)
                return
            try:
                target_id   = int(parts[0])
                mb_val      = int(parts[1])
                if mb_val < 1 or mb_val > 2048:
                    raise ValueError("1-2048 MB oralig'ida bo'lishi kerak")
                storage_bytes = mb_val * 1024 * 1024
                database.set_user_storage_limit(target_id, storage_bytes)
                await message.reply(f"✅ `{target_id}` uchun xotira limiti: *{mb_val} MB*",
                                    parse_mode=enums.ParseMode.MARKDOWN)
            except ValueError as ve:
                await message.reply(f"❌ Xato: {ve}", parse_mode=enums.ParseMode.MARKDOWN)
            except Exception:
                await message.reply("❌ Format: `USER_ID MB`", parse_mode=enums.ParseMode.MARKDOWN)
            return

        if action == "reset_limits":
            try:
                target_id = int(re.search(r"\d+", raw).group()) # type: ignore
                database.reset_user_limits(target_id)
                database.set_user_premium(target_id, False)
                database.remove_premium_record(target_id)
                await message.reply(f"✅ `{target_id}` limiti standartga qaytarildi.",
                                    parse_mode=enums.ParseMode.MARKDOWN)
            except Exception:
                await message.reply("❌ Noto'g'ri ID.")
            return

        # Yangi hamma uchun actionlar
        if action == "set_all_zip_limit":
            try:
                limit_val = int(raw)
                if limit_val < 0: raise ValueError
                database.set_all_users_zip_limit(limit_val)
                await message.reply(f"✅ Hamma foydalanuvchilar uchun kunlik ZIP limiti: *{limit_val}* ta",
                                    parse_mode=enums.ParseMode.MARKDOWN)
            except Exception:
                await message.reply("❌ Butun son yuboring.")
            return

        if action == "set_all_storage_limit":
            try:
                mb_val = int(raw)
                if mb_val < 1 or mb_val > 2048: raise ValueError("1-2048 MB oralig'ida bo'lishi kerak")
                database.set_all_users_storage_limit(mb_val)
                await message.reply(f"✅ Hamma foydalanuvchilar uchun xotira limiti: *{mb_val} MB*",
                                    parse_mode=enums.ParseMode.MARKDOWN)
            except Exception as e:
                await message.reply(f"❌ Xato: {e}")
            return

        if action == "set_comp_user_uid":
            try:
                target_uid = int(raw)
                state.admin_comp_target[ADMIN_ID] = target_uid
                await message.reply(
                    "🗜 Siqish darajasini tanlang:",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("0️⃣ Oddiy (siqilmasin)", callback_data="comp_sel_0"),
                         InlineKeyboardButton("6️⃣ O‘rta (tezkor)", callback_data="comp_sel_6"),
                         InlineKeyboardButton("9️⃣ Yuqori (kuchli siqish)", callback_data="comp_sel_9")]
                    ])
                )
                state.waiting_for_user_id.pop(ADMIN_ID, None)  # holat tugadi
            except Exception:
                await message.reply("❌ Noto'g'ri ID.")
            return

        # YANGI: fayl limiti uchun qo‘shimchalar
        if action == "set_file_limit":
            parts = raw.split()
            if len(parts) < 2:
                await message.reply("❌ Format: `USER_ID LIMIT`")
                return
            try:
                target_id = int(parts[0])
                limit_val = int(parts[1])
                database.set_user_max_files(target_id, limit_val)
                await message.reply(f"✅ `{target_id}` uchun fayl limiti: *{limit_val}* ta")
            except Exception:
                await message.reply("❌ Xato. Format: `USER_ID LIMIT`")
            return

        if action == "set_all_file_limit":
            try:
                limit_val = int(raw)
                database.set_all_users_max_files(limit_val)
                await message.reply(f"✅ Hamma uchun fayl limiti: *{limit_val}* ta")
            except Exception:
                await message.reply("❌ Butun son yuboring")
            return

        if action == "set_pw_limit":
            parts = raw.split()
            if len(parts) < 2:
                await message.reply("❌ Format: `USER_ID LIMIT`")
                return
            try:
                target_id = int(parts[0])
                limit_val = int(parts[1])
                database.set_user_pw_zip_limit(target_id, limit_val)
                await message.reply(f"✅ `{target_id}` uchun kunlik parol limiti: *{limit_val}* ta")
            except Exception:
                await message.reply("❌ Xato. Format: `USER_ID LIMIT`")
            return

        if action == "set_all_pw_limit":
            try:
                limit_val = int(raw)
                database.set_all_users_pw_zip_limit(limit_val)
                await message.reply(f"✅ Hamma uchun kunlik parol limiti: *{limit_val}* ta")
            except Exception:
                await message.reply("❌ Butun son yuboring")
            return

        if action == "set_premium_settings":
            parts = raw.split()
            if len(parts) != 5:
                await message.reply("❌ Format: `ZIP_KUN XOTIRA_MB FAYL SIQISH PAROL_KUN`\nMisol: `15 2048 60 6 15`")
                return
            try:
                zips_day, storage_mb, files, comp, pw_zips = (int(p) for p in parts)
                database.set_premium_settings(zips_day, storage_mb, files, comp, pw_zips)
                await message.reply(
                    "✅ Premium sozlamalari yangilandi!\n\n"
                    f"📦 ZIP/kun: *{zips_day}*\n"
                    f"💾 Xotira: *{storage_mb} MB*\n"
                    f"📎 Fayl/ZIP: *{files}*\n"
                    f"🗜 Siqish: *{comp}*\n"
                    f"🔐 Parol/kun: *{pw_zips}*\n\n"
                    "_Bu sozlamalar keyingi safar 'Premium yoqish' bosilganda qo'llanadi._",
                    parse_mode=enums.ParseMode.MARKDOWN,
                )
            except Exception:
                await message.reply("❌ Xato. Format: `ZIP_KUN XOTIRA_MB FAYL SIQISH PAROL_KUN`")
            return
        if action == "premium_on":
            try:
                target_id = int(raw)
                target_lang = database.get_lang(target_id) or "uz"

                s = database.get_premium_settings()
                database.apply_premium(target_id)

                comp_text_uz = {0: "Yo'q", 6: "O'rta daraja", 9: "Yuqori daraja"}.get(s["compression"], f"Daraja {s['compression']}")
                comp_text_en = {0: "None", 6: "Medium", 9: "High"}.get(s["compression"], f"Level {s['compression']}")

                await message.reply(
                    f"✅ Premium yoqildi!\n"
                    f"👤 ID: `{target_id}`\n"
                    f"📦 ZIP: {s['zips_day']} ta/kun | 💾 {s['storage_mb']} MB | "
                    f"📎 {s['files']} fayl | 🗜 {comp_text_uz} | 🔐 {s['pw_zips_day']} parolli zip/kun",
                    parse_mode=enums.ParseMode.MARKDOWN,
                )

                # Foydalanuvchiga xabar yuborish (tiliga qarab)
                try:
                    if target_lang == "en":
                        msg_text = (
                            "🎉 *Congratulations! You are now a Premium user!*\n\n"
                            f"✅ Daily ZIPs: *{s['zips_day']}*\n"
                            f"✅ Storage: *{s['storage_mb']} MB*\n"
                            f"✅ Files per ZIP: *{s['files']}*\n"
                            f"✅ Compression: *{comp_text_en}*\n"
                            f"✅ Password-protected ZIPs: *{s['pw_zips_day']} per day* 🔐\n\n"
                            "🚀 Enjoy unlimited possibilities!"
                        )
                    else:
                        msg_text = (
                            "🎉 *Tabriklaymiz! Siz Premium foydalanuvchi bo‘ldingiz!*\n\n"
                            f"✅ Kunlik ZIP: *{s['zips_day']} ta*\n"
                            f"✅ Xotira: *{s['storage_mb']} MB*\n"
                            f"✅ Fayllar soni: *{s['files']} ta*\n"
                            f"✅ Siqish: *{comp_text_uz}*\n"
                            f"✅ Parolli ZIP: *Kuniga {s['pw_zips_day']} ta* 🔐\n\n"
                            "🚀 Endi cheklovlarsiz ishlashingiz mumkin!"
                        )
                    await client.send_message(target_id, msg_text, parse_mode=enums.ParseMode.MARKDOWN)
                except Exception:
                    pass
            except Exception:
                await message.reply("❌ Noto‘g‘ri ID.")
            return

        if action == "premium_off":
            try:
                target_id = int(raw)
                target_lang = database.get_lang(target_id) or "uz"
                
                database.reset_user_limits(target_id)
                database.set_user_premium(target_id, False)
                database.remove_premium_record(target_id)
                
                await message.reply(
                    f"✅ Premium bekor qilindi!\n"
                    f"👤 ID: `{target_id}`\n"
                    f"Barcha limitlar standartga qaytarildi.",
                    parse_mode=enums.ParseMode.MARKDOWN,
                )
                
                # Foydalanuvchiga xabar yuborish (tiliga qarab)
                try:
                    if target_lang == "en":
                        msg_text = (
                            "❌ *Your Premium has been cancelled.*\n\n"
                            "All limits have been reset to default.\n"
                            "💎 Press /start to get Premium again."
                        )
                    else:
                        msg_text = (
                            "❌ *Premium muddatingiz tugadi yoki bekor qilindi.*\n\n"
                            "Barcha limitlaringiz standart holatga qaytarildi.\n"
                            "💎 Qayta premium olish uchun /start bosing."
                        )
                    await client.send_message(target_id, msg_text, parse_mode=enums.ParseMode.MARKDOWN)
                except Exception:
                    pass
            except Exception:
                await message.reply("❌ Noto‘g‘ri ID.")
            return
        
        if action == "add_channel":
            raw_text = raw.strip()

            # Avval chat ID sifatida tekshirib ko'ramiz (faqat sonlardan iborat bo'lsa)
            if raw_text.lstrip('-').isdigit():
                try:
                    chat = await client.get_chat(int(raw_text))
                    title = chat.title or str(chat.id)
                    uname = (getattr(chat, 'username', None) or '').lstrip('@')
                    database.add_channel(chat.id, title, username=uname)
                    await message.reply(f"✅ Kanal qo'shildi (ID orqali): *{title}*\n🆔 `{chat.id}`",
                                        parse_mode=enums.ParseMode.MARKDOWN)
                except Exception as e:
                    await message.reply(f"❌ Xato: {e}")
                return

            # Telegram havolasimi yoki username (@...)
            if raw_text.startswith('@') or 't.me/' in raw_text:
                normalized = raw_text
                if not normalized.startswith('@'):
                    normalized = normalized.replace('https://t.me/', '@').replace('http://t.me/', '@').replace('t.me/', '@')
                try:
                    chat = await client.get_chat(normalized)
                    title = chat.title or normalized
                    uname = (getattr(chat, 'username', None) or '').lstrip('@')
                    is_private = 0
                    invite_link = ''
                    if not uname:
                        try:
                            invite_link = await client.export_chat_invite_link(chat.id)
                        except Exception:
                            invite_link = raw_text
                        is_private = 1
                    database.add_channel(chat.id, title, username=uname, invite_link=invite_link, is_private=is_private)
                    ref = f"@{uname}" if uname else invite_link
                    await message.reply(f"✅ Kanal qo'shildi: *{title}*\n🔗 `{ref}`\n🆔 `{chat.id}`",
                                        parse_mode=enums.ParseMode.MARKDOWN)
                except Exception:
                    if '/joinchat' in raw_text or '/+' in raw_text:
                        try:
                            chat = await client.join_chat(raw_text)
                            title = chat.title or raw_text
                            database.add_channel(chat.id, title, username='', invite_link=raw_text, is_private=1)
                            await message.reply(f"✅ Maxfiy kanal qo'shildi: *{title}*\n🔗 `{raw_text}`\n🆔 `{chat.id}`",
                                                parse_mode=enums.ParseMode.MARKDOWN)
                        except Exception as e2:
                            database.add_channel(-abs(hash(raw_text)) % 1000000, raw_text, invite_link=raw_text, is_external=1)
                            await message.reply(f"⚠️ Bot kanalga qo'shila olmadi. Tashqi havola sifatida qo'shildi (tekshirilmaydi): {raw_text}")
                    else:
                        database.add_channel(-abs(hash(raw_text)) % 1000000, raw_text, invite_link=raw_text, is_external=1)
                        await message.reply(f"⚠️ Kanal topilmadi, tashqi havola sifatida qo'shildi.")
                return

            # Telegram emas – tashqi havola
            database.add_channel(-abs(hash(raw_text)) % 1000000, raw_text, invite_link=raw_text, is_external=1)
            await message.reply(f"✅ Tashqi havola qo'shildi (tekshirilmaydi): {raw_text}")
            return

        # Generic user lookup actions (ban, unban, info, clear)
        raw_stripped = raw.strip()
        if raw_stripped.startswith("@") or not re.search(r"\d", raw_stripped):
            # Username orqali qidirish (@username yoki username)
            data = database.get_user_by_username(raw_stripped)
            if not data:
                await message.reply(f"❌ `{raw_stripped}` topilmadi.", parse_mode=enums.ParseMode.MARKDOWN)
                return
            target_id = data[0]
        else:
            try:
                target_id = int(re.search(r"\d+", raw_stripped).group())
            except Exception:
                await message.reply("❌ Noto'g'ri ID yoki username.")
                return
            data = database.get_user_by_id(target_id)

        if action == "ban":
            if not data:
                await message.reply(f"❌ `{target_id}` topilmadi.", parse_mode=enums.ParseMode.MARKDOWN)
                return
            database.ban_user(target_id)
            await message.reply(f"⛔ *Bloklandi:* {data[1]} (`{target_id}`)",
                                parse_mode=enums.ParseMode.MARKDOWN)
            try:
                await client.send_message(target_id, tx(target_id, "banned"))
            except Exception:
                pass

        elif action == "unban":
            if not data:
                await message.reply(f"❌ `{target_id}` topilmadi.", parse_mode=enums.ParseMode.MARKDOWN)
                return
            database.unban_user(target_id)
            await message.reply(f"✅ *Blokdan chiqarildi:* {data[1]} (`{target_id}`)",
                                parse_mode=enums.ParseMode.MARKDOWN)

        elif action == "info":
            if not data:
                await message.reply(f"❌ `{target_id}` topilmadi.", parse_mode=enums.ParseMode.MARKDOWN)
                return
            tid, fn, ln, un, lg, jd, bnnd = data
            fcnt       = file_count(tid)
            used       = disk_used(tid)
            today_zips = database.get_daily_zip_count(tid)
            total_zips = database.get_user_zip_total(tid)
            mz, ms     = database.get_user_limits(tid)
            ban_status = "🚫 Ha" if bnnd else "✅ Yoq"
            uname      = f"@{un}" if un else "—"
            await message.reply(
                f"👤 *Foydalanuvchi*\n\n🆔 `{tid}`\n📛 {fn} {ln}\n🔗 {uname}\n"
                f"🌍 {lg.upper()} | 📅 {jd[:16]}\n📁 {fcnt} fayl | 💾 {fmt_size(used)}\n"
                f"📦 Bugun: {today_zips}/{mz} | 📦 Umumiy ZIP: *{total_zips}* ta\n"
                f"💾 Limit: {fmt_size(ms)}\n🚫 Ban: {ban_status}",
                parse_mode=enums.ParseMode.MARKDOWN,
            )

        elif action == "clear":
            if not data:
                await message.reply(f"❌ `{target_id}` topilmadi.", parse_mode=enums.ParseMode.MARKDOWN)
                return
            ud = os.path.join(BASE_DIR, str(target_id))
            if os.path.exists(ud):
                shutil.rmtree(ud); os.makedirs(ud, exist_ok=True)
            await message.reply(f"🗑️ `{target_id}` — tozalandi.", parse_mode=enums.ParseMode.MARKDOWN)
        return

    # ── Donate amount input ──
    if uid in state.user_donating:
        state.user_donating.pop(uid)
        parts    = text.split(maxsplit=1)
        amount   = parts[0] if parts else text
        currency = parts[1].upper() if len(parts) > 1 else "?"
        fn       = message.from_user.first_name or "Foydalanuvchi"
        don_id   = database.add_donation(uid, fn, amount, currency)
        await safe_delete(message)
        await client.send_message(message.chat.id, t["donate_sent"], parse_mode=enums.ParseMode.MARKDOWN)
        try:
            await client.send_message(
                ADMIN_ID,
                f"💰 *Yangi donat so'rovi!*\n\n🆔 Don ID: `{don_id}`\n"
                f"👤 {fn} (`{uid}`)\n💵 *{amount} {currency}*",
                parse_mode=enums.ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("✅ Tasdiqlash", callback_data=f"confirm_don_{don_id}"),
                    InlineKeyboardButton("❌ Bekor qilish", callback_data=f"reject_don_{don_id}"),
                ]]),
            )
        except Exception:
            pass
        return

    # ── Admin: taklif havolasini kutish (private kanal uchun) ──
    if uid == ADMIN_ID and state.awaiting_invite_link:
        link = text.strip()
        if link.startswith("https://t.me/") or link.startswith("http://t.me/") or link.startswith("t.me/"):
            for chat_id, admin_id in list(state.awaiting_invite_link.items()):
                if admin_id == ADMIN_ID:
                    c = database.get_db()
                    c.execute("UPDATE channels SET invite_link=? WHERE chat_id=?", (link, chat_id))
                    c.commit(); database.db_sync()
                    if chat_id in state.required_channels:
                        state.required_channels[chat_id]["invite_link"] = link
                    del state.awaiting_invite_link[chat_id]
                    await message.reply("✅ Taklif havolasi saqlandi. Endi foydalanuvchilar kanalga qo‘shila oladi.")
                    return
            await message.reply("❌ Kutilayotgan kanal topilmadi.")
        else:
            await message.reply("❌ Iltimos, to‘g‘ri Telegram havolasini yuboring.")
        return

    await safe_delete(message)
