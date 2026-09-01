"""Logger dùng chung: ghi ra console + file để dễ debug."""
import logging
import os

from app_constants import LOG_FILE, base_dir, ensure_dir

import re

_LOGGER = logging.getLogger("app")
_LOGGER.setLevel(logging.DEBUG)
_LOGGER.propagate = False

ANSI_REGEX = re.compile(r'\x1b\[[0-9;]*[a-zA-Z]')

def clean_ansi(text):
    if not text:
        return ""
    return ANSI_REGEX.sub("", str(text))


def setup_app_logging():
    """Khởi tạo FileHandler + StreamHandler một lần."""
    if _LOGGER.handlers:
        return _LOGGER

    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
    )

    try:
        log_path = os.path.join(base_dir(), LOG_FILE)
        ensure_dir(os.path.dirname(log_path))
        fh = logging.FileHandler(log_path, encoding="utf-8")
        fh.setFormatter(fmt)
        _LOGGER.addHandler(fh)
    except Exception as e:
        print(f"[LOG] Không tạo được file log: {e}")

    sh = logging.StreamHandler()
    sh.setFormatter(logging.Formatter("[%(levelname)s] %(message)s"))
    _LOGGER.addHandler(sh)
    return _LOGGER


def app_logger():
    return _LOGGER


class MyLogger:
    """Logger dành riêng cho yt-dlp; tích lũy warning & bắt luồng tiến độ stdout."""

    def __init__(self, callback=None):
        self.warnings = []
        self.callback = callback

    def debug(self, msg):
        if not msg:
            return
        clean_msg = clean_ansi(msg)
        if "[download]" in clean_msg:
            if "Got error" in clean_msg or "Retrying" in clean_msg or "more expected" in clean_msg or "Giving up" in clean_msg:
                print(f"[RETRY LOG] 🔄 {clean_msg}")
            elif "%" in clean_msg and self.callback:
                try:
                    self.callback(clean_msg)
                except Exception:
                    pass

    def warning(self, msg):
        clean_msg = clean_ansi(msg)
        if clean_msg:
            self.warnings.append(clean_msg)
            _LOGGER.warning("[YTDLP] %s", clean_msg)
            print(f"[WARNING] ⚠️ {clean_msg}")

    def error(self, msg):
        clean_msg = clean_ansi(msg)
        if clean_msg:
            _LOGGER.error("[YTDLP] %s", clean_msg)
            print(f"[ERROR] ❌ {clean_msg}")
