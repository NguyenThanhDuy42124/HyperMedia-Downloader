"""
providers.shortmax_provider
~~~~~~~~~~~~~~~~~~~~~~~~~~~
Free-first platform provider for ShortMax.
Enforces free episode boundary and marks locked episodes as requires_vip.
"""

import re
from urllib.parse import urlparse
from typing import Optional, List, Dict, Any

from .base import (
    BaseDramaProvider,
    Series,
    Episode,
    CatalogItem,
    CatalogResult,
    ACCESS_STATE_FREE,
    ACCESS_STATE_REQUIRES_VIP,
)


class ShortMaxProvider(BaseDramaProvider):
    platform_id = "shortmax"
    display_name = "ShortMax"
    supports_catalog = False

    BASE_URL = "https://shortmax.goodbos.online/api/v1"
    ALLOWED_HOSTS = {
        "shortmax.com",
        "www.shortmax.com",
        "shortmax.goodbos.online",
    }

    def can_handle(self, url: str) -> bool:
        if not url:
            return False
        u = str(url).strip()
        if u.lower().startswith("shortmax:"):
            return True
        try:
            host = (urlparse(u).netloc or "").lower().split(":")[0]
            return host in self.ALLOWED_HOSTS
        except Exception:
            return False

    def _extract_id(self, url: str) -> str:
        u = url.strip()
        m = re.search(r"shortmax:[/\\]*([A-Za-z0-9_-]+)", u, re.I)
        if m:
            return m.group(1)
        m = re.search(r"/(?:drama|series|detail|play)/([A-Za-z0-9_-]+)", u, re.I)
        if m:
            return m.group(1)
        m = re.search(r"([A-Za-z0-9_-]{8,})", u)
        return m.group(1) if m else ""

    def _pick_best_video(self, video_dict: Dict[str, Any]) -> Optional[str]:
        if not isinstance(video_dict, dict):
            return None
        for q in ["1080p", "720p", "540p", "480p", "360p"]:
            val = video_dict.get(q)
            if val and isinstance(val, str) and (val.startswith("http://") or val.startswith("https://")):
                return val
        for v in video_dict.values():
            if isinstance(v, str) and (v.startswith("http://") or v.startswith("https://")):
                return v
        return None

    def load_series(self, url: str) -> Series:
        sm_key = self._extract_id(url)
        if not sm_key:
            raise ValueError(f"Không thể nhận diện Drama Key của ShortMax từ URL: {url}")

        params = {"lang": "en"}
        resp = self.session.get(f"{self.BASE_URL}/alleps/{sm_key}", params=params, timeout=10)
        if resp.status_code in (401, 403):
            raise ValueError(f"Máy chủ ShortMax từ chối truy cập (HTTP {resp.status_code})")
        if resp.status_code != 200:
            raise ValueError(f"ShortMax API lỗi: HTTP {resp.status_code}")

        res_json = resp.json()
        data = res_json.get("data") or {}
        raw_episodes = data.get("episodes") or []
        if not raw_episodes:
            raise ValueError(f"ShortMax không trả về danh sách tập cho series: {sm_key}")

        raw_episodes = sorted(raw_episodes, key=lambda x: x.get("episode", 0))

        series_name = (data.get("name") or f"ShortMax Series {sm_key}").strip()
        cover = data.get("cover") or ""
        desc = data.get("summary") or ""

        episodes: List[Episode] = []
        for idx, ep_data in enumerate(raw_episodes):
            ep_num = idx + 1
            v_dict = ep_data.get("video") or {}
            direct_url = self._pick_best_video(v_dict)

            is_free = bool(direct_url)
            state = ACCESS_STATE_FREE if is_free else ACCESS_STATE_REQUIRES_VIP
            reason = "" if is_free else "Tập này yêu cầu quyền VIP trên ứng dụng chính thức. HyperMedia chưa thể xác minh quyền truy cập từ trình duyệt PC."

            ep_id = str(ep_data.get("id") or ep_data.get("episodeId") or f"{sm_key}_{ep_num}")
            episodes.append(
                Episode(
                    num=ep_num,
                    title=f"Tập {ep_num}",
                    url=f"https://www.shortmax.com/drama/{sm_key}/{ep_num}?ep_id={ep_id}",
                    direct_url=direct_url,
                    thumb=ep_data.get("cover") or cover,
                    locked=not is_free,
                    provider_id=self.platform_id,
                    series_id=f"shortmax:{sm_key}",
                    episode_id=ep_id,
                    episode_number=ep_num,
                    access_state=state,
                    access_reason=reason,
                    extra={"video": v_dict, "sm_key": sm_key, "episode_id": ep_id},
                )
            )

        accessible = sum(1 for ep in episodes if not ep.locked)
        return Series(
            name=series_name,
            platform=self.platform_id,
            series_id=f"shortmax:{sm_key}",
            cover=cover,
            description=desc,
            episode_count=len(episodes),
            accessible_count=accessible,
            episodes=episodes,
            url=f"https://www.shortmax.com/drama/{sm_key}",
        )

    def resolve_episode_stream(self, episode: Episode) -> Optional[str]:
        if episode.access_state != ACCESS_STATE_FREE or episode.locked:
            return None
        return episode.direct_url
