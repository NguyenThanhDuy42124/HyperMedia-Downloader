"""
providers/miniapp_douyin_provider.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Adapter tích hợp nền tảng MiniApp Douyin (họ duolai) và video Douyin theo kiến trúc Free-first.
Kế thừa hoàn toàn từ BaseDramaProvider, tương thích chặt chẽ với DownloadWorker và DramaEpisodeDialog:
- Không bypass VIP/DRM.
- Chặn cứng không gọi resolver / CDN với tập không phải Free.
- Nhận diện URL: douyin_miniapp:{app_id}:{collection_id}, link video Douyin (iesdouyin.com, douyin.com).
- Tự động bóc tách mỏ neo MiniApp trong video Douyin để chuyển tiếp sang danh sách tập phim ngắn.
- Sử dụng MiniAppDouyinClient để mint token và giao tiếp API qua mã hóa AES-128-CBC.
"""

import re
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

import requests

from .base import (
    ACCESS_STATE_FREE,
    ACCESS_STATE_AUTHORIZED,
    ACCESS_STATE_REQUIRES_LOGIN,
    ACCESS_STATE_REQUIRES_VIP,
    ACCESS_STATE_UNAVAILABLE,
    BaseDramaProvider,
    CatalogItem,
    CatalogResult,
    Episode,
    Series,
    Subtitle,
)
from .miniapp_douyin_client import (
    BUILTIN_MINIAPP_SOURCES,
    MiniAppDouyinClient,
    extract_douyin_aweme_id,
    get_douyin_session_status,
    load_douyin_session,
    resolve_douyin_video_and_miniapp,
    save_douyin_session,
)


class MiniAppDouyinProvider(BaseDramaProvider):
    """Provider cho phim ngắn trên nền tảng MiniApp Douyin và video Douyin."""

    platform_id: str = "miniapp_douyin"
    display_name: str = "MiniApp Douyin"
    supports_catalog: bool = True
    status: str = "active"

    def __init__(self, session: Optional[requests.Session] = None, cookie: str = ""):
        super().__init__(session=session)
        self.client = MiniAppDouyinClient(session=self.session, cookie=cookie)
        self.default_app_id = BUILTIN_MINIAPP_SOURCES[0]["app_id"]  # tt5b4d2df0c47bdd2201 (多来看点)

    def can_handle(self, url: str) -> bool:
        if not url:
            return False
        u = str(url).strip().lower()
        if u.startswith("douyin_miniapp:") or u.startswith("miniapp_douyin:"):
            return True
        try:
            host = (urlparse(u).netloc or "").lower().split(":")[0]
            return host in {
                "xiaoguofanxing.lizhibj.cn",
            }
        except Exception:
            return False

    def match_url(self, url: str) -> bool:
        """Alias cho can_handle() theo contract provider."""
        return self.can_handle(url)

    def _extract_ids(self, url: str) -> Tuple[str, str]:
        """Trích xuất (app_id, collection_id) từ URL hoặc URI."""
        u = str(url).strip()
        # Dạng douyin_miniapp:{app_id}:{collection_id} hoặc miniapp_douyin:{app_id}:{collection_id}
        m = re.search(r"(?:douyin_miniapp|miniapp_douyin):([A-Za-z0-9_-]+):([0-9]+)", u, re.I)
        if m:
            return m.group(1), m.group(2)

        # Dạng douyin_miniapp:{collection_id} (dùng default_app_id)
        m2 = re.search(r"(?:douyin_miniapp|miniapp_douyin):([0-9]+)", u, re.I)
        if m2:
            return self.default_app_id, m2.group(1)

        # Dạng query params
        m_app = re.search(r"[?&]app_id=([A-Za-z0-9_-]+)", u)
        m_cid = re.search(r"[?&]collection_id=([0-9]+)", u)
        if m_cid:
            return (m_app.group(1) if m_app else self.default_app_id), m_cid.group(1)

        return "", ""

    def load_series(self, url: str) -> Series:
        """Quét và lấy thông tin series kèm danh sách tập từ MiniApp Douyin hoặc link Douyin."""
        u = str(url).strip()

        # 1. Nhánh xử lý link video Douyin (iesdouyin / douyin.com)
        aweme_id = extract_douyin_aweme_id(u)
        is_douyin_link = aweme_id or any(h in u.lower() for h in ("douyin.com", "iesdouyin.com", "v.douyin.com"))

        if is_douyin_link:
            info = resolve_douyin_video_and_miniapp(u, session=self.session)
            if info and info.get("has_miniapp"):
                app_id = info["app_id"]
                cid = info["collection_id"]
                drama_name = info.get("drama_name") or f"MiniApp Douyin Series {cid}"
                cover = info.get("cover") or ""

                raw_eps, err = self.client.load_playlist(app_id, cid)
                if err and not raw_eps:
                    raise ValueError(f"Lỗi nạp danh sách tập MiniApp Douyin ({drama_name}): {err}")
                if not raw_eps:
                    raise ValueError(f"Danh sách tập phim MiniApp Douyin rỗng (CID: {cid})")

                episodes: List[Episode] = []
                session_status, _ = self.get_session_status()
                for idx, item in enumerate(raw_eps):
                    seq = int(item.get("sequence_no") or (idx + 1))
                    eid = str(item.get("id") or seq)
                    is_free = item.get("is_free") in ("T", True, 1)
                    is_unlocked = item.get("is_unlock") in ("T", True, 1) or item.get("unlocked") is True

                    if is_free:
                        state = ACCESS_STATE_FREE
                        locked = False
                        reason = ""
                    elif is_unlocked:
                        state = ACCESS_STATE_AUTHORIZED
                        locked = False
                        reason = "Đã xác thực quyền VIP qua tài khoản."
                    else:
                        state = ACCESS_STATE_REQUIRES_VIP
                        locked = True
                        if session_status in ("AUTHENTICATED", "valid"):
                            reason = "Không xác minh được quyền VIP. Tài khoản chưa mua gói/tập này trên MiniApp Douyin."
                        else:
                            reason = "Tập này yêu cầu mua VIP trên ứng dụng MiniApp Douyin."

                    ep_url = f"douyin_miniapp:{app_id}:{cid}?ep_id={eid}&ep={seq}"
                    episodes.append(
                        Episode(
                            num=seq,
                            title=f"Tập {seq}",
                            url=ep_url,
                            direct_url=None,
                            thumb=cover,
                            locked=locked,
                            provider_id=self.platform_id,
                            series_id=f"douyin_miniapp:{app_id}:{cid}",
                            episode_id=eid,
                            episode_number=seq,
                            access_state=state,
                            access_reason=reason,
                            extra={
                                "app_id": app_id,
                                "collection_id": cid,
                                "episode_id": eid,
                                "is_free": is_free,
                                "sequence_no": seq,
                            },
                        )
                    )

                accessible_count = sum(1 for e in episodes if not e.locked)
                return Series(
                    name=drama_name,
                    platform=self.platform_id,
                    series_id=f"douyin_miniapp:{app_id}:{cid}",
                    cover=cover,
                    description=f"Nguồn: {app_id} (Phát hiện từ Douyin Video {info.get('aweme_id')})",
                    episode_count=len(episodes),
                    accessible_count=accessible_count,
                    episodes=episodes,
                    url=f"douyin_miniapp:{app_id}:{cid}",
                )

            # Trường hợp video đơn lẻ từ Douyin (hoặc mỏ neo chưa mở)
            v_title = (info.get("title") if info else None) or f"Douyin Video {aweme_id or 'Single'}"
            direct_url = info.get("direct_url") if info else None
            cover = (info.get("cover") if info else "") or ""
            vid_id = str(aweme_id or "1")

            episodes = [
                Episode(
                    num=1,
                    title=v_title,
                    url=u,
                    direct_url=direct_url,
                    thumb=cover,
                    locked=False,
                    provider_id=self.platform_id,
                    series_id=f"douyin_video:{vid_id}",
                    episode_id=vid_id,
                    episode_number=1,
                    access_state=ACCESS_STATE_FREE,
                    access_reason="",
                    extra={
                        "aweme_id": vid_id,
                        "direct_url": direct_url,
                    },
                )
            ]
            is_mix = bool(info and info.get("is_mix"))
            mix_name = (info.get("mix_name") if info else None) or v_title
            mix_id = (info.get("mix_id") if info else None) or vid_id

            return Series(
                name=mix_name if is_mix else v_title,
                platform=self.platform_id,
                series_id=f"douyin_mix:{mix_id}" if is_mix else f"douyin_video:{vid_id}",
                cover=cover,
                description=f"Tuyển tập Douyin ({info.get('mix_count', 1)} video)" if is_mix else "Video trích xuất từ Douyin",
                episode_count=1,
                accessible_count=1,
                episodes=episodes,
                url=u,
            )

        # 2. Nhánh xử lý tiêu chuẩn qua URI douyin_miniapp:{app_id}:{collection_id}
        app_id, cid = self._extract_ids(u)
        if not cid:
            raise ValueError(f"Không thể nhận diện Collection ID của MiniApp Douyin từ URL: {url}")

        raw_eps, err = self.client.load_playlist(app_id, cid)
        if err and not raw_eps:
            raise ValueError(f"Lỗi nạp danh sách tập MiniApp Douyin (CID: {cid}): {err}")
        if not raw_eps:
            raise ValueError(f"Danh sách tập phim MiniApp Douyin rỗng (CID: {cid})")

        episodes: List[Episode] = []
        session_status, _ = self.get_session_status()
        for idx, item in enumerate(raw_eps):
            seq = int(item.get("sequence_no") or (idx + 1))
            eid = str(item.get("id") or seq)
            is_free = item.get("is_free") in ("T", True, 1)
            is_unlocked = item.get("is_unlock") in ("T", True, 1) or item.get("unlocked") is True

            if is_free:
                state = ACCESS_STATE_FREE
                locked = False
                reason = ""
            elif is_unlocked:
                state = ACCESS_STATE_AUTHORIZED
                locked = False
                reason = "Đã xác thực quyền VIP qua tài khoản."
            else:
                state = ACCESS_STATE_REQUIRES_VIP
                locked = True
                if session_status == "valid":
                    reason = "Không xác minh được quyền VIP. Tài khoản chưa mua gói/tập này trên MiniApp Douyin."
                else:
                    reason = "Tập này yêu cầu mua VIP trên ứng dụng MiniApp Douyin."

            ep_url = f"douyin_miniapp:{app_id}:{cid}?ep_id={eid}&ep={seq}"
            episodes.append(
                Episode(
                    num=seq,
                    title=f"Tập {seq}",
                    url=ep_url,
                    direct_url=None,
                    thumb="",
                    locked=locked,
                    provider_id=self.platform_id,
                    series_id=f"douyin_miniapp:{app_id}:{cid}",
                    episode_id=eid,
                    episode_number=seq,
                    access_state=state,
                    access_reason=reason,
                    extra={
                        "app_id": app_id,
                        "collection_id": cid,
                        "episode_id": eid,
                        "is_free": is_free,
                        "sequence_no": seq,
                    },
                )
            )

        accessible_count = sum(1 for e in episodes if not e.locked)
        return Series(
            name=f"MiniApp Douyin Series {cid}",
            platform=self.platform_id,
            series_id=f"douyin_miniapp:{app_id}:{cid}",
            cover="",
            description=f"Nguồn: {app_id}",
            episode_count=len(episodes),
            accessible_count=accessible_count,
            episodes=episodes,
            url=f"douyin_miniapp:{app_id}:{cid}",
        )

    def resolve_episode_stream(self, episode: Episode) -> Optional[str]:
        """Giải mã đường dẫn stream. TUYỆT ĐỐI CHẶN nếu tập bị khóa / VIP chưa xác thực."""
        if episode.locked or episode.access_state not in (ACCESS_STATE_FREE, ACCESS_STATE_AUTHORIZED):
            return None

        if episode.direct_url:
            return episode.direct_url

        app_id = episode.extra.get("app_id") or self.default_app_id
        eid = episode.episode_id or episode.extra.get("episode_id")
        is_free = (episode.access_state == ACCESS_STATE_FREE)
        is_auth = (episode.access_state == ACCESS_STATE_AUTHORIZED)

        if not eid:
            return None

        stream_url, err = self.client.get_play_url(app_id, eid, is_free=is_free, is_authorized=is_auth)
        if stream_url:
            episode.direct_url = stream_url
            return stream_url

        return None

    def resolve_stream(self, episode: Episode) -> Optional[str]:
        """Alias cho resolve_episode_stream() theo contract."""
        return self.resolve_episode_stream(episode)

    def load_catalog(
        self,
        page: int = 1,
        category: Optional[str] = None,
        app_id: Optional[str] = None,
    ) -> CatalogResult:
        """Alias cho get_catalog() theo contract."""
        return self.get_catalog(page=page, category=category, app_id=app_id)

    def search(
        self,
        query: str,
        page: int = 1,
        app_id: Optional[str] = None,
    ) -> CatalogResult:
        """Tìm kiếm phim trong catalog của MiniApp."""
        return self.get_catalog(page=page, query=query, app_id=app_id)

    def get_subtitle(self, episode: Episode) -> Optional[List[Subtitle]]:
        """Lấy danh sách phụ đề của tập phim nếu có."""
        return episode.subtitles if episode.subtitles else None

    def get_catalog(
        self,
        page: int = 1,
        query: Optional[str] = None,
        category: Optional[str] = None,
        app_id: Optional[str] = None,
    ) -> CatalogResult:
        """Duyệt danh sách phim đề xuất công khai."""
        target_app = app_id or category or self.default_app_id
        raw_list, has_more, err = self.client.browse_catalog(
            app_id=target_app,
            page=page,
            pagesize=18,
            query=query or "",
        )
        if err and not raw_list:
            return CatalogResult(
                items=[],
                total=0,
                platform=self.platform_id,
                page=page,
                error=err,
                has_more=False,
            )

        items: List[CatalogItem] = []
        for item in raw_list:
            cid = str(item.get("id") or item.get("collection_id") or "")
            if not cid:
                continue
            name = (item.get("name") or item.get("title") or f"Series {cid}").strip()
            cover = item.get("cover_url") or item.get("cover") or ""
            ep_cnt = int(item.get("episode_count") or item.get("total_episodes") or 0)
            desc = (item.get("describe") or item.get("intro") or "").strip()

            items.append(
                CatalogItem(
                    id=cid,
                    name=name,
                    cover=cover,
                    episodes=ep_cnt,
                    desc=desc,
                    link=f"douyin_miniapp:{target_app}:{cid}",
                    platform=self.platform_id,
                )
            )

        return CatalogResult(
            items=items,
            total=len(items),
            platform=self.platform_id,
            page=page,
            has_more=has_more,
        )

    def authenticate(self, credentials: Dict[str, Any]) -> bool:
        """Nhận cookie đồng bộ từ Extension và lưu vào DPAPI storage."""
        if not credentials:
            return False
        success, _ = save_douyin_session(credentials)
        return success

    def refresh_session(self) -> bool:
        """Interface chuẩn bị sẵn theo kiến trúc Free-first (trơ, 0 network ngầm)."""
        return False

    def validate_entitlement(self, episode: Episode) -> bool:
        """Kiểm tra quyền truy cập chính thức của tập phim."""
        return episode.access_state in (ACCESS_STATE_FREE, ACCESS_STATE_AUTHORIZED) and not episode.locked

    def get_session_status(self) -> Tuple[str, str]:
        """Trả về trạng thái phiên bảo vệ qua DPAPI của Douyin."""
        return get_douyin_session_status(client=self.client, app_id=self.default_app_id)

    def validate_session(self, app_id: str = "") -> Tuple[bool, str]:
        """Xác thực phiên MiniApp thật bằng cách mint token bắt buộc."""
        return self.client.validate_session(app_id or self.default_app_id)
