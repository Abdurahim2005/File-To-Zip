from pyrogram import Client, filters

from config import API_ID, API_HASH, BOT_TOKEN, ADMIN_ID


def _is_admin(_, __, q):
    return q.from_user.id == ADMIN_ID

admin_filter = filters.create(_is_admin)

app = Client(
    "zip_bot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN
)
