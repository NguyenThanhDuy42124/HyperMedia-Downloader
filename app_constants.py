"""Hằng số toàn cục của ứng dụng."""
import os
import sys

DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

BROWSER_MAP = {"Chrome": "chrome", "Edge": "edge", "Firefox": "firefox"}
AUTO_BROWSERS = ["chrome", "edge", "firefox"]

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

SESSION_FILE = "session.json"
LOG_FILE = "logs/app.log"


def base_dir():
    """Thư mục gốc: thư mục exe khi frozen, ngược lại là thư mục chạy."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.getcwd()


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
    return os.path.join(base_dir(), "cookies", "cookies.txt")


def ensure_dir(path):
    if path and not os.path.exists(path):
        os.makedirs(path)
    return path
