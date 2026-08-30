import os
import asyncio
from datetime import datetime, timedelta

from pyrogram import filters, enums
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton

import database
import state
import texts as texts_mod
from config import ADMIN_ID, TURSO_URL, LOCAL_DB
from bot_instance import app, admin_filter
from texts import tx
from fs_utils import file_count, fmt_size, make_zip_name, total_disk_all
from helpers import safe_delete, send_sticker
from batch import cancel_task, schedule_task
from zip_ops import create_and_send_zip

@app.on_message(filters.command("admin") & filters.user(ADMIN_ID))
async def cmd_admin(client, message):
    await show_admin_panel(client, message)


async def show_admin_panel(client, message):
    s    = database.get_global_stats()
    cnt  = database.user_count()
    today = database.today_count()
    disk = fmt_size(total_disk_all())
    await send_sticker(client, message.chat.id, "admin")
    await message.reply(
        f"🔐 *Admin Panel*\n\n"
        f"👥 Jami: *{cnt}* | 📅 Bugun: *{today}*\n"
        f"💾 Disk: *{disk}* | 🗄️ `Turso`\n\n"
        f"📦 Jami ZIP: *{s['total_zips']}* (bugun: *{s['today_zips']}*)\n"
        f"📊 Jami MB: *{s['total_mb']:.1f}* (bugun: *{s['today_mb']:.1f}*)\n"
        f"📎 Jami fayl: *{s['total_files']}*",
        parse_mode=enums.ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("👥 Foydalanuvchilar",  callback_data="adm_users"),
             InlineKeyboardButton("📊 Statistika",         callback_data="adm_stats")],
            [InlineKeyboardButton("📨 Broadcast",          callback_data="adm_broadcast"),
             InlineKeyboardButton("🔍 Izlash",             callback_data="adm_search")],
            [InlineKeyboardButton("⛔ Ban",                callback_data="adm_ban"),
             InlineKeyboardButton("✅ Unban",              callback_data="adm_unban")],
            [InlineKeyboardButton("🗑️ Fayllarni tozalash", callback_data="adm_clear"),
             InlineKeyboardButton("💾 Disk",               callback_data="adm_disk")],
            [InlineKeyboardButton("📢 Kanallar",           callback_data="adm_channels"),
             InlineKeyboardButton("💰 Donatlar",           callback_data="adm_donations")],
            [InlineKeyboardButton("⚙️ Limit boshqarish",  callback_data="adm_limits"),
             InlineKeyboardButton("🔁 DB tekshirish",      callback_data="adm_volume")],
            [InlineKeyboardButton("💳 To'lovlar",          callback_data="adm_payments_menu")],
            [InlineKeyboardButton("💬 Fikr-mulohaza",      callback_data="adm_feedback_menu")],
            [InlineKeyboardButton("🏆 Top-10 (eng ko'p ZIP)", callback_data="adm_top_users")],
        ]),
    )

# ════════════════════════════════════════════════════════════
#  ADMIN PANEL (ESKI + YANGI CALLBACKLAR)
# ════════════════════════════════════════════════════════════

# --- Eski callbacklar (sizda yo'q bo'lsa kerak) ---

@app.on_callback_query(admin_filter & filters.create(lambda _, __, q: q.data == "adm_users"))
async def adm_users(client, call):
    users = database.all_users()
    if not users:
        await call.message.reply("Hech qanday foydalanuvchi yo'q.")
        await call.answer(); return
    lines = ["👥 *Foydalanuvchilar* (oxirgi 30):\n"]
    for i, (tid, fn, ln, un, lg, jd, bnnd) in enumerate(users[:30], 1):
        full  = f"{fn} {ln}".strip() or "—"
        ustr  = f"@{un}" if un else "—"
        bmark = " 🚫" if bnnd else ""
        lines.append(f"`{i}.` {full}{bmark} | {ustr}\n   🆔 `{tid}` | {lg.upper()} | {jd[:10]}")
    if len(users) > 30:
        lines.append(f"\n… va yana *{len(users)-30}* ta")
    text = "\n".join(lines)
    for chunk in [text[i:i+4000] for i in range(0, len(text), 4000)]:
        await call.message.reply(chunk, parse_mode=enums.ParseMode.MARKDOWN)
    await call.answer()

@app.on_callback_query(admin_filter & filters.create(lambda _, __, q: q.data == "adm_stats"))
async def adm_stats(client, call):
    from datetime import timedelta
    users = database.all_users()
    total = len(users)
    today_str_val = datetime.now().strftime("%Y-%m-%d")
    today_cnt = sum(1 for u in users if (u[5] or "").startswith(today_str_val))
    uz_cnt = sum(1 for u in users if u[4] == "uz")
    en_cnt = sum(1 for u in users if u[4] == "en")
    ban_cnt = sum(1 for u in users if u[6])
    s = database.get_global_stats()
    week = []
    for i in range(6, -1, -1):
        d = (datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d")
        cnt_d = sum(1 for u in users if (u[5] or "").startswith(d))
        zr = database.get_db().execute(
            "SELECT COALESCE(SUM(zip_count),0), COALESCE(SUM(total_mb),0) FROM zip_stats WHERE date=?", (d,)
        ).fetchone()
        bar = "█" * min(cnt_d, 15)
        week.append(f"`{d[5:]}` {bar} *{cnt_d}* | *{zr[0]}* zip | *{zr[1]:.1f}* MB")
    left_total = database.left_users_count()
    left_today = database.left_users_today_count()
    await call.message.reply(
        f"📊 *Statistika*\n\n👥 *{total}* | 📅 Bugun: *{today_cnt}*\n"
        f"🇺🇿 *{uz_cnt}* | 🇬🇧 *{en_cnt}* | 🚫 Ban: *{ban_cnt}*\n"
        f"🚪 Chiqib ketgan: *{left_total}* | Bugun: *{left_today}*\n\n"
        f"📦 ZIP: *{s['total_zips']}* | Bugun: *{s['today_zips']}*\n"
        f"📊 MB: *{s['total_mb']:.1f}* | Bugun: *{s['today_mb']:.1f}*\n"
        f"📎 Fayl: *{s['total_files']}*\n\n📈 *7 kun:*\n" + "\n".join(week),
        parse_mode=enums.ParseMode.MARKDOWN,
    )
    await call.answer()

@app.on_callback_query(admin_filter & filters.create(lambda _, __, q: q.data == "adm_top_users"))
async def adm_top_users(client, call):
    await call.answer()
    text = build_top_users_text(reveal_username=True)
    await call.message.reply(text, parse_mode=enums.ParseMode.MARKDOWN)


def build_top_users_text(reveal_username: bool) -> str:
    """Top-10 matnini yasaydi. reveal_username=True bo'lsa (admin panel)
    @username ko'rinadi, aks holda (oddiy foydalanuvchilar uchun) faqat
    ism ko'rsatiladi -- boshqalarning shaxsiy ma'lumoti oshkor bo'lmasin."""
    top = database.get_top_zip_users(limit=10)
    if not top:
        return "📭 Hozircha hech kim ZIP yasamagan."

    medals = ["🥇", "🥈", "🥉"]
    lines = ["🏆 *Top-10 — eng ko'p ZIP yasaganlar*\n"]
    for i, (tid, fn, un, total) in enumerate(top):
        rank = medals[i] if i < 3 else f"{i+1}."
        name = fn or "Foydalanuvchi"
        if reveal_username and un:
            lines.append(f"{rank} {name} (@{un}) — *{total}* ta ZIP")
        else:
            lines.append(f"{rank} {name} — *{total}* ta ZIP")
    return "\n".join(lines)

@app.on_callback_query(admin_filter & filters.create(lambda _, __, q: q.data == "adm_broadcast"))
async def adm_broadcast(client, call):
    state.broadcast_mode.add(ADMIN_ID)
    await call.message.reply("📨 Xabarni yozing:\n_(Bekor: /admin)_", parse_mode=enums.ParseMode.MARKDOWN)
    await call.answer()

@app.on_callback_query(admin_filter & filters.create(lambda _, __, q: q.data == "adm_search"))
async def adm_search(client, call):
    state.waiting_for_user_id[ADMIN_ID] = "info"
    await call.message.reply("🔍 Foydalanuvchi ID yoki @username yuboring:")
    await call.answer()

@app.on_callback_query(admin_filter & filters.create(lambda _, __, q: q.data == "adm_ban"))
async def adm_ban(client, call):
    state.waiting_for_user_id[ADMIN_ID] = "ban"
    await call.message.reply("⛔ Ban qilmoqchi bo'lgan foydalanuvchi *ID* sini yuboring:",
                             parse_mode=enums.ParseMode.MARKDOWN)
    await call.answer()

@app.on_callback_query(admin_filter & filters.create(lambda _, __, q: q.data == "adm_unban"))
async def adm_unban(client, call):
    state.waiting_for_user_id[ADMIN_ID] = "unban"
    await call.message.reply("✅ Blokdan chiqarmoqchi bo'lgan foydalanuvchi *ID* sini yuboring:",
                             parse_mode=enums.ParseMode.MARKDOWN)
    await call.answer()

@app.on_callback_query(admin_filter & filters.create(lambda _, __, q: q.data == "adm_clear"))
async def adm_clear(client, call):
    state.waiting_for_user_id[ADMIN_ID] = "clear"
    await call.message.reply("🗑️ Fayllarini tozalamoqchi bo'lgan foydalanuvchi *ID* sini yuboring:",
                             parse_mode=enums.ParseMode.MARKDOWN)
    await call.answer()

@app.on_callback_query(admin_filter & filters.create(lambda _, __, q: q.data == "adm_disk"))
async def adm_disk(client, call):
    rows = database.all_users_disk()
    if not rows:
        await call.message.reply("💾 Diskda hech narsa yo'q."); await call.answer(); return
    db_map = {u[0]: (u[1], u[2], u[3]) for u in database.all_users()}
    total_sz = sum(r[1] for r in rows)
    lines = [f"💾 *Disk statistikasi*\nUmumiy: *{fmt_size(total_sz)}*\n"]
    for i, (uid, used) in enumerate(rows[:30], 1):
        info = db_map.get(uid)
        name = f"{info[0]} {info[1]}".strip() if info else "Noma'lum"
        ustr = f"@{info[2]}" if (info and info[2]) else "—"
        _, ms = database.get_user_limits(uid)
        pct = used / ms * 100
        bar = "█" * min(int(pct / 5), 20)
        lines.append(f"`{i}.` {name} ({ustr})\n   🆔 `{uid}` | {fmt_size(used)} ({pct:.1f}%) {bar}")
    if len(rows) > 30:
        lines.append(f"\n… va yana *{len(rows)-30}* ta")
    text = "\n".join(lines)
    for chunk in [text[i:i+4000] for i in range(0, len(text), 4000)]:
        await call.message.reply(chunk, parse_mode=enums.ParseMode.MARKDOWN)
    await call.answer()

@app.on_callback_query(admin_filter & filters.create(lambda _, __, q: q.data == "adm_channels"))
async def adm_channels(client, call):
    channels = database.get_channels()
    
    # Matnli ro'yxat tayyorlaymiz
    if channels:
        lines = ["📢 *Majburiy kanallar:*\n"]
        for cid, info in channels.items():
            icon = "🔒" if info.get("is_private", 0) else "📢"
            link = info.get("invite_link", "—")
            line = f"• {info['title']} {icon} — `{link}` (`{cid}`)"
            
           # Maxfiy kanal uchun so'rovlar sonini qo'shamiz
            if info.get("is_private", 0) == 1:
                try:
                    # Telegram API'ga so'rov yuborib botni qiynamaymiz, 
                    # chunki Telegram botlarga buni taqiqlagan [BOT_METHOD_INVALID].
                    # O'rniga, o'zimizning bazadan shu kanalga tegishli so'rovlarni sanaymiz:
                    c = database.get_db()
                    r = c.execute(
                        "SELECT COUNT(*) FROM join_requests WHERE chat_id=?", 
                        (cid,)
                    ).fetchone()
                    count = r[0] if r else 0
                    
                    line += f" | {count} ta so'rov"
                except Exception as e:
                    print(f"🔴 BAZADAN SANASHDA XATOLIK ({cid}): {e}")
                    line += " | so'rovlarni olishda xatolik"
            lines.append(line)
        text = "\n".join(lines)
    else:
        text = "📢 Hozircha kanal qo'shilmagan."

    # O'chirish tugmalari
    btns = [[InlineKeyboardButton(f"🗑 {info['title']} o'chirish", callback_data=f"adm_rmchan_{cid}")]
            for cid, info in channels.items()]
    btns.append([InlineKeyboardButton("➕ Kanal qo'shish", callback_data="adm_addchan")])

    await call.message.reply(text, parse_mode=enums.ParseMode.MARKDOWN,
                             reply_markup=InlineKeyboardMarkup(btns))
    await call.answer()

@app.on_callback_query(admin_filter & filters.create(lambda _, __, q: q.data == "adm_addchan"))
async def adm_addchan(client, call):
    # birdaniga havola yoki username so'raymiz
    state.waiting_for_user_id[call.from_user.id] = "add_channel"
    await call.message.reply(
        "📢 Kanal havolasini yoki @username yoki chat ID sini yuboring:",
        parse_mode=enums.ParseMode.MARKDOWN
    )
    await call.answer()

# --- Kanal qo‘shish: Telegram yoki yo‘q ---
@app.on_callback_query(admin_filter & filters.create(lambda _,__,q: q.data == "addchan_tg_yes"))
async def addchan_tg_yes(client, call):
    state.add_channel_state[call.from_user.id] = {"step": 1, "is_telegram": True}
    await call.message.edit_text(
        "📢 Kanal turini tanlang:",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🌐 Publik (username bor)", callback_data="addchan_public"),
             InlineKeyboardButton("🔒 Maxfiy (private)", callback_data="addchan_private")]
        ])
    )
    await call.answer()

@app.on_callback_query(admin_filter & filters.create(lambda _,__,q: q.data == "addchan_tg_no"))
async def addchan_tg_no(client, call):
    # Telegram emas – to‘g‘ridan-to‘g‘ri havolani so‘raymiz
    state.add_channel_state[call.from_user.id] = {"step": 3, "is_telegram": False}
    await call.message.edit_text("🔗 Tashqi havolani (to‘liq URL) yuboring:")
    await call.answer()

# --- Publik yoki Maxfiy ---
@app.on_callback_query(admin_filter & filters.create(lambda _,__,q: q.data == "addchan_public"))
async def addchan_public(client, call):
    state.add_channel_state[call.from_user.id] = {"step": 2, "is_telegram": True, "is_private": False}
    await call.message.edit_text("🌐 Publik kanalning @username yoki havolasini yuboring:")
    await call.answer()

@app.on_callback_query(admin_filter & filters.create(lambda _,__,q: q.data == "addchan_private"))
async def addchan_private(client, call):
    state.add_channel_state[call.from_user.id] = {"step": 2, "is_telegram": True, "is_private": True}
    await call.message.edit_text(
        "🔒 Maxfiy kanalning **chat ID** sini yuboring:\n"
        "(Kanalga botni admin qiling, so‘ng ID ni oling)",
    )
    await call.answer()

@app.on_callback_query(admin_filter & filters.create(lambda _, __, q: q.data.startswith("adm_rmchan_")))
async def adm_rmchan(client, call):
    try:
        cid = int(call.data.split("adm_rmchan_")[1])
        info = state.required_channels.get(cid, {})
        title = info.get("title", str(cid)) if isinstance(info, dict) else str(info)
        database.remove_channel(cid)
        await call.message.reply(f"✅ *{title}* o'chirildi.", parse_mode=enums.ParseMode.MARKDOWN)
    except Exception:
        await call.answer("Xato", show_alert=True)
    await call.answer()

@app.on_callback_query(admin_filter & filters.create(lambda _, __, q: q.data == "adm_donations"))
async def adm_donations(client, call):
    pend = database.get_pending_donations()
    if not pend:
        await call.message.reply("💰 Kutilayotgan donat so'rovlar yo'q."); await call.answer(); return
    lines = ["💰 *Kutilayotgan donatlar:*\n"]
    for don_id, tid, fn, amount, currency, created in pend:
        lines.append(f"ID: `{don_id}` | {fn} (`{tid}`)\n   💵 *{amount} {currency}* | {created[:16]}")
    await call.message.reply(
        "\n".join(lines),
        parse_mode=enums.ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Tasdiqlash", callback_data="adm_confirm_don"),
             InlineKeyboardButton("❌ Bekor qilish", callback_data="adm_reject_don")],
        ]),
    )
    await call.answer()

@app.on_callback_query(admin_filter & filters.create(lambda _, __, q: q.data == "adm_confirm_don"))
async def adm_confirm_don(client, call):
    state.waiting_for_user_id[ADMIN_ID] = "confirm_donation"
    await call.message.reply("✅ Tasdiqlash uchun Don ID sini yuboring:")
    await call.answer()

@app.on_callback_query(admin_filter & filters.create(lambda _, __, q: q.data == "adm_reject_don"))
async def adm_reject_don(client, call):
    state.waiting_for_user_id[ADMIN_ID] = "reject_donation"
    await call.message.reply("❌ Bekor qilish uchun Don ID sini yuboring:")
    await call.answer()

@app.on_callback_query(admin_filter & filters.create(lambda _, __, q: q.data == "adm_volume"))
async def adm_volume_check(client, call):
    lines = [
        "🗄️ *Turso DB*\n",
        f"URL: `{TURSO_URL[:40]}...`" if TURSO_URL else "❌ Ulanmagan!",
        f"Lokal: `{LOCAL_DB}` | Mavjud: `{os.path.exists(LOCAL_DB)}`",
        f"Foydalanuvchilar: `{database.user_count()}`",
    ]
    await call.message.reply("\n".join(lines), parse_mode=enums.ParseMode.MARKDOWN); await call.answer()

# --- Yangi admin callbacks (limit boshqarish, siqish darajasi) ---

@app.on_callback_query(admin_filter & filters.create(lambda _, __, q: q.data == "adm_limits"))
async def adm_limits(client, call):
    await call.message.reply(
        "⚙️ *Limit boshqarish*\n\n"
        "Foydalanuvchi limitini o'zgartirish uchun:\n\n"
        "📦 *Kunlik ZIP limiti:* USER\\_ID va LIMIT yuboring\n"
        "💾 *Xotira limiti:* USER\\_ID va MB yuboring (1-2048)\n"
        "🔄 *Standartga qaytarish:* USER\\_ID yuboring\n"
        "🗜 *Siqish darajasi:* USER\\_ID va daraja (0,6,9)",
        parse_mode=enums.ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("📦 ZIP limitini o'zgartirish", callback_data="adm_set_zip_limit"),
             InlineKeyboardButton("💾 Xotira limitini o'zgartirish", callback_data="adm_set_storage_limit")],
            [InlineKeyboardButton("🔄 Standartga qaytarish", callback_data="adm_reset_limits")],
            [InlineKeyboardButton("🗜 Foydalanuvchi siqish darajasi", callback_data="adm_set_comp_user"),
             InlineKeyboardButton("🗜 Hamma uchun siqish darajasi", callback_data="adm_set_comp_all")],
            [InlineKeyboardButton("📦 Hamma uchun ZIP limiti", callback_data="adm_all_zip_limit"),
             InlineKeyboardButton("💾 Hamma uchun xotira limiti", callback_data="adm_all_storage_limit")],
            [InlineKeyboardButton("🔄 Hamma uchun standartga qaytarish", callback_data="adm_all_reset")],
            [InlineKeyboardButton("📎 Foydalanuvchi fayl limiti", callback_data="adm_set_file_limit"),
            InlineKeyboardButton("📎 Hamma uchun fayl limiti", callback_data="adm_all_file_limit")],
            [InlineKeyboardButton("⭐ Premium yoqish", callback_data="adm_premium_on"),
            InlineKeyboardButton("❌ Premium bekor qilish", callback_data="adm_premium_off")],
            [InlineKeyboardButton("🔐 Foydalanuvchi parol limiti", callback_data="adm_set_pw_limit"),
            InlineKeyboardButton("🔐 Hamma uchun parol limiti", callback_data="adm_all_pw_limit")],
            [InlineKeyboardButton("⭐ Premium sozlamalarini o'zgartirish", callback_data="adm_premium_settings")],
            [InlineKeyboardButton("📋 Premium foydalanuvchilar ro'yxati", callback_data="adm_premium_list")],
        ]),
    )
    await call.answer()

@app.on_callback_query(admin_filter & filters.create(lambda _, __, q: q.data == "adm_premium_on"))
async def adm_premium_on(client, call):
    state.waiting_for_user_id[ADMIN_ID] = "premium_on"
    await call.message.reply(
        "⭐ Premium yoqish uchun foydalanuvchi ID sini yuboring:",
        parse_mode=enums.ParseMode.MARKDOWN,
    )
    await call.answer()

@app.on_callback_query(admin_filter & filters.create(lambda _, __, q: q.data == "adm_premium_off"))
async def adm_premium_off(client, call):
    state.waiting_for_user_id[ADMIN_ID] = "premium_off"
    await call.message.reply(
        "❌ Premium bekor qilish uchun foydalanuvchi ID sini yuboring:",
        parse_mode=enums.ParseMode.MARKDOWN,
    )
    await call.answer()

@app.on_callback_query(admin_filter & filters.create(lambda _, __, q: q.data == "adm_set_zip_limit"))
async def adm_set_zip_limit(client, call):
    state.waiting_for_user_id[ADMIN_ID] = "set_zip_limit"
    await call.message.reply("📦 *ZIP limitini o'zgartirish*\n\nFormat: `USER_ID LIMIT`\nMisol: `123456789 10`\n\n"
                             "_(0 = cheksiz)_",
                             parse_mode=enums.ParseMode.MARKDOWN)
    await call.answer()

@app.on_callback_query(admin_filter & filters.create(lambda _, __, q: q.data == "adm_set_storage_limit"))
async def adm_set_storage_limit(client, call):
    state.waiting_for_user_id[ADMIN_ID] = "set_storage_limit"
    await call.message.reply("💾 *Xotira limitini o'zgartirish*\n\nFormat: `USER_ID MB`\nMisol: `123456789 1024`\n\n"
                             "_(1-2048 MB, ya'ni 1 MB dan 2 GB gacha)_",
                             parse_mode=enums.ParseMode.MARKDOWN)
    await call.answer()

@app.on_callback_query(admin_filter & filters.create(lambda _, __, q: q.data == "adm_all_zip_limit"))
async def adm_all_zip_limit(client, call):
    state.waiting_for_user_id[ADMIN_ID] = "set_all_zip_limit"
    await call.message.reply("📦 *Hamma uchun kunlik ZIP limiti*\n\nFaqat son yuboring.\nMisol: `10`\n\n"
                             "_(0 = cheksiz)_",
                             parse_mode=enums.ParseMode.MARKDOWN)
    await call.answer()

@app.on_callback_query(admin_filter & filters.create(lambda _, __, q: q.data == "adm_all_storage_limit"))
async def adm_all_storage_limit(client, call):
    state.waiting_for_user_id[ADMIN_ID] = "set_all_storage_limit"
    await call.message.reply("💾 *Hamma uchun xotira limiti*\n\nFaqat MB yuboring.\nMisol: `1024`\n\n"
                             "_(1-2048 MB, ya'ni 1 MB dan 2 GB gacha)_",
                             parse_mode=enums.ParseMode.MARKDOWN)
    await call.answer()

@app.on_callback_query(admin_filter & filters.create(lambda _, __, q: q.data == "adm_set_file_limit"))
async def adm_set_file_limit(client, call):
    state.waiting_for_user_id[ADMIN_ID] = "set_file_limit"
    await call.message.reply("📎 *Foydalanuvchi fayl limiti*\n\nFormat: `USER_ID LIMIT`\nMisol: `123456789 20`",
                             parse_mode=enums.ParseMode.MARKDOWN)
    await call.answer()

@app.on_callback_query(admin_filter & filters.create(lambda _, __, q: q.data == "adm_all_file_limit"))
async def adm_all_file_limit(client, call):
    state.waiting_for_user_id[ADMIN_ID] = "set_all_file_limit"
    await call.message.reply("📎 *Hamma uchun fayl limiti*\n\nFaqat son yuboring.\nMisol: `20`",
                             parse_mode=enums.ParseMode.MARKDOWN)
    await call.answer()

@app.on_callback_query(admin_filter & filters.create(lambda _, __, q: q.data == "adm_set_pw_limit"))
async def adm_set_pw_limit(client, call):
    state.waiting_for_user_id[ADMIN_ID] = "set_pw_limit"
    await call.message.reply("🔐 *Foydalanuvchi kunlik parol limiti*\n\nFormat: `USER_ID LIMIT`\nMisol: `123456789 5`",
                             parse_mode=enums.ParseMode.MARKDOWN)
    await call.answer()

@app.on_callback_query(admin_filter & filters.create(lambda _, __, q: q.data == "adm_all_pw_limit"))
async def adm_all_pw_limit(client, call):
    state.waiting_for_user_id[ADMIN_ID] = "set_all_pw_limit"
    await call.message.reply("🔐 *Hamma uchun kunlik parol limiti*\n\nFaqat son yuboring.\nMisol: `1`",
                             parse_mode=enums.ParseMode.MARKDOWN)
    await call.answer()

@app.on_callback_query(admin_filter & filters.create(lambda _, __, q: q.data == "adm_premium_settings"))
async def adm_premium_settings(client, call):
    s = database.get_premium_settings()
    state.waiting_for_user_id[ADMIN_ID] = "set_premium_settings"
    await call.message.reply(
        "⭐ *Premium sozlamalarini qayta belgilash*\n\n"
        f"Joriy qiymatlar:\n"
        f"📦 ZIP/kun: *{s['zips_day']}*\n"
        f"💾 Xotira: *{s['storage_mb']} MB*\n"
        f"📎 Fayl/ZIP: *{s['files']}*\n"
        f"🗜 Siqish: *{s['compression']}* (0/6/9)\n"
        f"🔐 Parol/kun: *{s['pw_zips_day']}*\n\n"
        "Yangi qiymatlarni shu tartibda, bo'sh joy bilan ajratib yuboring:\n"
        "`ZIP_KUN XOTIRA_MB FAYL SIQISH PAROL_KUN`\n\n"
        "Misol: `15 2048 60 6 15`\n\n"
        "_Eslatma: bu faqat yangi premium yoqilganda qo'llanadi — mavjud premium foydalanuvchilarga ta'sir qilmaydi._",
        parse_mode=enums.ParseMode.MARKDOWN,
    )
    await call.answer()

@app.on_callback_query(admin_filter & filters.create(lambda _, __, q: q.data == "adm_premium_list"))
async def adm_premium_list(client, call):
    users = database.list_premium_users()
    await call.answer()
    if not users:
        await call.message.reply("📋 Hozircha premium foydalanuvchi yo'q.")
        return

    lines = ["📋 *Premium foydalanuvchilar ro'yxati*\n"]
    for uid, started_at, expires_at in users:
        lines.append(f"👤 `{uid}`\n   🟢 Boshlangan: {started_at}\n   🔴 Tugaydi: {expires_at}")
    text = "\n\n".join(lines)

    # Telegram xabar uzunligi cheklovi -- bo'lib yuborish
    for i in range(0, len(text), 3500):
        await call.message.reply(text[i:i+3500], parse_mode=enums.ParseMode.MARKDOWN)

@app.on_callback_query(admin_filter & filters.create(lambda _, __, q: q.data == "adm_reset_limits"))
async def adm_reset_limits(client, call):
    state.waiting_for_user_id[ADMIN_ID] = "reset_limits"
    await call.message.reply("🔄 Standartga qaytarish uchun USER\\_ID yuboring:",
                             parse_mode=enums.ParseMode.MARKDOWN)
    await call.answer()

@app.on_callback_query(admin_filter & filters.create(lambda _,__,q: q.data == "adm_set_comp_user"))
async def adm_set_comp_user(client, call):
    state.waiting_for_user_id[ADMIN_ID] = "set_comp_user_uid"
    await call.message.reply("👤 Siqish darajasini o‘rnatmoqchi bo‘lgan foydalanuvchi ID sini yuboring:",
                             parse_mode=enums.ParseMode.MARKDOWN)
    await call.answer()

@app.on_callback_query(admin_filter & filters.create(lambda _,__,q: q.data == "adm_set_comp_all"))
async def adm_set_comp_all(client, call):
    await call.message.reply(
        "🗜 Hamma uchun siqish darajasini tanlang:",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("0️⃣ Oddiy (siqilmasin)", callback_data="comp_all_0"),
             InlineKeyboardButton("6️⃣ O‘rta (tezkor)", callback_data="comp_all_6"),
             InlineKeyboardButton("9️⃣ Yuqori (kuchli siqish)", callback_data="comp_all_9")]
        ])
    )
    await call.answer()

@app.on_callback_query(admin_filter & filters.create(lambda _,__,q: q.data.startswith("comp_sel_")))
async def cb_comp_user_select(client, call):
    level = int(call.data.split("_")[2])
    uid = state.admin_comp_target.pop(ADMIN_ID, None)
    if uid is None:
        await call.answer("Xatolik", show_alert=True)
        return
    database.set_user_compression(uid, level)
    await call.message.edit_text(f"✅ `{uid}` uchun siqish darajasi: {level}", parse_mode=enums.ParseMode.MARKDOWN)
    awa
