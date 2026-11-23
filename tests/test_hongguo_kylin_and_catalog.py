"""
tests/test_hongguo_kylin_and_catalog.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Unit & mock integration test suite verifying:
1. Short links / share links resolution: kylin.hainanyuyue.com and novelquickapp.com.
2. Modern.js EdenX SSR video-animation-share_page parsing (86 episodes).
3. Automatic fallback to detail_page from query string video_id.
4. Modern.js NDJSON multi-line response handling.
5. Hongguo catalog browsing (banners + 4 home sections, pagination, deduplication).
6. Douyin video & MiniApp anchor auto-routing in MiniAppDouyinProvider.
"""

import json
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from providers.base import (
    ACCESS_STATE_FREE,
    ACCESS_STATE_REQUIRES_VIP,
    CatalogItem,
    CatalogResult,
    Episode,
    Series,
)
from providers.hongguo_provider import HongguoProvider
from providers.miniapp_douyin_provider import MiniAppDouyinProvider
from providers.registry import detect_provider


class TestHongguoKylinAndCatalog(unittest.TestCase):

    def setUp(self):
        self.provider = HongguoProvider()
        self.miniapp_provider = MiniAppDouyinProvider()

    def test_hongguo_can_handle_domains_and_ids(self):
        """HongguoProvider nhận diện đúng các domain hệ sinh thái và ID số nguyên."""
        valid_urls = [
            "https://kylin.hainanyuyue.com/s/-mVjL3iKXGY/",
            "https://hainanyuyue.com/share/video-animation-share?video_id=123",
            "https://novelquickapp.com/s/leok-rgP11w/",
            "https://hongguoduanju.com/detail?series_id=7503745441910017049",
            "https://www.fqnovel.com/detail/12345678",
            "hongguo:7671508506402376729",
        ]
        for u in valid_urls:
            self.assertTrue(self.provider.can_handle(u), f"Phải nhận diện URL: {u}")
            matched = detect_provider(u)
            self.assertIsNotNone(matched)
            self.assertEqual(matched.platform_id, "hongguo")

    def test_load_series_kylin_share_link_extraction(self):
        """Kylin share link giải mã đúng 86 tập từ _ROUTER_DATA của video-animation-share."""
        mock_cids = [f"767151020479350684{i:02d}" for i in range(86)]
        mock_router_data = {
            "loaderData": {
                "video-animation-share_page": {
                    "pageData": {
                        "series_data": {
                            "title": "你强我更强，仙帝见我也得跪",
                            "series_cover": "https://img.test/kylin_cover.webp",
                            "series_intro": "Mô tả phim animation",
                            "play_url": "https://v3-hongman.cdn.test/video/ep1.mp4",
                            "chapter_id": mock_cids[0],
                        },
                        "chapter_ids": mock_cids,
                        "used_chapter_id": mock_cids[0],
                    }
                }
            }
        }
        mock_html = f"<html><script>window._ROUTER_DATA = {json.dumps(mock_router_data)};</script></html>"

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.url = "https://hainanyuyue.com/share/video-animation-share?encrypt_did=abc&video_id=7671508506402376729"
        mock_resp.text = mock_html

        with patch.object(self.provider.session, "get", return_value=mock_resp):
            series = self.provider.load_series("https://kylin.hainanyuyue.com/s/-mVjL3iKXGY/")

        self.assertEqual(series.name, "你强我更强，仙帝见我也得跪")
        self.assertEqual(series.episode_count, 86)
        self.assertEqual(series.accessible_count, 86)
        self.assertEqual(len(series.episodes), 86)

        # Tập 1 có sẵn direct_url
        ep1 = series.episodes[0]
        self.assertEqual(ep1.num, 1)
        self.assertEqual(ep1.direct_url, "https://v3-hongman.cdn.test/video/ep1.mp4")
        self.assertEqual(ep1.access_state, ACCESS_STATE_FREE)
        self.assertFalse(ep1.locked)

        # Tập 2 chưa có direct_url nhưng có base_loader và extra info
        ep2 = series.episodes[1]
        self.assertEqual(ep2.num, 2)
        self.assertIsNone(ep2.direct_url)
        self.assertEqual(ep2.extra["cid"], mock_cids[1])
        self.assertEqual(ep2.extra["platform"], "hongguo_share")

    def test_resolve_episode_stream_kylin_share(self):
        """Tập phim animation share giải mã stream URL qua loader API."""
        ep = Episode(
            num=2,
            title="Tập 2",
            url="https://hainanyuyue.com/share/video-animation-share#ep=2",
            direct_url=None,
            locked=False,
            provider_id="hongguo",
            series_id="hongguo:test",
            episode_id="7671510266168740888",
            episode_number=2,
            access_state=ACCESS_STATE_FREE,
            extra={
                "cid": "7671510266168740888",
                "base_loader": "https://hainanyuyue.com/share/video-animation-share?encrypt_did=test1234",
                "platform": "hongguo_share",
            },
        )

        mock_stream_data = {
            "pageData": {
                "series_data": {
                    "play_url": "https://v3-hongman.cdn.test/stream_ep2.mp4"
                }
            }
        }
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = json.dumps(mock_stream_data) + "\n{\"__meta\": 1}"

        with patch.object(self.provider.session, "get", return_value=mock_resp):
            stream_url = self.provider.resolve_episode_stream(ep)

        self.assertEqual(stream_url, "https://v3-hongman.cdn.test/stream_ep2.mp4")
        self.assertEqual(ep.direct_url, "https://v3-hongman.cdn.test/stream_ep2.mp4")

    def test_load_series_novelquickapp_fallback_detail(self):
        """Novelquickapp share link chuyển tiếp sang fallback detail_page theo video_id."""
        # 1. Mock share page redirect sang URL chứa video_id
        mock_share_resp = MagicMock()
        mock_share_resp.status_code = 200
        mock_share_resp.url = "https://novelquickapp.com/hongguo/ug/pages/video-animation-share?video_id=7637909835178052670"
        mock_share_resp.text = "<html><body>Empty share</body></html>"

        # 2. Mock detail_page response (47 tập, 5 tập free)
        mock_detail = {
            "seriesDetail": {
                "series_name": "全宗都是我的分身",
                "series_cover": "https://img.test/novel_cover.jpg",
                "series_intro": "Giới thiệu phim",
                "vid_list": [f"vid_{i}" for i in range(1, 48)],
                "accessible_episode_cnt": 5,
            }
        }
        mock_loader_resp = MagicMock()
        mock_loader_resp.status_code = 200
        mock_loader_resp.text = json.dumps(mock_detail) + "\n{\"__trace\": \"ok\"}"

        def fake_get(url, *args, **kwargs):
            if "__loader=detail_page" in url:
                return mock_loader_resp
            return mock_share_resp

        with patch.object(self.provider.session, "get", side_effect=fake_get):
            series = self.provider.load_series("https://novelquickapp.com/s/leok-rgP11w/")

        self.assertEqual(series.name, "全宗都是我的分身")
        self.assertEqual(series.episode_count, 47)
        self.assertEqual(series.accessible_count, 5)

        # 5 tập đầu free
        for ep in series.episodes[:5]:
            self.assertEqual(ep.access_state, ACCESS_STATE_FREE)
            self.assertFalse(ep.locked)

        # Tập 6 trở đi là VIP và Locked
        for ep in series.episodes[5:]:
            self.assertEqual(ep.access_state, ACCESS_STATE_REQUIRES_VIP)
            self.assertTrue(ep.locked)

    def test_hongguo_catalog_browsing_and_pagination(self):
        """get_catalog() bóc tách bannerList và 4 homeSections, phân trang chuẩn 10 phim/trang."""
        mock_banners = [
            {"series_id": f"banner_{i}", "series_name": f"Banner Drama {i}", "series_cover": f"https://img.test/b{i}.jpg"}
            for i in range(1, 5)  # 4 banners
        ]
        mock_sections = [
            {
                "tab_name": f"Section {s}",
                "video_list": [
                    {
                        "series_id": f"sec_{s}_{i}",
                        "series_title": f"Drama Sec {s} Ep {i}",
                        "series_cover": f"https://img.test/s_{s}_{i}.jpg",
                        "episode_cnt": 80 + i,
                    }
                    for i in range(1, 10)  # 9 phim/section x 4 = 36 phim
                ]
            }
            for s in range(1, 5)
        ]

        mock_page_data = {
            "loaderData": {
                "page": {
                    "bannerList": mock_banners,
                    "homeSections": mock_sections,
                }
            }
        }
        # 4 + 36 = 40 phim tổng cộng
        mock_html = f"<html><script>window._ROUTER_DATA = {json.dumps(mock_page_data)};</script></html>"
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = mock_html

        with patch.object(self.provider.session, "get", return_value=mock_resp):
            # Trang 1: 10 phim
            res1 = self.provider.get_catalog(page=1)
            self.assertEqual(len(res1.items), 10)
            self.assertEqual(res1.total, 40)
            self.assertTrue(res1.has_more)
            self.assertEqual(res1.items[0].id, "banner_1")

            # Trang 4: 10 phim cuối cùng, has_more = False
            res4 = self.provider.get_catalog(page=4)
            self.assertEqual(len(res4.items), 10)
            self.assertFalse(res4.has_more)

            # Lọc theo query
            res_query = self.provider.get_catalog(page=1, query="Sec 2")
            self.assertEqual(res_query.total, 9)
            self.assertTrue(all("Sec 2" in item.name for item in res_query.items))

    def test_miniapp_douyin_video_routing_single_and_anchor(self):
        """MiniAppDouyinProvider nhận diện link video Douyin và mỏ neo phim ngắn."""
        # 1. can_handle
        miniapp_uri = "douyin_miniapp:tt5b4d2df0c47bdd2201:998877"
        self.assertTrue(self.miniapp_provider.can_handle(miniapp_uri))
        self.assertFalse(self.miniapp_provider.can_handle("https://v.douyin.com/test1234/"))
        douyin_url = "https://www.iesdouyin.com/share/video/7700535750642748706/?region=VN"

        # 2. Single video without miniapp anchor
        mock_single_info = {
            "aweme_id": "7700535750642748706",
            "title": "Video Douyin Solo",
            "cover": "https://img.test/solo.jpg",
            "direct_url": "https://cdn.douyin.test/video.mp4",
            "has_miniapp": False,
        }
        with patch("providers.miniapp_douyin_provider.resolve_douyin_video_and_miniapp", return_value=mock_single_info):
            series = self.miniapp_provider.load_series(douyin_url)
            self.assertEqual(series.episode_count, 1)
            self.assertEqual(series.name, "Video Douyin Solo")
            self.assertEqual(series.episodes[0].direct_url, "https://cdn.douyin.test/video.mp4")

        # 3. Video with miniapp drama anchor
        mock_anchor_info = {
            "aweme_id": "7700535750642748706",
            "title": "Clip quảng cáo",
            "cover": "https://img.test/anchor.jpg",
            "has_miniapp": True,
            "app_id": "tt5b4d2df0c47bdd2201",
            "collection_id": "998877",
            "drama_name": "Phim Ngắn Đa Lai Siêu Hay",
        }
        mock_playlist = [
            {"id": "ep_1", "sequence_no": 1, "is_free": "T"},
            {"id": "ep_2", "sequence_no": 2, "is_free": "T"},
            {"id": "ep_3", "sequence_no": 3, "is_free": "F"},
        ]
        with patch("providers.miniapp_douyin_provider.resolve_douyin_video_and_miniapp", return_value=mock_anchor_info):
            with patch.object(self.miniapp_provider.client, "load_playlist", return_value=(mock_playlist, "")) as mock_load:
                series_anchor = self.miniapp_provider.load_series(douyin_url)
                self.assertEqual(series_anchor.name, "Phim Ngắn Đa Lai Siêu Hay")
                self.assertEqual(series_anchor.episode_count, 3)
                self.assertEqual(series_anchor.accessible_count, 2)
                self.assertEqual(series_anchor.episodes[0].access_state, ACCESS_STATE_FREE)
                self.assertEqual(series_anchor.episodes[2].access_state, ACCESS_STATE_REQUIRES_VIP)
                mock_load.assert_called_once_with("tt5b4d2df0c47bdd2201", "998877")

    def test_douyin_client_real_fixtures(self):
        """Kiểm tra resolve_douyin_video_and_miniapp với các fixture thực tế (anchor_info, micro_app_info, mix_info)."""
        from providers.miniapp_douyin_client import resolve_douyin_video_and_miniapp

        # 1. Fixture anchor_info chứa JSON string trong extra
        fixture_anchor = {
            "aweme_detail": {
                "desc": "Review phim ngắn cực hay",
                "video": {
                    "cover": {"url_list": ["https://img.test/c1.jpg"]},
                    "play_addr": {"url_list": ["https://cdn.test/p1.mp4"]},
                },
                "anchor_info": {
                    "type": 28,
                    "title": "Chàng Rể Quyền Thế",
                    "extra": json.dumps({"app_id": "tt5b4d2df0c47bdd2201", "book_id": "888999"}),
                },
            }
        }
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = fixture_anchor

        with patch("requests.Session.get", return_value=mock_resp):
            info = resolve_douyin_video_and_miniapp("https://www.douyin.com/video/7700535750642748706")
            self.assertTrue(info["has_miniapp"])
            self.assertEqual(info["app_id"], "tt5b4d2df0c47bdd2201")
            self.assertEqual(info["collection_id"], "888999")
            self.assertEqual(info["drama_name"], "Chàng Rể Quyền Thế")

        # 2. Fixture micro_app_info chứa open_url
        fixture_micro = {
            "aweme_detail": {
                "desc": "Trailer tập 1",
                "video": {
                    "cover": {"url_list": ["https://img.test/c2.jpg"]},
                    "play_addr": {"url_list": ["https://cdn.test/p2.mp4"]},
                },
                "micro_app_info": {
                    "app_id": "tt11223344",
                    "title": "Bá Đạo Tổng Tài",
                    "open_url": "sslocal://microapp?app_id=tt11223344&series_id=556677",
                },
            }
        }
        mock_resp.json.return_value = fixture_micro
        with patch("requests.Session.get", return_value=mock_resp):
            info2 = resolve_douyin_video_and_miniapp("https://www.douyin.com/video/7700535750642748706")
            self.assertTrue(info2["has_miniapp"])
            self.assertEqual(info2["app_id"], "tt11223344")
            self.assertEqual(info2["collection_id"], "556677")

        # 3. Fixture Douyin mix_info (tuyển tập)
        fixture_mix = {
            "aweme_detail": {
                "desc": "Tập 5 Tuyển tập",
                "video": {
                    "cover": {"url_list": ["https://img.test/c3.jpg"]},
                    "play_addr": {"url_list": ["https://cdn.test/p3.mp4"]},
                },
                "mix_info": {
                    "mix_id": "71122334455",
                    "mix_name": "Series Phim Ngắn Đô Thị",
                    "staged_total_count": 25,
                },
            }
        }
        mock_resp.json.return_value = fixture_mix
        with patch("requests.Session.get", return_value=mock_resp):
            info3 = resolve_douyin_video_and_miniapp("https://www.douyin.com/video/7700535750642748706")
            self.assertFalse(info3["has_miniapp"])
            self.assertTrue(info3["is_mix"])
            self.assertEqual(info3["mix_id"], "71122334455")
            self.assertEqual(info3["mix_count"], 25)

    def test_access_guards_strictly_block_locked_episodes(self):
        """Access guards tuyệt đối chặn không resolve stream và không enqueue tập locked/VIP."""
        from download_worker import DownloadWorker

        locked_ep = Episode(
            num=10,
            title="Tập 10 (VIP)",
            url="https://hongguoduanju.com/player/123?vid=v10",
            direct_url=None,
            thumb="",
            locked=True,
            provider_id="hongguo",
            series_id="hongguo:123",
            episode_id="v10",
            episode_number=10,
            access_state=ACCESS_STATE_REQUIRES_VIP,
            access_reason="Tập VIP trên ứng dụng",
        )

        # 1. HongguoProvider.resolve_episode_stream trả về None và 0 network
        with patch.object(self.provider.session, "get") as mock_get:
            res = self.provider.resolve_episode_stream(locked_ep)
            self.assertIsNone(res)
            mock_get.assert_not_called()

        # 2. MiniAppDouyinProvider.resolve_episode_stream trả về None và 0 network
        with patch.object(self.miniapp_provider.client, "get_play_url") as mock_client:
            res_mini = self.miniapp_provider.resolve_episode_stream(locked_ep)
            self.assertIsNone(res_mini)
            mock_client.assert_not_called()

        # 3. DownloadWorker từ chối tải tập locked/VIP và raise ValueError ngay trước khi gọi mạng
        worker = DownloadWorker(
            url="https://hongguoduanju.com/player/123?ep=10&vid=v10",
            options={"drama_episode": locked_ep, "episode_id": "v10", "episode_number": 10, "output_path": os.getcwd()},
        )
        mock_series = Series(
            name="Test Series",
            platform="hongguo",
            series_id="hongguo:123",
            cover="",
            description="",
            episode_count=1,
            accessible_count=0,
            episodes=[locked_ep],
            url="https://hongguoduanju.com/player/123",
        )
        with patch("providers.detect_provider", return_value=self.provider):
            with patch.object(self.provider, "load_series", return_value=mock_series):
                with self.assertRaises(ValueError) as ctx:
                    worker._download_drama_episode(os.path.join(os.getcwd(), "test.mp4"))
                self.assertIn("không thể tải", str(ctx.exception).lower())


if __name__ == "__main__":
    unittest.main()
