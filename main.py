import os
import threading

from flask import Flask

import database
import state
from config import BASE_DIR, STICKER_DIR
from bot_instance import app
from fs_utils import fmt_size, total_disk_all

# Importing these registers every handler on `app` as a side effect of
# their @app.on_message / @app.on_callback_query decorators.
from handlers import media, user_commands, text_router, admin  # noqa: F401

# ════════════════════════════════════════════════════════════
#  FLASK — keep-alive
# ════════════════════════════════════════════════════════════
def keep_alive():
    flask_app = Flask(__name__)
    @flask_app.route("/")
    def home():
        s = database.get_global_stats()
        return (f"Bot ishlayapti! Foydalanuvchilar: {database.user_count()} | "
                f"Jami ZIP: {s['total_zips']} | {fmt_size(total_disk_all())} disk")
    port = int(os.environ.get("PORT", 5000))
    flask_app.run(host="0.0.0.0", port=port)

# ════════════════════════════════════════════════════════════
#  MAIN
# ════════════════════════════════════════════════════════════
if __name__ == "__main__":
    if not all([os.environ.get("API_ID"), os.environ.get("API_HASH"), os.environ.get("BOT_TOKEN")]):
        raise RuntimeError("API_ID, API_HASH, BOT_TOKEN to'ldirilmagan!")
    database.get_db(); database.init_db(); database._load_channels()
    os.makedirs(BASE_DIR, exist_ok=True)
    os.makedirs(STICKER_DIR, exist_ok=True)
    print(f"[BOT] Tayyorlanmoqda... Kanallar: {len(state.required_channels)}")
    threading.Thread(target=keep_alive, daemon=True).start()
    print("[BOT] Ishga tushdi!")
    app.run()
