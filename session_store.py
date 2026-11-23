"""Lưu/khôi phục danh sách đã quét (session) ra file JSON."""
import json
import os

from app_constants import SESSION_FILE


def _session_path():
    return SESSION_FILE


_DRAMA_PERSIST_KEYS = (
    "provider",
    "provider_id",
    "platform",
    "source_name",
    "source_app_id",
    "source_display_name",
    "series_id",
    "series_name",
    "episode_id",
    "episode_number",
    "access_state",
    "locked",
    "source_url",
    "subtitle_url",
    "subtitles",
    "output_dir",
    "exact_file_stem",
    "extra",
    "format_id",
    "formats_list",
    "item_index",
)


def _sanitize_headers_for_session(headers):
    if not isinstance(headers, dict):
        return {}
    return {
        str(k): str(v)
        for k, v in headers.items()
        if str(k).lower() not in ("cookie", "authorization", "token")
    }


def save_session(items):
    """items: list dict (title, url, thumb_url, heights, type, resolution, bitrate, codec + drama metadata)."""
    try:
        data = []
        for it in items:
            entry = {
                "title": it.get("title", ""),
                "url": it.get("url", ""),
                "thumb_url": it.get("thumb_url", "") or it.get("thumb", ""),
                "heights": it.get("heights", []),
                "type": it.get("type", "mp4"),
                "resolution": it.get("resolution", "best"),
                "bitrate": it.get("bitrate", "320"),
                "codec": it.get("codec", "H.264"),
            }
            for k in _DRAMA_PERSIST_KEYS:
                if k in it and it[k] is not None:
                    entry[k] = it[k]
            if isinstance(it.get("headers"), dict):
                entry["headers"] = _sanitize_headers_for_session(it["headers"])
            data.append(entry)
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