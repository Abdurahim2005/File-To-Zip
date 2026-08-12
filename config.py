import os

# ════════════════════════════════════════════════════════════
#  CONFIG
# ════════════════════════════════════════════════════════════
API_ID    = int(os.environ["API_ID"])
API_HASH  = os.environ["API_HASH"]
BOT_TOKEN = os.environ["BOT_TOKEN"]

TURSO_URL   = os.environ.get("TURSO_URL", "")
TURSO_TOKEN = os.environ.get("TURSO_TOKEN", "")
LOCAL_DB    = "/tmp/bot_replica.db"

BASE_DIR    = "user_files"
STICKER_DIR = "stickers"
ADMIN_ID    = int(os.environ.get("ADMIN_ID", "1663567950"))
ADMIN_USERNAME = os.environ.get("ADMIN_USERNAME", "Abdurahim0525")  # @ belgisiz, masalan "ZiplaAdmin"
# Default limits
ORIGINAL_MAX_ZIPS_DAY = 3
ORIGINAL_MAX_STORAGE  = 314572800   # 300 MB
ORIGINAL_COMPRESSION  = 0           # siqilmasin
ORIGINAL_PW_ZIPS_DAY  = 1           # oddiy foydalanuvchi: kuniga 1 marta parolli zip
PREMIUM_PW_ZIPS_DAY   = 5           # premium: kuniga 5 marta parolli zip

AUTO_ZIP_DELAY = 40
DEBOUNCE_SEC  = 1.5

# Premium to'lov narxi (30 kunlik)
PREMIUM_PRICE_UZS  = 25000
PREMIUM_PRICE_USDT = 2
