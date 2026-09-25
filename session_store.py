"""Lưu/khôi phục danh sách đã quét (session) ra file JSON."""
import json
import os

from app_constants import SESSION_FILE


def _session_path():
    return SESSION_FILE


def save_session(items):
    """items: list dict (title, url, thumb_url, heights, type, resolution, bitrate, codec)."""
    try:
        data = []
        for it in items:
            data.append(
                {
                    "title": it.get("title", ""),
                    "url": it.get("url", ""),
                    "thumb_url": it.get("thumb_url", ""),
                    "heights": it.get("heights", []),
                    "type": it.get("type", "mp4"),
                    "resolution": it.get("resolution", "best"),
                    "bitrate": it.get("bitrate", "320"),
                    "codec": it.get("codec", "H.264"),
                }
            )
        with open(_session_path(), "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
    except Exception as e:
        print(f"[SESSION] Lỗi lưu session: {e}")


def load_session():
    if not os.path.exists(_session_path()):
        return []
    try:
        with open(_session_path(), "r", encoding="utf-8") as f:
            data = json.load(f)
        return [it for it in data if isinstance(it, dict) and it.get("url")]
    except Exception as e:
        print(f"[SESSION] Lỗi đọc session: {e}")
        return []