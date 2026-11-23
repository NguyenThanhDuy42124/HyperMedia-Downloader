"""
tests/miniapp_douyin_adapter.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Mã thử nghiệm (Prototype Adapter) cho Douyin MiniApp dựa trên reverse-engineering từ
repository MiniApp-Downloader (adapter họ duolai).
Sử dụng Cryptodome có sẵn trong môi trường để thực hiện AES-128-CBC.

Tuân thủ nghiêm ngặt nguyên tắc Free-first & Bảo vệ dữ liệu:
- Không lưu, in hoặc log cookie/token thô.
- Không gửi cookie đến domain ngoài allowlist (chỉ zijieapi.com và lizhibj.cn).
- Tập locked/VIP bị chặn cứng tại tầng client/adapter, không gửi request play_url.
- Định danh Episode ID ổn định từ trường 'id' của API, không dùng index hàng đợi.
"""

import hashlib
import json
import os
import re
import time
import uuid
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

import requests
from Cryptodome.Cipher import AES

from providers.base import (
    ACCESS_STATE_FREE,
    ACCESS_STATE_REQUIRES_LOGIN,
    ACCESS_STATE_REQUIRES_VIP,
    ACCESS_STATE_UNAVAILABLE,
    BaseDramaProvider,
    CatalogItem,
    CatalogResult,
    Episode,
    Series,
    parse_episode_selection,
)

# Domain allowlist an toàn cho cookie
COOKIE_ALLOWED_DOMAINS = {
    "ma.zijieapi.com",
    "xiaoguofanxing.lizhibj.cn",
}

# Các nguồn MiniApp Douyin builtin
BUILTIN_MINIAPP_SOURCES = [
    {"name": "多来看点", "app_id": "tt5b4d2df0c47bdd2201", "adapter": "duolai"},
    {"name": "黑岩漫故事", "app_id": "tt839df5201ca3d79a01", "adapter": "duolai"},
    {"name": "金猫漫品", "app_id": "tt3eca4877a1fed32a01", "adapter": "duolai"},
    {"name": "万花故事会", "app_id": "ttbe17c8aa2121c82101", "adapter": "duolai"},
]


def mask_sensitive(text: str) -> str:
    """Loại bỏ và che giấu cookie/token trước khi log hoặc in ra màn hình."""
    if not text:
        return ""
    # Mask sessionid, uid_tt, passport token
    s = re.sub(r'(sessionid|uid_tt|passport_csrf_token)=([0-9a-zA-Z_-]+)', r'\1=***REDACTED***', str(text))
    # Mask duolai token
    s = re.sub(r'duolai_[0-9a-zA-Z]{20,}', r'duolai_***REDACTED***', s)
    return s


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


class MiniAppDouyinClient:
    """Client giao tiếp với hệ sinh thái MiniApp Douyin (họ duolai)."""

    def __init__(self, session: Optional[requests.Session] = None, cookie: str = ""):
        self.session = session or requests.Session()
        self.cookie = cookie.strip()
        self.device_id = str(uuid.uuid4())
        self.token_cache: Dict[str, str] = {}  # app_id -> token

    def check_cookie_domain_safe(self, url: str) -> bool:
        """Đảm bảo cookie chỉ được gửi đến domain trong allowlist."""
        host = (urlparse(url).netloc or "").lower().split(":")[0]
        return host in COOKIE_ALLOWED_DOMAINS

    def mint_token(self, app_id: str, cookie: Optional[str] = None) -> Tuple[Optional[str], str]:
        """Quy trình mint token:
        1. Gọi ma.zijieapi.com lấy js_code từ cookie Douyin.
        2. Gọi xiaoguofanxing.lizhibj.cn/api/duolai/login đổi token.
        """
        ck = (cookie or self.cookie).strip()
        if not ck:
            return None, "Thiếu cookie Douyin để xác thực"

        # Bước 1: Login MiniApp lấy js_code
        login_url = "https://ma.zijieapi.com/api/apps/v3/login"
        if not self.check_cookie_domain_safe(login_url):
            return None, "Domain vi phạm cookie allowlist"

        headers = {
            "User-Agent": "Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 ToutiaoMicroApp",
            "Cookie": ck,
        }
        params = {"aid": 1128, "appid": app_id}

        try:
            r = self.session.get(login_url, params=params, headers=headers, timeout=10)
            if r.status_code != 200:
                return None, f"Lỗi HTTP {r.status_code} khi gọi ma.zijieapi.com"
            d = (r.json() or {}).get("data") or {}
            code = d.get("code") or d.get("anonymousCode")
            if not code:
                return None, "Cookie hết hạn hoặc không có quyền MiniApp (thiếu code)"
        except Exception as e:
            return None, f"Lỗi kết nối mint code: {type(e).__name__}"

        # Bước 2: Đổi js_code lấy token duolai
        token_url = "https://xiaoguofanxing.lizhibj.cn/api/duolai/login"
        if not self.check_cookie_domain_safe(token_url):
            return None, "Domain vi phạm cookie allowlist"

        ts = str(int(time.time()))
        h2 = {
            "content-type": "application/json",
            "Cookie": ck,
            "timestamp": ts,
            "koc-referer": f"https://tmaservice.developer.toutiao.com/?appid={app_id}&version=3.9.39",
        }
        body = {"provider": "toutiao", "js_code": code, "appid": app_id, "system": "AND"}

        try:
            r2 = self.session.post(token_url, headers=h2, json=body, timeout=10)
            if r2.status_code != 200:
                return None, f"Lỗi HTTP {r2.status_code} khi login duolai"
            j = r2.json() or {}
            tok = (j.get("data") or {}).get("token")
            if tok:
                self.token_cache[app_id] = tok
                return tok, "OK"
            msg = j.get("msg") or j.get("message") or "Không nhận được token"
            return None, str(msg)
        except Exception as e:
            return None, f"Lỗi kết nối login duolai: {type(e).__name__}"

    def browse_catalog(self, app_id: str, page: int = 1, pagesize: int = 18) -> CatalogResult:
        """Duyệt danh sách phim đề xuất công khai (public recommend)."""
        url = "https://xiaoguofanxing.lizhibj.cn/api/duolai/video/recommend"
        params = {"system": "AND", "page": page, "pagesize": pagesize}
        headers = {
            "koc-referer": f"https://tmaservice.developer.toutiao.com/?appid={app_id}&version=3.9.39",
            "User-Agent": "Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 ToutiaoMicroApp",
        }

        try:
            r = self.session.get(url, params=params, headers=headers, timeout=10)
            if r.status_code != 200:
                return CatalogResult(items=[], total=0, platform="douyin_miniapp", page=page, error=f"HTTP {r.status_code}")
            j = r.json() or {}
            raw_list = j.get("data")
            if isinstance(raw_list, dict):
                raw_list = raw_list.get("list") or []
            if not isinstance(raw_list, list):
                raw_list = []

            items = []
            for item in raw_list:
                cid = str(item.get("id") or item.get("collection_id") or "")
                if not cid:
                    continue
                name = (item.get("name") or item.get("title") or f"Series {cid}").strip()
                cover = item.get("cover_url") or item.get("cover") or ""
                ep_cnt = int(item.get("episode_count") or item.get("total_episodes") or item.get("watch_num") or 0)
                desc = (item.get("describe") or item.get("intro") or "").strip()

                items.append(
                    CatalogItem(
                        id=cid,
                        name=name,
                        cover=cover,
                        episodes=ep_cnt,
                        desc=desc,
                        link=f"douyin_miniapp:{app_id}:{cid}",
                        platform="douyin_miniapp",
                    )
                )

            return CatalogResult(items=items, total=len(items), platform="douyin_miniapp", page=page, has_more=len(items) >= pagesize)
        except Exception as e:
            return CatalogResult(items=[], total=0, platform="douyin_miniapp", page=page, error=str(e))

    def load_playlist(self, app_id: str, collection_id: str, token: Optional[str] = None) -> List[Dict[str, Any]]:
        """Lấy danh sách episode của một collection (yêu cầu ký l_sign)."""
        tok = token or self.token_cache.get(app_id) or ""
        ts = str(int(time.time()))
        url = "https://xiaoguofanxing.lizhibj.cn/api/duolai/video/play_list"
        params = {"collection_id": collection_id, "page": 1, "pagesize": 100}
        l_sign = duolai_encrypt(params, tok, self.device_id, ts)

        headers = {
            "deviceid": self.device_id,
            "timestamp": ts,
            "token": tok,
            "koc-referer": f"https://tmaservice.developer.toutiao.com/?appid={app_id}&version=3.9.39",
            "User-Agent": "Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 ToutiaoMicroApp",
        }

        try:
            r = self.session.get(url, params={"l_sign": l_sign}, headers=headers, timeout=10)
            if r.status_code != 200:
                return []
            j = r.json() or {}
            if "r_sign" in j:
                dec = duolai_decrypt(j["r_sign"], tok, self.device_id, ts)
                j = json.loads(dec)
            data = j.get("data")
            if isinstance(data, list):
                return data
            if isinstance(data, dict):
                return data.get("list") or []
            return []
        except Exception:
            return []

    def get_play_url(self, app_id: str, episode_id: str, is_free: bool, token: Optional[str] = None) -> Optional[str]:
        """Lấy URL phát video. Chặn cứng nếu episode không phải Free!"""
        if not is_free:
            # CHẶN CỨNG: Không bao giờ gửi request tới play_url nếu tập bị khóa
            return None

        tok = token or self.token_cache.get(app_id) or ""
        ts = str(int(time.time()))
        url = "https://xiaoguofanxing.lizhibj.cn/api/duolai/video/play_url"
        params = {"id": episode_id, "system": "AND"}
        l_sign = duolai_encrypt(params, tok, self.device_id, ts)

        headers = {
            "deviceid": self.device_id,
            "timestamp": ts,
            "token": tok,
            "koc-referer": f"https://tmaservice.developer.toutiao.com/?appid={app_id}&version=3.9.39",
        }

        try:
            r = self.session.get(url, params={"l_sign": l_sign}, headers=headers, timeout=10)
            if r.status_code != 200:
                return None
            j = r.json() or {}
            if "r_sign" in j:
                dec = duolai_decrypt(j["r_sign"], tok, self.device_id, ts)
                j = json.loads(dec)
            d = j.get("data")
            if isinstance(d, dict):
                return d.get("url")
            return None
        except Exception:
            return None


class MiniAppDouyinProvider(BaseDramaProvider):
    """Adapter nguyên mẫu tích hợp vào kiến trúc BaseDramaProvider của HyperMedia."""

    platform_id: str = "douyin_miniapp"
    display_name: str = "Douyin MiniApp"
    supports_catalog: bool = True
    status: str = "planned"  # Đánh dấu rõ ràng là Planned

    def __init__(self, session: Optional[requests.Session] = None, cookie: str = ""):
        super().__init__(session=session)
        self.client = MiniAppDouyinClient(session=self.session, cookie=cookie)

    def can_handle(self, url: str) -> bool:
        if not url:
            return False
        u = str(url).strip().lower()
        return u.startswith("douyin_miniapp:") or "xiaoguofanxing.lizhibj.cn" in u

    def load_series(self, url: str) -> Series:
        """Phân tích URL dạng douyin_miniapp:{app_id}:{collection_id}."""
        m = re.search(r"douyin_miniapp:([A-Za-z0-9_-]+):([0-9]+)", url)
        if not m:
            raise ValueError(f"URL không đúng định dạng MiniApp Douyin: {url}")
        app_id, cid = m.group(1), m.group(2)

        raw_eps = self.client.load_playlist(app_id, cid)
        if not raw_eps:
            raise ValueError(f"Không thể nạp playlist cho MiniApp Douyin {app_id} ID {cid}")

        episodes: List[Episode] = []
        for idx, item in enumerate(raw_eps):
            seq = int(item.get("sequence_no") or (idx + 1))
            eid = str(item.get("id") or seq)
            is_free = item.get("is_free") in ("T", True, 1)

            state = ACCESS_STATE_FREE if is_free else ACCESS_STATE_REQUIRES_VIP
            reason = "" if is_free else "Tập này yêu cầu mua VIP trên MiniApp Douyin."

            episodes.append(
                Episode(
                    num=seq,
                    title=f"Tập {seq}",
                    url=f"douyin_miniapp:{app_id}:{cid}?ep_id={eid}&ep={seq}",
                    direct_url=None,
                    locked=not is_free,
                    provider_id=self.platform_id,
                    series_id=f"douyin_miniapp:{app_id}:{cid}",
                    episode_id=eid,
                    episode_number=seq,
                    access_state=state,
                    access_reason=reason,
                    extra={"app_id": app_id, "collection_id": cid, "episode_id": eid, "is_free": is_free},
                )
            )

        accessible = sum(1 for e in episodes if not e.locked)
        return Series(
            name=f"Douyin MiniApp Series {cid}",
            platform=self.platform_id,
            series_id=f"douyin_miniapp:{app_id}:{cid}",
            episode_count=len(episodes),
            accessible_count=accessible,
            episodes=episodes,
            url=url,
        )

    def resolve_episode_stream(self, episode: Episode) -> Optional[str]:
        """Chặn cứng tập locked; chỉ giải mã tập Free."""
        if episode.access_state != ACCESS_STATE_FREE or episode.locked:
            return None

        app_id = episode.extra.get("app_id")
        eid = episode.episode_id or episode.extra.get("episode_id")
        is_free = episode.extra.get("is_free", True)

        if not app_id or not eid:
            return None

        return self.client.get_play_url(app_id, eid, is_free=is_free)
