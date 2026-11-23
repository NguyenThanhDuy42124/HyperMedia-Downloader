"""
tests.test_drama_reproductions
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Reproduction unit tests for P1 and P2 findings identified in Drama review.
"""

import os
import sys
import time
import unittest
from unittest.mock import MagicMock, patch

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from providers.base import parse_episode_selection, Series, Episode
from providers.dramabox_provider import DramaBoxProvider
from providers.kisskh_provider import KisskhProvider
import providers
from site_utils import is_drama_url


class TestDramaReproduction(unittest.TestCase):

    def test_dramabox_shifted_chapter_order_matching(self):
        """P1-2: Refresh DramaBox phải match bằng chapter_id, không match nhầm ordinal bị đảo."""
        p = DramaBoxProvider()

        # Giả lập trang trả về danh sách bị đảo thứ tự hoặc có chapter mới chèn vào đầu:
        # Item 0 có id="ch_OTHER", index=0 (ordinal 1)
        # Item 1 có id="ch_TARGET", index=1 (ordinal 2)
        mock_html = """
        <html>
        <script id="__NEXT_DATA__" type="application/json">
        {
            "props": {
                "pageProps": {
                    "bookInfo": {"bookName": "Test", "cover": ""},
                    "chapterList": [
                        {"id": "ch_OTHER", "index": 0, "mp4": "https://wrong.stream"},
                        {"id": "ch_TARGET", "index": 1, "mp4": "https://correct.stream"}
                    ]
                }
            }
        }
        </script>
        </html>
        """
        target_ep = Episode(
            num=1,  # ordinal cũ là 1
            title="Tập 1",
            url="https://www.dramaboxdb.com/movie/42000011111/drama?ep=1",
            direct_url=None,
            extra={"book_id": "42000011111", "chapter_id": "ch_TARGET"},
        )

        with patch.object(p.session, "get") as mock_get:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.text = mock_html
            mock_get.return_value = mock_resp

            stream = p.resolve_episode_stream(target_ep)
            self.assertEqual(stream, "https://correct.stream", "Đã match nhầm ordinal thay vì chapter_id")

    def test_range_huge_input_clamping(self):
        """P2-1: Input khoảng cực lớn phải được clamp ngay, không lặp nghẽn CPU."""
        t0 = time.time()
        res = parse_episode_selection("1-999999999999", max_ep=10)
        elapsed = time.time() - t0
        self.assertLess(elapsed, 0.05, f"Quá chậm ({elapsed}s), chưa clamp range trước khi loop")
        self.assertEqual(res, list(range(1, 11)))

    def test_router_no_false_positive_on_query_param(self):
        """P2-4: URL YouTube chứa query 'dramabox' không được nhận diện là Drama URL."""
        yt_url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ&q=dramabox&feature=kisskh"
        self.assertFalse(is_drama_url(yt_url))
        self.assertIsNone(providers.detect_provider(yt_url))

    def test_thumbnail_loader_cache_and_fanout(self):
        """P2-3: ThumbnailLoader phải hỗ trợ fan-out nhiều callback và cache in-memory."""
        from thumbnail_loader import ThumbnailLoader
        from PySide6.QtGui import QPixmap
        from PySide6.QtWidgets import QApplication
        import sys

        app = QApplication.instance() or QApplication(sys.argv)
        loader = ThumbnailLoader()

        dummy_pm = QPixmap(10, 10)
        loader._cache["https://fake.url/img.jpg"] = dummy_pm

        called = []
        loader.load_thumbnail("https://fake.url/img.jpg", lambda pm: called.append(1))
        loader.load_thumbnail("https://fake.url/img.jpg", lambda pm: called.append(2))

        self.assertEqual(called, [1, 2], "Fan-out callback từ cache không được gọi đủ")

    def test_dialog_gapped_episodes_no_index_error(self):
        """P1-6: Danh sách tập khuyết (vd [2, 4]) không được ném IndexError khi chọn tập 4."""
        from drama_dialog import DramaEpisodeDialog
        from PySide6.QtWidgets import QApplication
        import sys

        app = QApplication.instance() or QApplication(sys.argv)
        series = Series(
            series_id="test_gap",
            name="Gapped Series",
            platform="kisskh",
            episodes=[
                Episode(num=2, title="Tập 2", url="https://kisskh.co/watch/ep?ep_id=202&ep=2"),
                Episode(num=4, title="Tập 4", url="https://kisskh.co/watch/ep?ep_id=204&ep=4"),
            ],
            episode_count=4,
        )
        dialog = DramaEpisodeDialog(series)
        dialog.txt_range.setText("4")
        dialog._apply_range_filter()

        selected = []
        dialog.episodes_selected.connect(lambda eps: selected.extend(eps))
        dialog._on_confirm()

        self.assertEqual(len(selected), 1)
        self.assertEqual(selected[0].num, 4)

    def test_kisskh_ep_id_vs_ordinal_strict_matching(self):
        """P1-1: KissKH matching ưu tiên ep_id chính xác, không lấy nhầm vị trí hàng đợi."""
        from download_worker import DownloadWorker

        worker = DownloadWorker(
            "https://kisskh.co/drama/test/episode-3?ep_id=152755&ep=3",
            options={"item_index": 1, "title": "Test KissKH Ep 3"}  # item_index trong queue là 1, nhưng ep_id là 152755
        )
        mock_series = Series(
            series_id="test_kk",
            name="Test KissKH",
            platform="kisskh",
            episodes=[
                Episode(num=1, title="Tập 1", url="https://kisskh.co/watch/ep?ep_id=152701&ep=1", extra={"kk_ep": "152701"}),
                Episode(num=2, title="Tập 2", url="https://kisskh.co/watch/ep?ep_id=152702&ep=2", extra={"kk_ep": "152702"}),
                Episode(num=3, title="Tập 3", url="https://kisskh.co/watch/ep?ep_id=152755&ep=3", extra={"kk_ep": "152755"}),
            ]
        )

        mock_provider = MagicMock()
        mock_provider.load_series.return_value = mock_series
        mock_provider.resolve_episode_stream.return_value = "https://cdn.stream/ep3.m3u8"
        mock_provider.download_subtitle.return_value = None

        with patch("providers.detect_provider", return_value=mock_provider):
            with patch.object(worker, "get_base_opts", return_value={"format": "best"}), \
                 patch("yt_dlp.YoutubeDL") as mock_ydl:
                mock_ydl_instance = MagicMock()
                mock_ydl.return_value.__enter__.return_value = mock_ydl_instance
                
                # Chạy _download_drama_episode
                worker._download_drama_episode("downloads")
                # Xác nhận stream_url được gọi đúng là của tập 3
                mock_ydl_instance.download.assert_called_with(["https://cdn.stream/ep3.m3u8"])

    def test_drama_apply_format_options_mp3(self):
        """P1-3: Tùy chọn định dạng MP3 phải được truyền trọn vẹn vào YoutubeDL khi tải Drama."""
        from download_worker import DownloadWorker

        worker = DownloadWorker(
            "https://www.dramaboxdb.com/movie/42000011111/drama?ep=1",
            options={"file_type": "mp3", "bitrate": "320"}
        )
        mock_series = Series(
            series_id="test_db",
            name="Test Drama MP3",
            platform="dramabox",
            episodes=[Episode(num=1, title="Tập 1", url="https://dramaboxdb.com/1?ep=1", direct_url="https://direct.mp4")]
        )
        mock_provider = MagicMock()
        mock_provider.load_series.return_value = mock_series
        mock_provider.resolve_episode_stream.return_value = "https://direct.mp4"
        mock_provider.download_subtitle.return_value = None

        with patch("providers.detect_provider", return_value=mock_provider), \
             patch("yt_dlp.YoutubeDL") as mock_ydl:
            mock_ydl_instance = MagicMock()
            mock_ydl.return_value.__enter__.return_value = mock_ydl_instance

            # Chạy trực tiếp nhánh _download_drama_episode
            worker._download_drama_episode("downloads")

            # Lấy options thực tế được truyền vào yt_dlp.YoutubeDL(opts)
            self.assertTrue(mock_ydl.called, "YoutubeDL chưa được khởi tạo trong luồng drama")
            passed_opts = mock_ydl.call_args[0][0]
            self.assertEqual(passed_opts.get("format"), "bestaudio/best")
            has_extract_audio = any(
                p.get("key") == "FFmpegExtractAudio" and p.get("preferredcodec") == "mp3"
                for p in passed_opts.get("postprocessors", [])
            )
            self.assertTrue(has_extract_audio, "Nhánh Drama không áp dụng FFmpegExtractAudio postprocessor")

    def test_drama_download_cancellation_during_youtubedl_download(self):
        """P1-4: Khi worker.stop() được gọi giữa chừng trong YoutubeDL.download(), phải emit task_stopped."""
        from download_worker import DownloadWorker
        from PySide6.QtWidgets import QApplication
        import sys

        app = QApplication.instance() or QApplication(sys.argv)
        worker = DownloadWorker(
            "https://www.dramaboxdb.com/movie/42000011111/drama?ep=1",
            options={}
        )
        mock_series = Series(
            series_id="test_db",
            name="Test Drama",
            platform="dramabox",
            episodes=[Episode(num=1, title="Tập 1", url="https://dramaboxdb.com/1?ep=1", direct_url="https://direct.mp4")]
        )
        mock_provider = MagicMock()
        mock_provider.load_series.return_value = mock_series
        mock_provider.resolve_episode_stream.return_value = "https://direct.mp4"

        stopped_called = []
        finished_called = []
        worker.task_stopped.connect(lambda: stopped_called.append(True))
        worker.task_finished.connect(lambda: finished_called.append(True))

        def _simulate_stop_during_dl(*args, **kwargs):
            worker.stop()
            raise Exception("Stopped by user")

        with patch("providers.detect_provider", return_value=mock_provider), \
             patch("yt_dlp.YoutubeDL") as mock_ydl:
            mock_ydl_instance = MagicMock()
            mock_ydl_instance.download.side_effect = _simulate_stop_during_dl
            mock_ydl.return_value.__enter__.return_value = mock_ydl_instance

            worker._download_drama_episode("downloads")

        self.assertTrue(stopped_called, "Không emit task_stopped khi bị dừng trong YoutubeDL")
        self.assertFalse(finished_called, "Đã emit nhầm task_finished khi tiến trình bị hủy")

    def test_drama_download_cancellation_during_subtitle_fetch(self):
        """P1-4: Khi worker.stop() được gọi trong lúc đang tải phụ đề, phải emit task_stopped."""
        from download_worker import DownloadWorker
        from providers.base import Subtitle
        from PySide6.QtWidgets import QApplication
        import sys

        app = QApplication.instance() or QApplication(sys.argv)
        worker = DownloadWorker(
            "https://www.dramaboxdb.com/movie/42000011111/drama?ep=1",
            options={}
        )
        mock_ep = Episode(
            num=1,
            title="Tập 1",
            url="https://dramaboxdb.com/1?ep=1",
            direct_url="https://direct.mp4",
            subtitles=[Subtitle(lang="vi", name="Tiếng Việt", url="https://sub.url/vi.vtt")]
        )
        mock_series = Series(series_id="test_db", name="Test Sub", platform="dramabox", episodes=[mock_ep])
        mock_provider = MagicMock()
        mock_provider.load_series.return_value = mock_series
        mock_provider.resolve_episode_stream.return_value = "https://direct.mp4"

        stopped_called = []
        finished_called = []
        worker.task_stopped.connect(lambda: stopped_called.append(True))
        worker.task_finished.connect(lambda: finished_called.append(True))

        def _simulate_stop_during_sub(*args, **kwargs):
            worker.stop()
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.text = "WEBVTT\n\n00:00.000 --> 00:02.000\nHello"
            return mock_resp

        mock_provider.session.get.side_effect = _simulate_stop_during_sub

        with patch("providers.detect_provider", return_value=mock_provider), \
             patch("yt_dlp.YoutubeDL") as mock_ydl:
            mock_ydl_instance = MagicMock()
            mock_ydl.return_value.__enter__.return_value = mock_ydl_instance

            worker._download_drama_episode("downloads")

        self.assertTrue(stopped_called, "Không emit task_stopped khi bị dừng trong lúc tải phụ đề")
        self.assertFalse(finished_called, "Đã emit nhầm task_finished sau khi dừng ở phụ đề")

    def test_kisskh_end_to_end_from_provider_to_worker(self):
        """P1-1: Luồng hoàn chỉnh từ KisskhProvider.load_series() -> lấy Episode.url -> DownloadWorker."""
        from download_worker import DownloadWorker
        from providers.kisskh_provider import KisskhProvider

        p = KisskhProvider()
        mock_api_drama = {
            "title": "KissKH Real Series",
            "thumbnail": "https://img.kisskh.co/cover.jpg",
            "description": "Desc",
            "episodes": [
                {"id": 8801, "number": 1, "sub": 1},
                {"id": 8802, "number": 2, "sub": 1},
                {"id": 8803, "number": 3, "sub": 1},
            ]
        }

        with patch.object(p, "_request_api", return_value=mock_api_drama):
            series = p.load_series("https://kisskh.co/Drama/Real-Series?id=8800")
            self.assertEqual(len(series.episodes), 3)
            # Chọn tập 3 sinh ra từ provider thực tế
            ep3 = series.episodes[2]
            self.assertIn("ep_id=8803", ep3.url)
            self.assertIn("ep=3", ep3.url)

            # Đẩy URL của tập 3 vào DownloadWorker với item_index = 1 (giả lập vị trí đầu trong queue người dùng)
            worker = DownloadWorker(ep3.url, options={"item_index": 1, "title": ep3.title})

            mock_provider = MagicMock()
            mock_provider.load_series.return_value = series
            mock_provider.resolve_episode_stream.return_value = "https://cdn.stream/ep8803.m3u8"
            mock_provider.session.get.return_value = MagicMock(status_code=404)

            with patch("providers.detect_provider", return_value=mock_provider), \
                 patch("yt_dlp.YoutubeDL") as mock_ydl:
                mock_ydl_instance = MagicMock()
                mock_ydl.return_value.__enter__.return_value = mock_ydl_instance

                worker._download_drama_episode("downloads")

                # Khẳng định stream URL được gọi đúng của tập 3 (id=8803), không bị ép theo item_index = 1
                mock_ydl_instance.download.assert_called_with(["https://cdn.stream/ep8803.m3u8"])

    def test_subtitle_path_traversal_commonpath(self):
        """P2: os.path.commonpath phải ngăn chặn path traversal và prefix collision."""
        out_path = os.path.abspath("downloads")
        # Giả lập đường dẫn cố tình thoát thư mục
        evil_sub = os.path.abspath(os.path.join(out_path, "..", "downloads_evil", "sub.srt"))
        self.assertNotEqual(
            os.path.commonpath([evil_sub, out_path]),
            out_path,
            "os.path.commonpath không phát hiện prefix collision / directory traversal"
        )

    def test_thumbnail_loader_lru_bounded_size(self):
        """P2-3: ThumbnailLoader phải giới hạn tối đa MAX_CACHE_SIZE và áp dụng LRU eviction."""
        from thumbnail_loader import ThumbnailLoader
        from PySide6.QtGui import QPixmap
        from PySide6.QtWidgets import QApplication
        import sys

        app = QApplication.instance() or QApplication(sys.argv)
        loader = ThumbnailLoader()
        loader.MAX_CACHE_SIZE = 5  # Đặt mức nhỏ để test LRU nhanh

        # Nạp 10 pixmap giả lập
        for i in range(10):
            pm = QPixmap(5, 5)
            loader._on_ready(f"req_{i}|https://fake.url/{i}.jpg", pm)

        # Cache chỉ được giữ tối đa 5 items
        self.assertEqual(len(loader._cache), 5)
        # Các items cũ 0..4 phải bị popitem, chỉ còn 5..9
        self.assertNotIn("https://fake.url/0.jpg", loader._cache)
        self.assertIn("https://fake.url/9.jpg", loader._cache)
        loader.shutdown()
        self.assertEqual(len(loader._cache), 0)


if __name__ == "__main__":
    unittest.main()
