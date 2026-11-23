"""
providers/miniapp_douyin_client.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
MiniApp Douyin (họ duolai) API Client & Quản lý phiên bảo mật bằng Windows DPAPI.
Tương thích hoàn toàn kiến trúc Free-first:
- Quản lý phiên cookie độc lập, lưu trữ mã hóa qua DPAPI (CryptProtectData).
- Allowlist nghiêm ngặt chỉ chấp nhận cookie Douyin (.douyin.com).
- Che giấu và không bao giờ ghi cookie/token vào log.
- Mã hóa tham số l_sign và giải mã r_sign bằng AES-128-CBC.
- Hỗ trợ tải stream MP4 trực tiếp hoặc giải mã HLS Antihook.
"""

import ctypes
import ctypes.wintypes
import hashlib
import json
import os
import re
import shutil
import subprocess
import threading
import time
import uuid
from typing import Any, Callable, Dict, List, Optional, Tuple
from urllib.parse import urljoin, urlparse

import requests
from Cryptodome.Cipher import AES
from ca_bundle_utils import get_ca_bundle_path, sanitize_error_message

from app_constants import app_data_dir, ensure_dir

# Domain allowlist an toàn cho cookie
COOKIE_ALLOWED_DOMAINS = {
    "douyin.com",
    ".douyin.com",
    "www.douyin.com",
    "ma.zijieapi.com",
    "xiaoguofanxing.lizhibj.cn",
}

# Các nguồn MiniApp Douyin builtin
BUILTIN_MINIAPP_SOURCES = [
    {"name": "多来看点", "app_id": "tt5b4d2df0c47bdd2201", "adapter": "duolai"},
    {"name": "黑岩漫故事", "app_id": "tt839df5201ca3d79a01", "adapter": "duolai"},
    {"name": "金猫漫品", "app_id": "tt3eca4877a1fed32a01", "adapter": "duolai"},
    {"name": "万花故事会", "app_id": "ttbe17c8aa2121c82101", "adapter": "duolai"},
    {"name": "小七漫爽阁", "app_id": "tt48293e94d71caebe01", "adapter": "duolai"},
    {"name": "星月漫故事", "app_id": "tte1e6975b7eecc91e01", "adapter": "duolai"},
    {"name": "萌漫时空", "app_id": "tte06596d87f5402a101", "adapter": "duolai"},
]

AUTH_REALM = {
    "tt3eca4877a1fed32a01": "tt5b4d2df0c47bdd2201",
    "tt48293e94d71caebe01": "tt5b4d2df0c47bdd2201",
}

APP_VERSION = {
    "tt5b4d2df0c47bdd2201": "3.9.39",
    "tt3eca4877a1fed32a01": "3.9.39",
    "tt48293e94d71caebe01": "3.9.39",
    "tt839df5201ca3d79a01": "3.9.41",
    "ttbe17c8aa2121c82101": "3.9.41",
    "tte06596d87f5402a101": "3.9.41",
}


def auth_app(app_id: str) -> str:
    return AUTH_REALM.get(app_id, app_id)


def app_version(app_id: str, default: str = "3.9.39") -> str:
    return APP_VERSION.get(app_id, default)


# Trạng thái phiên chuẩn hóa theo kiến trúc phân tách Cookie vs MiniApp Auth
SESSION_STATE_NO_SESSION = "NO_SESSION"
SESSION_STATE_COOKIE_STORED = "COOKIE_STORED"
SESSION_STATE_SYNC_REQUESTED = "SYNC_REQUESTED"
SESSION_STATE_SYNC_RECEIVED = "SYNC_RECEIVED"
SESSION_STATE_AUTHENTICATING = "AUTHENTICATING"
SESSION_STATE_AUTHENTICATED = "AUTHENTICATED"
SESSION_STATE_SESSION_EXPIRED = "SESSION_EXPIRED"
SESSION_STATE_AUTH_FAILED = "AUTH_FAILED"
SESSION_STATE_SYNC_TIMEOUT = "SYNC_TIMEOUT"


# ==============================================================================
# 1. BẢO VỆ DỮ LIỆU & QUẢN LÝ PHIÊN (WINDOWS DPAPI)
# ==============================================================================

class DATA_BLOB(ctypes.Structure):
    _fields_ = [
        ("cbData", ctypes.wintypes.DWORD),
        ("pbData", ctypes.POINTER(ctypes.c_byte)),
    ]


def dpapi_protect(data: bytes) -> bytes:
    """Mã hóa dữ liệu bằng Windows Data Protection API (DPAPI)."""
    if not data:
        return b""
    try:
        b_data = (ctypes.c_byte * len(data)).from_buffer_copy(data)
        inp = DATA_BLOB(len(data), b_data)
        out = DATA_BLOB()
        if not ctypes.windll.crypt32.CryptProtectData(
            ctypes.byref(inp), "HM_DOUYIN_SESSION", None, None, None, 0, ctypes.byref(out)
        ):
            raise RuntimeError("CryptProtectData failed")
        res = bytes(ctypes.string_at(out.pbData, out.cbData))
        ctypes.windll.kernel32.LocalFree(out.pbData)
        return res
    except Exception:
        # Fallback an toàn nếu môi trường không phải Windows thật
        return b"PLAIN:" + data


def dpapi_unprotect(cipher: bytes) -> bytes:
    """Giải mã dữ liệu bằng Windows Data Protection API (DPAPI)."""
    if not cipher:
        return b""
    if cipher.startswith(b"PLAIN:"):
        return cipher[6:]
    try:
        b_data = (ctypes.c_byte * len(cipher)).from_buffer_copy(cipher)
        inp = DATA_BLOB(len(cipher), b_data)
        out = DATA_BLOB()
        if not ctypes.windll.crypt32.CryptUnprotectData(
            ctypes.byref(inp), None, None, None, None, 0, ctypes.byref(out)
        ):
            raise RuntimeError("CryptUnprotectData failed")
        res = bytes(ctypes.string_at(out.pbData, out.cbData))
        ctypes.windll.kernel32.LocalFree(out.pbData)
        return res
    except Exception:
        return b""


def get_douyin_session_path() -> str:
    folder = app_data_dir()
    ensure_dir(folder)
    return os.path.join(folder, "miniapp_douyin_session.dat")


def mask_sensitive(text: str) -> str:
    """Loại bỏ và che giấu thông tin nhạy cảm trước khi log ra màn hình."""
    if not text:
        return ""
    s = str(text)
    s = re.sub(r"duolai_[0-9a-zA-Z_-]{10,}", r"duolai_***REDACTED***", s)
    s = re.sub(r"(sessionid|uid_tt|passport_csrf_token)=([0-9a-zA-Z_-]+)", r"\1=***REDACTED***", s, flags=re.IGNORECASE)
    s = re.sub(r"(Bearer\s+)[0-9a-zA-Z_\-\.]+", r"\1***REDACTED***", s, flags=re.IGNORECASE)
    return s


def save_douyin_session(payload: Dict[str, Any]) -> Tuple[bool, str]:
    """Lưu phiên đồng bộ từ Extension sau khi kiểm tra allowlist và mã hóa DPAPI."""
    if not isinstance(payload, dict):
        return False, "Payload không hợp lệ"

    domain = str(payload.get("domain", "")).lower().strip()
    allowed_douyin = ("douyin.com", "iesdouyin.com")
    if not any(domain == d or domain.endswith("." + d) for d in allowed_douyin):
        return False, f"Domain không được phép: {domain}"

    cookies_data = payload.get("cookies")
    cookie_str = ""
    if isinstance(cookies_data, list):
        # Mảng cookie từ Chrome Extension: [{name: ..., value: ...}, ...]
        cookie_str = "; ".join(
            f"{c.get('name')}={c.get('value')}"
            for c in cookies_data
            if isinstance(c, dict) and c.get("name") and c.get("value")
        )
    elif isinstance(cookies_data, str):
        cookie_str = cookies_data.strip()

    if not cookie_str:
        return False, "Dữ liệu cookie rỗng"

    session_record = {
        "provider": "miniapp_douyin",
        "domain": domain,
        "cookie_str": cookie_str,
        "captured_at": payload.get("captured_at") or time.time(),
        "expires_at": payload.get("expires_at") or (time.time() + 86400 * 30),
    }

    try:
        raw_bytes = json.dumps(session_record).encode("utf-8")
        enc_bytes = dpapi_protect(raw_bytes)
        with open(get_douyin_session_path(), "wb") as f:
            f.write(enc_bytes)
        try:
            export_douyin_session_to_cookies_file()
        except Exception:
            pass
        return True, "Đã lưu phiên Douyin bảo mật qua Windows DPAPI"
    except Exception as e:
        return False, f"Lỗi lưu trữ phiên: {e}"


def load_douyin_session() -> Optional[Dict[str, Any]]:
    """Tải và giải mã phiên cookie từ tệp mã hóa DPAPI."""
    path = get_douyin_session_path()
    if not os.path.exists(path):
        return None
    try:
        with open(path, "rb") as f:
            enc_bytes = f.read()
        dec_bytes = dpapi_unprotect(enc_bytes)
        if not dec_bytes:
            return None
        return json.loads(dec_bytes.decode("utf-8"))
    except Exception:
        return None


def clear_douyin_session() -> bool:
    """Xóa bỏ phiên cookie đã lưu."""
    path = get_douyin_session_path()
    if os.path.exists(path):
        try:
            os.remove(path)
            return True
        except Exception:
            return False
    return True


def sync_session_from_cookies_file() -> int:
    """Nạp cookie Douyin từ cookies.txt có sẵn vào DPAPI nếu session hiện tại chưa hợp lệ.
    Trả về số lượng cookie đã nạp (0 nếu không tìm thấy hoặc đã hợp lệ).
    """
    from app_constants import cookies_file
    c_path = cookies_file()
    if not os.path.exists(c_path):
        return 0

    douyin_parts = []
    try:
        with open(c_path, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                parts = line.strip().split("\t")
                if len(parts) == 7 and any(d in parts[0] for d in ("douyin.com", "iesdouyin.com")):
                    name, val = parts[5], parts[6]
                    if name and val:
                        douyin_parts.append(f"{name}={val}")
    except Exception:
        return 0

    if not douyin_parts:
        return 0

    payload = {
        "provider": "miniapp_douyin",
        "domain": "douyin.com",
        "cookies": "; ".join(douyin_parts),
        "captured_at": time.time(),
        "expires_at": time.time() + 86400 * 30,
    }
    ok, _ = save_douyin_session(payload)
    return len(douyin_parts) if ok else 0


def get_douyin_session_status(
    auto_import: bool = False,
    client: Optional["MiniAppDouyinClient"] = None,
    check_mint: bool = False,
    app_id: str = "",
) -> Tuple[str, str]:
    """Trả về trạng thái: (status_code, status_message).
    Chỉ trả về 'AUTHENTICATED' khi:
    - DPAPI giải mã được session;
    - Cookie không hết hạn;
    - Có token cache còn hạn hoặc mint token thành công.
    Nếu có cookie nhưng chưa mint/xác thực token -> 'COOKIE_STORED', không dùng valid.
    """
    sess = load_douyin_session()
    if (not sess or not sess.get("cookie_str")) and auto_import:
        sync_session_from_cookies_file()
        sess = load_douyin_session()

    if not sess or not sess.get("cookie_str"):
        return SESSION_STATE_NO_SESSION, "Chưa có phiên"

    expires_at = sess.get("expires_at", 0)
    if expires_at and expires_at < time.time():
        return SESSION_STATE_SESSION_EXPIRED, "Phiên hết hạn"

    target_app = app_id or BUILTIN_MINIAPP_SOURCES[0]["app_id"]
    realm = auth_app(target_app)
    if client and hasattr(client, "token_cache") and realm in client.token_cache:
        cached = client.token_cache[realm]
        if cached.get("expires_at", 0) > time.time() + 60 and cached.get("token"):
            return SESSION_STATE_AUTHENTICATED, "Đã kết nối"

    if check_mint and client:
        tok, msg = client.mint_token(target_app, force=False)
        if tok:
            return SESSION_STATE_AUTHENTICATED, "Đã kết nối"
        return SESSION_STATE_AUTH_FAILED, f"Xác thực thất bại: {msg}"

    # Có cookie nhưng chưa mint/xác thực token -> COOKIE_STORED
    return SESSION_STATE_COOKIE_STORED, "Đã lưu cookie"


def export_douyin_session_to_cookies_file() -> int:
    """Xuất cookie Douyin từ phiên DPAPI sang tệp cookies.txt (định dạng Netscape chuẩn)
    để yt-dlp có thể sử dụng khi tải video Douyin mà không bị ArgusSecurityPlugin chặn 403.
    """
    from app_constants import cookies_file, ensure_dir
    sess = load_douyin_session()
    if not sess or not sess.get("cookie_str"):
        return 0

    cookie_str = sess.get("cookie_str", "")
    pairs = [c.strip() for c in cookie_str.split(";") if "=" in c]
    if not pairs:
        return 0

    c_path = cookies_file()
    ensure_dir(os.path.dirname(c_path))

    header_lines = []
    cookie_map = {}

    if os.path.exists(c_path):
        try:
            with open(c_path, "r", encoding="utf-8", errors="ignore") as f:
                for line in f.read().splitlines():
                    line_s = line.strip()
                    if not line_s or line.startswith("#"):
                        if not header_lines and line.startswith("#"):
                            header_lines.append(line)
                        continue
                    parts = line.split("\t")
                    if len(parts) == 7:
                        key = (parts[0].lower(), parts[2], parts[5])
                        cookie_map[key] = line
        except Exception:
            pass

    if not header_lines:
        header_lines = [
            "# Netscape HTTP Cookie File",
            "# https://curl.haxx.se/rfc/cookie_spec.html",
            "# Generated by HyperMedia Helper",
        ]

    expire_ts = str(int(sess.get("expires_at") or (time.time() + 86400 * 30)))
    added = 0
    for p in pairs:
        k, v = p.split("=", 1)
        name = k.strip()
        val = v.strip()
        if not name or not val:
            continue
        line = f".douyin.com\tTRUE\t/\tFALSE\t{expire_ts}\t{name}\t{val}"
        key = (".douyin.com", "/", name)
        cookie_map[key] = line
        added += 1

    merged = "\n".join(header_lines) + "\n" + "\n".join(cookie_map.values()) + "\n"
    try:
        with open(c_path, "w", encoding="utf-8") as f:
            f.write(merged)
        return added
    except Exception:
        return 0


def extract_douyin_aweme_id(url: str) -> Optional[str]:
    """Trích xuất aweme_id từ link share hoặc video Douyin."""
    if not url:
        return None
    u = str(url).strip()
    m = re.search(r"/(?:video|share/video)/(\d+)", u)
    if m:
        return m.group(1)
    m = re.search(r"[?&](?:modal_id|aweme_id|item_id|item_ids)=(\d+)", u)
    if m:
        return m.group(1)
    m = re.search(r"^(\d{15,22})$", u)
    if m:
        return m.group(1)
    return None


def resolve_douyin_video_and_miniapp(
    url_or_id: str,
    session: Optional[requests.Session] = None,
) -> Optional[Dict[str, Any]]:
    """Phân giải URL Douyin (video/iesdouyin) để trích xuất metadata video
    và nhận diện nếu có mỏ neo MiniApp phim ngắn (họ duolai / Đa Lai / Hắc Nham...).
    """
    aweme_id = extract_douyin_aweme_id(url_or_id)
    if not aweme_id:
        return None

    sess = load_douyin_session()
    cookie_str = sess.get("cookie_str", "") if sess else ""
    if not cookie_str:
        sync_session_from_cookies_file()
        sess = load_douyin_session()
        cookie_str = sess.get("cookie_str", "") if sess else ""

    http = session or requests.Session()
    http.verify = get_ca_bundle_path()
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/131.0.0.0 Safari/537.36"
        ),
        "Referer": "https://www.douyin.com/",
        "Accept": "application/json, text/plain, */*",
    }
    if cookie_str:
        headers["Cookie"] = cookie_str

    api_url = f"https://www.douyin.com/aweme/v1/web/aweme/detail/?aweme_id={aweme_id}"
    try:
        resp = http.get(api_url, headers=headers, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            detail = data.get("aweme_detail") or {}
            if detail:
                desc = detail.get("desc") or f"Douyin Video {aweme_id}"
                video_obj = detail.get("video") or {}
                cover = (
                    (video_obj.get("cover") or {}).get("url_list", [""])[0]
                    or (video_obj.get("origin_cover") or {}).get("url_list", [""])[0]
                )
                play_urls = (video_obj.get("play_addr") or {}).get("url_list", [])
                direct_url = play_urls[0] if play_urls else None

                # Kiểm tra anchor MiniApp
                anchor = detail.get("anchor_info") or detail.get("micro_app_info") or {}
                open_url = anchor.get("open_url") or anchor.get("mp_url") or anchor.get("web_url") or ""
                app_id = str(anchor.get("app_id") or "")
                collection_id = ""
                drama_name = anchor.get("title") or anchor.get("name") or desc

                # Bóc tách JSON trong extra nếu có
                extra_raw = anchor.get("extra")
                if extra_raw and isinstance(extra_raw, str):
                    try:
                        extra_dict = json.loads(extra_raw)
                        app_id = app_id or str(extra_dict.get("app_id") or "")
                        collection_id = str(extra_dict.get("book_id") or extra_dict.get("album_id") or extra_dict.get("series_id") or extra_dict.get("collection_id") or "")
                        drama_name = extra_dict.get("title") or extra_dict.get("name") or drama_name
                    except Exception:
                        pass

                if open_url:
                    m_app = re.search(r"app_id=([A-Za-z0-9_-]+)", open_url)
                    if m_app and not app_id:
                        app_id = m_app.group(1)
                    m_col = re.search(r"(?:book_id|album_id|series_id|collection_id|id)=([0-9]+)", open_url)
                    if m_col and not collection_id:
                        collection_id = m_col.group(1)

                has_miniapp = bool(app_id and collection_id)

                # Kiểm tra Douyin Mix / Series tuyển tập
                mix_info = detail.get("mix_info") or {}
                is_mix = bool(mix_info and mix_info.get("mix_id"))
                mix_id = str(mix_info.get("mix_id") or "")
                mix_name = mix_info.get("mix_name") or desc
                mix_count = int(mix_info.get("staged_total_count") or mix_info.get("total_count") or 1)

                return {
                    "aweme_id": aweme_id,
                    "title": desc,
                    "cover": cover,
                    "direct_url": direct_url,
                    "has_miniapp": has_miniapp,
                    "app_id": app_id,
                    "collection_id": collection_id,
                    "drama_name": drama_name,
                    "miniapp_uri": f"douyin_miniapp:{app_id}:{collection_id}" if has_miniapp else "",
                    "is_mix": is_mix,
                    "mix_id": mix_id,
                    "mix_name": mix_name,
                    "mix_count": mix_count,
                }
    except Exception:
        pass

    return {
        "aweme_id": aweme_id,
        "title": f"Douyin Video {aweme_id}",
        "cover": "",
        "direct_url": None,
        "has_miniapp": False,
        "app_id": "",
        "collection_id": "",
        "drama_name": "",
        "miniapp_uri": "",
        "is_mix": False,
        "mix_id": "",
        "mix_name": "",
        "mix_count": 1,
    }


# ==============================================================================
# 2. CRYPTO UTILS (AES-128-CBC CHO L_SIGN VÀ R_SIGN)
# ==============================================================================

def pad_key(token: str) -> bytes:
    t = (token or "").strip()
    return (t.ljust(32, "0") if len(t) < 32 else t[:32]).encode("utf-8")


def duolai_iv(deviceid: str, ts: str) -> bytes:
    return bytes.fromhex(hashlib.md5(f"{deviceid}{ts}".encode("utf-8")).hexdigest())


def duolai_encrypt(payload: Dict[str, Any], token: str, deviceid: str, ts: str) -> str:
    """Mã hóa AES-128-CBC cho tham số l_sign."""
    data = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    p = 16 - (len(data) % 16)
    padded = data + bytes([p]) * p
    cipher = AES.new(pad_key(token), AES.MODE_CBC, duolai_iv(deviceid, ts))
    return cipher.encrypt(padded).hex()


def duolai_decrypt(hex_str: str, token: str, deviceid: str, ts: str) -> str:
    """Giải mã AES-128-CBC cho phản hồi r_sign."""
    raw_bytes = bytes.fromhex(hex_str)
    cipher = AES.new(pad_key(token), AES.MODE_CBC, duolai_iv(deviceid, ts))
    decrypted = cipher.decrypt(raw_bytes)
    pad_len = decrypted[-1]
    if 0 < pad_len <= 16:
        decrypted = decrypted[:-pad_len]
    return decrypted.decode("utf-8", "ignore")


# ==============================================================================
# 3. MINIAPP CLIENT THỰC THI GIAO THỨC DUOLAI
# ==============================================================================

class MiniAppDouyinClient:
    """Client giao tiếp với hệ sinh thái MiniApp Douyin (họ duolai)."""

    def __init__(self, session: Optional[requests.Session] = None, cookie: str = ""):
        self.session = session or requests.Session()
        self.session.verify = get_ca_bundle_path()
        self.cookie = cookie.strip()
        self.device_id = str(uuid.uuid4())
        self.token_cache: Dict[str, Dict[str, Any]] = {}  # app_id -> {"token": ..., "expires_at": ...}
        self.timeout = 15

    def get_effective_cookie(self) -> str:
        """Lấy cookie cấu hình trực tiếp hoặc nạp từ phiên DPAPI đã lưu."""
        if self.cookie:
            return self.cookie
        saved = load_douyin_session()
        if saved and saved.get("cookie_str"):
            return saved.get("cookie_str")
        # Fallback tự động nạp từ cookies.txt có sẵn
        count = sync_session_from_cookies_file()
        if count > 0:
            saved = load_douyin_session()
            if saved and saved.get("cookie_str"):
                return saved.get("cookie_str")
        return ""

    def check_cookie_domain_safe(self, url: str) -> bool:
        """Đảm bảo cookie chỉ được gửi đến domain trong allowlist."""
        host = (urlparse(url).netloc or "").lower().split(":")[0]
        return any(host.endswith(d.lstrip(".")) or host == d for d in COOKIE_ALLOWED_DOMAINS)

    def mint_token(self, app_id: str, force: bool = False) -> Tuple[Optional[str], str]:
        """Quy trình mint token:
        1. Kiểm tra cache còn hạn (TTL 12h).
        2. Gọi ma.zijieapi.com lấy js_code từ cookie Douyin.
        3. Gọi xiaoguofanxing.lizhibj.cn/api/duolai/login đổi token.
        """
        now = time.time()
        realm = auth_app(app_id)

        if not force and realm in self.token_cache:
            entry = self.token_cache[realm]
            if entry.get("expires_at", 0) > now + 60:
                return entry["token"], "OK (cache)"

        ck = self.get_effective_cookie()
        if not ck:
            return None, "missing_cookie: Thiếu cookie Douyin để xác thực MiniApp"

        # Bước 1: Login MiniApp lấy js_code
        login_url = "https://ma.zijieapi.com/api/apps/v3/login"
        if not self.check_cookie_domain_safe(login_url):
            return None, "mint_invalid_response: Domain vi phạm cookie allowlist"

        headers = {
            "User-Agent": "Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 ToutiaoMicroApp",
            "Cookie": ck,
        }
        params = {"aid": 1128, "appid": realm}

        try:
            r = self.session.get(login_url, params=params, headers=headers, timeout=self.timeout)
            if r.status_code != 200:
                return None, f"mint_http_error: Lỗi HTTP {r.status_code} khi xác thực ma.zijieapi.com"
            d = (r.json() or {}).get("data") or {}
            code = d.get("code") or d.get("anonymousCode")
            if not code:
                return None, "expired_cookie: Cookie Douyin đã hết hạn hoặc không lấy được mã xác thực js_code"
        except Exception as e:
            return None, f"mint_http_error: Lỗi kết nối mint code ({type(e).__name__})"

        # Bước 2: Đổi js_code lấy token duolai
        token_url = "https://xiaoguofanxing.lizhibj.cn/api/duolai/login"
        if not self.check_cookie_domain_safe(token_url):
            return None, "mint_invalid_response: Domain vi phạm cookie allowlist"

        ts = str(int(time.time()))
        h2 = {
            "content-type": "application/json",
            "Cookie": ck,
            "timestamp": ts,
            "koc-referer": f"https://tmaservice.developer.toutiao.com/?appid={realm}&version={app_version(realm)}",
        }
        body = {"provider": "toutiao", "js_code": code, "appid": realm, "system": "AND"}

        try:
            r2 = self.session.post(token_url, headers=h2, json=body, timeout=self.timeout)
            if r2.status_code != 200:
                return None, f"mint_http_error: Lỗi HTTP {r2.status_code} khi login duolai"
            j = r2.json() or {}
            tok = (j.get("data") or {}).get("token")
            if tok:
                self.token_cache[realm] = {
                    "token": tok,
                    "expires_at": now + (12 * 3600),
                }
                return tok, "OK"
            msg = j.get("msg") or j.get("message") or "Không nhận được token từ máy chủ duolai"
            return None, f"mint_invalid_response: {msg}"
        except Exception as e:
            return None, f"mint_http_error: Lỗi kết nối login duolai ({type(e).__name__})"

    def validate_session(self, app_id: str = "") -> Tuple[bool, str]:
        """Xác thực phiên MiniApp thật bằng cách mint token bắt buộc (force=True)."""
        target_app = app_id or BUILTIN_MINIAPP_SOURCES[0]["app_id"]
        token, msg = self.mint_token(target_app, force=True)
        if not token:
            return False, msg
        return True, "MiniApp session authenticated"

    def browse_catalog(self, app_id: str, page: int = 1, pagesize: int = 18, query: str = "") -> Tuple[List[Dict[str, Any]], bool, Optional[str]]:
        """Duyệt danh sách phim đề xuất công khai hoặc tìm kiếm."""
        url = "https://xiaoguofanxing.lizhibj.cn/api/duolai/video/recommend" if page == 1 and not query else "https://xiaoguofanxing.lizhibj.cn/api/duolai/video/list"
        params = {"system": "AND", "page": page, "pagesize": pagesize}
        if query:
            params["query"] = query

        headers = {
            "koc-referer": f"https://tmaservice.developer.toutiao.com/?appid={app_id}&version={app_version(app_id)}",
            "User-Agent": "Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 ToutiaoMicroApp",
        }

        try:
            r = self.session.get(url, params=params, headers=headers, timeout=self.timeout)
            if r.status_code != 200:
                return [], False, f"Lỗi máy chủ HTTP {r.status_code}"
            try:
                j = r.json()
            except Exception as e:
                return [], False, f"Phản hồi từ API MiniApp không phải JSON hợp lệ: {e}"

            if not isinstance(j, dict):
                return [], False, "Phản hồi API MiniApp không đúng định dạng (không phải dict)"

            if "data" not in j:
                return [], False, "Phản hồi API MiniApp không chứa trường 'data'"

            raw_data = j["data"]
            if isinstance(raw_data, dict):
                if "list" in raw_data:
                    raw_list = raw_data.get("list")
                    if not isinstance(raw_list, list):
                        return [], False, "Trường 'data.list' từ API MiniApp không phải danh sách hợp lệ"
                else:
                    if raw_data == {} or raw_data.get("total") == 0:
                        raw_list = []
                    else:
                        return [], False, "Cấu trúc 'data' từ API MiniApp thiếu danh sách phim"
            elif isinstance(raw_data, list):
                raw_list = raw_data
            elif raw_data is None:
                msg = j.get("msg") or j.get("message") or "Trường 'data' có giá trị None"
                return [], False, f"API MiniApp báo lỗi: {msg}"
            else:
                return [], False, "Trường 'data' từ API MiniApp không phải là list hoặc dict"

            has_more = len(raw_list) >= pagesize
            return raw_list, has_more, None
        except Exception as e:
            return [], False, str(e)

    def load_playlist(self, app_id: str, collection_id: str) -> Tuple[List[Dict[str, Any]], Optional[str]]:
        """Lấy danh sách episode của một collection (yêu cầu ký l_sign)."""
        tok, msg = self.mint_token(app_id)
        if not tok:
            return [], f"Không thể xác thực phiên MiniApp Douyin ({msg})"

        ts = str(int(time.time()))
        url = "https://xiaoguofanxing.lizhibj.cn/api/duolai/video/play_list"
        params = {"collection_id": collection_id, "page": 1, "pagesize": 200}
        l_sign = duolai_encrypt(params, tok, self.device_id, ts)

        headers = {
            "deviceid": self.device_id,
            "timestamp": ts,
            "token": tok,
            "koc-referer": f"https://tmaservice.developer.toutiao.com/?appid={app_id}&version={app_version(app_id)}",
            "User-Agent": "Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 ToutiaoMicroApp",
        }

        try:
            r = self.session.get(url, params={"l_sign": l_sign}, headers=headers, timeout=self.timeout)
            if r.status_code == 401:
                return [], "playlist_http_401: Phiên không hợp lệ hoặc hết hạn (HTTP 401)"
            if r.status_code == 403:
                return [], "playlist_http_403: Bị từ chối truy cập danh sách tập (HTTP 403)"
            if r.status_code != 200:
                return [], f"Lỗi máy chủ HTTP {r.status_code}"
            j = r.json() or {}
            if "r_sign" in j:
                dec = duolai_decrypt(j["r_sign"], tok, self.device_id, ts)
                j = json.loads(dec)
            data = j.get("data")
            if isinstance(data, list):
                return data, None
            if isinstance(data, dict):
                return data.get("list") or [], None
            return [], None
        except Exception as e:
            return [], str(e)

    def get_play_url(self, app_id: str, episode_id: str, is_free: bool = True, is_authorized: bool = False) -> Tuple[Optional[str], Optional[str]]:
        """Lấy URL phát video. Chặn cứng nếu episode không phải Free và chưa được ủy quyền (authorized)!"""
        if not is_free and not is_authorized:
            # CHẶN CỨNG: Không bao giờ gửi request tới play_url nếu tập bị khóa và chưa được ủy quyền
            return None, "Tập phim yêu cầu quyền VIP trên ứng dụng gốc"

        tok, msg = self.mint_token(app_id)
        if not tok:
            return None, f"Không thể xác thực phiên MiniApp Douyin ({msg})"

        ts = str(int(time.time()))
        url = "https://xiaoguofanxing.lizhibj.cn/api/duolai/video/play_url"
        params = {"id": episode_id, "system": "AND"}
        l_sign = duolai_encrypt(params, tok, self.device_id, ts)

        headers = {
            "deviceid": self.device_id,
            "timestamp": ts,
            "token": tok,
            "koc-referer": f"https://tmaservice.developer.toutiao.com/?appid={app_id}&version={app_version(app_id)}",
        }

        try:
            r = self.session.get(url, params={"l_sign": l_sign}, headers=headers, timeout=self.timeout)
            if r.status_code == 401:
                return None, "playlist_http_401: Phiên không hợp lệ hoặc hết hạn (HTTP 401)"
            if r.status_code == 403:
                return None, "playlist_http_403: Bị từ chối truy cập stream (HTTP 403)"
            if r.status_code != 200:
                return None, f"Lỗi HTTP {r.status_code}"
            j = r.json() or {}
            if "r_sign" in j:
                dec = duolai_decrypt(j["r_sign"], tok, self.device_id, ts)
                j = json.loads(dec)
            d = j.get("data")
            if isinstance(d, dict) and d.get("url"):
                return d.get("url"), None
            msg = j.get("msg") or j.get("message") or "Không có luồng phát khả dụng"
            return None, str(msg)
        except Exception as e:
            return None, str(e)

    def check_entitlement(self, app_id: str, episode_id: str) -> Tuple[bool, Optional[str]]:
        """Kiểm tra quyền truy cập/VIP chính thức từ máy chủ duolai cho một tập phim."""
        tok, msg = self.mint_token(app_id)
        if not tok:
            return False, "Thiếu token xác thực tài khoản MiniApp"

        stream_url, err = self.get_play_url(app_id, episode_id, is_free=False, is_authorized=True)
        if stream_url:
            return True, stream_url
        return False, err or "Không xác minh được quyền VIP"

    def download_hls_antihook(
        self,
        m3u8_url: str,
        out_path: str,
        app_id: str,
        progress_cb: Optional[Callable[[int, int, float, str], None]] = None,
        stop_cb: Optional[Callable[[], bool]] = None,
        ffmpeg_bin: Optional[str] = None,
    ) -> bool:
        """Tải và giải mã luồng phát HLS m3u8 bảo vệ qua cơ chế Antihook."""
        antihook_headers = {
            "Accept": "*/*",
            "User-Agent": "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 ToutiaoMicroApp",
            "Referer": f"https://tmaservice.developer.toutiao.com/?appid={app_id}&version={app_version(app_id)}",
            "X-Tt-Tag": "miniapp",
            "X-Tt-SubTag": f"miniapp_appid:{app_id}",
            "Connection": "keep-alive",
        }

        # Định vị ffmpeg nhúng hoặc hệ thống
        if not ffmpeg_bin:
            import sys
            if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
                candidate = os.path.join(sys._MEIPASS, "ffmpeg.exe")
                if os.path.exists(candidate):
                    ffmpeg_bin = candidate
            if not ffmpeg_bin:
                cwd_candidate = os.path.join(os.getcwd(), "ffmpeg.exe")
                if os.path.exists(cwd_candidate):
                    ffmpeg_bin = cwd_candidate
                else:
                    ffmpeg_bin = "ffmpeg"

        segdir = out_path + ".segs"
        tmp_ts = out_path + ".ts.part"
        success = False

        try:
            r = self.session.get(m3u8_url, headers=antihook_headers, timeout=20)
            if r.status_code != 200:
                return False

            key_url = None
            iv = bytes(16)
            segs = []
            for line in r.text.strip().splitlines():
                line = line.strip()
                if line.startswith("#EXT-X-KEY"):
                    m = re.search(r'URI="([^"]+)"', line)
                    if m:
                        key_url = urljoin(m3u8_url, m.group(1))
                    mi = re.search(r"IV=0x([0-9a-fA-F]+)", line)
                    if mi:
                        iv = bytes.fromhex(mi.group(1).zfill(32))
                elif line and not line.startswith("#"):
                    segs.append(urljoin(m3u8_url, line))

            if not segs:
                return False

            key = None
            if key_url:
                kr = self.session.get(key_url, headers=antihook_headers, timeout=15)
                if kr.status_code == 200 and len(kr.content) == 16:
                    key = kr.content
                else:
                    return False

            os.makedirs(segdir, exist_ok=True)
            seg_paths = []
            total = len(segs)

            for i, s_url in enumerate(segs):
                if stop_cb and stop_cb():
                    return False
                sr = self.session.get(s_url, headers=antihook_headers, timeout=30)
                if sr.status_code != 200:
                    return False
                chunk = sr.content
                if key:
                    chunk = AES.new(key, AES.MODE_CBC, iv).decrypt(chunk)
                p_file = os.path.join(segdir, f"{i:05d}.bin")
                with open(p_file, "wb") as sf:
                    sf.write(chunk)
                seg_paths.append(p_file)
                if progress_cb:
                    progress_cb(i + 1, total, 0.0, f"Giải mã HLS {i + 1}/{total}")

            # Ghép file TS
            with open(tmp_ts, "wb") as fo:
                for p in seg_paths:
                    with open(p, "rb") as fi:
                        fo.write(fi.read())

            # Xóa thư mục segments sau khi ghép xong TS
            shutil.rmtree(segdir, ignore_errors=True)

            # Remux sang MP4 bằng FFmpeg
            rc = subprocess.call(
                [ffmpeg_bin, "-y", "-loglevel", "error", "-i", tmp_ts, "-c", "copy", "-bsf:a", "aac_adtstoasc", out_path]
            )
            if rc == 0 and os.path.exists(out_path) and os.path.getsize(out_path) > 1024:
                try:
                    os.remove(tmp_ts)
                except Exception:
                    pass
                success = True
                return True

            # Fallback nếu không có ffmpeg: đổi tên file ts
            if os.path.exists(tmp_ts):
                os.replace(tmp_ts, out_path)
                success = True
                return True
            return False
        except Exception:
            return False
        finally:
            # Luôn dọn dẹp segment directory nếu còn sót
            if os.path.exists(segdir):
                shutil.rmtree(segdir, ignore_errors=True)
            # Nếu thất bại hoặc dừng, dọn dẹp file tạm tmp_ts
            if not success and os.path.exists(tmp_ts):
                try:
                    os.remove(tmp_ts)
                except Exception:
                    pass
