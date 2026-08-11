from datetime import datetime, date

import libsql_experimental as libsql

import state
from config import (
    LOCAL_DB, TURSO_URL, TURSO_TOKEN,
    ORIGINAL_MAX_ZIPS_DAY, ORIGINAL_MAX_STORAGE, ORIGINAL_COMPRESSION,
)

# ════════════════════════════════════════════════════════════
#  TURSO DB
# ════════════════════════════════════════════════════════════
_db_conn = None

def get_db():
    global _db_conn
    if _db_conn is not None:
        return _db_conn
    if not TURSO_URL or not TURSO_TOKEN:
        raise RuntimeError("TURSO_URL va TURSO_TOKEN to'ldirilmagan!")
    _db_conn = libsql.connect(LOCAL_DB, sync_url=TURSO_URL, auth_token=TURSO_TOKEN)
    _db_conn.sync()
    print("[DB] Turso ulandi")
    return _db_conn

def db_sync():
    if _db_conn:
        try:
            _db_conn.sync()
        except Exception as e:
            print(f"[db_sync xato] {e}")

# ════════════════════════════════════════════════════════════
#  DATABASE INIT
# ════════════════════════════════════════════════════════════
def init_db():
    c = get_db()
    c.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            telegram_id INTEGER UNIQUE NOT NULL,
            first_name  TEXT    DEFAULT '',
            last_name   TEXT    DEFAULT '',
            username    TEXT    DEFAULT '',
            language    TEXT    DEFAULT 'uz',
            waiting_zip INTEGER DEFAULT 0,
            is_banned   INTEGER DEFAULT 0,
            joined_at   TEXT    NOT NULL
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS channels (
            chat_id     INTEGER PRIMARY KEY,
            title       TEXT DEFAULT '',
            username    TEXT DEFAULT '',
            invite_link TEXT DEFAULT ''
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS zip_stats (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            date        TEXT NOT NULL,
            telegram_id INTEGER NOT NULL,
            zip_count   INTEGER DEFAULT 0,
            total_mb    REAL    DEFAULT 0.0,
            file_count  INTEGER DEFAULT 0
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS donations (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            telegram_id  INTEGER NOT NULL,
            first_name   TEXT    DEFAULT '',
            amount       TEXT    DEFAULT '',
            currency     TEXT    DEFAULT '',
            confirmed    INTEGER DEFAULT 0,
            created_at   TEXT    NOT NULL,
            confirmed_at TEXT    DEFAULT ''
        )
    """)
    # user_limits jadvaliga compression_level ustunini qo'shish
    c.execute("""
        CREATE TABLE IF NOT EXISTS user_limits (
            telegram_id       INTEGER PRIMARY KEY,
            max_zips_day      INTEGER DEFAULT 3,
            max_storage_bytes INTEGER DEFAULT 314572800,
            compression_level INTEGER DEFAULT 0
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS join_requests (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            telegram_id INTEGER NOT NULL,
            chat_id     INTEGER NOT NULL,
            created_at  TEXT    NOT NULL,
            UNIQUE(telegram_id, chat_id)
        )
    """)
    # "Hamma uchun" global limitlarni doimiy saqlash uchun (redeploy'dan keyin ham yashaydi)
    c.execute("""
        CREATE TABLE IF NOT EXISTS app_settings (
            key   TEXT PRIMARY KEY,
            value INTEGER NOT NULL
        )
    """)

    # Mavjud jadvallarda eski ustunlarni qo'shish
    for col, dfn in [("waiting_zip","INTEGER DEFAULT 0"), ("is_banned","INTEGER DEFAULT 0")]:
        try: c.execute(f"ALTER TABLE users ADD COLUMN {col} {dfn}")
        except Exception: pass
    for col, dfn in [("username","TEXT DEFAULT ''"), ("invite_link","TEXT DEFAULT ''")]:
        try: c.execute(f"ALTER TABLE channels ADD COLUMN {col} {dfn}")
        except Exception: pass
    # user_limits jadvaliga compression_level qo'shish agar eski bo'lsa
    try:
        c.execute("ALTER TABLE user_limits ADD COLUMN compression_level INTEGER DEFAULT 0")
    except Exception:
        pass
    try:
        c.execute("ALTER TABLE user_limits ADD COLUMN max_files_per_zip INTEGER DEFAULT 0")
    except Exception:
        pass
    try:
        c.execute("ALTER TABLE user_limits ADD COLUMN pw_zips_day INTEGER DEFAULT NULL")
    except Exception:
        pass
    try:
        c.execute("ALTER TABLE user_limits ADD COLUMN pw_zips_used INTEGER DEFAULT 0")
    except Exception:
        pass
    try:
        c.execute("ALTER TABLE user_limits ADD COLUMN pw_zips_date TEXT DEFAULT ''")
    except Exception:
        pass
    try:
        c.execute("ALTER TABLE user_limits ADD COLUMN is_premium INTEGER DEFAULT 0")
    except Exception:
        pass
    try:
        c.execute("ALTER TABLE channels ADD COLUMN is_external INTEGER DEFAULT 0")
    except Exception:
        pass
    try:
        c.execute("ALTER TABLE channels ADD COLUMN is_private INTEGER DEFAULT 0")
    except Exception:
        pass

    # Yangi standartlarni yuklash (admin panel orqali o'zgartirilgan bo'lishi mumkin emas, shuning uchun o'zgarmas)
    # Ammo global ozgaruvchilarni joriy holatini saqlaymiz
    # (state.DEFAULT_ZIPS_DAY / state.DEFAULT_STORAGE / state.DEFAULT_COMPRESSION)
    # Mavjud bo'lgan holatda admin global limitlarni o'zgartirmagan bo'lsa, bu yerda o'zgarmas

    c.commit()
    db_sync()

    # "Hamma uchun" global limitlarni bazadan RAM'ga qaytarib yuklash
    # (redeploy bo'lganda state.py qayta import bo'lib, o'zgaruvchilar boshlang'ich
    # qiymatga qaytadi -- shu qatorlar bazada saqlangan oxirgi qiymatni tiklaydi)
    _load_app_settings()

def _load_app_settings():
    rows = get_db().execute("SELECT key, value FROM app_settings").fetchall()
    values = {k: v for k, v in rows}
    if "default_zips_day" in values:
        state.DEFAULT_ZIPS_DAY = values["default_zips_day"]
    if "default_storage_bytes" in values:
        state.DEFAULT_STORAGE = values["default_storage_bytes"]
    if "default_compression" in values:
        state.DEFAULT_COMPRESSION = values["default_compression"]
    if "max_files" in values:
        state.MAX_FILES = values["max_files"]
    if "pw_zips_day" in values:
        state.DEFAULT_PW_ZIPS_DAY = values["pw_zips_day"]
    if "prem_zips_day" in values:
        state.PREMIUM_ZIPS_DAY = values["prem_zips_day"]
    if "prem_storage_mb" in values:
        state.PREMIUM_STORAGE_MB = values["prem_storage_mb"]
    if "prem_files" in values:
        state.PREMIUM_FILES = values["prem_files"]
    if "prem_compression" in values:
        state.PREMIUM_COMPRESSION = values["prem_compression"]
    if "prem_pw_zips_day" in values:
        state.PREMIUM_PW_ZIPS_DAY = values["prem_pw_zips_day"]

def _save_app_setting(key: str, value: int):
    c = get_db()
    c.execute(
        "INSERT INTO app_settings(key,value) VALUES(?,?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, value),
    )
    c.commit(); db_sync()

# ── Users ────────────────────────────────────────────────
def upsert_user(user, lang=None):
    c = get_db()
    c.execute("""
        INSERT INTO users(telegram_id,first_name,last_name,username,language,joined_at)
        VALUES(?,?,?,?,?,?)
        ON CONFLICT(telegram_id) DO UPDATE SET
            first_name=excluded.first_name, last_name=excluded.last_name,
            username=excluded.username, language=COALESCE(?,language)
    """, (
        user.id, user.first_name or "", user.last_name or "",
        user.username or "", lang or "uz",
        datetime.now().strftime("%Y-%m-%d %H:%M:%S"), lang,
    ))
    c.commit(); db_sync()

def get_lang(uid: int):
    r = get_db().execute("SELECT language FROM users WHERE telegram_id=?", (uid,)).fetchone()
    return r[0] if r else None

def is_banned(uid: int) -> bool:
    r = get_db().execute("SELECT is_banned FROM users WHERE telegram_id=?", (uid,)).fetchone()
    return bool(r[0]) if r else False

def ban_user(uid: int):
    c = get_db(); c.execute("UPDATE users SET is_banned=1 WHERE telegram_id=?", (uid,))
    c.commit(); db_sync()

def unban_user(uid: int):
    c = get_db(); c.execute("UPDATE users SET is_banned=0 WHERE telegram_id=?", (uid,))
    c.commit(); db_sync()

def all_users() -> list:
    return get_db().execute(
        "SELECT telegram_id,first_name,last_name,username,language,joined_at,is_banned "
        "FROM users ORDER BY id DESC"
    ).fetchall()

def user_count() -> int:
    return get_db().execute("SELECT COUNT(*) FROM users").fetchone()[0]

def today_count() -> int:
    t = datetime.now().strftime("%Y-%m-%d")
    return get_db().execute("SELECT COUNT(*) FROM users WHERE joined_at LIKE ?", (f"{t}%",)).fetchone()[0]

def get_user_by_id(tid: int):
    return get_db().execute(
        "SELECT telegram_id,first_name,last_name,username,language,joined_at,is_banned "
        "FROM users WHERE telegram_id=?", (tid,)
    ).fetchone()

# ── Per-user limits ───────────────────────────────────────
def get_user_limits(uid: int) -> tuple:
    """Returns (max_zips_day, max_storage_bytes)"""
    r = get_db().execute(
        "SELECT max_zips_day, max_storage_bytes FROM user_limits WHERE telegram_id=?", (uid,)
    ).fetchone()
    if r:
        return (r[0], r[1])
    return (state.DEFAULT_ZIPS_DAY, state.DEFAULT_STORAGE)

def get_compression_level(uid: int) -> int:
    r = get_db().execute("SELECT compression_level FROM user_limits WHERE telegram_id=?", (uid,)).fetchone()
    if r:
        return r[0]
    return state.DEFAULT_COMPRESSION

def set_user_zip_limit(uid: int, limit: int):
    c = get_db()
    existing = c.execute("SELECT telegram_id FROM user_limits WHERE telegram_id=?", (uid,)).fetchone()
    if existing:
        c.execute("UPDATE user_limits SET max_zips_day=? WHERE telegram_id=?", (limit, uid))
    else:
        c.execute("INSERT INTO user_limits(telegram_id,max_zips_day,max_storage_bytes,compression_level) VALUES(?,?,?,?)",
                  (uid, limit, state.DEFAULT_STORAGE, state.DEFAULT_COMPRESSION))
    c.commit(); db_sync()

def set_user_storage_limit(uid: int, storage_bytes: int):
    c = get_db()
    existing = c.execute("SELECT telegram_id FROM user_limits WHERE telegram_id=?", (uid,)).fetchone()
    if existing:
        c.execute("UPDATE user_limits SET max_storage_bytes=? WHERE telegram_id=?", (storage_bytes, uid))
    else:
        c.execute("INSERT INTO user_limits(telegram_id,max_zips_day,max_storage_bytes,compression_level) VALUES(?,?,?,?)",
                  (uid, state.DEFAULT_ZIPS_DAY, storage_bytes, state.DEFAULT_COMPRESSION))
    c.commit(); db_sync()

def set_user_compression(uid: int, level: int):
    c = get_db()
    existing = c.execute("SELECT telegram_id FROM user_limits WHERE telegram_id=?", (uid,)).fetchone()
    if existing:
        c.execute("UPDATE user_limits SET compression_level=? WHERE telegram_id=?", (level, uid))
    else:
        c.execute("INSERT INTO user_limits(telegram_id,max_zips_day,max_storage_bytes,compression_level) VALUES(?,?,?,?)",
                  (uid, state.DEFAULT_ZIPS_DAY, state.DEFAULT_STORAGE, level))
    c.commit(); db_sync()

def set_all_users_compression(level: int):
    c = get_db()
    # Barcha mavjud foydalanuvchilar uchun yangilash
    c.execute("UPDATE user_limits SET compression_level=?", (level,))
    state.DEFAULT_COMPRESSION = level
    c.commit(); db_sync()
    _save_app_setting("default_compression", level)

def set_all_users_zip_limit(limit: int):
    c = get_db()
    c.execute("UPDATE user_limits SET max_zips_day=?", (limit,))
    state.DEFAULT_ZIPS_DAY = limit
    c.commit(); db_sync()
    _save_app_setting("default_zips_day", limit)

def set_all_users_storage_limit(mb: int):
    storage_bytes = mb * 1024 * 1024
    c = get_db()
    c.execute("UPDATE user_limits SET max_storage_bytes=?", (storage_bytes,))
    state.DEFAULT_STORAGE = storage_bytes
    c.commit(); db_sync()
    _save_app_setting("default_storage_bytes", storage_bytes)

def reset_all_limits():
    c = get_db()
    c.execute("DELETE FROM user_limits")
    state.DEFAULT_ZIPS_DAY = ORIGINAL_MAX_ZIPS_DAY
    state.DEFAULT_STORAGE = ORIGINAL_MAX_STORAGE
    state.DEFAULT_COMPRESSION = ORIGINAL_COMPRESSION
    state.MAX_FILES = 20
    from config import ORIGINAL_PW_ZIPS_DAY
    state.DEFAULT_PW_ZIPS_DAY = ORIGINAL_PW_ZIPS_DAY
    c.execute("DELETE FROM app_settings")
    c.commit(); db_sync()

def reset_user_limits(uid: int):
    c = get_db()
    c.execute("DELETE FROM user_limits WHERE telegram_id=?", (uid,))
    c.commit(); db_sync()
    
def get_user_max_files(uid: int) -> int:
    """Foydalanuvchi uchun bir ZIPdagi maksimal fayl sonini qaytaradi."""
    r = get_db().execute(
        "SELECT max_files_per_zip FROM user_limits WHERE telegram_id=?", (uid,)
    ).fetchone()
    # Agar 0 yoki NULL bo‘lsa, global MAX_FILES qaytariladi
    if r and r[0] and r[0] > 0:
        return r[0]
    return state.MAX_FILES

def set_user_max_files(uid: int, limit: int):
    """Foydalanuvchi uchun fayl soni limitini o‘rnatish."""
    c = get_db()
    existing = c.execute("SELECT telegram_id FROM user_limits WHERE telegram_id=?", (uid,)).fetchone()
    if existing:
        c.execute("UPDATE user_limits SET max_files_per_zip=? WHERE telegram_id=?", (limit, uid))
    else:
        c.execute("INSERT INTO user_limits(telegram_id,max_zips_day,max_storage_bytes,compression_level,max_files_per_zip) VALUES(?,?,?,?,?)",
                  (uid, state.DEFAULT_ZIPS_DAY, state.DEFAULT_STORAGE, state.DEFAULT_COMPRESSION, limit))
    c.commit(); db_sync()

def set_all_users_max_files(limit: int):
    """Hamma foydalanuvchilar uchun fayl limitini yangilash."""
    c = get_db()
    c.execute("UPDATE user_limits SET max_files_per_zip=?", (limit,))
    state.MAX_FILES = limit
    c.commit(); db_sync()
    _save_app_setting("max_files", limit)

# ── Channels ─────────────────────────────────────────────
def _load_channels():
    rows = get_db().execute(
        "SELECT chat_id, title, username, invite_link, COALESCE(is_external,0), COALESCE(is_private,0) FROM channels"
    ).fetchall()
    state.required_channels.clear()
    for r in rows:
        state.required_channels[r[0]] = {
            "title": r[1] or "",
            "username": (r[2] or "").lstrip("@"),
            "invite_link": r[3] or "",
            "is_external": r[4],
            "is_private": r[5],
        }

def add_channel(chat_id: int, title: str, username: str = "", invite_link: str = "", is_external: int = 0, is_private: int = 0):
    username = (username or "").lstrip("@")
    c = get_db()
    c.execute("INSERT OR REPLACE INTO channels(chat_id,title,username,invite_link,is_external,is_private) VALUES(?,?,?,?,?,?)",
              (chat_id, title, username, invite_link, is_external, is_private))
    c.commit(); db_sync()
    state.required_channels[chat_id] = {
        "title": title, "username": username, "invite_link": invite_link,
        "is_external": is_external, "is_private": is_private
    }

def remove_channel(chat_id: int):
    c = get_db(); c.execute("DELETE FROM channels WHERE chat_id=?", (chat_id,))
    c.commit(); db_sync(); state.required_channels.pop(chat_id, None)

def get_channels() -> dict:
    return {cid: data.copy() for cid, data in state.required_channels.items()}

# ── ZIP statistikasi ─────────────────────────────────────
def today_str() -> str:
    return date.today().isoformat()

def get_daily_zip_count(uid: int) -> int:
    r = get_db().execute(
        "SELECT zip_count FROM zip_stats WHERE date=? AND telegram_id=?", (today_str(), uid)
    ).fetchone()
    return r[0] if r else 0

def add_zip_stat(uid: int, mb: float, fcount: int):
    c = get_db(); d = today_str()
    existing = c.execute(
        "SELECT id FROM zip_stats WHERE date=? AND telegram_id=?", (d, uid)
    ).fetchone()
    if existing:
        c.execute("UPDATE zip_stats SET zip_count=zip_count+1, total_mb=total_mb+?, file_count=file_count+? WHERE id=?",
                  (mb, fcount, existing[0]))
    else:
        c.execute("INSERT INTO zip_stats(date,telegram_id,zip_count,total_mb,file_count) VALUES(?,?,1,?,?)",
                  (d, uid, mb, fcount))
    c.commit(); db_sync()

def get_global_stats() -> dict:
    c = get_db(); today = today_str()
    return {
        "total_zips":  c.execute("SELECT COALESCE(SUM(zip_count),0) FROM zip_stats").fetchone()[0],
        "today_zips":  c.execute("SELECT COALESCE(SUM(zip_count),0) FROM zip_stats WHERE date=?", (today,)).fetchone()[0],
        "total_mb":    c.execute("SELECT COALESCE(SUM(total_mb),0) FROM zip_stats").fetchone()[0],
        "today_mb":    c.execute("SELECT COALESCE(SUM(total_mb),0) FROM zip_stats WHERE date=?", (today,)).fetchone()[0],
        "total_files": c.execute("SELECT COALESCE(SUM(file_count),0) FROM zip_stats").fetchone()[0],
    }

# ── Donations ────────────────────────────────────────────
def add_donation(uid: int, first_name: str, amount: str, currency: str) -> int:
    c = get_db()
    c.execute("INSERT INTO donations(telegram_id,first_name,amount,currency,created_at) VALUES(?,?,?,?,?)",
              (uid, first_name, amount, currency, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
    c.commit(); db_sync()
    return c.execute("SELECT last_insert_rowid()").fetchone()[0]

def confirm_donation(donation_id: int):
    c = get_db()
    c.execute("UPDATE donations SET confirmed=1, confirmed_at=? WHERE id=?",
              (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), donation_id))
    c.commit(); db_sync()

def reject_donation(donation_id: int):
    c = get_db()
    c.execute("DELETE FROM donations WHERE id=? AND confirmed=0", (donation_id,))
    c.commit(); db_sync()

def get_top_donors(limit: int = 10) -> list:
    return get_db().execute(
        "SELECT telegram_id, first_name, GROUP_CONCAT(amount||' '||currency, ', '), COUNT(*) "
        "FROM donations WHERE confirmed=1 GROUP BY telegram_id ORDER BY COUNT(*) DESC LIMIT ?", (limit,)
    ).fetchall()

def get_pending_donations() -> list:
    return get_db().execute(
        "SELECT id, telegram_id, first_name, amount, currency, created_at "
        "FROM donations WHERE confirmed=0 ORDER BY id DESC LIMIT 20"
    ).fetchall()

# ════════════════════════════════════════════════════════════
#  ZIPGA PAROL QO'YISH -- kunlik limit boshqaruvi
# ════════════════════════════════════════════════════════════
def is_premium(uid: int) -> bool:
    r = get_db().execute(
        "SELECT is_premium FROM user_limits WHERE telegram_id=?", (uid,)
    ).fetchone()
    return bool(r and r[0])

def get_user_pw_zip_limit(uid: int) -> int:
    """Foydalanuvchining kunlik parol-zip limitini qaytaradi.
    Individual sozlangan bo'lsa o'shani, aks holda global standartni ishlatadi."""
    r = get_db().execute(
        "SELECT pw_zips_day FROM user_limits WHERE telegram_id=?", (uid,)
    ).fetchone()
    if r and r[0] is not None:
        return r[0]
    return state.DEFAULT_PW_ZIPS_DAY

def get_pw_zips_used_today(uid: int) -> int:
    today = datetime.now().strftime("%Y-%m-%d")
    r = get_db().execute(
        "SELECT pw_zips_used, pw_zips_date FROM user_limits WHERE telegram_id=?", (uid,)
    ).fetchone()
    if not r:
        return 0
    used, saved_date = r
    if saved_date != today:
        return 0
    return used or 0

def can_use_pw_zip_today(uid: int) -> bool:
    return get_pw_zips_used_today(uid) < get_user_pw_zip_limit(uid)

def register_pw_zip_used(uid: int):
    """Bugungi parol-zip hisoblagichini +1 qiladi (kun almashsa 0 dan boshlaydi)."""
    today = datetime.now().strftime("%Y-%m-%d")
    c = get_db()
    existing = c.execute("SELECT telegram_id, pw_zips_used, pw_zips_date FROM user_limits WHERE telegram_id=?", (uid,)).fetchone()
    if not existing:
        c.execute(
            "INSERT INTO user_limits(telegram_id,max_zips_day,max_storage_bytes,compression_level,pw_zips_used,pw_zips_date) "
            "VALUES(?,?,?,?,?,?)",
            (uid, state.DEFAULT_ZIPS_DAY, state.DEFAULT_STORAGE, state.DEFAULT_COMPRESSION, 1, today),
        )
    else:
        _, used, saved_date = existing
        new_used = 1 if saved_date != today else (used or 0) + 1
        c.execute("UPDATE user_limits SET pw_zips_used=?, pw_zips_date=? WHERE telegram_id=?", (new_used, today, uid))
    c.commit(); db_sync()

def set_user_pw_zip_limit(uid: int, limit: int):
    """Bitta foydalanuvchi uchun kunlik parol-zip limitini o'rnatish."""
    c = get_db()
    existing = c.execute("SELECT telegram_id FROM user_limits WHERE telegram_id=?", (uid,)).fetchone()
    if existing:
        c.execute("UPDATE user_limits SET pw_zips_day=? WHERE telegram_id=?", (limit, uid))
    else:
        c.execute(
            "INSERT INTO user_limits(telegram_id,max_zips_day,max_storage_bytes,compression_level,pw_zips_day) "
            "VALUES(?,?,?,?,?)",
            (uid, state.DEFAULT_ZIPS_DAY, state.DEFAULT_STORAGE, state.DEFAULT_COMPRESSION, limit),
        )
    c.commit(); db_sync()

def set_all_users_pw_zip_limit(limit: int):
    """Hamma uchun (individual sozlanmagan) standart kunlik parol-zip limitini o'rnatish."""
    state.DEFAULT_PW_ZIPS_DAY = limit
    c = get_db()
    # faqat individual moslashtirilmagan foydalanuvchilarga (NULL) global qiymat ta'sir qiladi -- bu tabiiy ravishda ishlaydi
    c.commit(); db_sync()
    _save_app_setting("pw_zips_day", limit)

def set_user_premium(uid: int, premium: bool):
    c = get_db()
    existing = c.execute("SELECT telegram_id FROM user_limits WHERE telegram_id=?", (uid,)).fetchone()
    val = 1 if premium else 0
    if existing:
        c.execute("UPDATE user_limits SET is_premium=? WHERE telegram_id=?", (val, uid))
    else:
        c.execute(
            "INSERT INTO user_limits(telegram_id,max_zips_day,max_storage_bytes,compression_level,is_premium) "
            "VALUES(?,?,?,?,?)",
            (uid, state.DEFAULT_ZIPS_DAY, state.DEFAULT_STORAGE, state.DEFAULT_COMPRESSION, val),
        )
    c.commit(); db_sync()

# ════════════════════════════════════════════════════════════
#  PREMIUM SOZLAMALARI (admin panel orqali qayta belgilanadi, bazada saqlanadi)
# ════════════════════════════════════════════════════════════
def get_premium_settings() -> dict:
    return {
        "zips_day":   state.PREMIUM_ZIPS_DAY,
        "storage_mb": state.PREMIUM_STORAGE_MB,
        "files":      state.PREMIUM_FILES,
        "compression": state.PREMIUM_COMPRESSION,
        "pw_zips_day": state.PREMIUM_PW_ZIPS_DAY,
    }

def set_premium_settings(zips_day: int, storage_mb: int, files: int, compression: int, pw_zips_day: int):
    state.PREMIUM_ZIPS_DAY = zips_day
    state.PREMIUM_STORAGE_MB = storage_mb
    state.PREMIUM_FILES = files
    state.PREMIUM_COMPRESSION = compression
    state.PREMIUM_PW_ZIPS_DAY = pw_zips_day
    _save_app_setting("prem_zips_day", zips_day)
    _save_app_setting("prem_storage_mb", storage_mb)
    _save_app_setting("prem_files", files)
    _save_app_setting("prem_compression", compression)
    _save_app_setting("prem_pw_zips_day", pw_zips_day)

def apply_premium(uid: int):
    """Joriy saqlangan Premium sozlamalarini foydalanuvchiga o'rnatadi."""
    s = get_premium_settings()
    set_user_zip_limit(uid, s["zips_day"])
    set_user_storage_limit(uid, s["storage_mb"] * 1024 * 1024)
    set_user_max_files(uid, s["files"])
    set_user_compression(uid, s["compression"])
    set_user_pw_zip_limit(uid, s["pw_zips_day"])
    set_user_premium(uid, True)
