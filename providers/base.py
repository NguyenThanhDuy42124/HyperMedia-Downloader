"""
providers.base
~~~~~~~~~~~~~~
Core domain models and abstract interface for Drama Providers.
Provides clean isolation between the UI/queue and platform-specific extractors.
"""

import os
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any, Tuple
import requests
from ca_bundle_utils import get_ca_bundle_path

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9,vi;q=0.8",
}


ACCESS_STATE_FREE = "free"
ACCESS_STATE_AUTHORIZED = "authorized"
ACCESS_STATE_REQUIRES_LOGIN = "requires_login"
ACCESS_STATE_REQUIRES_VIP = "requires_vip"
ACCESS_STATE_UNAVAILABLE = "unavailable"
ACCESS_STATE_ERROR = "error"

VALID_ACCESS_STATES = {
    ACCESS_STATE_FREE,
    ACCESS_STATE_AUTHORIZED,
    ACCESS_STATE_REQUIRES_LOGIN,
    ACCESS_STATE_REQUIRES_VIP,
    ACCESS_STATE_UNAVAILABLE,
    ACCESS_STATE_ERROR,
}


@dataclass
class Subtitle:
    lang: str
    name: str
    url: str

    def to_dict(self) -> Dict[str, Any]:
        return {"lang": self.lang, "name": self.name, "url": self.url}


@dataclass
class Episode:
    num: int
    title: str
    url: str
    direct_url: Optional[str] = None
    thumb: str = ""
    locked: bool = False
    subtitles: List[Subtitle] = field(default_factory=list)
    extra: Dict[str, Any] = field(default_factory=dict)
    # Standardized metadata & access control contract
    provider_id: str = ""
    series_id: str = ""
    episode_id: str = ""
    episode_number: int = 0
    access_state: str = ACCESS_STATE_FREE
    access_reason: str = ""
    subtitle: Optional[str] = None
    expires_at: Optional[int] = None

    def __post_init__(self):
        if self.episode_number == 0:
            self.episode_number = self.num
        # Synchronize locked state and access_state
        if self.locked and self.access_state == ACCESS_STATE_FREE:
            self.access_state = ACCESS_STATE_REQUIRES_VIP
        elif self.access_state in (ACCESS_STATE_REQUIRES_VIP, ACCESS_STATE_UNAVAILABLE, ACCESS_STATE_REQUIRES_LOGIN):
            self.locked = True
        elif self.access_state == ACCESS_STATE_FREE:
            self.locked = False

        if not self.subtitle and self.subtitles:
            self.subtitle = self.subtitles[0].url

    def to_dict(self) -> Dict[str, Any]:
        return {
            "num": self.num,
            "title": self.title,
            "url": self.url,
            "direct_url": self.direct_url,
            "thumb": self.thumb,
            "locked": self.locked,
            "subtitles": [s.to_dict() for s in self.subtitles],
            "extra": self.extra,
            "provider_id": self.provider_id,
            "series_id": self.series_id,
            "episode_id": self.episode_id,
            "episode_number": self.episode_number,
            "access_state": self.access_state,
            "access_reason": self.access_reason,
            "subtitle": self.subtitle,
            "expires_at": self.expires_at,
        }


@dataclass
class Series:
    name: str
    platform: str
    series_id: str
    cover: str = ""
    description: str = ""
    episode_count: int = 0
    accessible_count: int = 0
    episodes: List[Episode] = field(default_factory=list)
    url: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "platform": self.platform,
            "series_id": self.series_id,
            "cover": self.cover,
            "description": self.description,
            "episode_count": self.episode_count,
            "accessible_count": self.accessible_count,
            "episodes": [e.to_dict() for e in self.episodes],
            "url": self.url,
        }


@dataclass
class CatalogItem:
    id: str
    name: str
    cover: str = ""
    episodes: int = 0
    desc: str = ""
    link: str = ""
    platform: str = ""


@dataclass
class CatalogResult:
    items: List[CatalogItem]
    total: int
    platform: str
    page: int = 1
    error: Optional[str] = None
    has_more: bool = True


def parse_episode_selection(range_str: str, max_ep: int) -> List[int]:
    """Phân tích chuỗi khoảng tập (ví dụ: '1-5, 8, 10-12') thành danh sách số tập hợp lệ."""
    if not range_str or not range_str.strip() or max_ep <= 0:
        return []
    clean_str = range_str.strip()[:200]
    result = set()
    parts = [p.strip() for p in clean_str.split(",") if p.strip()]
    for part in parts:
        if "-" in part:
            sub = part.split("-")
            if len(sub) == 2 and sub[0].strip().isdigit() and sub[1].strip().isdigit():
                raw_start = int(sub[0].strip())
                raw_end = int(sub[1].strip())
                low = min(raw_start, raw_end)
                high = max(raw_start, raw_end)
                clamped_start = max(1, low)
                clamped_end = min(max_ep, high)
                if clamped_start <= clamped_end:
                    result.update(range(clamped_start, clamped_end + 1))
        elif part.isdigit():
            n = int(part)
            if 1 <= n <= max_ep:
                result.add(n)
    return sorted(result)


def vtt_to_srt(vtt_text: str) -> str:
    """Chuyển đổi phụ đề WebVTT sang SubRip (.srt)."""
    import re
    lines = vtt_text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    output = []
    idx = 1
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if not line or line.startswith("WEBVTT") or line.startswith("NOTE") or line.startswith("STYLE"):
            if line.startswith("STYLE") or line.startswith("NOTE"):
                while i < len(lines) and lines[i].strip():
                    i += 1
            i += 1
            continue

        m = re.search(
            r"(?:(\d{2}):)?(\d{2}):(\d{2})\.(\d{3})\s*-->\s*(?:(\d{2}):)?(\d{2}):(\d{2})\.(\d{3})",
            line,
        )
        if m:
            h1 = m.group(1) or "00"
            m1, s1, ms1 = m.group(2), m.group(3), m.group(4)
            h2 = m.group(5) or "00"
            m2, s2, ms2 = m.group(6), m.group(7), m.group(8)
            srt_timestamp = f"{h1}:{m1}:{s1},{ms1} --> {h2}:{m2}:{s2},{ms2}"

            output.append(str(idx))
            output.append(srt_timestamp)
            idx += 1
            i += 1
            while i < len(lines) and lines[i].strip():
                cleaned_text = re.sub(r"<[^>]+>", "", lines[i].strip())
                if cleaned_text:
                    output.append(cleaned_text)
                i += 1
            output.append("")
        else:
            i += 1

    return "\n".join(output)


class BaseDramaProvider(ABC):
    """Abstract base class for drama platform providers."""

    platform_id: str = "base"
    display_name: str = "Base Provider"
    supports_catalog: bool = False
    status: str = "planned"  # "active" (live verified) hoặc "planned" (adapter contract)

    def __init__(self, session: Optional[requests.Session] = None):
        self.session = session or requests.Session()
        self.session.verify = get_ca_bundle_path()
        self.session.headers.update(DEFAULT_HEADERS)
        self.last_error: str = ""

    @abstractmethod
    def can_handle(self, url: str) -> bool:
        """Kiểm tra xem provider này có nhận diện được URL hay không."""
        pass

    @abstractmethod
    def load_series(self, url: str) -> Series:
        """Quét và lấy thông tin series kèm danh sách tập."""
        pass

    def resolve_episode_stream(self, episode: Episode) -> Optional[str]:
        """Làm mới URL phát trực tiếp (Direct MP4 hoặc HLS) ngay trước khi tải."""
        return episode.direct_url

    def resolve_stream(self, episode: Episode) -> Optional[str]:
        """Bí danh cho resolve_episode_stream theo contract chuẩn."""
        return self.resolve_episode_stream(episode)

    def match_url(self, url: str) -> bool:
        """Bí danh cho can_handle theo contract chuẩn."""
        return self.can_handle(url)

    def get_catalog(
        self,
        page: int = 1,
        query: Optional[str] = None,
        category: Optional[str] = None,
    ) -> CatalogResult:
        """Lấy danh sách catalog / duyệt phim nếu platform hỗ trợ."""
        if not self.supports_catalog:
            return CatalogResult(
                items=[],
                total=0,
                platform=self.platform_id,
                page=page,
                has_more=False,
                error="Nguồn này hiện chưa hỗ trợ duyệt danh mục. Hãy dán link phim trực tiếp.",
            )
        return CatalogResult(items=[], total=0, platform=self.platform_id, page=page, has_more=False)

    def load_catalog(
        self,
        page: int = 1,
        query: Optional[str] = None,
        category: Optional[str] = None,
    ) -> CatalogResult:
        """Bí danh cho get_catalog theo contract chuẩn."""
        return self.get_catalog(page=page, query=query, category=category)

    def search(self, query: str, page: int = 1) -> CatalogResult:
        """Tìm kiếm phim trên nền tảng."""
        return self.get_catalog(page=page, query=query)

    def get_subtitle(self, episode: Episode) -> List[Subtitle]:
        """Lấy danh sách phụ đề cho tập phim."""
        return getattr(episode, "subtitles", [])

    def load_cookies_from_file(self, domain_keywords: Optional[List[str]] = None) -> int:
        """Nạp cookies từ tệp cookies.txt chuẩn Netscape vào self.session cho các domain tương ứng."""
        from app_constants import cookies_file
        c_path = cookies_file()
        if not os.path.exists(c_path):
            return 0
        loaded = 0
        now = time.time()
        try:
            with open(c_path, "r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    line_s = line.strip()
                    if not line_s or line_s.startswith("#"):
                        continue
                    parts = line_s.split("\t")
                    if len(parts) == 7:
                        dom, _, path, is_sec, exp, name, val = parts
                        if domain_keywords:
                            if not any(k in dom.lower() for k in domain_keywords):
                                continue
                        try:
                            exp_ts = int(exp)
                            if exp_ts > 0 and exp_ts < now:
                                continue  # Bỏ qua cookie đã hết hạn
                        except Exception:
                            pass
                        self.session.cookies.set(name, val, domain=dom, path=path)
                        loaded += 1
        except Exception:
            pass
        return loaded

    def authenticate(self, credentials: Dict[str, Any]) -> bool:
        """Thiết kế interface cho xác thực tài khoản chính thức."""
        return False

    def refresh_session(self) -> bool:
        """Thiết kế interface làm mới phiên đăng nhập chính thức."""
        return False

    def validate_entitlement(self, episode: Episode) -> bool:
        """Kiểm tra quyền sở hữu/VIP của người dùng đối với tập phim."""
        return episode.access_state in (ACCESS_STATE_FREE, ACCESS_STATE_AUTHORIZED) and not episode.locked

    def get_session_status(self) -> Tuple[str, str]:
        """Trả về tuple (status_code, status_message) cho phiên người dùng trên provider."""
        return "none", "Chưa đăng nhập"
