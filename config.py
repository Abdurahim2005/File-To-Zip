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

AUTO_ZIP_DELAY = 40
DEBOUNCE_SEC  = 1.5
