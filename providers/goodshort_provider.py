"""
providers.goodshort_provider
~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Free-first platform provider for GoodShort and GoodReels.
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


class GoodShortProvider(BaseDramaProvider):
    platform_id = "goodshort"
    display_name = "GoodShort"
    supports_catalog = False

    BASE_URL = "https://goodshort.goodbos.online"
    ALLOWED_HOSTS = {
        "goodshort.com",
        "www.goodshort.com",
        "goodreels.com",
        "www.goodreels.com",
        "goodshort.goodbos.online",
    }

    def can_handle(self, url: str) -> bool:
        if not url:
            return False
        u = str(url).strip()
        if u.lower().startswith("goodshort:") or u.lower().startswith("goodreels:"):
            return True
        try:
            host = (urlparse(u).netloc or "").lower().split(":")[0]
            return host in self.ALLOWED_HOSTS
        except Exception:
            return False

    def _extract_id(self, url: str) -> str:
        u = url.strip()
        m = re.search(r"(?:goodshort|goodreels):(\d+)", u, re.I)
        if m:
            return m.group(1)
        m = re.search(r"/(?:video|book|detail)/(\d+)", u)
        if m:
            return m.group(1)
        m = re.search(r"[?&]id=(\d+)", u)
        if m:
            return m.group(1)
        m = re.search(r"(\d{6,})", u)
        return m.group(1) if m else ""

    def load_series(self, url: str) -> Series:
        book_id = self._extract_id(url)
        if not book_id:
            raise ValueError(f"Không thể nhận diện Book ID của GoodShort từ URL: {url}")

        headers = {"User-Agent": "okhttp/4.10.0"}

        name = f"GoodShort Series {book_id}"
        cover = ""
        desc = ""
        total_episodes = 0

        try:
            resp = self.session.get(f"{self.BASE_URL}/book/{book_id}?lang=en", headers=headers, timeout=10)
            if resp.status_code == 200:
                data = resp.json().get("data", {})
                book_data = data.get("book") or data
                name = (book_data.get("bookName") or book_data.get("title") or name).strip()
                cover = book_data.get("cover") or book_data.get("bookDetailCover") or ""
                desc = book_data.get("introduction") or book_data.get("desc") or ""
                total_episodes = int(book_data.get("chapterCount") or 0)
            elif resp.status_code in (401, 403):
                raise ValueError(f"Máy chủ GoodShort từ chối truy cập (HTTP {resp.status_code})")
        except ValueError:
            raise
        except Exception:
            pass

        episodes: List[Episode] = []
        try:
            resp = self.session.get(f"{self.BASE_URL}/chapters/{book_id}?lang=en", headers=headers, timeout=10)
            if resp.status_code == 200:
                ch_list = resp.json().get("data", {}).get("list", [])
                for idx, item in enumerate(ch_list):
                    ep_num = (item.get("index") + 1 if item.get("index") is not None else None) or (idx + 1)
                    cdn_list = item.get("cdnList") or []
                    first_cdn = cdn_list[0].get("videoPath") if cdn_list and isinstance(cdn_list[0], dict) else ""
                    direct_url = item.get("cdn") or first_cdn or None

                    is_free = bool(direct_url)
                    state = ACCESS_STATE_FREE if is_free else ACCESS_STATE_REQUIRES_VIP
                    reason = "" if is_free else "Tập này yêu cầu quyền VIP trên ứng dụng chính thức. HyperMedia chưa thể xác minh quyền truy cập từ trình duyệt PC."

                    ep_id = str(item.get("chapterId") or f"{book_id}_{ep_num}")
                    episodes.append(
                        Episode(
                            num=ep_num,
                            title=item.get("chapterName") or f"Tập {ep_num}",
                            url=f"https://www.goodshort.com/video/{book_id}/{ep_num}?ch_id={ep_id}",
                            direct_url=direct_url,
                            thumb=cover,
                            locked=not is_free,
                            provider_id=self.platform_id,
                            series_id=f"goodshort:{book_id}",
                            episode_id=ep_id,
                            episode_number=ep_num,
                            access_state=state,
                            access_reason=reason,
                            extra={"book_id": book_id, "chapter_id": ep_id},
                        )
                    )
            elif resp.status_code in (401, 403):
                raise ValueError(f"Máy chủ GoodShort từ chối truy cập chapters (HTTP {resp.status_code})")
        except ValueError:
            raise
        except Exception:
            pass

        if not episodes and total_episodes > 0:
            for i in range(1, total_episodes + 1):
                episodes.append(
                    Episode(
                        num=i,
                        title=f"Tập {i}",
                        url=f"https://www.goodshort.com/video/{book_id}/{i}",
                        direct_url=None,
                        thumb=cover,
                        locked=True,
                        provider_id=self.platform_id,
                        series_id=f"goodshort:{book_id}",
                        episode_id=f"{book_id}_{i}",
                        episode_number=i,
                        access_state=ACCESS_STATE_REQUIRES_VIP,
                        access_reason="Tập này yêu cầu quyền VIP trên ứng dụng chính thức. HyperMedia chưa thể xác minh quyền truy cập từ trình duyệt PC.",
                        extra={"book_id": book_id},
                    )
                )

        if not episodes:
            raise ValueError(f"Không thể nạp thông tin tập phim của GoodShort ID: {book_id}")

        accessible = sum(1 for ep in episodes if not ep.locked)
        return Series(
            name=name,
            platform=self.platform_id,
            series_id=f"goodshort:{book_id}",
            cover=cover,
            description=desc,
            episode_count=len(episodes),
            accessible_count=accessible,
            episodes=episodes,
            url=f"https://www.goodshort.com/video/{book_id}/1",
        )

    def resolve_episode_stream(self, episode: Episode) -> Optional[str]:
        if episode.access_state != ACCESS_STATE_FREE or episode.locked:
            return None
        return episode.direct_url
