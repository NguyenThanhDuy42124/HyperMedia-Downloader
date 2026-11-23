"""
providers.kisskh_provider
~~~~~~~~~~~~~~~~~~~~~~~~~
KissKH platform provider for drama series catalog browsing, search,
and episode extraction across mirrors.
"""

import re
import urllib.parse
from typing import Optional, List, Dict, Any, Tuple
from .base import (
    BaseDramaProvider,
    Series,
    Episode,
    Subtitle,
    CatalogItem,
    CatalogResult,
    ACCESS_STATE_FREE,
)


class KisskhProvider(BaseDramaProvider):
    platform_id: str = "kisskh"
    display_name: str = "KissKH"
    supports_catalog: bool = True
    status: str = "active"

    MIRRORS = ["kisskh.co", "kisskh.do", "kisskh.id", "kisskh.is"]

    def can_handle(self, url: str) -> bool:
        if not url:
            return False
        u = str(url).strip()
        if u.lower().startswith("kisskh:"):
            return True
        try:
            from urllib.parse import urlparse
            host = (urlparse(u).netloc or "").lower().split(":")[0]
            return host in {"kisskh.co", "www.kisskh.co", "kisskh.do", "kisskh.id", "kisskh.is"}
        except Exception:
            return False

    def _extract_id(self, url: str) -> str:
        u = url.strip()
        m = re.search(r"kisskh:(\d+)", u, re.I)
        if m:
            return m.group(1)
        m = re.search(r"[?&]id=(\d+)", u, re.I)
        if m:
            return m.group(1)
        m = re.search(r"/DramaList/Drama/(\d+)", u, re.I)
        if m:
            return m.group(1)
        m = re.search(r"/Drama/[^/]+.*?id=(\d+)", u, re.I)
        return m.group(1) if m else ""

    def _request_api(self, endpoint: str) -> Any:
        last_err = None
        for domain in self.MIRRORS:
            try:
                url = f"https://{domain}/api/{endpoint}"
                headers = {
                    "User-Agent": (
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/131.0.0.0 Safari/537.36"
                    ),
                    "Referer": f"https://{domain}/",
                }
                resp = self.session.get(url, headers=headers, timeout=8)
                if resp.status_code == 200:
                    return resp.json()
                last_err = f"HTTP {resp.status_code}"
            except Exception as e:
                last_err = e
        self.last_error = str(last_err or "unknown_error")
        raise ValueError(f"KissKH không phản hồi trên các mirror: {last_err}")

    def load_series(self, url: str) -> Series:
        kk_id = self._extract_id(url)
        if not kk_id:
            raise ValueError(f"Không thể nhận diện ID từ URL KissKH: {url}")

        data = self._request_api(f"DramaList/Drama/{kk_id}?isq=false")
        if not data or not isinstance(data.get("episodes"), list):
            raise ValueError(f"KissKH: Không tìm thấy dữ liệu cho series ID: {kk_id}")

        raw_episodes = data["episodes"]
        raw_episodes = sorted(raw_episodes, key=lambda x: float(x.get("number") or 0))

        title = str(data.get("title") or f"KissKH Drama {kk_id}").strip()
        cover = str(data.get("thumbnail") or "")
        desc = str(data.get("description") or "")

        episodes: List[Episode] = []
        for idx, ep_data in enumerate(raw_episodes):
            ep_num = idx + 1
            ep_no = str(ep_data.get("number", ep_num))
            ep_id = str(ep_data.get("id"))

            parsed_ep_no = ep_num
            try:
                parsed_ep_no = int(float(ep_no))
            except Exception:
                pass

            episodes.append(
                Episode(
                    num=ep_num,
                    title=f"Tập {ep_no}" if len(raw_episodes) > 1 else title,
                    url=f"https://kisskh.co/Drama/?id={kk_id}&ep_id={ep_id}&ep={ep_no}",
                    direct_url=None,
                    thumb=cover,
                    locked=False,
                    provider_id=self.platform_id,
                    series_id=f"kisskh:{kk_id}",
                    episode_id=ep_id,
                    episode_number=parsed_ep_no,
                    access_state="free",
                    access_reason="",
                    extra={"kk_id": kk_id, "kk_ep": ep_id, "kk_num": ep_no},
                )
            )

        return Series(
            name=title,
            platform=self.platform_id,
            series_id=f"kisskh:{kk_id}",
            cover=cover,
            description=desc,
            episode_count=len(episodes),
            accessible_count=len(episodes),
            episodes=episodes,
            url=f"https://kisskh.co/Drama/?id={kk_id}",
        )

    def resolve_episode_stream(self, episode: Episode) -> Optional[str]:
        self.last_error = ""
        if episode.access_state not in (ACCESS_STATE_FREE, "authorized") or episode.locked:
            return None

        if episode.direct_url:
            return episode.direct_url

        kk_ep = episode.extra.get("kk_ep") or episode.episode_id
        if not kk_ep and episode.url:
            m_ep = re.search(r"[?&]ep_id=(\d+)", str(episode.url))
            if m_ep:
                kk_ep = m_ep.group(1)
        if not kk_ep:
            return None

        try:
            res = self._request_api(f"DramaList/Episode/{kk_ep}.png?err=false&ts=null&time=null")
            if res and isinstance(res, dict):
                v_url = res.get("Video") or res.get("Video_tmp")
                if v_url:
                    if v_url.startswith("//"):
                        v_url = "https:" + v_url
                    episode.direct_url = v_url

                    # Trích xuất danh sách phụ đề nếu có
                    sub_list = res.get("subtitles") or []
                    if isinstance(sub_list, list):
                        subs = []
                        for s in sub_list:
                            if isinstance(s, dict) and s.get("src"):
                                subs.append(
                                    Subtitle(
                                        lang=s.get("label", "en"),
                                        name=s.get("label", "en"),
                                        url=s.get("src"),
                                    )
                                )
                        episode.subtitles = subs

                    return v_url
        except Exception:
            pass

        return None

    def get_catalog(
        self,
        page: int = 1,
        query: Optional[str] = None,
        category: Optional[str] = None,
    ) -> CatalogResult:
        try:
            items: List[CatalogItem] = []
            seen_ids = set()

            if query and query.strip():
                q = query.strip()
                try:
                    data = self._request_api(f"DramaList/Search?q={urllib.parse.quote(q)}&page={page}")
                except Exception as e:
                    return CatalogResult(
                        items=[],
                        total=0,
                        platform=self.platform_id,
                        page=page,
                        has_more=False,
                        error=f"Không thể tìm kiếm trên KissKH: {e}",
                    )
                raw_list = data if isinstance(data, list) else (data.get("data") or [])
                total = data.get("totalCount", len(raw_list)) if isinstance(data, dict) else len(raw_list)

                for it in raw_list:
                    if not isinstance(it, dict):
                        continue
                    sid = str(it.get("id") or "")
                    if not sid or sid in seen_ids:
                        continue
                    seen_ids.add(sid)
                    name = str(it.get("title") or "").strip()
                    cover = str(it.get("thumbnail") or "")
                    ep_cnt = int(it.get("episodesCount") or 0)
                    desc = str(it.get("description") or it.get("label") or "")

                    items.append(
                        CatalogItem(
                            id=sid,
                            name=name,
                            cover=cover,
                            episodes=ep_cnt,
                            desc=desc,
                            link=f"https://kisskh.co/Drama/?id={sid}",
                            platform=self.platform_id,
                        )
                    )

                if total <= 0:
                    total = len(items)
                has_more = (page * 10) < total if total > len(items) else len(items) >= 10
                partial_warn = None
            else:
                p1 = (page - 1) * 2 + 1
                p2 = (page - 1) * 2 + 2

                total = 0
                raw_list = []
                errors = []

                # Nạp trang API 1
                try:
                    d1 = self._request_api(f"DramaList/List?page={p1}&type=0&sub=0&country=0&status=0&order=1")
                    if isinstance(d1, dict):
                        total = int(d1.get("totalCount") or 0)
                        raw_list.extend(d1.get("data") or [])
                    elif isinstance(d1, list):
                        raw_list.extend(d1)
                except Exception as e:
                    errors.append(f"Trang {p1}: {e}")

                # Nạp trang API 2
                try:
                    d2 = self._request_api(f"DramaList/List?page={p2}&type=0&sub=0&country=0&status=0&order=1")
                    if isinstance(d2, dict):
                        if not total:
                            total = int(d2.get("totalCount") or 0)
                        raw_list.extend(d2.get("data") or [])
                    elif isinstance(d2, list):
                        raw_list.extend(d2)
                except Exception as e:
                    errors.append(f"Trang {p2}: {e}")

                # Nếu cả 2 trang đều thất bại: trả lỗi rõ ràng, không nuốt lỗi
                if len(errors) == 2 and not raw_list:
                    return CatalogResult(
                        items=[],
                        total=0,
                        platform=self.platform_id,
                        page=page,
                        has_more=False,
                        error=f"Không thể kết nối danh mục KissKH: {'; '.join(errors)}",
                    )

                partial_warn = f"Cảnh báo một phần: {errors[0]}" if (errors and raw_list) else None

                for it in raw_list:
                    if not isinstance(it, dict):
                        continue
                    sid = str(it.get("id") or "")
                    if not sid or sid in seen_ids:
                        continue
                    seen_ids.add(sid)
                    name = str(it.get("title") or "").strip()
                    cover = str(it.get("thumbnail") or "")
                    ep_cnt = int(it.get("episodesCount") or 0)
                    desc = str(it.get("description") or it.get("label") or "")

                    items.append(
                        CatalogItem(
                            id=sid,
                            name=name,
                            cover=cover,
                            episodes=ep_cnt,
                            desc=desc,
                            link=f"https://kisskh.co/Drama/?id={sid}",
                            platform=self.platform_id,
                        )
                    )

                if total <= 0:
                    total = len(items)
                has_more = (page * 20) < total

            return CatalogResult(
                items=items,
                total=total,
                platform=self.platform_id,
                page=page,
                has_more=has_more,
                error=partial_warn,
            )
        except Exception as e:
            return CatalogResult(
                items=[],
                total=0,
                platform=self.platform_id,
                page=page,
                error=f"Lỗi kết nối KissKH: {e}",
                has_more=False,
            )

    def get_session_status(self) -> Tuple[str, str]:
        """KissKH là nền tảng cộng đồng miễn phí 100%, không yêu cầu tài khoản VIP."""
        return "free_platform", "KissKH là nền tảng miễn phí 100%, không yêu cầu tài khoản VIP"

    def authenticate(self, credentials: Dict[str, Any]) -> bool:
        """KissKH là nền tảng mở công khai, không có API đăng nhập tài khoản."""
        return False

    def refresh_session(self) -> bool:
        """KissKH không sử dụng phiên người dùng."""
        return False

    def validate_entitlement(self, episode: Episode) -> bool:
        """KissKH cho phép truy cập toàn bộ tập phim miễn phí."""
        return not episode.locked
