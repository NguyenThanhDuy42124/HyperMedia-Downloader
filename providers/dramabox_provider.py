"""
providers.dramabox_provider
~~~~~~~~~~~~~~~~~~~~~~~~~~~
DramaBox platform provider with live stream extraction, signed URL refresh,
and catalog discovery.
"""

import json
import re
from typing import Optional, List, Dict, Any, Tuple
from .base import (
    BaseDramaProvider,
    Series,
    Episode,
    CatalogItem,
    CatalogResult,
    ACCESS_STATE_FREE,
)


class DramaBoxProvider(BaseDramaProvider):
    platform_id: str = "dramabox"
    display_name: str = "DramaBox"
    supports_catalog: bool = True
    status: str = "active"

    BASE_URL = "https://www.dramaboxdb.com"

    def can_handle(self, url: str) -> bool:
        if not url:
            return False
        u = str(url).strip()
        if u.lower().startswith("dramabox:"):
            return True
        try:
            from urllib.parse import urlparse
            host = (urlparse(u).netloc or "").lower().split(":")[0]
            return host in {"dramaboxdb.com", "www.dramaboxdb.com"}
        except Exception:
            return False

    def _extract_id(self, url: str) -> str:
        u = url.strip()
        m = re.search(r"/(?:movie|ep|detail)[/-](\d+)", u)
        if m:
            return m.group(1)
        m = re.search(r"dramabox:(\d+)", u, re.I)
        if m:
            return m.group(1)
        m = re.search(r"(\d{6,})", u)
        return m.group(1) if m else ""

    def load_series(self, url: str) -> Series:
        book_id = self._extract_id(url)
        if not book_id:
            raise ValueError(f"Không thể nhận diện Book ID của DramaBox từ URL: {url}")

        db_url = f"{self.BASE_URL}/movie/{book_id}/drama"
        resp = self.session.get(db_url, timeout=12)
        if resp.status_code != 200:
            raise ValueError(f"DramaBox trả về mã lỗi HTTP {resp.status_code} khi tải series {book_id}")

        m = re.search(r'<script id="__NEXT_DATA__"[^>]*>([\s\S]*?)</script>', resp.text)
        if not m:
            raise ValueError(f"Không tìm thấy dữ liệu __NEXT_DATA__ trên trang DramaBox ({db_url})")

        data = json.loads(m.group(1))
        page_props = data.get("props", {}).get("pageProps", {})
        book_info = page_props.get("bookInfo", {})

        series_name = (
            book_info.get("bookName")
            or book_info.get("name")
            or f"DramaBox Series {book_id}"
        ).strip()
        cover = book_info.get("cover") or book_info.get("coverWap") or ""
        description = book_info.get("introduction") or book_info.get("desc") or ""

        chapter_list = page_props.get("chapterList", [])
        episodes: List[Episode] = []

        for idx, ch in enumerate(chapter_list):
            ep_num = (ch.get("index") + 1 if ch.get("index") is not None else ch.get("chapterIndex")) or (idx + 1)
            is_unlocked = bool(ch.get("unlock", False))
            mp4_url = ch.get("mp4") or ""
            m3u8_url = ch.get("m3u8Url") or ""

            # Ưu tiên direct MP4 chất lượng cao nhất, nếu không có thì dùng HLS m3u8
            stream_url = mp4_url or m3u8_url or None
            exp_val = None
            if stream_url:
                m_exp = re.search(r"Expires=(\d+)", stream_url)
                if m_exp:
                    exp_val = int(m_exp.group(1))

            ep_id = str(ch.get("id") or f"{book_id}_{ep_num}")
            ch_name = ch.get("name") or f"Tập {ep_num}"

            episodes.append(
                Episode(
                    num=ep_num,
                    title=ch_name,
                    url=f"{self.BASE_URL}/movie/{book_id}/drama?ch_id={ep_id}&ep={ep_num}",
                    direct_url=stream_url if is_unlocked else None,
                    thumb=ch.get("cover") or cover,
                    locked=not is_unlocked,
                    provider_id=self.platform_id,
                    series_id=f"dramabox:{book_id}",
                    episode_id=ep_id,
                    episode_number=ep_num,
                    access_state="free" if is_unlocked else "requires_vip",
                    access_reason="" if is_unlocked else "Tập yêu cầu mở khóa VIP trên nền tảng DramaBox",
                    expires_at=exp_val,
                    extra={
                        "book_id": book_id,
                        "chapter_id": ep_id,
                        "mp4": mp4_url,
                        "m3u8": m3u8_url,
                        "duration": ch.get("duration", 0),
                    },
                )
            )

        accessible_count = sum(1 for ep in episodes if not ep.locked)

        return Series(
            name=series_name,
            platform=self.platform_id,
            series_id=f"dramabox:{book_id}",
            cover=cover,
            description=description,
            episode_count=len(episodes),
            accessible_count=accessible_count,
            episodes=episodes,
            url=db_url,
        )

    def resolve_episode_stream(self, episode: Episode) -> Optional[str]:
        """Làm mới stream URL có chữ ký CloudFront ngay trước khi bắt đầu tải."""
        if episode.access_state != ACCESS_STATE_FREE or episode.locked:
            return None

        # Kiểm tra xem direct_url hiện tại có còn hạn hay không (nếu có tham số Expires)
        current_url = episode.direct_url
        if current_url:
            m = re.search(r"Expires=(\d+)", current_url)
            if m:
                import time
                expires_at = int(m.group(1))
                if expires_at > time.time() + 60:
                    return current_url

        # Nếu chưa có URL hoặc sắp hết hạn, fetch lại trang để lấy fresh signed tokens
        book_id = episode.extra.get("book_id")
        ch_id = episode.extra.get("chapter_id") or episode.episode_id
        if not book_id and episode.series_id and "dramabox:" in episode.series_id:
            book_id = episode.series_id.split(":", 1)[1]
        if not book_id:
            # Thử trích xuất từ episode.url
            book_id = self._extract_id(episode.url)
        if not book_id:
            return current_url

        try:
            db_url = f"{self.BASE_URL}/movie/{book_id}/drama"
            resp = self.session.get(db_url, timeout=10)
            if resp.status_code == 200:
                m = re.search(r'<script id="__NEXT_DATA__"[^>]*>([\s\S]*?)</script>', resp.text)
                if m:
                    data = json.loads(m.group(1))
                    chs = data.get("props", {}).get("pageProps", {}).get("chapterList", [])
                    matched_ch = None
                    # Ưu tiên 100% khớp chapter_id (định danh bền vững)
                    if ch_id:
                        for ch in chs:
                            if str(ch.get("id")) == str(ch_id):
                                matched_ch = ch
                                break
                    # Chỉ fallback theo ordinal khi hoàn toàn không có chapter_id
                    if not matched_ch and not ch_id and episode.num:
                        for ch in chs:
                            if ch.get("index") is not None and ch.get("index") + 1 == episode.num:
                                matched_ch = ch
                                break

                    if matched_ch:
                        fresh_stream = matched_ch.get("mp4") or matched_ch.get("m3u8Url")
                        if fresh_stream:
                            episode.direct_url = fresh_stream
                            return fresh_stream
        except Exception:
            pass

        return current_url

    def get_catalog(
        self,
        page: int = 1,
        query: Optional[str] = None,
        category: Optional[str] = None,
    ) -> CatalogResult:
        """Duyệt danh sách phim thịnh hành hoặc tìm kiếm từ DramaBox với phân trang chuẩn."""
        try:
            resp = self.session.get(self.BASE_URL, timeout=10)
            if resp.status_code != 200:
                return CatalogResult(
                    items=[],
                    total=0,
                    platform=self.platform_id,
                    page=page,
                    error=f"DramaBox phản hồi mã lỗi HTTP {resp.status_code}",
                    has_more=False,
                )

            m = re.search(r'<script id="__NEXT_DATA__"[^>]*>([\s\S]*?)</script>', resp.text)
            if not m:
                return CatalogResult(
                    items=[],
                    total=0,
                    platform=self.platform_id,
                    page=page,
                    error="Không tìm thấy cấu trúc __NEXT_DATA__ từ trang chủ",
                    has_more=False,
                )

            data = json.loads(m.group(1))
            props = data.get("props", {}).get("pageProps", {})

            # Kiểm tra cấu trúc bắt buộc: bigList hoặc smallData phải tồn tại
            has_big = "bigList" in props and props.get("bigList") is not None
            has_small = "smallData" in props and props.get("smallData") is not None
            if not has_big and not has_small:
                return CatalogResult(
                    items=[],
                    total=0,
                    platform=self.platform_id,
                    page=page,
                    error="Dữ liệu danh mục từ nguồn đã thay đổi. Hãy thử lại hoặc dùng tìm kiếm/link trực tiếp.",
                    has_more=False,
                )

            raw_items = []
            # 1. Thu thập từ bigList
            raw_items.extend(props.get("bigList") or [])

            # 2. Thu thập an toàn từ smallData (hỗ trợ cả dạng list của các section và dict)
            small = props.get("smallData")
            if isinstance(small, list):
                for sec in small:
                    if isinstance(sec, dict):
                        sec_items = sec.get("items") or sec.get("list") or []
                        if isinstance(sec_items, list):
                            raw_items.extend(sec_items)
            elif isinstance(small, dict):
                for v in small.values():
                    if isinstance(v, list):
                        raw_items.extend(v)
                    elif isinstance(v, dict):
                        sub_items = v.get("items") or v.get("list") or []
                        if isinstance(sub_items, list):
                            raw_items.extend(sub_items)

            items: List[CatalogItem] = []
            seen_ids = set()

            q_clean = query.lower().strip() if query else None

            for it in raw_items:
                if not isinstance(it, dict):
                    continue
                bid = str(it.get("bookId") or it.get("action") or "")
                if not bid or bid in seen_ids:
                    continue
                name = str(it.get("bookName") or it.get("name") or "").strip()
                desc = str(it.get("introduction") or it.get("desc") or "").strip()
                if not name:
                    continue

                if q_clean and (q_clean not in name.lower() and q_clean not in desc.lower()):
                    continue

                seen_ids.add(bid)
                cover = str(it.get("cover") or it.get("coverWap") or "")
                ep_count = int(it.get("chapterCount") or 0)

                items.append(
                    CatalogItem(
                        id=bid,
                        name=name,
                        cover=cover,
                        episodes=ep_count,
                        desc=desc,
                        link=f"{self.BASE_URL}/movie/{bid}/drama",
                        platform=self.platform_id,
                    )
                )

            # Phân trang client-side xác định (10 phim / trang)
            page_size = 10
            total_items = len(items)
            start_idx = (page - 1) * page_size
            end_idx = start_idx + page_size
            page_items = items[start_idx:end_idx] if start_idx < total_items else []
            has_more = end_idx < total_items

            return CatalogResult(
                items=page_items,
                total=total_items,
                platform=self.platform_id,
                page=page,
                has_more=has_more,
            )
        except Exception as e:
            return CatalogResult(
                items=[],
                total=0,
                platform=self.platform_id,
                page=page,
                error=f"Lỗi kết nối DramaBox: {e}",
                has_more=False,
            )

    def get_session_status(self) -> Tuple[str, str]:
        """DramaBox không có API xác thực tài khoản VIP trên Web PC."""
        return "unsupported", "DramaBox chưa hỗ trợ API tài khoản VIP trên Web PC (giao dịch thực hiện qua app di động)"

    def authenticate(self, credentials: Dict[str, Any]) -> bool:
        """DramaBox không hỗ trợ xác thực tài khoản VIP từ Web PC."""
        return False

    def refresh_session(self) -> bool:
        """DramaBox không hỗ trợ phiên người dùng trên Web PC."""
        return False

    def validate_entitlement(self, episode: Episode) -> bool:
        """Kiểm tra quyền truy cập: Chỉ cho phép các tập Free có stream hợp lệ."""
        return episode.access_state == ACCESS_STATE_FREE and not episode.locked
