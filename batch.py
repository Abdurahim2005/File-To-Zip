import asyncio
from datetime import datetime

from pyrogram import enums
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton

import database
import state
from config import AUTO_ZIP_DELAY
from texts import tx
from fs_utils import file_count, make_zip_name
from helpers import safe_delete

# ════════════════════════════════════════════════════════════
#  TASK HELPERS
# ════════════════════════════════════════════════════════════
async def cancel_task(d: dict, uid: int):
    task = d.get(uid)
    if task and not task.done():
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
    d.pop(uid, None)

def schedule_task(d: dict, uid: int, coro):
    loop = asyncio.get_event_loop()
    old = d.get(uid)
    if old and not old.done():
        old.cancel()
    d[uid] = loop.create_task(coro)

# ════════════════════════════════════════════════════════════
#  STATUS XABAR — debounce
# ════════════════════════════════════════════════════════════
async def _send_final_status(client, chat_id: int, uid: int):
    """Hamma fayl yuklab bo‘lingach yakuniy status xabarini yuborish."""
    cnt = file_count(uid)
    if cnt == 0:
        return
    text = tx(uid, "files_saved", count=cnt)
    markup = InlineKeyboardMarkup([[InlineKeyboardButton(tx(uid, "ready_btn"), callback_data="zip_now")]])
    sm = await client.send_message(chat_id, text, parse_mode=enums.ParseMode.MARKDOWN, reply_markup=markup)
    # Avvalgi status xabarini yangilash o‘rniga yangi xabar saqlanadi
    state.user_status_msg[uid] = sm

async def _batch_timer_job(uid: int, chat_id: int, client):
    """1.5 sekunddan so‘ng qabul qilinmoqda xabarini yuboradi."""
    await asyncio.sleep(1.5)
    # Agar hali ham yuklanayotgan fayllar bo‘lsa va xabar yuborilmagan bo‘lsa
    if state.user_downloading.get(uid, 0) > 0 and not state.user_batch_active.get(uid, False):
        text = tx(uid, "receiving", count="")  # "count" kerak emas, lekin matn bor
        # aniq matn: "📥 *Fayllar qabul qilinmoqda...* kutib turing" (countsiz)
        msg = await client.send_message(chat_id, text, parse_mode=enums.ParseMode.MARKDOWN)
        state.user_receiving_msg[uid] = msg
        state.user_batch_active[uid] = True
    # Taymer o‘chiriladi
    state.user_batch_timer.pop(uid, None)

def schedule_batch_timer(uid: int, chat_id: int, client):
    """Birinchi fayl kelganda yoki yangi to‘plam boshlanganda 1.5 sekundlik taymer ishga tushadi."""
    # Avvalgi taymerni bekor qilamiz
    old = state.user_batch_timer.pop(uid, None)
    if old and not old.done():
        old.cancel()
    # Yangi taymer
    task = asyncio.ensure_future(_batch_timer_job(uid, chat_id, client))
    state.user_batch_timer[uid] = task

def _build_batch_result_text(lang: str, accepted: int, rejected: int, user_max: int) -> str:
    """Shared by check_batch_complete: the 'N files received / M rejected'
    status text, in the user's language. Extracted here because the same
    four message variants (uz/en × with-rejects/without-rejects) used to
    be written out twice in this file -- once here, once in the now-removed
    _send_excess_msg, which was dead code (defined but never called; the
    original author's own comment marked it as superseded)."""
    if rejected > 0:
        if lang == "uz":
            return (f"✅ *{accepted} ta fayl* qabul qilindi!\n"
                    f"❌ *{rejected} ta fayl* qabul qilinmadi ({user_max} ta limit).\n\n"
                    f"👇 ZIP yasash tugmasini bosing:")
        return (f"✅ *{accepted} file(s)* received!\n"
                f"❌ *{rejected} file(s)* rejected ({user_max} file limit).\n\n"
                f"👇 Press Create ZIP when ready:")
    if lang == "uz":
        return (f"✅ *{accepted} ta fayl* qabul qilindi!\n\n"
                f"👇 ZIP yasash tugmasini bosing:")
    return (f"✅ *{accepted} file(s)* received!\n\n"
            f"👇 Press Create ZIP:")


async def check_batch_complete(client, uid: int, chat_id: int, user_obj):
    """Har bir fayl jarayoni tugagach chaqiriladi."""
    if state.user_downloading.get(uid, 0) > 0:
        return  # hali yuklanayotgan real fayllar bor

    # Batch tugadi – taymerni bekor qilamiz
    t = state.user_batch_timer.pop(uid, None)
    if t and not t.done():
        t.cancel()

    # "Qabul qilinmoqda..." xabarini o‘chiramiz
    recv_msg = state.user_receiving_msg.pop(uid, None)
    await safe_delete(recv_msg)

    state.user_batch_active[uid] = False

    # 🔥 YAKUNIY STATUSNI SHU YERDA ANIQ VA BITTA XABAR BILAN CHIQARAMIZ:
    accepted = file_count(uid)
    rejected = state.user_excess.pop(uid, 0) # excess_msg o'rniga shu yerda olamiz

    if accepted > 0 or rejected > 0:
        sm = state.user_status_msg.pop(uid, None)
        await safe_delete(sm)  # eski status xabarini tozalaymiz

        lang = database.get_lang(uid) or "uz"
        user_max = database.get_user_max_files(uid)
        markup = InlineKeyboardMarkup([[InlineKeyboardButton(tx(uid, "ready_btn"), callback_data="zip_now")]])
        text = _build_batch_result_text(lang, accepted, rejected, user_max)

        sent = await client.send_message(chat_id, text, parse_mode=enums.ParseMode.MARKDOWN, reply_markup=markup)
        state.user_status_msg[uid] = sent

    # Avto-zip taymerini ishga tushiramiz
    await cancel_task(state.user_auto_zip, uid)
    start_auto_zip(client, chat_id, uid, user_obj=user_obj)

async def _send_daily_limit_msg(client, chat_id: int, uid: int):
    await asyncio.sleep(2.0)
    sm = state.user_status_msg.pop(uid, None)
    await safe_delete(sm)
    max_zips, _ = database.get_user_limits(uid)
    await client.send_message(chat_id, tx(uid, "daily_limit", limit=max_zips), parse_mode=enums.ParseMode.MARKDOWN)

def schedule_limit_msg(client, chat_id: int, uid: int):
    schedule_task(state.user_limit_debounce, uid, _send_daily_limit_msg(client, chat_id, uid))

# ════════════════════════════════════════════════════════════
#  AUTO-ZIP TIMER
# ════════════════════════════════════════════════════════════
async def _auto_zip_runner(client, chat_id: int, uid: int, delay: int, user_obj=None):
    await asyncio.sleep(delay)
    if file_count(uid) == 0:
        return
    # Cancel any pending zip naming
    state.user_zip_naming.pop(uid, None)
    sm = state.user_status_msg.pop(uid, None)
    await safe_delete(sm)
    auto_name = make_zip_name(user_obj) if user_obj else f"auto_{datetime.now():%Y%m%d_%H%M%S}"
    # Imported here (not at module top) to avoid a circular import:
    # zip.py imports several functions from this module (batch.py).
    from zip_ops import create_and_send_zip
    await create_and_send_zip(client, chat_id, uid, auto_name, auto=True)

def start_auto_zip(client, chat_id: int, uid: int, delay: int = AUTO_ZIP_DELAY, user_obj=None):
    schedule_task(state.user_auto_zip, uid, _auto_zip_runner(client, chat_id, uid, delay, user_obj))
