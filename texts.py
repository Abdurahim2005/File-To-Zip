import database
import state

# ════════════════════════════════════════════════════════════
#  TEXTS
# ════════════════════════════════════════════════════════════
TEXTS = {
    "uz": {
        "choose_lang": "🌍 Tilni tanlang:",
        "welcome": (
            "✅ Til saqlandi!\n\n"
            "👋 Salom, *{name}*!\n\n"
            "📦 Fayllaringizni *ZIP arxivga* yig'ib beraman.\n\n"
            "━━━━━━━━━━━━━━━\n"
            "📎 *Qanday ishlaydi:*\n"
            "① Istalgan fayl yuboring\n"
            "② «📦 ZIP yasash» tugmasini bosing\n"
            "③ Tayyor! ZIP avtomatik yaratiladi.\n\n"
            "⏱ *40 soniya* ichida tugma bosilmasa — avtozip.\n\n"
            "📋 *Cheklovlar:*\n"
            "• Max *{max_files} ta fayl* (bir ZIP uchun)\n"
            "• Max *{max_storage} MB* umumiy hajm\n"
            "• Kuniga *{max_zips} ta ZIP*"
        ),
        "files_saved":  "✅ *{count} ta fayl* qabul qilindi!\n\n👇 ZIP yasash tugmasini bosing:",
        "receiving":    "📥 *Fayllar qabul qilinmoqda...*",
        "max_files":    "⛔ *Fayl cheklovi!*\n\nBir ZIP uchun maksimal *{max_files} ta fayl*.\nHozirgi fayllarni avval ziplab oling.",
        "daily_limit":  "⛔ *Kunlik limit!*\n\nBugun *{limit} ta ZIP* limitingiz tugadi.\nErtaga yana foydalanishingiz mumkin! 😊",
        "join_required": "👋 Botdan foydalanish uchun\nquyidagi kanal(lar)ga obuna bo'ling:\n\n✅ Obuna bo'lgach «Tekshirish» tugmasini bosing.",
        "join_check_btn": "✅ Tekshirish",
        "join_ok":      "✅ Obuna tasdiqlandi!",
        "join_fail":    "❌ Hali obuna bo'lmadingiz.",
        "storage_full": "⚠️ *Xotira to'lib qoldi!*\n\n📄 Oxirgi fayl: `{last_file}`\n💾 Band: *{used}* / *{max}*\n\nZIP yasash tugmasini bosing — 40 soniyada avto-zip.",
        "ready_btn":    "📦 ZIP yasash",
        "ask_zip_name": "📝 ZIP uchun nom yuboring (30 soniya)\n_Yubormasangiz: `{default}`_",
        "zip_wait":     "⏳ *Fayllar hali yuklanmoqda...* biroz kuting.",
        "zip_queue":    "⏳ *Navbatda...* ZIP jarayoni band, kuting.",
        "zip_caption":  "📦 *ZIP tayyor!*\n🤖 @Zipla_bot — Hayotni Ziplab o't!",
        "no_files":     "⚠️ Avval fayl yuboring.",
        "zip_error":    "❌ ZIP yaratishda xato. Qaytadan urining.",
        "lang_set":     "✅ Til saqlandi!",
        "change_lang":  "🌍 Tilni o'zgartirish",
        "creating_zip": "⚙️ *ZIP yaratilmoqda...* iltimos kuting",
        "banned":       "🚫 Bloklangansiz.",
        "auto_zip_done":"🤖 *Avtomatik ZIP* yaratildi.",
        # Donate
        "donate_text": (
            "☕ *Kofe sotib oling!*\n\n"
            "Botni rivojlantirish uchun istalgan miqdorda yordam bering.\n\n"
            "━━━━━━━━━━━━━━━\n"
            "🇺🇿 *Humo:* `9860096601718388`\n"
            "💳 *Visa:* `4916990318718514`\n\n"
            "🪙 *USDT (TRC20):*\n`TAs1YHxyz8tgYYTsDYPFqdtu9VxMjWPbKw`\n\n"
            "🪙 *USDT (BEP20 / PLASMA):*\n`0x10355140b54a53188c056a29e5973a40181b21ef`\n\n"
            "━━━━━━━━━━━━━━━\n"
            "To'lov qilgach miqdor va valyutani yozing,\n«✅ Donat qildim» tugmasini bosing."
        ),
        "donate_ask":       "💬 Donat miqdori va valyutasini yozing:\nMisol: `50000 UZS` yoki `5 USDT`",
        "donate_sent":      "✅ So'rovingiz qabul qilindi! Admin tez orada tasdiqlaydi. 🙏",
        "top_donors":       "🏆 *Top Donatorlar*\n\n{list}",
        "no_donors":        "Hali hech kim donat qilmagan. Birinchi bo'ling! ☕",
        # Main keyboard buttons
        "btn_donate":       "💰 Donat",
        "btn_stats":        "📊 Statistika",
        "btn_contact":      "📞 Admin bilan bog'lanish",
        # Public stats
        "pub_stats": (
            "📊 *Bot statistikasi*\n\n"
            "👥 Jami foydalanuvchilar: *{users}*\n"
            "📅 Bugun qo'shildi: *{today}*\n\n"
            "📦 Jami ZIP: *{total_zips}*\n"
            "📊 Jami hajm: *{total_mb:.1f}* MB\n"
            "📎 Jami fayl: *{total_files}*\n\n"
            "🕐 Bugun ZIP: *{today_zips}*\n"
            "📈 Bugun hajm: *{today_mb:.1f}* MB"
        ),
        # Contact admin
        "contact_text": "📞 Admin bilan bog‘lanish uchun quyidagi tugmani bosing:",
        "admin_msg_from":   "📩 *Foydalanuvchi xabari*\n\n👤 {name}\n🆔 `{uid}`\n🔗 {username}",
        "admin_reply_ask":  "↩️ Javob yozing yoki rasm/video yuboring:",
        "admin_reply_sent": "✅ Javob yuborildi.",
        "reply_from_admin": "📬 *Admin javobi:*",
        "reply_btn":        "↩️ Javob berish",
        # ZIP naming
        "zip_name_ask":     "📝 *ZIP nomini kiriting:*\n_(Bo'sh qoldirsangiz avtomatik nom beriladi, 30 soniya ichida)_",
        "zip_name_skip":    "⏭ O'tkazib yuborish",
        # Premium
        "premium_text": (
            "⭐ *Premium haqida*\n\nPremium funksiyalar hozircha ishlab chiqilmoqda.\n\n"
            "📋 *Rejalashtirilgan imkoniyatlar:*\n"
            "• Kunlik ZIP limiti yo'q\n• Max 1 GB fayl hajmi\n"
            "• Max 100 ta fayl per ZIP\n• Ustuvor navbat\n\nQiziqasizmi? Adminga yozing!"
        ),
        "premium_info": (
    "🦯🤩 *Premium – Cheklovlarni unuting!*\n\n"
    "Oddiy foydalanuvchi bo‘lishdan charchadingizmi? "
    "Premium bilan bot imkoniyatlari cheksizlikka yaqinlashadi! 🚀\n\n"
    "━━━━━━━━━━━━━━━━━━━\n"
    "💎 *15 kunlik Premium narxlari:*\n\n"
    "🗂 *Xotira:* 300 MB → *1 GB*\n"
    "📦 *Kunlik ZIP:* 3 ta → *10 ta*\n"
    "📎 *Fayllar soni:* 20 ta → *40 ta*\n"
    "🗜 *Siqish:* Matnli fayllar uchun *O‘rta daraja*\n"
    "   _(❌ Rasm, video, pptx siqilmaydi)_\n\n"
    "━━━━━━━━━━━━━━━━━━━\n"
    "💸 *Narx:* 13 000 UZS\n"
    "🪙 *Crypto:* 1 USDT\n\n"
    "💳 *To‘lov:* Humo, Uzcard, Visa, Crypto\n\n"
    "━━━━━━━━━━━━━━━━━━━\n"
    "👮‍♂ Admin: @Abdurahim0525\n"
    "📡 Kanal: @Zipla_Bot_News\n"
    "🤖 Bot: @Zipla_bot\n\n"
    "👇 Pastdagi tugmani bosing va Premium oling!"
),
    },
    "en": {
        "choose_lang": "🌍 Choose language:",
        "welcome": (
            "✅ Language saved!\n\n"
            "👋 Hello, *{name}*!\n\n"
            "📦 I pack your files into a *ZIP archive*.\n\n"
            "━━━━━━━━━━━━━━━\n"
            "📎 *How it works:*\n"
            "① Send any files\n"
            "② Press «📦 Create ZIP»\n"
            "③ Done! ZIP is created automatically.\n\n"
            "⏱ *Auto-zipped* after 40 seconds.\n\n"
            "📋 *Limits:*\n"
            "• Max *{max_files} files* per ZIP\n"
            "• Max *{max_storage} MB* total size\n"
            "• *{max_zips} ZIPs* per day"
        ),
        "contact_text": "📞 Click the button below to contact the admin:",
        "files_saved":  "✅ *{count} file(s)* received!\n\n👇 Press Create ZIP when ready:",
        "receiving":    "📥 *Receiving files...*",
        "max_files":    "⛔ *File limit reached!*\n\nMaximum *{max_files} files* per ZIP.\nPlease ZIP current files first.",
        "daily_limit":  "⛔ *Daily limit reached!*\n\nYou've used *{limit} ZIPs* today.\nCome back tomorrow! 😊",
        "join_required": "👋 To use this bot, please join\nthe following channel(s):\n\n✅ After joining, press «Check» button.",
        "join_check_btn": "✅ Check",
        "join_ok":      "✅ Subscription confirmed!",
        "join_fail":    "❌ You haven't joined yet.",
        "storage_full": "⚠️ *Storage full!*\n\n📄 Last file: `{last_file}`\n💾 Used: *{used}* of *{max}*\n\nPress Create ZIP — auto-zip in 40 seconds.",
        "ready_btn":    "📦 Create ZIP",
        "ask_zip_name": "📝 Send a name for the ZIP (30 sec)\n_If you don't: `{default}`_",
        "zip_wait":     "⏳ *Files still uploading...* please wait.",
        "zip_queue":    "⏳ *In queue...* ZIP process is busy, please wait.",
        "zip_caption":  "📦 *ZIP is ready!*\n🤖 @Zipla_bot — Zip your life!",
        "no_files":     "⚠️ Please send files first.",
        "zip_error":    "❌ ZIP creation failed. Please try again.",
        "lang_set":     "✅ Language saved!",
        "change_lang":  "🌍 Change language",
        "creating_zip": "⚙️ *Creating ZIP...* please wait",
        "banned":       "🚫 You are blocked.",
        "auto_zip_done":"🤖 *Auto ZIP* created.",
        "donate_text": (
            "☕ *Buy me a coffee!*\n\nSupport bot development with any amount.\n\n"
            "━━━━━━━━━━━━━━━\n"
            "🇺🇿 *Uzcard:* `Hozircha yo'q,admin bilan bog'laning!`\n"
            "💳 *Visa:* `4916990318718514`\n\n"
            "🪙 *USDT (TRC20):*\n`TAs1YHxyz8tgYYTsDYPFqdtu9VxMjWPbKw`\n\n"
            "🪙 *USDT (BEP20 / PLASMA):*\n`0x10355140b54a53188c056a29e5973a40181b21ef`\n\n"
            "━━━━━━━━━━━━━━━\n"
            "After payment, type the amount and currency,\nthen press «✅ I donated»."
        ),
        "donate_ask":       "💬 Type the amount and currency:\nExample: `5 USDT` or `50000 UZS`",
        "donate_sent":      "✅ Request received! Admin will confirm soon. 🙏",
        "top_donors":       "🏆 *Top Donors*\n\n{list}",
        "no_donors":        "No donors yet. Be the first! ☕",
        "btn_donate":       "💰 Donate",
        "btn_stats":        "📊 Statistics",
        "btn_contact":      "📞 Contact admin",
        "pub_stats": (
            "📊 *Bot statistics*\n\n"
            "👥 Total users: *{users}*\n"
            "📅 Joined today: *{today}*\n\n"
            "📦 Total ZIPs: *{total_zips}*\n"
            "📊 Total size: *{total_mb:.1f}* MB\n"
            "📎 Total files: *{total_files}*\n\n"
            "🕐 Today ZIPs: *{today_zips}*\n"
            "📈 Today size: *{today_mb:.1f}* MB"
        ),
        "admin_msg_from":   "📩 *User message*\n\n👤 {name}\n🆔 `{uid}`\n🔗 {username}",
        "admin_reply_ask":  "↩️ Write your reply or send a photo/video:",
        "admin_reply_sent": "✅ Reply sent.",
        "reply_from_admin": "📬 *Reply from admin:*",
        "reply_btn":        "↩️ Reply",
        "zip_name_ask":     "📝 *Enter ZIP name:*\n_(Leave empty for auto name, 30 seconds)_",
        "zip_name_skip":    "⏭ Skip",
        "premium_info": (
            "🦯🤩 *Premium – Break All Limits!*\n\n"
            "Tired of being an ordinary user? "
            "With Premium, your bot capabilities become almost limitless! 🚀\n\n"
            "━━━━━━━━━━━━━━━━━━━\n"
            "💎 *15 Days Premium Pricing:*\n\n"
            "🗂 *Storage:* 300 MB → *1 GB*\n"
            "📦 *Daily ZIPs:* 3 → *10*\n"
            "📎 *Files per ZIP:* 20 → *40*\n"
            "🗜 *Compression:* Medium for text files\n"
            "   _(❌ Images, video, pptx excluded)_\n\n"
            "━━━━━━━━━━━━━━━━━━━\n"
            "💸 *Price:* 13 000 UZS\n"
            "🪙 *Crypto:* 1 USDT\n\n"
            "💳 *Payment:* Humo, Uzcard, Visa, Crypto\n\n"
            "━━━━━━━━━━━━━━━━━━━\n"
            "👮‍♂ Admin: @Abdurahim0525\n"
            "📡 Channel: @Zipla_Bot_News\n"
            "🤖 Bot: @Zipla_bot\n\n"
            "👇 Press the button below and get Premium!"
        ),
    },
}


def tx(uid: int, key: str, **kw) -> str:
    lang = database.get_lang(uid) or "uz"
    text = TEXTS.get(lang, TEXTS["uz"]).get(key, key)
    
    # Avtomatik o'zgaruvchilarni matnga yetkazish
    if 'max_files' not in kw:
        kw['max_files'] = database.get_user_max_files(uid) if uid else state.MAX_FILES
        
    if 'max_zips' not in kw or 'max_storage' not in kw:
        # get_user_limits(uid) funksiyangiz (max_zips, max_storage) qaytaradi deb hisoblaymiz
        max_zips, max_storage = database.get_user_limits(uid) if uid else (state.DEFAULT_ZIPS_DAY, state.DEFAULT_STORAGE)
        
        if 'max_zips' not in kw:
            kw['max_zips'] = max_zips
            
        if 'max_storage' not in kw:
            # Baytni MB ga o'giramiz: 314572800 / 1024 / 1024 = 300
            kw['max_storage'] = int(max_storage / 1024 / 1024)
            
    return text.format(**kw)
