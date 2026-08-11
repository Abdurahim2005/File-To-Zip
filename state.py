import asyncio

from config import ORIGINAL_MAX_ZIPS_DAY, ORIGINAL_MAX_STORAGE, ORIGINAL_COMPRESSION, ORIGINAL_PW_ZIPS_DAY

# ════════════════════════════════════════════════════════════
#  RUNTIME-MUTABLE SETTINGS
#  (admin panel changes these via database.py functions using
#  `global`, so every module must do `import state` and read/write
#  `state.NAME` -- never `from state import NAME`, which would only
#  capture the value at import time and go stale.)
# ════════════════════════════════════════════════════════════
DEFAULT_ZIPS_DAY      = ORIGINAL_MAX_ZIPS_DAY
DEFAULT_STORAGE       = ORIGINAL_MAX_STORAGE
DEFAULT_COMPRESSION   = ORIGINAL_COMPRESSION
DEFAULT_PW_ZIPS_DAY   = ORIGINAL_PW_ZIPS_DAY   # "hamma uchun" standart kunlik parol-zip limiti

MAX_FILES     = 20

# ════════════════════════════════════════════════════════════
#  IN-MEMORY STATE
# ════════════════════════════════════════════════════════════
processed_messages: set = set()   # ishlangan xabar ID lari
broadcast_mode:      set  = set()
waiting_for_user_id: dict = {}
add_channel_state: dict = {}   # admin_id -> {"step": 1 yoki 2 yoki 3, "is_telegram": True/False, "is_private": True/False}
user_status_msg:     dict = {}
user_welcome_msg:    dict = {}
user_auto_zip:       dict = {}
user_debounce:       dict = {}
user_downloading:    dict = {}
user_reserved_bytes: dict = {}
user_excess:         dict = {}
user_limit_debounce: dict = {}
user_storage_rej:    dict = {}
required_channels:   dict = {}
awaiting_invite_link: dict = {}   # chat_id -> admin_id (taklif havolasi kutilmoqda)

user_donating:       dict = {}
admin_reply_to:      dict = {}
user_zip_naming:     dict = {}
user_pw_asking:      dict = {}   # uid -> {"chat_id","zip_name"} -- parol kiritilishi kutilmoqda
_user_file_locks:    dict = {}

user_batch_timer:   dict = {}   # uid -> asyncio.Task (1.5 sekundlik taymer)
user_receiving_msg: dict = {}   # uid -> "Qabul qilinmoqda..." xabari
user_batch_active:  dict = {}   # uid -> True/False (qabul jarayoni faolmi)

# Admin uchun siqish darajasi uchun vaqtinchalik saqlash
admin_comp_target:   dict = {}

# Joriy hisobni saqlovchi o'zgaruvchi (asl faylda globals()['user_base_count'] = {}
# orqali dinamik yaratilgan edi -- oddiy modul-darajasidagi dict bilan bir xil natija)
user_base_count: dict = {}

ZIP_SEMAPHORE: asyncio.Semaphore = None
