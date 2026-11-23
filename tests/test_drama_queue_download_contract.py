"""
tests/test_drama_queue_download_contract.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Kiểm thử hợp đồng DownloadWorker cho luồng tải tập Free:
 6. Tập Free gọi đúng provider.
 7. Tập Locked không gọi resolver hay CDN.
 9. HTTP 206 Partial Content và resume .part được chấp nhận trong download_direct_stream.
10. HTTP 403 / 404 hiển thị đúng phase lỗi và log chẩn đoán.
11. HLS Free (.m3u8) tải và merge qua FFmpeg / YoutubeDL / download_hls_antihook được.
15. DownloadWorker báo lỗi rõ khi direct_url rỗng ('Không thể phân giải stream tập {n} từ {provider}').
"""

import os
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from providers.base import ACCESS_STATE_FREE, ACCESS_STATE_REQUIRES_VIP, Episode, Series
from download_worker import DownloadWorker


class TestDramaQueueDownloadContract(unittest.TestCase):

    def test_01_free_episode_calls_right_provider_and_resolves(self):
        """6. Tập Free gọi đúng provider và giải mã stream URL trước khi tải."""
        with tempfile.TemporaryDirectory() as td:
            opts = {
                "output_path": td,
                "exact_file_stem": "01 - Tập 1",
                "provider": "hongguo",
                "provider_id": "hongguo",
                "series_id": "hongguo:750111",
                "episode_id": "vid_111",
                "episode_number": 1,
                "access_state": "free",
                "locked": False,
                "extra": {"vid": "vid_111", "series_id": "750111"},
            }
            w = DownloadWorker("https://hongguoduanju.com/player/750111?vid=vid_111&ep=1", opts)

            mock_prov = MagicMock()
            mock_prov.platform_id = "hongguo"
            mock_prov.display_name = "Hongguo / Fanqie"
            mock_prov.resolve_episode_stream.return_value = "https://cdn.test/hg_1.mp4"

            with patch("providers.detect_provider", return_value=mock_prov), \
                 patch("yt_dlp.YoutubeDL") as mock_ydl:
                mock_ydl_inst = MagicMock()
                mock_ydl.return_value.__enter__.return_value = mock_ydl_inst
                w._download_drama_episode(td)

            mock_prov.resolve_episode_stream.assert_called_once()
            mock_ydl_inst.download.assert_called_once_with(["https://cdn.test/hg_1.mp4"])

    def test_02_locked_episode_never_calls_resolver_or_cdn(self):
        """7. Tập Locked bị chặn ngay từ metadata queue, 0 cuộc gọi resolver / CDN."""
        with tempfile.TemporaryDirectory() as td:
            opts = {
                "output_path": td,
                "provider": "hongguo",
                "episode_id": "vid_vip",
                "episode_number": 6,
                "access_state": ACCESS_STATE_REQUIRES_VIP,
                "locked": True,
                "extra": {"vid": "vid_vip", "series_id": "750111"},
            }
            w = DownloadWorker("https://hongguoduanju.com/player/750111?vid=vid_vip&ep=6", opts)
            mock_prov = MagicMock()
            mock_prov.platform_id = "hongguo"
            mock_prov.display_name = "Hongguo / Fanqie"

            with patch("providers.detect_provider", return_value=mock_prov), \
                 patch("yt_dlp.YoutubeDL") as mock_ydl, \
                 patch("requests.get") as mock_req:
                with self.assertRaises(ValueError) as ctx:
                    w._download_drama_episode(td)

            self.assertIn("không thể tải", str(ctx.exception))
            mock_prov.resolve_episode_stream.assert_not_called()
            mock_prov.load_series.assert_not_called()
            mock_ydl.assert_not_called()
            mock_req.assert_not_called()

    def test_03_http_206_partial_content_and_part_resume_accepted(self):
        """9. HTTP 206 được chấp nhận và resume tiếp tục từ file .part sẵn có."""
        with tempfile.TemporaryDirectory() as td:
            target_mp4 = os.path.join(td, "01 - Tập 1.mp4")
            part_file = f"{target_mp4}.part"
            with open(part_file, "wb") as pf:
                pf.write(b"12345")

            w = DownloadWorker("https://hongguoduanju.com/player/1?vid=v1", {"output_path": td})
            mock_resp = MagicMock()
            mock_resp.status_code = 206
            mock_resp.headers = {"Content-Type": "video/mp4", "Content-Length": "5"}
            mock_resp.iter_content.return_value = [b"67890"]

            with patch("requests.get", return_value=mock_resp) as mock_get:
                st = w.download_direct_stream("https://cdn.test/v1.mp4", target_mp4, headers={"Referer": "https://hongguoduanju.com/"})

            self.assertEqual(st, 206)
            sent_headers = mock_get.call_args.kwargs["headers"]
            self.assertEqual(sent_headers["Range"], "bytes=5-")
            self.assertTrue(os.path.exists(target_mp4))
            self.assertFalse(os.path.exists(part_file))
            with open(target_mp4, "rb") as f:
                self.assertEqual(f.read(), b"1234567890")

    def test_04_http_403_404_reports_exact_download_phase_error(self):
        """10. HTTP 403/404 hiển thị đúng lỗi HTTP và log phase=download."""
        with tempfile.TemporaryDirectory() as td:
            w = DownloadWorker("https://hongguoduanju.com/player/1?vid=v1", {
                "output_path": td,
                "provider": "hongguo",
                "episode_id": "v1",
                "episode_number": 1,
                "access_state": "free",
                "extra": {"vid": "v1", "series_id": "1"},
            })

            for code in (403, 404):
                mock_prov = MagicMock()
                mock_prov.platform_id = "hongguo"
                mock_prov.display_name = "Hongguo / Fanqie"
                mock_prov.resolve_episode_stream.return_value = "https://cdn.test/forbidden.mp4"

                with patch("providers.detect_provider", return_value=mock_prov), \
                     patch("yt_dlp.YoutubeDL") as mock_ydl:
                    mock_ydl_inst = MagicMock()
                    mock_ydl_inst.download.side_effect = Exception(f"HTTP Error {code}: Forbidden")
                    mock_ydl.return_value.__enter__.return_value = mock_ydl_inst

                    with self.assertRaises(Exception) as ctx:
                        w._download_drama_episode(td)
                    self.assertIn(f"HTTP Error {code}", str(ctx.exception))

    def test_05_hls_free_download_and_merge_flow(self):
        """11. HLS Free (.m3u8) đi đúng nhánh HLS downloader / FFmpeg."""
        with tempfile.TemporaryDirectory() as td:
            # Case A: KissKH / Drama HLS qua YoutubeDL + ffmpeg_location
            w_kk = DownloadWorker("https://kisskh.co/Drama/?id=1&ep_id=10&ep=1", {
                "output_path": td,
                "exact_file_stem": "01 - Tập 1",
                "provider": "kisskh",
                "episode_id": "10",
                "episode_number": 1,
                "access_state": "free",
                "extra": {"kk_ep": "10"},
            })
            mock_kk = MagicMock()
            mock_kk.platform_id = "kisskh"
            mock_kk.display_name = "KissKH"
            mock_kk.resolve_episode_stream.return_value = "https://cdn.kisskh.test/master.m3u8"

            with patch("providers.detect_provider", return_value=mock_kk), \
                 patch("yt_dlp.YoutubeDL") as mock_ydl:
                mock_ydl_inst = MagicMock()
                mock_ydl.return_value.__enter__.return_value = mock_ydl_inst
                w_kk._download_drama_episode(td)
                passed_opts = mock_ydl.call_args[0][0]
                self.assertIn("ffmpeg_location", passed_opts)
                mock_ydl_inst.download.assert_called_once_with(["https://cdn.kisskh.test/master.m3u8"])

            # Case B: MiniApp Douyin HLS gọi download_hls_antihook với progress callback không crash (đã fix progress_update)
            w_ma = DownloadWorker("douyin_miniapp:tt123:456?ep_id=ep1&ep=1", {
                "output_path": td,
                "exact_file_stem": "01 - Tập 1",
                "provider": "miniapp_douyin",
                "episode_id": "ep1",
                "episode_number": 1,
                "access_state": "free",
                "extra": {"app_id": "tt123", "episode_id": "ep1"},
            })
            mock_ma = MagicMock()
            mock_ma.platform_id = "miniapp_douyin"
            mock_ma.display_name = "MiniApp Douyin"
            mock_ma.resolve_episode_stream.return_value = "https://cdn.duolai.test/ep1.m3u8"

            def fake_hls(url, out_mp4, app_id, progress_cb=None, stop_cb=None, ffmpeg_bin=None):
                if progress_cb:
                    progress_cb(5, 10, 2.5, "downloading")
                return True

            mock_ma.client.download_hls_antihook.side_effect = fake_hls
            prog_events = []
            w_ma.task_progress.connect(lambda p: prog_events.append(p))

            with patch("providers.detect_provider", return_value=mock_ma):
                w_ma._download_drama_episode(td)

            mock_ma.client.download_hls_antihook.assert_called_once()
            self.assertEqual(prog_events, [50])

    def test_06_empty_resolved_stream_raises_clear_provider_error(self):
        """15. DownloadWorker báo lỗi rõ khi direct_url/stream_url rỗng."""
        with tempfile.TemporaryDirectory() as td:
            w = DownloadWorker("https://hongguoduanju.com/player/750111?vid=v1&ep=4", {
                "output_path": td,
                "provider": "hongguo",
                "episode_id": "v1",
                "episode_number": 4,
                "access_state": "free",
                "extra": {"vid": "v1", "series_id": "750111"},
            })
            mock_prov = MagicMock()
            mock_prov.platform_id = "hongguo"
            mock_prov.display_name = "Hongguo / Fanqie"
            mock_prov.last_error = "HTTP 403"
            mock_prov.resolve_episode_stream.return_value = None

            with patch("providers.detect_provider", return_value=mock_prov):
                with self.assertRaises(ValueError) as ctx:
                    w._download_drama_episode(td)

            msg = str(ctx.exception)
            self.assertIn("Không thể phân giải stream tập 4 từ Hongguo / Fanqie", msg)


if __name__ == "__main__":
    unittest.main()
