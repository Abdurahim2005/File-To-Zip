import os
import re
import threading as _threading
from datetime import datetime

from config import BASE_DIR

# ════════════════════════════════════════════════════════════
#  FILE UTILITIES
# ════════════════════════════════════════════════════════════
def user_dir(uid: int) -> str:
    p = os.path.join(BASE_DIR, str(uid))
    os.makedirs(p, exist_ok=True)
    return p

def disk_used(uid: int) -> int:
    d = user_dir(uid)
    return sum(os.path.getsize(os.path.join(d, f)) for f in os.listdir(d) if os.path.isfile(os.path.join(d, f)))

def file_count(uid: int) -> int:
    d = user_dir(uid)
    return len([f for f in os.listdir(d) if os.path.isfile(os.path.join(d, f))])

def total_disk_all() -> int:
    total = 0
    if not os.path.exists(BASE_DIR):
        return 0
    for folder in os.listdir(BASE_DIR):
        fp = os.path.join(BASE_DIR, folder)
        if os.path.isdir(fp):
            for f in os.listdir(fp):
                fpath = os.path.join(fp, f)
                if os.path.isfile(fpath):
                    total += os.path.getsize(fpath)
    return total

def all_users_disk() -> list:
    result = []
    if not os.path.exists(BASE_DIR):
        return result
    for folder in os.listdir(BASE_DIR):
        try:
            uid = int(folder)
            used = disk_used(uid)
            if used > 0:
                result.append((uid, used))
        except ValueError:
            pass
    result.sort(key=lambda x: x[1], reverse=True)
    return result

_file_counter = 0
_file_counter_lock = _threading.Lock()

def unique_path(directory: str, filename: str) -> str:
    global _file_counter
    with _file_counter_lock:
        _file_counter += 1
        counter = _file_counter
    base, ext = os.path.splitext(filename)
    stamp = datetime.now().strftime("%H%M%S_%f")
    return os.path.join(directory, f"{base}_{stamp}_{counter}{ext}")

def fmt_size(b: int) -> str:
    if b < 1024**2:
        return f"{b / 1024:.1f} KB"
    return f"{b / 1024**2:.1f} MB"

def sanitize_filename(filename: str) -> str:
    name = re.sub(r'[\\/:*?"<>|]', "_", filename)
    name = re.sub(r"\s+", "_", name)
    name = name.strip("._")
    return name if name else f"file_{datetime.now():%Y%m%d_%H%M%S}"

def sanitize_zip_name(name: str) -> str:
    """Sanitize user-provided ZIP name — allow spaces converted to underscores."""
    name = name.strip()
    name = re.sub(r'[\\/:*?"<>|]', "", name)
    name = re.sub(r"\s+", "_", name)
    name = name.strip("._")
    if not name:
        return ""
    return name[:64]  # max length

def make_zip_name(user) -> str:
    name = (user.first_name or "") + ("_" + user.last_name if user.last_name else "")
    name = re.sub(r"\s+", "_", name.strip())
    name = re.sub(r"[^\w\-]", "", name)
    if not name:
        name = f"user_{user.id}"
    stamp = datetime.now().strftime("%d%m%y_%H%M")
    return f"{name}_{stamp}"
