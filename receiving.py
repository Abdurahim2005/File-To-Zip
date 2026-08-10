import os
import asyncio

from pyrogram import enums
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton

import database
import state
from config import DEBOUNCE_SEC
from texts import tx
from fs_utils import user_dir, disk_used, sanitize_filename, unique_path, fmt_size
from helpers import safe_delete, get_user_file_lock
from subscription import gate_check
from batch import (
    cancel_task, schedule_task, schedule_limit_msg, schedule_batch_timer,
    check_batch_complete, start_auto_zip,
)

# ════════════════════════════════════════════════════════════
#  FAYL QABUL QILISH (Pure In-Memory Counter & Temp File Filtered)
# ════════════════════════════════════════════════════════════
async def receive_file(client, message: Message, obj, filename: str):
    uid = message.from_user.id

    # Ikki marta ishlov berilishini oldini olish
    if hasattr(message, '_handled'):
        return
    message._handled = True

    if database.is_banned(uid):
        # Banlangan foydalanuvchini tozalash ma'qul, buni qoldirishingiz mumkin
        await safe_delete(message)
        return

    lang = database.get_lang(uid) or "uz"
    if not await gate_check(client, uid, message.chat.id, lang):
        # Kanallarga a'zo bo'lmaganda yuborilgan faylni o'chiramiz (tartib uchun)
        await safe_delete(message)
        return

    max_zips, max_storage = database.get_user_limits(uid)
    if database.get_daily_zip_count(uid) >= max_zips:
        # 🔥 O'ZGARTIRILDI: safe_delete olib tashlandi. Fayl chatda qoladi!
        schedule_limit_msg(client, message.chat.id, uid)
        return

    fsize    = getattr(obj, "file_size", 0) or 0
    accepted = False
    was_downloading = False

    udir      = user_dir(uid)
    safe_name = sanitize_filename(filename)

    lock = get_user_file_lock(uid)
    async with lock:
        save_path = unique_path(udir, safe_name)

        # 1. Paket boshlanganda diskni bir marta sanab olish
        if state.user_downloading.get(uid, 0) == 0:
            if os.path.exists(udir):
                disk_files = [f for f in os.listdir(udir) if os.path.isfile(os.path.join(udir, f)) and not f.endswith(('.temp', '.part', '.download'))]
                state.user_base_count[uid] = len(disk_files)
            else:
                state.user_base_count[uid] = 0

        used_now = disk_used(uid) + state.user_reserved_bytes.get(uid, 0)
        cur_cnt = state.user_base_count.get(uid, 0) + state.user_downloading.get(uid, 0)

        # 2. Limitlarni tekshirish qismi (receive_file ichida)
        if cur_cnt >= database.get_user_max_files(uid):
            state.user_excess[uid] = state.user_excess.get(uid, 0) + 1

            # 🔥 O'ZGARTIRILDI: Alvido _send_excess_msg! 
            # Faqatgina paket taymeri o'chib qolmasligi uchun uni yangilab qo'yamiz
            if not state.user_downloading.get(uid, 0) > 0 and not state.user_batch_active.get(uid, False):
                schedule_batch_timer(uid, message.chat.id, client)
        elif used_now + fsize > max_storage:
            state.user_storage_rej[uid] = state.user_storage_rej.get(uid, 0) + 1

            async def _send_storage_full_msg(chat_id, u, _used_now=used_now, _max_storage=max_storage):
                await asyncio.sleep(DEBOUNCE_SEC)
                rej_cnt = state.user_storage_rej.pop(u, 0)
                u_dir   = user_dir(u)
                acc_cnt = len([f for f in os.listdir(u_dir) if os.path.isfile(os.path.join(u_dir, f)) and not f.endswith(('.temp', '.part', '.download'))])
                lang_u  = database.get_lang(u) or "uz"
                if lang_u == "uz":
                    text = (f"⚠️ *Xotira to'lib qoldi!*\n\n"
                            f"✅ Qabul qilindi: *{acc_cnt} ta fayl*\n"
                            f"❌ Qabul qilinmadi: *{rej_cnt} ta fayl*\n"
                            f"💾 Band: *{fmt_size(_used_now)}* / *{fmt_size(_max_storage)}*\n\n"
                            f"ZIP yasash tugmasini bosing — 40 soniyada avto-zip.")
                else:
                    text = (f"⚠️ *Storage full!*\n\n"
                            f"✅ Accepted: *{acc_cnt} file(s)*\n"
                            f"❌ Rejected: *{rej_cnt} file(s)*\n"
                            f"💾 Used: *{fmt_size(_used_now)}* of *{fmt_size(_max_storage)}*\n\n"
                            f"Press Create ZIP — auto-zip in 40 seconds.")
                sm = state.user_status_msg.pop(u, None)
                await safe_delete(sm)
                sfm = await client.send_message(
                    chat_id, text, parse_mode=enums.ParseMode.MARKDOWN,
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(tx(u, "ready_btn"), callback_data="zip_now")]]),
                )
                state.user_status_msg[u] = sfm
                await cancel_task(state.user_auto_zip, u)
                start_auto_zip(client, chat_id, u, delay=40, user_obj=None)

            schedule_task(state.user_debounce, uid, _send_storage_full_msg(message.chat.id, uid))
            # 🔥 Fayl qabul qilinmadi (accepted = False), return bo'ladi va chatda qoladi!
        else:
            was_downloading = state.user_downloading.get(uid, 0) > 0
            state.user_reserved_bytes[uid] = state.user_reserved_bytes.get(uid, 0) + fsize
            state.user_downloading[uid]    = state.user_downloading.get(uid, 0) + 1
            accepted = True

    # Agar qabul qilinmagan bo'lsa, shunchaki funksiyani yakunlaymiz (fayl chatda o'chmaydi!)
    if not accepted:
        return

    # Oldingi taymer va xabarlarni tozalash (Faqat qabul qilingan fayllar uchun)
    await cancel_task(state.user_auto_zip, uid)
    sm_old = state.user_status_msg.pop(uid, None)
    await safe_delete(sm_old)
    recv_old = state.user_receiving_msg.pop(uid, None)
    await safe_delete(recv_old)
    state.user_batch_active.pop(uid, None)

    if not was_downloading:
        schedule_batch_timer(uid, message.chat.id, client)
    else:
        if not state.user_batch_active.get(uid, False):
            schedule_batch_timer(uid, message.chat.id, client)

    # Faylni diskka yuklash jarayoni
    download_success = False
    try:
        await message.download(file_name=save_path)
        download_success = True
    except Exception:
        pass
    finally:
        async with lock:
            state.user_downloading[uid]    = max(0, state.user_downloading.get(uid, 1) - 1)
            state.user_reserved_bytes[uid] = max(0, state.user_reserved_bytes.get(uid, fsize) - fsize)

            if download_success:
                state.user_base_count[uid] = state.user_base_count.get(uid, 0) + 1

        await check_batch_complete(client, uid, message.chat.id, message.from_user)

    # 🔥 FAQATGINA muvaffaqiyatli qabul qilingan va yuklangan faylni chatdan tozalaymiz!
    if accepted and download_success:
        await safe_delete(message)
