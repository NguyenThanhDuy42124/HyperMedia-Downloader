"""
providers package
~~~~~~~~~~~~~~~~~
Unified adapter layer for Drama platforms integration.
"""

from .base import (
    BaseDramaProvider,
    Series,
    Episode,
    Subtitle,
    CatalogItem,
    CatalogResult,
    ACCESS_STATE_FREE,
    ACCESS_STATE_REQUIRES_LOGIN,
    ACCESS_STATE_REQUIRES_VIP,
    ACCESS_STATE_UNAVAILABLE,
    ACCESS_STATE_ERROR,
    VALID_ACCESS_STATES,
)
from .registry import (
    get_all_providers,
    get_active_providers,
    get_catalog_providers,
    get_url_only_providers,
    get_planned_providers,
    get_provider,
    detect_provider,
    is_drama_url,
    load_series,
    resolve_episode_stream,
)

__all__ = [
    "BaseDramaProvider",
    "Series",
    "Episode",
    "Subtitle",
    "CatalogItem",
    "CatalogResult",
    "ACCESS_STATE_FREE",
    "ACCESS_STATE_REQUIRES_LOGIN",
    "ACCESS_STATE_REQUIRES_VIP",
    "ACCESS_STATE_UNAVAILABLE",
    "ACCESS_STATE_ERROR",
    "VALID_ACCESS_STATES",
    "get_all_providers",
    "get_active_providers",
    "get_catalog_providers",
    "get_url_only_providers",
    "get_planned_providers",
    "get_provider",
    "detect_provider",
    "is_drama_url",
    "load_series",
    "resolve_episode_stream",
]
