from pyrogram import enums
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton

import database
import state
from texts import TEXTS
from helpers import safe_delete

# ════════════════════════════════════════════════════════════
#  SUBSCRIPTION CHECK
# ════════════════════════════════════════════════════════════
async def check_subscription(client, uid: int) -> list:
    not_joined = []
    for chat_id, info in state.required_channels.items():
        if info.get("is_external", 0) == 1:
            continue

        if info.get("is_private", 0) == 1:
            # Maxfiy kanal: 1) get_chat_member, 2) join_request bazasi
            try:
                # chat_id raqam bo'lsa uni int turiga o'tkazib tekshirishni kafolatlaymiz
                member = await client.get_chat_member(int(chat_id), uid)
                if member.status in (enums.ChatMemberStatus.MEMBER, enums.ChatMemberStatus.ADMINISTRATOR):
                    continue  # a'zo
            except Exception as e:
                # Xatolikni logga chiqaramiz, muammo nimadaligini bilish uchun:
                print(f"🔴 MAXFIY KANALDA XATOLIK ({chat_id}): {e}")

            # get_chat_member a'zo deb topmadi, bazaga qaraymiz
            r = database.get_db().execute(
                "SELECT 1 FROM join_requests WHERE telegram_id=? AND chat_id=?",
                (uid, chat_id)
            ).fetchone()
            if r:
                # So‘rov yuborgan, hali admin tasdiqlamagan bo‘lsa ham ruxsat beramiz
                continue
            not_joined.append((chat_id, info))
            continue

        # Publik kanal (avvalgidek)
        refs = []
        username = (info.get("username") or "").lstrip("@")
        if username:
            refs.append(f"@{username}")
        refs.append(chat_id)
        member = None
        for ref in refs:
            try:
                member = await client.get_chat_member(ref, uid)
                break
            except Exception:
                continue
        if member is None or member.status in (enums.ChatMemberStatus.BANNED, enums.ChatMemberStatus.LEFT):
            not_joined.append((chat_id, info))
    return not_joined
async def gate_check(client, uid: int, chat_id: int, lang: str) -> bool:
    if not state.required_channels:
        return True

    not_joined = await check_subscription(client, uid)
    if not not_joined:                     # hamma kanalga obuna bo‘lsa
        return True

    texts = TEXTS.get(lang, TEXTS["uz"])
    buttons = []

    # Faqat obuna bo‘lmagan kanallar ro‘yxati
    for cid, info in not_joined:
        if info.get("is_external", 0) == 1:
            buttons.append([InlineKeyboardButton(f"🔗 {info['title']}", url=info.get("invite_link", "https://t.me"))])
        elif info.get("is_private", 0) == 1:
            link = info.get("invite_link", "https://t.me")
            buttons.append([InlineKeyboardButton(f"🔒 {info['title']}", url=link)])
        else:
            username = (info.get("username") or "").lstrip("@")
            if username:
                buttons.append([InlineKeyboardButton(f"📢 @{username}", url=f"https://t.me/{username}")])
            elif info.get("invite_link"):
                buttons.append([InlineKeyboardButton(f"📢 {info['title']}", url=info.get("invite_link"))])

    buttons.append([InlineKeyboardButton(texts["join_check_btn"], callback_data="check_join")])

    old_welcome = state.user_welcome_msg.pop(uid, None)
    await safe_delete(old_welcome)

    await client.send_message(
        chat_id, texts["join_required"],
        parse_mode=enums.ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup(buttons),
        disable_web_page_preview=True,
    )
    return False
