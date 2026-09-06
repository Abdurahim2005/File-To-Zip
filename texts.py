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
            "• Kuniga *{max_zips} ta ZIP*\n"
            "• Kuniga *{pw_zips} ta parolli ZIP* 🔐"
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
        "ask_pw_yesno": "🔐 ZIP'ga parol qo'yishni xohlaysizmi?",
        "pw_yes_btn":   "🔐 Ha, parol qo'yaman",
        "pw_no_btn":    "📦 Yo'q, oddiy ziplansin",
        "ask_password": "🔑 ZIP uchun parol yuboring (30 soniya)\n_Yubormasangiz: parolsiz ziplanadi_",
        "pw_limit_over": "⚠️ Bugungi parol qo'yish imkoniyatingiz tugadi.\n📦 Oddiy ziplab beraman.",
        "pw_left":      "🔐 Bugun yana *{left}* marta parol qo'yish imkoniyatingiz bor.",
        "zip_pw_locked": "🔐 *Ushbu ZIP parol bilan qulflangan*",

        # To'lov
        "btn_get_premium":   "⭐ 30 kunlik Premium olish",
        "choose_payment_method": "💳 To'lov usulini tanlang:",
        "btn_card":   "💳 Karta orqali",
        "btn_crypto": "🪙 Kripto orqali",
        "btn_cancel": "❌ Bekor qilish",
        "no_active_cards":  "⚠️ Hozircha faol karta yo'q. Admin bilan bog'laning.",
        "no_active_tokens": "⚠️ Hozircha faol kripto token yo'q. Admin bilan bog'laning.",
        "no_active_networks": "⚠️ Bu token uchun faol tarmoq yo'q. Admin bilan bog'laning.",
        "choose_card":  "💳 Kartani tanlang:",
        "choose_token": "🪙 Tokenni tanlang:",
        "choose_network": "🌐 *{token}* uchun tarmoqni tanlang:",
        "card_details": (
            "💳 *To'lov ma'lumotlari*\n\n"
            "🏦 Bank: *{bank}*\n"
            "💳 Karta: `{number}`\n"
            "👤 Egasi: *{owner}*\n\n"
            "💰 To'lov summasi: *{amount:,} so'm*\n\n"
            "Toʻlovni amalga oshirgach, pastdagi «✅ Toʻladim» tugmasini bosing."
        ),
        "network_details_usdt": (
            "🪙 *{token} ({network})* orqali to'lov\n\n"
            "📮 Manzil: `{address}`\n\n"
            "💰 To'lov summasi: *{amount} USDT*\n\n"
            "⚠️ *Diqqat:* faqat shu manzilga *{token} ({network})* tarmog'ida to'lov yuboring. "
            "Boshqa token yoki tarmoqda yuborilgan mablag' qaytarilmaydi.\n\n"
            "Toʻlovni amalga oshirgach, pastdagi «✅ Toʻladim» tugmasini bosing."
        ),
        "network_details_other": (
            "🪙 *{token} ({network})* orqali to'lov\n\n"
            "📮 Manzil: `{address}`\n\n"
            "💰 To'lov summasi: *{amount} USDT* ga teng qiymatda\n\n"
            "⚠️ *Diqqat:* bu manzilga faqat *{token} ({network})* tarmog'ida yuboring. "
            "Yuborilayotgan aktiv qiymati aynan *{amount} USDT* ga teng bo'lishi kerak.\n\n"
            "Toʻlovni amalga oshirgach, pastdagi «✅ Toʻladim» tugmasini bosing."
        ),
        "btn_i_paid": "✅ To'ladim",
        "upload_receipt": "📎 Chek (rasm yoki PDF) yuboring:",
        "invalid_receipt": "⚠️ Faqat rasm yoki PDF fayl yuboring.",
        "payment_submitted": "✅ So'rovingiz qabul qilindi (№{payment_id}).\n\n⏳ Admin tekshirib, tez orada tasdiqlaydi.",
        "payment_review": (
            "🆕 *Yangi to'lov so'rovi* №{id}\n\n"
            "👤 {user} (`{user_id}`)\n"
            "💳 Usul: {method}\n"
            "💰 Summa: {amount} {currency}\n"
            "🕒 {created_at}"
        ),
        "btn_approve": "✅ Tasdiqlash",
        "btn_reject":  "❌ Bekor qilish",
        "no_pending_payments": "📭 Hozircha kutilayotgan to'lov yo'q.",
        "payment_approved_admin": "✅ To'lov №{id} tasdiqlandi. Foydalanuvchiga Premium yoqildi.",
        "payment_rejected_admin": "❌ To'lov №{id} bekor qilindi.",
        "payment_approved_user": "🎉 To'lovingiz tasdiqlandi! Sizga 30 kunlik *Premium* yoqildi. /start bosing.",
        "payment_rejected_user": "❌ To'lovingiz (№{payment_id}) tasdiqlanmadi.\n\nSabab noaniq bo'lsa, admin bilan bog'laning.",
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
        "btn_top":          "🏆 Top-10",
        "btn_myid":         "👤 Kabinetim",
        "myid_text": (
            "👤 *Kabinetim*\n\n"
            "📛 Ism: *{name}*\n"
            "🆔 ID: `{id}`\n"
            "🏷 Daraja: *{level}*\n\n"
            "📦 Bugungi ZIP: *{today_zips}/{max_zips}*\n"
            "🔐 Bugungi parolli ZIP: *{today_pw}/{max_pw}*\n"
            "📊 Umumiy yasalgan ZIP: *{total_zips}* ta\n"
            "📁 Saqlangan fayllar: *{file_count}* ta\n"
            "💾 Xotira: *{used_storage} / {max_storage}*"
        ),
        "btn_contact":      "📞 Admin bilan bog'lanish",
        "btn_feedback":     "💬 Fikr-mulohaza",
        "fb_choose_target": "💬 Fikringizni qayerga yubormoqchisiz?",
        "fb_target_channel": "📡 Kanalga (hamma ko'radi)",
        "fb_target_admin":   "👮 Faqat adminga",
        "feedback_ask": "💬 Fikringiz, taklifingiz yoki muammoingizni yozing (link/reklama yubormang):",
        "feedback_ask_admin": "✉️ Adminga xabaringizni yozing (matn, rasm, video, hujjat, silka — hammasi mumkin):",
        "feedback_link_blocked": "⚠️ Xabaringizda link yoki @username bor. Iltimos, ularsiz qaytadan yozing:",
        "feedback_thanks": "✅ Rahmat! Fikringiz kanalga joylandi.",
        "feedback_thanks_admin": "✅ Xabaringiz adminga yuborildi.",
        "feedback_failed": "⚠️ Hozircha yubora olmadik. Birozdan so'ng qayta urinib ko'ring.",
        "feedback_banned": "🚫 Sizga fikr-mulohaza yozish cheklangan.",
        "feedback_rate_limited": "⏳ Kuniga faqat 1 marta yozish mumkin.\nKeyingi safar: *{when}*",
        "feedback_channel_post": (
            "💬 *Yangi fikr-mulohaza*\n\n"
            "👤 Kimdan: {sender}\n"
            "🆔 ID: `{user_id}`\n\n"
            "{text}"
        ),
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
    "⭐ *Premium — Cheklovlarsiz ishlang!*\n\n"
    "━━━━━━━━━━━━━━━━━━━\n"
    "💎 *30 kunlik Premium imkoniyatlari:*\n\n"
    "🗂 *Xotira:* {reg_storage} MB → *{prem_storage} MB*\n"
    "📦 *Kunlik ZIP:* {reg_zips} ta → *{prem_zips} ta*\n"
    "📎 *Fayllar soni:* {reg_files} ta → *{prem_files} ta*\n"
    "🔐 *Parolli ZIP:* {reg_pw} ta → *{prem_pw} ta* /kun\n"
    "🗜 *Siqish:* Matnli fayllar uchun *O‘rta daraja*\n"
    "   _(❌ Rasm, video, pptx siqilmaydi)_\n\n"
    "💰 *Narxi:* {price_uzs:,} so'm / {price_usdt} USDT\n\n"
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
            "• *{max_zips} ZIPs* per day\n"
            "• *{pw_zips} password ZIPs* per day 🔐"
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
        "ask_pw_yesno": "🔐 Do you want to protect the ZIP with a password?",
        "pw_yes_btn":   "🔐 Yes, set a password",
        "pw_no_btn":    "📦 No, just zip it",
        "ask_password": "🔑 Send a password for the ZIP (30 sec)\n_If you don't: it will be zipped without a password_",
        "pw_limit_over": "⚠️ You've used today's password limit.\n📦 I'll zip it without a password.",
        "pw_left":      "🔐 You have *{left}* password-protected ZIP(s) left today.",
        "zip_pw_locked": "🔐 *This ZIP is password-protected*",

        # Payment
        "btn_get_premium":   "⭐ Get 30-day Premium",
        "choose_payment_method": "💳 Choose payment method:",
        "btn_card":   "💳 By Card",
        "btn_crypto": "🪙 By Crypto",
        "btn_cancel": "❌ Cancel",
        "no_active_cards":  "⚠️ No active cards right now. Contact the admin.",
        "no_active_tokens": "⚠️ No active crypto tokens right now. Contact the admin.",
        "no_active_networks": "⚠️ No active network for this token. Contact the admin.",
        "choose_card":  "💳 Choose a card:",
        "choose_token": "🪙 Choose a token:",
        "choose_network": "🌐 Choose a network for *{token}*:",
        "card_details": (
            "💳 *Payment details*\n\n"
            "🏦 Bank: *{bank}*\n"
            "💳 Card: `{number}`\n"
            "👤 Owner: *{owner}*\n\n"
            "💰 Amount: *{amount:,} UZS*\n\n"
            "After paying, press «✅ I paid» below."
        ),
        "network_details_usdt": (
            "🪙 Payment via *{token} ({network})*\n\n"
            "📮 Address: `{address}`\n\n"
            "💰 Amount: *{amount} USDT*\n\n"
            "⚠️ *Note:* only send *{token}* on the *{network}* network to this address. "
            "Funds sent via a different token or network cannot be recovered.\n\n"
            "After paying, press «✅ I paid» below."
        ),
        "network_details_other": (
            "🪙 Payment via *{token} ({network})*\n\n"
            "📮 Address: `{address}`\n\n"
            "💰 Amount: value equal to *{amount} USDT*\n\n"
            "⚠️ *Note:* only send *{token}* on the *{network}* network to this address. "
            "The value sent must equal exactly *{amount} USDT*.\n\n"
            "After paying, press «✅ I paid» below."
        ),
        "btn_i_paid": "✅ I paid",
        "upload_receipt": "📎 Send the receipt (photo or PDF):",
        "invalid_receipt": "⚠️ Please send a photo or PDF file only.",
        "payment_submitted": "✅ Your request was submitted (#{payment_id}).\n\n⏳ The admin will review it shortly.",
        "payment_review": (
            "🆕 *New payment request* #{id}\n\n"
            "👤 {user} (`{user_id}`)\n"
            "💳 Method: {method}\n"
            "💰 Amount: {amount} {currency}\n"
            "🕒 {created_at}"
        ),
        "btn_approve": "✅ Approve",
        "btn_reject":  "❌ Reject",
        "no_pending_payments": "📭 No pending payments right now.",
        "payment_approved_admin": "✅ Payment #{id} approved. Premium activated for the user.",
        "payment_rejected_admin": "❌ Payment #{id} rejected.",
        "payment_approved_user": "🎉 Your payment was approved! You now have 30-day *Premium*. Press /start.",
        "payment_rejected_user": "❌ Your payment (#{payment_id}) was not approved.\n\nIf unclear, contact the admin.",
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
        "btn_top":          "🏆 Top-10",
        "btn_myid":         "👤 My Cabinet",
        "myid_text": (
            "👤 *My Cabinet*\n\n"
            "📛 Name: *{name}*\n"
            "🆔 ID: `{id}`\n"
            "🏷 Level: *{level}*\n\n"
            "📦 Today's ZIPs: *{today_zips}/{max_zips}*\n"
            "🔐 Today's password ZIPs: *{today_pw}/{max_pw}*\n"
            "📊 Total ZIPs created: *{total_zips}*\n"
            "📁 Stored files: *{file_count}*\n"
            "💾 Storage: *{used_storage} / {max_storage}*"
        ),
        "btn_contact":      "📞 Contact admin",
        "btn_feedback":     "💬 Feedback",
        "fb_choose_target": "💬 Where do you want to send your message?",
        "fb_target_channel": "📡 To the channel (everyone sees it)",
        "fb_target_admin":   "👮 To admin only",
        "feedback_ask": "💬 Write your feedback, suggestion, or issue (no links/ads):",
        "feedback_ask_admin": "✉️ Write your message to the admin (text, photo, video, file, link — all allowed):",
        "feedback_link_blocked": "⚠️ Your message contains a link or @username. Please rewrite without them:",
        "feedback_thanks_admin": "✅ Your message was sent to the admin.",
        "feedback_thanks": "✅ Thanks! Your feedback was posted to the channel.",
        "feedback_failed": "⚠️ Couldn't send it right now. Please try again shortly.",
        "feedback_banned": "🚫 You're restricted from sending feedback.",
        "feedback_rate_limited": "⏳ Only 1 message per day is allowed.\nNext time: *{when}*",
        "feedback_channel_post": (
            "💬 *New feedback*\n\n"
            "👤 From: {sender}\n"
            "🆔 ID: `{user_id}`\n\n"
            "{text}"
        ),
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
            "⭐ *Premium — Work Without Limits!*\n\n"
            "━━━━━━━━━━━━━━━━━━━\n"
            "💎 *30 Days Premium Benefits:*\n\n"
            "🗂 *Storage:* {reg_storage} MB → *{prem_storage} MB*\n"
            "📦 *Daily ZIPs:* {reg_zips} → *{prem_zips}*\n"
            "📎 *Files per ZIP:* {reg_files} → *{prem_files}*\n"
            "🔐 *Password ZIPs:* {reg_pw} → *{prem_pw}* /day\n"
            "🗜 *Compression:* Medium for text files\n"
            "   _(❌ Images, video, pptx excluded)_\n\n"
            "💰 *Price:* {price_uzs:,} UZS / {price_usdt} USDT\n\n"
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

    if 'pw_zips' not in kw:
        kw['pw_zips'] = database.get_user_pw_zip_limit(uid) if uid else state.DEFAULT_PW_ZIPS_DAY

    return text.format(**kw)
