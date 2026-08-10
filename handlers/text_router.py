import os
import re
import shutil
from datetime import datetime

from pyrogram import filters, enums
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton

import database
import state
import texts as texts_mod
from config import ADMIN_ID, ADMIN_USERNAME, BASE_DIR
from bot_instance import app
from texts import tx
from fs_utils import file_count, disk_used, fmt_size, sanitize_zip_name, make_zip_name
from helpers import safe_delete
from batch import cancel_task
from zip_ops import create_and_send_zip

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

        # ── Keyboard button: Premium ──
    if text == "⭐ Premium":
        await safe_delete(message)
        lang = database.get_lang(uid) or "uz"
        await client.send_message(
            message.chat.id,
            texts_mod.TEXTS[lang]["premium_info"],
            parse_mode=enums.ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("💎 Premium olish | Get Premium", url="https://t.me/Abdurahim0525")
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
        zip_name = sanitize_zip_name(text) or (info["default_name"] if info else f"zip_{datetime.now():%Y%m%d_%H%M%S}")
        if not zip_name:
            zip_name = info["default_name"] if info else make_zip_name(message.from_user)
        await safe_delete(message)
        if info and file_count(uid) > 0:
            sm = state.user_status_msg.pop(uid, None)
            await safe_delete(sm)
            await create_and_send_zip(client, info["chat_id"], uid, zip_name)
        return


    # ── Admin replying to user ──
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
        if action == "premium_on":
            try:
                target_id = int(raw)
                target_lang = database.get_lang(target_id) or "uz"
                
                # Premium qiymatlar:
                database.set_user_zip_limit(target_id, 10)           # kunlik 10 ta ZIP
                database.set_user_storage_limit(target_id, 1024 * 1024 * 1024)  # 1 GB
                database.set_user_max_files(target_id, 40)           # 40 ta fayl
                database.set_user_compression(target_id, 6)          # o‘rta siqish
                
                await message.reply(
                    f"✅ Premium yoqildi!\n"
                    f"👤 ID: `{target_id}`\n"
                    f"📦 ZIP: 10 ta/kun | 💾 1 GB | 📎 40 fayl | 🗜 O‘rta siqish",
                    parse_mode=enums.ParseMode.MARKDOWN,
                )
                
                # Foydalanuvchiga xabar yuborish (tiliga qarab)
                try:
                    if target_lang == "en":
                        msg_text = (
                            "🎉 *Congratulations! You are now a Premium user!*\n\n"
                            "✅ Daily ZIPs: *10*\n"
                            "✅ Storage: *1 GB*\n"
                            "✅ Files per ZIP: *40*\n"
                            "✅ Compression: *Medium*\n\n"
                            "🚀 Enjoy unlimited possibilities!"
                        )
                    else:
                        msg_text = (
                            "🎉 *Tabriklaymiz! Siz Premium foydalanuvchi bo‘ldingiz!*\n\n"
                            "✅ Kunlik ZIP: *10 ta*\n"
                            "✅ Xotira: *1 GB*\n"
                            "✅ Fayllar soni: *40 ta*\n"
                            "✅ Siqish: *O‘rta daraja*\n\n"
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
        try:
            target_id = int(re.search(r"\d+", raw).group())
        except Exception:
            await message.reply("❌ Noto'g'ri ID.")
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
            mz, ms     = database.get_user_limits(tid)
            ban_status = "🚫 Ha" if bnnd else "✅ Yoq"
            uname      = f"@{un}" if un else "—"
            await message.reply(
                f"👤 *Foydalanuvchi*\n\n🆔 `{tid}`\n📛 {fn} {ln}\n🔗 {uname}\n"
                f"🌍 {lg.upper()} | 📅 {jd[:16]}\n📁 {fcnt} fayl | 💾 {fmt_size(used)}\n"
                f"📦 ZIP: {today_zips}/{mz} | 💾 Limit: {fmt_size(ms)}\n🚫 Ban: {ban_status}",
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
