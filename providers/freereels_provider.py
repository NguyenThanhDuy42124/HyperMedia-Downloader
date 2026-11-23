"""
providers.freereels_provider
~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Free-first platform provider for FreeReels.
Enforces free episode boundary, subtitle extraction, and marks locked episodes as requires_vip.
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


class FreeReelsProvider(BaseDramaProvider):
    platform_id = "freereels"
    display_name = "FreeReels"
    supports_catalog = False

    BASE_URL = "https://drakula.goodbos.online/api/freereels"
    ALLOWED_HOSTS = {
        "freereels.app",
        "www.freereels.app",
        "freereels.cc",
        "www.freereels.cc",
        "drakula.goodbos.online",
    }

    def can_handle(self, url: str) -> bool:
        if not url:
            return False
        u = str(url).strip()
        if u.lower().startswith("freereels:"):
            return True
        try:
            host = (urlparse(u).netloc or "").lower().split(":")[0]
            return host in self.ALLOWED_HOSTS
        except Exception:
            return False

    def _extract_id(self, url: str) -> str:
        u = url.strip()
        m = re.search(r"freereels:[/\\]*([A-Za-z0-9_-]+)", u, re.I)
        if m:
            return m.group(1)
        m = re.search(r"/(?:drama|series|detail|video)/([A-Za-z0-9_-]{6,})", u, re.I)
        if m:
            return m.group(1)
        m = re.search(r"[?&](?:id|key|series_id)=([A-Za-z0-9_-]{6,})", u, re.I)
        if m:
            return m.group(1)
        m = re.search(r"/([A-Za-z0-9_-]{8,14})/?(?:[?#].*)?$", u)
        return m.group(1) if m else ""

    def _pick_mp4(self, item: Dict[str, Any]) -> Optional[str]:
        vlist = item.get("video_list") or item.get("play_list") or []
        if isinstance(vlist, list) and vlist:
            for item_v in vlist:
                if isinstance(item_v, dict) and item_v.get("video_path"):
                    return item_v["video_path"]
        return item.get("video_path") or item.get("play_url") or item.get("m3u8_url") or None

    def load_series(self, url: str) -> Series:
        fr_key = self._extract_id(url)
        if not fr_key:
            raise ValueError(f"Không thể nhận diện Drama Key của FreeReels từ URL: {url}")

        params = {"key": fr_key, "lang": "en"}
        resp = self.session.get(f"{self.BASE_URL}/episodes", params=params, timeout=10)
        if resp.status_code in (401, 403):
            raise ValueError(f"Máy chủ FreeReels từ chối truy cập (HTTP {resp.status_code})")
        if resp.status_code != 200:
            raise ValueError(f"FreeReels API lỗi: HTTP {resp.status_code}")

        res_json = resp.json()
        data = res_json.get("data") or res_json
        items = data.get("items") or data.get("episodes") or []

        valid_items = [it for it in items if not it.get("is_blooper")]
        if not valid_items:
            valid_items = items
        if not valid_items:
            raise ValueError(f"FreeReels không trả về danh sách tập cho series: {fr_key}")

        valid_items = sorted(valid_items, key=lambda x: x.get("serial_number", 0))

        series_name = (data.get("name") or data.get("title") or f"FreeReels Drama {fr_key}").strip()
        cover = data.get("cover") or ""
        desc = data.get("desc") or ""

        episodes: List[Episode] = []
        for idx, it in enumerate(valid_items):
            ep_num = idx + 1
            direct_url = self._pick_mp4(it)

            subs = []
            sub_list = it.get("subtitle_list") or []
            if isinstance(sub_list, list):
                for s in sub_list:
                    if isinstance(s, dict) and s.get("subtitle_url"):
                        lang = str(s.get("language_name") or s.get("lang") or "en")
                        subs.append(Subtitle(lang=lang, name=lang, url=s["subtitle_url"]))

            is_free = bool(direct_url)
            state = ACCESS_STATE_FREE if is_free else ACCESS_STATE_REQUIRES_VIP
            reason = "" if is_free else "Tập này yêu cầu quyền VIP trên ứng dụng chính thức. HyperMedia chưa thể xác minh quyền truy cập từ trình duyệt PC."

            ep_id = str(it.get("id") or it.get("episode_id") or f"{fr_key}_{ep_num}")
            episodes.append(
                Episode(
                    num=ep_num,
                    title=it.get("name") or f"Tập {ep_num}",
                    url=f"https://freereels.app/drama/{fr_key}/{ep_num}?ep_id={ep_id}",
                    direct_url=direct_url,
                    thumb=it.get("cover") or cover,
                    locked=not is_free,
                    subtitles=subs,
                    provider_id=self.platform_id,
                    series_id=f"freereels:{fr_key}",
                    episode_id=ep_id,
                    episode_number=ep_num,
                    access_state=state,
                    access_reason=reason,
                    extra={"fr_key": fr_key},
                )
            )

        accessible = sum(1 for ep in episodes if not ep.locked)
        return Series(
            name=series_name,
            platform=self.platform_id,
            series_id=f"freereels:{fr_key}",
            cover=cover,
            description=desc,
            episode_count=len(episodes),
            accessible_count=accessible,
            episodes=episodes,
            url=f"https://freereels.app/drama/{fr_key}",
        )

    def resolve_episode_stream(self, episode: Episode) -> Optional[str]:
        if episode.access_state != ACCESS_STATE_FREE or episode.locked:
            return None
        return episode.direct_url
