"""
tests/test_drama_network_guard.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Bộ kiểm thử Spy & Network Guard chứng minh tính toàn vẹn của kiến trúc Free-first:
1. Episode locked tuyệt đối không gọi resolve_episode_stream() trong DownloadWorker.
2. access_state != free tuyệt đối không gọi YoutubeDL hoặc HTTP stream tới CDN.
3. Trực tiếp gọi resolve_episode_stream() trên toàn bộ 11 provider với tập locked/VIP
   luôn trả về None và phát sinh chính xác 0 network request ngầm.
4. Quá trình chọn và enqueue tập trong DramaEpisodeDialog không phát sinh network request ngầm
   khi các tập bị khóa hoặc từ chối.
5. Các method stub authenticate(), refresh_session(), validate_entitlement()
   hoàn toàn trơ (inert) và không giả mạo hỗ trợ VIP.
"""

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
    ACCESS_STATE_REQUIRES_LOGIN,
    ACCESS_STATE_UNAVAILABLE,
    Episode,
    Series,
)
import providers
from download_worker import DownloadWorker


class TestDramaNetworkGuard(unittest.TestCase):

    def test_locked_episode_strictly_bypasses_resolve_stream_in_worker(self):
        """Worker gặp episode.locked=True phải raise ValueError TRƯỚC KHI gọi resolve_episode_stream()."""
        locked_ep = Episode(
            num=3,
            title="Tập 3 Khóa",
            url="https://www.shortmax.com/drama/sm_test/3?ep_id=ch_3",
            episode_id="ch_3",
            episode_number=3,
            access_state=ACCESS_STATE_REQUIRES_VIP,
            access_reason="Yêu cầu mua VIP trên ứng dụng gốc",
            locked=True,
            extra={"episode_id": "ch_3"},
        )
        series = Series(
            name="ShortMax Test",
            platform="shortmax",
            series_id="shortmax:sm_test",
            episode_count=3,
            accessible_count=2,
            episodes=[locked_ep],
        )

        worker = DownloadWorker(url=locked_ep.url, options={"output_path": "downloads"})

        mock_provider = providers.get_provider("shortmax")
        self.assertIsNotNone(mock_provider)

        # Đặt spy lên resolve_episode_stream
        mock_resolve = MagicMock()

        with patch.object(mock_provider, "load_series", return_value=series), \
             patch.object(mock_provider, "resolve_episode_stream", mock_resolve), \
             patch("providers.detect_provider", return_value=mock_provider):

            with self.assertRaises(ValueError) as ctx:
                worker._download_drama_episode("downloads")

            self.assertIn("không thể tải", str(ctx.exception))
            # Chứng minh: resolver không bao giờ được gọi
            mock_resolve.assert_not_called()

    def test_access_state_not_free_never_calls_cdn_or_network(self):
        """Worker gặp access_state != 'free' tuyệt đối không gọi YoutubeDL hay HTTP request tới CDN."""
        states = [ACCESS_STATE_REQUIRES_VIP, ACCESS_STATE_REQUIRES_LOGIN, ACCESS_STATE_UNAVAILABLE]

        for st in states:
            test_ep = Episode(
                num=4,
                title=f"Tập 4 {st}",
                url=f"https://hongguoduanju.com/player/741000?vid=v4&ep=4&ep_id=v4",
                episode_id="v4",
                episode_number=4,
                access_state=st,
                access_reason=f"Lý do truy cập: {st}",
                locked=True,
                extra={"vid": "v4", "episode_id": "v4"},
            )
            series = Series(
                name="Hongguo Test Series",
                platform="hongguo",
                series_id="hongguo:741000",
                episode_count=5,
                accessible_count=3,
                episodes=[test_ep],
            )

            worker = DownloadWorker(url=test_ep.url, options={"output_path": "downloads"})
            mock_p = providers.get_provider("hongguo")

            with patch.object(mock_p, "load_series", return_value=series), \
                 patch("providers.detect_provider", return_value=mock_p), \
                 patch("yt_dlp.YoutubeDL") as mock_ydl, \
                 patch("requests.Session.get") as mock_sess_get, \
                 patch("requests.get") as mock_req_get:

                with self.assertRaises(ValueError) as ctx:
                    worker._download_drama_episode("downloads")

                self.assertIn("không thể tải", str(ctx.exception))
                # Chứng minh: Hoàn toàn 0 cuộc gọi tới YoutubeDL hoặc CDN
                mock_ydl.assert_not_called()
                mock_sess_get.assert_not_called()
                mock_req_get.assert_not_called()

    def test_provider_resolve_returns_none_and_zero_network_for_locked_episodes(self):
        """Gọi trực tiếp resolve_episode_stream() trên TOÀN BỘ 12 provider với tập locked trả về None và 0 network."""
        all_provs = providers.get_all_providers()
        self.assertEqual(len(all_provs), 12, "Phải có đủ 12 provider đăng ký")

        for p in all_provs:
            locked_ep = Episode(
                num=10,
                title="Tập 10 Khóa",
                url=f"https://test.platform/drama/10",
                episode_id="100010",
                access_state=ACCESS_STATE_REQUIRES_VIP,
                locked=True,
                extra={"chapter_id": "100010", "kk_ep": "100010", "vid": "100010"},
            )

            with patch.object(p.session, "get") as mock_p_get, \
                 patch("requests.get") as mock_req_get:

                stream = p.resolve_episode_stream(locked_ep)

                self.assertIsNone(stream, f"Provider {p.display_name} không được giải mã stream cho tập locked")
                mock_p_get.assert_not_called()
                mock_req_get.assert_not_called()

    def test_dialog_rejected_enqueue_makes_zero_network_requests(self):
        """Kiểm tra DramaEpisodeDialog lọc bỏ hoàn toàn các tập VIP/locked và không sinh network request ngầm."""
        from PySide6.QtWidgets import QApplication
        from drama_dialog import DramaEpisodeDialog

        app = QApplication.instance() or QApplication(sys.argv)

        episodes = [
            Episode(num=1, title="T1", url="https://test/1", access_state=ACCESS_STATE_FREE, locked=False),
            Episode(num=2, title="T2", url="https://test/2", access_state=ACCESS_STATE_FREE, locked=False),
            Episode(num=3, title="T3", url="https://test/3", access_state=ACCESS_STATE_REQUIRES_VIP, locked=True),
            Episode(num=4, title="T4", url="https://test/4", access_state=ACCESS_STATE_REQUIRES_LOGIN, locked=True),
        ]
        series = Series(
            name="Dialog Guard Test",
            platform="goodshort",
            series_id="goodshort:123",
            episode_count=4,
            accessible_count=2,
            episodes=episodes,
        )

        with patch("requests.get") as mock_get, \
             patch("requests.Session.get") as mock_sess_get:

            dlg = DramaEpisodeDialog(series)

            # Checkbox trạng thái ban đầu
            self.assertTrue(dlg.episode_checkboxes[1].isEnabled())
            self.assertTrue(dlg.episode_checkboxes[2].isEnabled())
            self.assertFalse(dlg.episode_checkboxes[3].isEnabled())
            self.assertFalse(dlg.episode_checkboxes[4].isEnabled())

            # Thử select all
            dlg._select_all()
            self.assertTrue(dlg.episode_checkboxes[1].isChecked())
            self.assertTrue(dlg.episode_checkboxes[2].isChecked())
            self.assertFalse(dlg.episode_checkboxes[3].isChecked())
            self.assertFalse(dlg.episode_checkboxes[4].isChecked())

            # Thử áp dụng range 1-4
            dlg.txt_range.setText("1-4")
            dlg._apply_range_filter()
            self.assertTrue(dlg.episode_checkboxes[1].isChecked())
            self.assertTrue(dlg.episode_checkboxes[2].isChecked())
            self.assertFalse(dlg.episode_checkboxes[3].isChecked())
            self.assertFalse(dlg.episode_checkboxes[4].isChecked())

            # Xác nhận emitter chỉ phát sinh đúng các tập free
            emitted_eps = []
            dlg.episodes_selected.connect(lambda eps: emitted_eps.extend(eps))
            dlg._on_confirm()

            self.assertEqual(len(emitted_eps), 2)
            self.assertEqual([e.num for e in emitted_eps], [1, 2])

            # Đảm bảo không phát sinh bất kỳ network request ngầm nào
            mock_get.assert_not_called()
            mock_sess_get.assert_not_called()

    def test_vip_stubs_are_inert_interfaces_with_zero_network(self):
        """Xác nhận authenticate(), refresh_session(), validate_entitlement() là interface trơ, 0 network."""
        all_provs = providers.get_all_providers()
        free_ep = Episode(num=1, title="T1", url="https://test/1", access_state=ACCESS_STATE_FREE, locked=False)
        vip_ep = Episode(num=2, title="T2", url="https://test/2", access_state=ACCESS_STATE_REQUIRES_VIP, locked=True)

        for p in all_provs:
            with patch.object(p.session, "get") as mock_p_get, \
                 patch.object(p.session, "post") as mock_p_post, \
                 patch("requests.get") as mock_req_get, \
                 patch("requests.post") as mock_req_post:

                self.assertFalse(p.authenticate({"username": "user", "password": "pwd"}))
                self.assertFalse(p.refresh_session())
                self.assertTrue(p.validate_entitlement(free_ep))
                self.assertFalse(p.validate_entitlement(vip_ep))

                mock_p_get.assert_not_called()
                mock_p_post.assert_not_called()
                mock_req_get.assert_not_called()
                mock_req_post.assert_not_called()


if __name__ == "__main__":
    unittest.main()
