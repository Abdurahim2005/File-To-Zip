import os
import shutil
import asyncio
import zipfile

from pyrogram import enums

import database
import state
from texts import tx
from fs_utils import user_dir, sanitize_zip_name
from helpers import safe_delete

# ════════════════════════════════════════════════════════════
#  ZIP YASASH - SIQISH DARAJASI QO'SHILDI
# ════════════════════════════════════════════════════════════
async def create_and_send_zip(client, chat_id: int, uid: int, zip_name_raw: str, auto: bool = False):
    if state.ZIP_SEMAPHORE is None:
        state.ZIP_SEMAPHORE = asyncio.Semaphore(2)

    udir  = user_dir(uid)
    files = [f for f in os.listdir(udir) if os.path.isfile(os.path.join(udir, f))]
    if not files:
        return

    clean = sanitize_zip_name(zip_name_raw)
    if not clean:
        clean = zip_name_raw
    zip_name = f"{clean}.zip"
    zip_path = os.path.join(udir, zip_name)

    existing_sm = state.user_status_msg.get(uid)
    if existing_sm:
        try:
            await existing_sm.edit_text(tx(uid, "creating_zip"), parse_mode=enums.ParseMode.MARKDOWN)
        except Exception:
            existing_sm = None

    if not existing_sm:
        progress = await client.send_message(chat_id, tx(uid, "creating_zip"), parse_mode=enums.ParseMode.MARKDOWN)
    else:
        progress = None

    queue_msg = None
    if state.ZIP_SEMAPHORE.locked():
        queue_msg = await client.send_message(chat_id, tx(uid, "zip_queue"), parse_mode=enums.ParseMode.MARKDOWN)

    async with state.ZIP_SEMAPHORE:
        if queue_msg:
            await safe_delete(queue_msg)
        fcount = len(files)
        try:
            # Siqish darajasini olish
            comp_level = database.get_compression_level(uid)
            if comp_level == 0:
                zf_kwargs = {"compression": zipfile.ZIP_STORED}
            else:
                zf_kwargs = {"compression": zipfile.ZIP_DEFLATED, "compresslevel": comp_level}

            with zipfile.ZipFile(zip_path, "w", **zf_kwargs) as zf:
                for fname in files:
                    fpath = os.path.join(udir, fname)
                    if os.path.isfile(fpath) and fname != zip_name:
                        zf.write(fpath, arcname=fname)

            zip_size = os.path.getsize(zip_path) if os.path.exists(zip_path) else 0

            # Foydalanuvchi darajasini va tilini aniqlash
            user_max_files = database.get_user_max_files(uid)
            lang = database.get_lang(uid) or "uz"
            if user_max_files >= 40:
                level_text = "👑Level:⭐ Premium" if lang == "uz" else "👑Level:⭐ Premium"
            else:
                level_text = "🪖Level:🔹 Oddiy" if lang == "uz" else "🪖Level:🔹 Regular"

            caption  = tx(uid, "zip_caption") + f"\n\n{level_text}"
            if auto:
                caption = tx(uid, "auto_zip_done") + "\n\n" + caption
            await client.send_document(
                chat_id, zip_path,
                caption=caption, file_name=zip_name,
                parse_mode=enums.ParseMode.MARKDOWN,
            )
            database.add_zip_stat(uid, zip_size / 1024 / 1024, fcount)
        except Exception as e:
            await client.send_message(chat_id, tx(uid, "zip_error"), parse_mode=enums.ParseMode.MARKDOWN)
            return
        finally:
            await safe_delete(progress)
            sm = state.user_status_msg.pop(uid, None)
            await safe_delete(sm)
            wm = state.user_welcome_msg.pop(uid, None)
            await safe_delete(wm)

    try:
        if os.path.exists(udir):
            shutil.rmtree(udir)
            os.makedirs(udir, exist_ok=True)
    except Exception as e:
        print(f"[cleanup] {e}")

    state.user_auto_zip.pop(uid, None)
