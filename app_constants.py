import os
import sys
import random

USER_AGENT_POOL = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36 Edg/129.0.0.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Safari/605.1.15",
]

DEFAULT_UA = USER_AGENT_POOL[0]

def get_random_user_agent():
    return random.choice(USER_AGENT_POOL)


def get_js_runtime():
    """Tự động phát hiện JavaScript Runtime (Node.js, Deno, Bun) để giải mã YouTube cipher/n-sig."""
    import shutil
    for name in ["node", "deno", "bun", "quickjs"]:
        p = shutil.which(name)
        if p:
            return {name: {}}
    candidates = [
        r"C:\nvm4w\nodejs\node.exe",
        r"C:\Program Files\nodejs\node.exe",
        r"C:\Program Files (x86)\nodejs\node.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Programs\node\node.exe"),
        os.path.expandvars(r"%APPDATA%\npm\node.exe"),
    ]
    for c in candidates:
        if os.path.exists(c):
            return {"node": {"path": c}}
    return None


BROWSER_MAP = {
    "Chrome": "chrome",
    "Edge": "edge",
    "Cốc Cốc": "chrome",
    "Firefox": "firefox",
    "Brave": "brave",
    "Opera": "opera",
}
AUTO_BROWSERS = ["edge", "chrome", "firefox", "brave", "opera"]

RESOLUTION_MAP = {
    "8K": 4320, "4K": 2160, "2K": 1440, "1440": 1440, "1080": 1080,
    "720": 720, "480": 480, "360": 360,
}

APP_NAME = "HyperMedia Downloader Pro"
DEFAULT_LIMIT = 10
DEFAULT_PARALLEL = 3
MAX_PARALLEL = 5
DEFAULT_THREADS = 4
MAX_THUMB_WORKERS = 6


def app_data_dir() -> str:
    """Thư mục lưu dữ liệu người dùng: %APPDATA%\\HyperMedia (Windows) hoặc ~/HyperMedia (fallback).
    Tất cả session, log, cookies đều lưu ở đây — không bao giờ bị mất khi di chuyển exe."""
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    path = os.path.join(base, "HyperMedia")
    os.makedirs(path, exist_ok=True)
    return path


SESSION_FILE = os.path.join(app_data_dir(), "session.json")
LOG_FILE = os.path.join(app_data_dir(), "logs", "app.log")


def base_dir():
    """Thư mục gốc: thư mục exe khi frozen, ngược lại là thư mục chạy."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.getcwd()


def migrate_legacy_data():
    """Tự động chuyển file dữ liệu cũ (nằm cạnh exe) sang %APPDATA%\\HyperMedia lần đầu chạy.
    Gọi một lần duy nhất lúc khởi động app."""
    old_base = base_dir()
    migrations = [
        (os.path.join(old_base, "session.json"),          SESSION_FILE),
        (os.path.join(old_base, "cookies", "cookies.txt"), cookies_file()),
    ]
    for src, dst in migrations:
        if os.path.exists(src) and not os.path.exists(dst):
            try:
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                import shutil
                shutil.copy2(src, dst)
                print(f"[MIGRATE] {src} -> {dst}")
            except Exception as e:
                print(f"[MIGRATE] Lỗi chuyển {src}: {e}")


def get_icon_path():
    """Đường dẫn icon cho cả script lẫn exe."""
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        m_ico = os.path.join(sys._MEIPASS, "icon", "icon.ico")
        m_png = os.path.join(sys._MEIPASS, "icon", "icon.png")
        if os.path.exists(m_ico):
            return m_ico
        if os.path.exists(m_png):
            return m_png
    base = base_dir()
    ico_path = os.path.join(base, "icon", "icon.ico")
    png_path = os.path.join(base, "icon", "icon.png")
    if os.path.exists(ico_path):
        return ico_path
    elif os.path.exists(png_path):
        return png_path
    return None


def cookies_file():
    return os.path.join(app_data_dir(), "cookies", "cookies.txt")


def ensure_dir(path):
    if path and not os.path.exists(path):
        os.makedirs(path)
    return path
