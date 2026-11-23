"""
providers.netshort_provider
~~~~~~~~~~~~~~~~~~~~~~~~~~~
Free-first platform provider for NetShort and FlickReels.
Enforces free episode boundary, subtitle parsing, and marks locked episodes as requires_vip.
"""

import re
from urllib.parse import urlparse
from typing import Optional, List, Dict, Any

from .base import (
    BaseDramaProvider,
    Series,
    Episode,
    Subtitle,
    CatalogItem,
    CatalogResult,
    ACCESS_STATE_FREE,
    ACCESS_STATE_REQUIRES_VIP,
)


class NetShortProvider(BaseDramaProvider):
    platform_id = "netshort"
    display_name = "NetShort"
    supports_catalog = False

    BASE_URL = "https://netshort.goodbos.online/api"
    ALLOWED_HOSTS = {
        "netshort.com",
        "www.netshort.com",
        "flickreels.com",
        "www.flickreels.com",
        "netshort.goodbos.online",
    }

    def can_handle(self, url: str) -> bool:
        if not url:
            return False
        u = str(url).strip()
        if u.lower().startswith("netshort:") or u.lower().startswith("flickreels:"):
            return True
        try:
            host = (urlparse(u).netloc or "").lower().split(":")[0]
            return host in self.ALLOWED_HOSTS
        except Exception:
            return False

    def _extract_id(self, url: str) -> str:
        u = url.strip()
        m = re.search(r"(?:netshort|flickreels):([A-Za-z0-9_-]+)", u, re.I)
        if m:
            return m.group(1)
        m = re.search(r"/(?:drama|series|detail|play)/([A-Za-z0-9_-]+)", u, re.I)
        if m:
            return m.group(1)
        m = re.search(r"[?&](?:id|dramaId|bookId)=([A-Za-z0-9_-]+)", u, re.I)
        if m:
            return m.group(1)
        m = re.search(r"([A-Za-z0-9_-]{8,})", u)
        return m.group(1) if m else ""

    def _parse_subs(self, sub_list: Any) -> List[Subtitle]:
        if not isinstance(sub_list, list):
            return []
        subs = []
        for s in sub_list:
            if isinstance(s, dict) and s.get("url"):
                lang = str(s.get("lang") or s.get("subtitleLanguage") or "en").replace("_", "-")
                subs.append(Subtitle(lang=lang, name=lang, url=s["url"]))
        return subs

    def load_series(self, url: str) -> Series:
        ns_key = self._extract_id(url)
        if not ns_key:
            raise ValueError(f"Không thể nhận diện Drama Key của NetShort từ URL: {url}")

        params = {"lang": "en"}
        resp = self.session.get(f"{self.BASE_URL}/drama/{ns_key}", params=params, timeout=10)
        if resp.status_code == 429:
            raise ValueError("NetShort API bị giới hạn tốc độ (HTTP 429), vui lòng thử lại sau")
        if resp.status_code in (401, 403):
            raise ValueError(f"Máy chủ NetShort từ chối truy cập (HTTP {resp.status_code})")
        if resp.status_code != 200:
            raise ValueError(f"NetShort API lỗi: HTTP {resp.status_code}")

        res_json = resp.json()
        data = res_json.get("data") or {}
        raw_episodes = data.get("shortPlayEpisodeList") or []
        if not raw_episodes:
            raise ValueError(f"NetShort không trả về danh sách tập cho: {ns_key}")

        raw_episodes = sorted(raw_episodes, key=lambda x: x.get("episodeNo", 0))

        series_name = (data.get("shortPlayName") or f"NetShort Drama {ns_key}").strip()
        cover = data.get("shortPlayCover") or ""

        episodes: List[Episode] = []
        for idx, ep in enumerate(raw_episodes):
            ep_num = idx + 1
            ep_no = ep.get("episodeNo") or ep_num
            direct_url = ep.get("playVoucher") or None
            subs = self._parse_subs(ep.get("subtitleList"))

            is_free = bool(direct_url)
            state = ACCESS_STATE_FREE if is_free else ACCESS_STATE_REQUIRES_VIP
            reason = "" if is_free else "Tập này yêu cầu quyền VIP trên ứng dụng chính thức. HyperMedia chưa thể xác minh quyền truy cập từ trình duyệt PC."

            ep_id = str(ep.get("episodeId") or ep.get("id") or f"{ns_key}_{ep_no}")
            episodes.append(
                Episode(
                    num=ep_num,
                    title=f"Tập {ep_num}",
                    url=f"https://netshort.com/drama/{ns_key}/{ep_num}?ep_id={ep_id}",
                    direct_url=direct_url,
                    thumb=ep.get("episodeCover") or cover,
                    locked=not is_free,
                    subtitles=subs,
                    provider_id=self.platform_id,
                    series_id=f"netshort:{ns_key}",
                    episode_id=ep_id,
                    episode_number=ep_num,
                    access_state=state,
                    access_reason=reason,
                    extra={"ns_key": ns_key, "ns_ep": ep_no},
                )
            )

        accessible = sum(1 for ep in episodes if not ep.locked)
        return Series(
            name=series_name,
            platform=self.platform_id,
            series_id=f"netshort:{ns_key}",
            cover=cover,
            episode_count=len(episodes),
            accessible_count=accessible,
            episodes=episodes,
            url=f"https://netshort.com/drama/{ns_key}",
        )

    def resolve_episode_stream(self, episode: Episode) -> Optional[str]:
        if episode.access_state != ACCESS_STATE_FREE or episode.locked:
            return None
        return episode.direct_url
