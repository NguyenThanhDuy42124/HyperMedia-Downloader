"""
providers.stardusttv_provider
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Free-first platform provider for StardustTV.
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


class StardustTVProvider(BaseDramaProvider):
    platform_id = "stardusttv"
    display_name = "StardustTV"
    supports_catalog = False

    BASE_URL = "https://stardusttv2.goodbos.online"
    ALLOWED_HOSTS = {
        "stardusttv.com",
        "www.stardusttv.com",
        "stardusttv2.goodbos.online",
    }

    def can_handle(self, url: str) -> bool:
        if not url:
            return False
        u = str(url).strip()
        if u.lower().startswith("stardust:") or u.lower().startswith("stardusttv:"):
            return True
        try:
            host = (urlparse(u).netloc or "").lower().split(":")[0]
            return host in self.ALLOWED_HOSTS
        except Exception:
            return False

    def _extract_id(self, url: str) -> str:
        u = url.strip()
        m = re.search(r"stardust(?:tv)?:(\d+)", u, re.I)
        if m:
            return m.group(1)
        m = re.search(r"[?&](?:vid|id)=(\d+)", u, re.I)
        if m:
            return m.group(1)
        m = re.search(r"/(?:video|drama|detail|episodes)/(\d+)", u, re.I)
        return m.group(1) if m else ""

    def load_series(self, url: str) -> Series:
        sd_id = self._extract_id(url)
        if not sd_id:
            raise ValueError(f"Không thể nhận diện ID của StardustTV từ URL: {url}")

        resp = self.session.get(f"{self.BASE_URL}/video/episodes", params={"vid": sd_id, "lang": "en_US"}, timeout=10)
        if resp.status_code in (401, 403):
            raise ValueError(f"Máy chủ StardustTV từ chối truy cập (HTTP {resp.status_code})")
        if resp.status_code != 200:
            raise ValueError(f"StardustTV API lỗi: HTTP {resp.status_code}")

        res_json = resp.json()
        data = res_json.get("data") or res_json
        items = data.get("episodes") or []
        if not items:
            raise ValueError(f"StardustTV không trả về danh sách tập cho: {sd_id}")

        name = (data.get("name") or f"StardustTV Series {sd_id}").strip()
        cover = data.get("cover") or ""

        episodes: List[Episode] = []
        for idx, it in enumerate(items):
            ep_num = idx + 1
            v_url = it.get("m3u8") or it.get("video_url") or it.get("url") or None

            is_free = bool(v_url)
            state = ACCESS_STATE_FREE if is_free else ACCESS_STATE_REQUIRES_VIP
            reason = "" if is_free else "Tập này yêu cầu quyền VIP trên ứng dụng chính thức. HyperMedia chưa thể xác minh quyền truy cập từ trình duyệt PC."

            ep_id = str(it.get("id") or f"{sd_id}_{ep_num}")
            episodes.append(
                Episode(
                    num=ep_num,
                    title=f"Tập {ep_num}",
                    url=f"https://stardusttv.com/video/{sd_id}?ep={ep_num}&ep_id={ep_id}",
                    direct_url=v_url,
                    thumb=it.get("cover") or cover,
                    locked=not is_free,
                    provider_id=self.platform_id,
                    series_id=f"stardusttv:{sd_id}",
                    episode_id=ep_id,
                    episode_number=ep_num,
                    access_state=state,
                    access_reason=reason,
                    extra={"sd_id": sd_id},
                )
            )

        accessible = sum(1 for ep in episodes if not ep.locked)
        return Series(
            name=name,
            platform=self.platform_id,
            series_id=f"stardusttv:{sd_id}",
            cover=cover,
            episode_count=len(episodes),
            accessible_count=accessible,
            episodes=episodes,
            url=f"https://stardusttv.com/video/{sd_id}",
        )

    def resolve_episode_stream(self, episode: Episode) -> Optional[str]:
        if episode.access_state != ACCESS_STATE_FREE or episode.locked:
            return None
        return episode.direct_url
