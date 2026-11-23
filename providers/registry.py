"""
providers.registry
~~~~~~~~~~~~~~~~~~
Centralized provider registry and automatic routing for drama platforms.
Supports Free-first architecture across all verified providers.
"""

from typing import Optional, List, Dict
from .base import BaseDramaProvider, Series, Episode, CatalogResult
from .dramabox_provider import DramaBoxProvider
from .kisskh_provider import KisskhProvider
from .hongguo_provider import HongguoProvider
from .goodshort_provider import GoodShortProvider
from .shortmax_provider import ShortMaxProvider
from .netshort_provider import NetShortProvider
from .freereels_provider import FreeReelsProvider
from .dramawave_provider import DramaWaveProvider
from .raptdrama_provider import RaptDramaProvider
from .flextv_provider import FlexTVProvider
from .stardusttv_provider import StardustTVProvider
from .miniapp_douyin_provider import MiniAppDouyinProvider

# 1. Nhóm A — Browse Catalog Enabled (Hỗ trợ duyệt danh mục trực tiếp trên giao diện)
CATALOG_PROVIDERS: List[BaseDramaProvider] = [
    HongguoProvider(),
    DramaBoxProvider(),
    KisskhProvider(),
]

# 2. Nhóm B — URL-only / Adapter Contract (Chỉ nhận diện và tải qua URL dán trực tiếp)
URL_ONLY_PROVIDERS: List[BaseDramaProvider] = [
    GoodShortProvider(),
    ShortMaxProvider(),
    NetShortProvider(),
    FreeReelsProvider(),
    DramaWaveProvider(),
    RaptDramaProvider(),
    FlexTVProvider(),
    StardustTVProvider(),
]

# 3. Nhóm C — Provider dự kiến / Tab chuyên biệt
PLANNED_PROVIDERS: List[BaseDramaProvider] = [
    MiniAppDouyinProvider(),
]

# Danh sách toàn bộ Provider đang hoạt động
ACTIVE_PROVIDERS: List[BaseDramaProvider] = CATALOG_PROVIDERS + URL_ONLY_PROVIDERS

# Danh sách toàn bộ Provider đã đăng ký mã adapter trong hệ thống
REGISTERED_PROVIDERS: List[BaseDramaProvider] = ACTIVE_PROVIDERS + PLANNED_PROVIDERS


def get_all_providers() -> List[BaseDramaProvider]:
    """Trả về danh sách tất cả các provider đã đăng ký trong hệ thống."""
    return list(REGISTERED_PROVIDERS)


def get_active_providers() -> List[BaseDramaProvider]:
    """Trả về danh sách các provider đang ở trạng thái active (hỗ trợ browse & live verified)."""
    return list(ACTIVE_PROVIDERS)


def get_catalog_providers() -> List[BaseDramaProvider]:
    """Trả về danh sách các provider có supports_catalog=True phục vụ duyệt danh mục."""
    return list(CATALOG_PROVIDERS)


def get_url_only_providers() -> List[BaseDramaProvider]:
    """Trả về danh sách các provider dạng URL-only / Adapter contract."""
    return list(URL_ONLY_PROVIDERS)


def get_planned_providers() -> List[BaseDramaProvider]:
    """Trả về danh sách các provider ở trạng thái planned (adapter contract test)."""
    return list(PLANNED_PROVIDERS)


def get_provider(platform_id: str) -> Optional[BaseDramaProvider]:
    """Tìm provider theo ID (ví dụ: 'dramabox', 'kisskh', 'hongguo', 'goodshort')."""
    if not platform_id:
        return None
    target = platform_id.lower().strip()
    for p in REGISTERED_PROVIDERS:
        if p.platform_id.lower() == target or p.display_name.lower() == target:
            return p
    return None


def detect_provider(url_or_id: str) -> Optional[BaseDramaProvider]:
    """Tự động phát hiện provider tương ứng từ URL hoặc định danh."""
    if not url_or_id:
        return None
    for p in REGISTERED_PROVIDERS:
        if p.can_handle(url_or_id):
            return p
    return None


def is_drama_url(url: str) -> bool:
    """Kiểm tra nhanh xem một URL có thuộc nền tảng phim ngắn hay không."""
    return detect_provider(url) is not None


def load_series(url_or_id: str, platform_hint: Optional[str] = None) -> Series:
    """Nạp metadata series và danh sách tập từ URL hoặc ID."""
    p = None
    if platform_hint:
        p = get_provider(platform_hint)
    if not p:
        p = detect_provider(url_or_id)
    if not p:
        raise ValueError(f"Không có provider phim ngắn nào hỗ trợ URL: {url_or_id}")
    return p.load_series(url_or_id)


def resolve_episode_stream(episode: Episode, platform_hint: Optional[str] = None) -> Optional[str]:
    """Làm mới URL phát trực tiếp (Direct MP4 hoặc HLS) trước khi tải."""
    p = None
    if platform_hint:
        p = get_provider(platform_hint)
    if not p:
        p = detect_provider(episode.url)
    if p:
        return p.resolve_episode_stream(episode)
    return episode.direct_url
