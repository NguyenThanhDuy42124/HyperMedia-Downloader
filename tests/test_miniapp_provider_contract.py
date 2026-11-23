"""
tests/test_miniapp_provider_contract.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Kiểm thử hợp đồng (Contract Tests) độc lập cho MiniAppDouyinProvider:
1. Provider kế thừa đầy đủ từ BaseDramaProvider.
2. Kiểm tra đầy đủ các phương thức bắt buộc:
   - match_url() / can_handle()
   - load_catalog() / get_catalog()
   - search()
   - load_series()
   - resolve_stream() / resolve_episode_stream()
   - get_subtitle()
   - authenticate()
   - refresh_session()
   - validate_entitlement()
3. Xác minh hoạt động của từng phương thức trên dữ liệu giả lập (Mock).
"""

import os
import sys
import unittest
from unittest.mock import MagicMock, patch

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from providers.base import (
    ACCESS_STATE_FREE,
    ACCESS_STATE_REQUIRES_VIP,
    BaseDramaProvider,
    CatalogItem,
    CatalogResult,
    Episode,
    Series,
)
from providers.miniapp_douyin_provider import MiniAppDouyinProvider


class TestMiniAppProviderContract(unittest.TestCase):
    def setUp(self):
        self.provider = MiniAppDouyinProvider()

    def test_01_subclass_and_attributes(self):
        """1. Provider phải kế thừa BaseDramaProvider và có metadata hợp lệ."""
        self.assertTrue(issubclass(MiniAppDouyinProvider, BaseDramaProvider))
        self.assertIsInstance(self.provider, BaseDramaProvider)
        self.assertEqual(self.provider.platform_id, "miniapp_douyin")
        self.assertEqual(self.provider.display_name, "MiniApp Douyin")
        self.assertTrue(self.provider.supports_catalog)

    def test_02_required_methods_exist(self):
        """2. Provider phải hỗ trợ đầy đủ các phương thức chuẩn."""
        required_methods = [
            "match_url",
            "can_handle",
            "load_catalog",
            "get_catalog",
            "search",
            "load_series",
            "resolve_stream",
            "resolve_episode_stream",
            "get_subtitle",
            "authenticate",
            "refresh_session",
            "validate_entitlement",
        ]
        for m in required_methods:
            self.assertTrue(
                callable(getattr(self.provider, m, None)),
                f"MiniAppDouyinProvider thiếu phương thức: {m}",
            )

    def test_03_match_url(self):
        """3. Kiểm tra match_url() và can_handle() nhận diện đúng URL của nền tảng."""
        valid_urls = [
            "douyin_miniapp:tt5b4d2df0c47bdd2201:8888",
            "miniapp_douyin:tt5b4d2df0c47bdd2201:8888",
            "douyin_miniapp:8888",
            "miniapp_douyin:8888",
            "https://xiaoguofanxing.lizhibj.cn/api/duolai/video/play?collection_id=8888",
        ]
        invalid_urls = [
            "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            "https://www.bilibili.com/video/BV1xx411c7mD",
            "https://dramaboxdb.com/drama/1001",
            "https://kisskh.co/Drama/Test-Series",
            "",
            None,
        ]
        for u in valid_urls:
            self.assertTrue(self.provider.match_url(u), f"Phải nhận diện được URL: {u}")
            self.assertTrue(self.provider.can_handle(u), f"can_handle phải True cho: {u}")

        for u in invalid_urls:
            self.assertFalse(self.provider.match_url(u), f"Không được nhận nhầm URL: {u}")
            self.assertFalse(self.provider.can_handle(u), f"can_handle phải False cho: {u}")

    def test_04_load_catalog_and_search(self):
        """4. Kiểm tra load_catalog() và search() trả về CatalogResult hợp lệ."""
        mock_raw = [
            {"id": "col_101", "name": "Thiên Kim Trở Về", "cover_url": "https://img.cdn/c1.jpg", "episode_count": 80},
            {"id": "col_102", "name": "Vua Chiến Trường", "cover_url": "https://img.cdn/c2.jpg", "episode_count": 100},
        ]
        with patch.object(self.provider.client, "browse_catalog", return_value=(mock_raw, True, None)):
            res = self.provider.load_catalog(page=1)
            self.assertIsInstance(res, CatalogResult)
            self.assertEqual(res.platform, "miniapp_douyin")
            self.assertEqual(len(res.items), 2)
            self.assertEqual(res.items[0].id, "col_101")
            self.assertEqual(res.items[0].name, "Thiên Kim Trở Về")
            self.assertTrue(res.items[0].link.startswith("douyin_miniapp:"))

            # Thử nghiệm search()
            search_res = self.provider.search("Chiến Trường", page=1)
            self.assertIsInstance(search_res, CatalogResult)
            self.assertEqual(len(search_res.items), 2)

    def test_05_load_series_and_access_states(self):
        """5. Kiểm tra load_series() phân loại tập Free và tập VIP."""
        mock_playlist = [
            {"id": "ep_1", "sequence_no": 1, "is_free": "T"},
            {"id": "ep_2", "sequence_no": 2, "is_free": True},
            {"id": "ep_3", "sequence_no": 3, "is_free": 1},
            {"id": "ep_4", "sequence_no": 4, "is_free": "F"},
            {"id": "ep_5", "sequence_no": 5, "is_free": False},
        ]
        with patch.object(self.provider.client, "load_playlist", return_value=(mock_playlist, None)):
            series = self.provider.load_series("douyin_miniapp:tt5b4d2df0c47bdd2201:8888")
            self.assertIsInstance(series, Series)
            self.assertEqual(series.episode_count, 5)
            self.assertEqual(series.accessible_count, 3)

            # 3 tập đầu là Free
            for i in range(3):
                ep = series.episodes[i]
                self.assertEqual(ep.access_state, ACCESS_STATE_FREE)
                self.assertFalse(ep.locked)
                self.assertTrue(self.provider.validate_entitlement(ep))

            # 2 tập sau là VIP / Locked
            for i in range(3, 5):
                ep = series.episodes[i]
                self.assertEqual(ep.access_state, ACCESS_STATE_REQUIRES_VIP)
                self.assertTrue(ep.locked)
                self.assertFalse(self.provider.validate_entitlement(ep))

    def test_06_resolve_stream_contract(self):
        """6. Kiểm tra resolve_stream() phân giải URL cho tập Free và chặn tập VIP."""
        free_ep = Episode(
            num=1,
            title="Tập 1",
            url="douyin_miniapp:tt_app:100?ep_id=ep_1&ep=1",
            locked=False,
            access_state=ACCESS_STATE_FREE,
            episode_id="ep_1",
            extra={"app_id": "tt_app", "episode_id": "ep_1", "is_free": True},
        )
        vip_ep = Episode(
            num=4,
            title="Tập 4",
            url="douyin_miniapp:tt_app:100?ep_id=ep_4&ep=4",
            locked=True,
            access_state=ACCESS_STATE_REQUIRES_VIP,
            episode_id="ep_4",
            extra={"app_id": "tt_app", "episode_id": "ep_4", "is_free": False},
        )

        with patch.object(self.provider.client, "get_play_url", return_value=("https://cdn.example.com/stream1.mp4", None)):
            stream_url = self.provider.resolve_stream(free_ep)
            self.assertEqual(stream_url, "https://cdn.example.com/stream1.mp4")

        # Tập VIP: client.get_play_url TUYỆT ĐỐI không được gọi, resolve_stream trả về None
        with patch.object(self.provider.client, "get_play_url") as spy_get_play:
            vip_url = self.provider.resolve_stream(vip_ep)
            self.assertIsNone(vip_url)
            spy_get_play.assert_not_called()

    def test_07_get_subtitle(self):
        """7. get_subtitle() trả về None hoặc danh sách subtitle nếu có."""
        ep = Episode(num=1, title="Tập 1", url="douyin_miniapp:test:1", subtitles=[])
        self.assertIsNone(self.provider.get_subtitle(ep))


if __name__ == "__main__":
    unittest.main()
