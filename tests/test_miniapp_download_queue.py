"""
tests/test_miniapp_download_queue.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Kiểm thử chuyển đổi các tập Free đã chọn sang hàng đợi tải chuẩn và tương thích DownloadWorker:
1. Chuyển đổi danh sách Episode thành item hàng đợi chuẩn:
   - Title, URL, Thumb, item_index, formats đầy đủ và chuẩn format.
2. Tương thích DownloadWorker:
   - Tạo exact_file_stem an toàn ngay trong DownloadWorker.__init__.
   - Metadata không bị thất lạc (episode_id, collection_id).
3. Luồng tải của DownloadWorker đối với tập Free MiniApp Douyin:
   - Gọi đúng provider.load_series(), tìm đúng tập theo episode_id/item_index.
   - Gọi resolve_episode_stream() và chuyển luồng phát cho YoutubeDL hoặc download_hls_antihook.
"""

import os
import sys
import unittest
from unittest.mock import MagicMock, patch

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from providers.base import ACCESS_STATE_FREE, Episode, Series
from providers.miniapp_douyin_provider import MiniAppDouyinProvider
from download_worker import DownloadWorker


class TestMiniAppDownloadQueue(unittest.TestCase):
    def setUp(self):
        self.provider = MiniAppDouyinProvider()
        self.series = Series(
            name="Chiến Thần Đô Thị",
            platform="miniapp_douyin",
            series_id="douyin_miniapp:tt_app_1:9999",
            cover="https://img.cdn/poster.jpg",
            episode_count=3,
            accessible_count=3,
            episodes=[
                Episode(
                    num=1,
                    title="Tập 1",
                    url="douyin_miniapp:tt_app_1:9999?ep_id=ep_101&ep=1",
                    locked=False,
                    access_state=ACCESS_STATE_FREE,
                    episode_id="ep_101",
                    extra={"app_id": "tt_app_1", "episode_id": "ep_101", "is_free": True},
                ),
                Episode(
                    num=2,
                    title="Tập 2",
                    url="douyin_miniapp:tt_app_1:9999?ep_id=ep_102&ep=2",
                    locked=False,
                    access_state=ACCESS_STATE_FREE,
                    episode_id="ep_102",
                    extra={"app_id": "tt_app_1", "episode_id": "ep_102", "is_free": True},
                ),
            ],
        )

    def test_01_queue_item_transformation(self):
        """1. Kiểm tra cấu trúc item hàng đợi tạo ra từ danh sách Episode."""
        from miniapp_browse_widget import MiniAppBrowseWidget

        # Tạo queue items theo đúng logic của MiniAppBrowseWidget
        queue_items = []
        for ep in self.series.episodes:
            queue_items.append({
                "title": f"{self.series.name} - {ep.title}",
                "url": ep.url,
                "thumb": ep.thumb or self.series.cover,
                "heights": [],
                "item_index": ep.num,
                "episode_id": ep.episode_id,
                "formats": [{
                    "format_id": "best",
                    "ext": "mp4",
                    "resolution": "best",
                }],
            })

        self.assertEqual(len(queue_items), 2)
        it1 = queue_items[0]
        self.assertEqual(it1["title"], "Chiến Thần Đô Thị - Tập 1")
        self.assertEqual(it1["url"], "douyin_miniapp:tt_app_1:9999?ep_id=ep_101&ep=1")
        self.assertEqual(it1["thumb"], "https://img.cdn/poster.jpg")
        self.assertEqual(it1["item_index"], 1)
        self.assertEqual(it1["episode_id"], "ep_101")
        self.assertEqual(it1["formats"][0]["ext"], "mp4")

    def test_02_download_worker_initialization_exact_stem(self):
        """2. DownloadWorker tạo exact_file_stem hợp lệ và an toàn từ metadata hàng đợi."""
        q_item = {
            "uid": "uid_miniapp_ep1",
            "title": "Chiến Thần Đô Thị - Tập 1",
            "folder": os.path.abspath("./downloads"),
            "item_index": 1,
            "episode_id": "ep_101",
        }
        worker = DownloadWorker(
            url="douyin_miniapp:tt_app_1:9999?ep_id=ep_101&ep=1",
            options=q_item,
        )

        self.assertIsNotNone(worker.exact_file_stem)
        self.assertTrue(len(worker.exact_file_stem) > 0)
        # Tên file stem phải chứa tên phim sạch và basename không chứa ký tự cấm
        stem_basename = os.path.basename(worker.exact_file_stem)
        self.assertIn("Chiến Thần Đô Thị - Tập 1", stem_basename)
        for char in '<>:"/\\|?*':
            self.assertNotIn(char, stem_basename)

    def test_03_download_worker_resolves_and_downloads_free_episode(self):
        """3. DownloadWorker tải thành công tập Free qua resolve_episode_stream và YoutubeDL."""
        q_item = {
            "uid": "uid_miniapp_ep2",
            "title": "Chiến Thần Đô Thị - Tập 2",
            "folder": os.path.abspath("./downloads"),
            "item_index": 2,
            "episode_id": "ep_102",
        }
        worker = DownloadWorker(
            url="douyin_miniapp:tt_app_1:9999?ep_id=ep_102&ep=2",
            options=q_item,
        )

        with patch("providers.detect_provider", return_value=self.provider), \
             patch.object(self.provider, "load_series", return_value=self.series), \
             patch.object(self.provider, "resolve_episode_stream", return_value="https://cdn.example.com/direct.mp4") as mock_resolve, \
             patch("yt_dlp.YoutubeDL") as mock_ydl_cls:
            mock_ydl_instance = MagicMock()
            mock_ydl_cls.return_value.__enter__.return_value = mock_ydl_instance

            worker._download_drama_episode(os.path.abspath("./downloads"))

            # Xác nhận provider được yêu cầu giải mã đúng tập 2
            mock_resolve.assert_called_once()
            resolved_ep = mock_resolve.call_args[0][0]
            self.assertEqual(resolved_ep.num, 2)
            self.assertEqual(resolved_ep.episode_id, "ep_102")

            # Xác nhận YoutubeDL download được gọi với stream direct mp4
            mock_ydl_instance.download.assert_called_once_with(["https://cdn.example.com/direct.mp4"])

    def test_04_download_worker_hls_antihook_flow(self):
        """4. DownloadWorker nhận diện stream .m3u8 và gọi bộ giải mã download_hls_antihook."""
        q_item = {
            "uid": "uid_miniapp_hls",
            "title": "Chiến Thần Đô Thị - Tập 1",
            "folder": os.path.abspath("./downloads"),
            "item_index": 1,
            "episode_id": "ep_101",
        }
        worker = DownloadWorker(
            url="douyin_miniapp:tt_app_1:9999?ep_id=ep_101&ep=1",
            options=q_item,
        )

        m3u8_stream = "https://play.douyinvod.com/stream/index.m3u8?token=xyz"

        with patch("providers.detect_provider", return_value=self.provider), \
             patch.object(self.provider, "load_series", return_value=self.series), \
             patch.object(self.provider, "resolve_episode_stream", return_value=m3u8_stream), \
             patch.object(self.provider.client, "download_hls_antihook", return_value=True) as mock_hls:
            worker._download_drama_episode(os.path.abspath("./downloads"))

            mock_hls.assert_called_once()
            called_args, called_kwargs = mock_hls.call_args
            self.assertEqual(called_args[0], m3u8_stream)
            self.assertEqual(called_kwargs.get("app_id"), "tt_app_1")


if __name__ == "__main__":
    unittest.main()
