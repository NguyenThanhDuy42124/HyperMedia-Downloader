"""
tests/test_miniapp_access_guard.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Kiểm thử Spy & Network Guard chứng minh tính toàn vẹn bảo mật cho MiniApp Douyin:
1. resolve_stream() hoặc request tải tập khóa:
   - Ném lỗi hoặc trả về None / chặn truy cập.
   - KHÔNG gửi bất kỳ HTTP request nào đến API play_url hay CDN video khi tập không phải Free.
2. MiniAppDouyinClient.get_play_url():
   - Khi is_free=False, chặn ngay lập tức, 0 HTTP request phát sinh.
3. DownloadWorker:
   - Chặn đứng việc tải tập locked/VIP với ValueError trước khi gọi CDN stream.
4. validate_entitlement():
   - Trả về False cho mọi tập locked hoặc access_state != free.
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
    ACCESS_STATE_UNAVAILABLE,
    Episode,
    Series,
)
from providers.miniapp_douyin_provider import MiniAppDouyinProvider
from download_worker import DownloadWorker


class TestMiniAppAccessGuard(unittest.TestCase):
    def setUp(self):
        self.provider = MiniAppDouyinProvider()

    def test_01_client_get_play_url_blocks_locked_with_zero_network(self):
        """1. Client get_play_url() chặn cứng khi is_free=False, 0 HTTP request phát sinh."""
        with patch.object(self.provider.client.session, "get") as spy_http:
            url, err = self.provider.client.get_play_url(
                app_id="tt5b4d2df0c47bdd2201",
                episode_id="ep_vip_999",
                is_free=False,
            )
            self.assertIsNone(url)
            self.assertIn("VIP", str(err))
            spy_http.assert_not_called()

    def test_02_resolve_stream_returns_none_and_sends_zero_requests(self):
        """2. resolve_stream() trả về None cho tập locked, không gọi API play_url hay CDN."""
        vip_ep = Episode(
            num=10,
            title="Tập 10 (VIP)",
            url="douyin_miniapp:tt_app:888?ep_id=ep_vip_10&ep=10",
            locked=True,
            access_state=ACCESS_STATE_REQUIRES_VIP,
            episode_id="ep_vip_10",
            extra={"app_id": "tt_app", "episode_id": "ep_vip_10", "is_free": False},
        )

        with patch.object(self.provider.client, "get_play_url") as spy_get_play, \
             patch.object(self.provider.session, "get") as spy_http:
            res = self.provider.resolve_stream(vip_ep)
            self.assertIsNone(res)
            spy_get_play.assert_not_called()
            spy_http.assert_not_called()

    def test_03_download_worker_aborts_on_locked_episode(self):
        """3. DownloadWorker ném ValueError khi gặp tập bị khóa, không phát sinh request CDN."""
        worker = DownloadWorker(
            url="douyin_miniapp:tt_app:888?ep_id=ep_locked_5&ep=5",
            options={
                "uid": "test_uid_guard",
                "title": "Phim Douyin - Tập 5",
                "folder": os.path.abspath("./downloads"),
                "episode_id": "ep_locked_5",
                "item_index": 5,
            },
        )

        # Giả lập series có tập 5 bị khóa
        mock_series = Series(
            name="Phim Douyin",
            platform="miniapp_douyin",
            series_id="douyin_miniapp:tt_app:888",
            episode_count=5,
            accessible_count=4,
            episodes=[
                Episode(
                    num=5,
                    title="Tập 5",
                    url="douyin_miniapp:tt_app:888?ep_id=ep_locked_5&ep=5",
                    locked=True,
                    access_state=ACCESS_STATE_REQUIRES_VIP,
                    episode_id="ep_locked_5",
                    extra={"app_id": "tt_app", "episode_id": "ep_locked_5", "is_free": False},
                )
            ],
        )

        with patch("providers.detect_provider", return_value=self.provider), \
             patch.object(self.provider, "load_series", return_value=mock_series), \
             patch.object(self.provider, "resolve_episode_stream") as spy_resolve, \
             patch("yt_dlp.YoutubeDL") as spy_ydl:
            with self.assertRaises(ValueError) as ctx:
                worker._download_drama_episode(os.path.abspath("./downloads"))

            self.assertIn("không thể tải", str(ctx.exception))
            spy_resolve.assert_not_called()
            spy_ydl.assert_not_called()

    def test_04_validate_entitlement_contract(self):
        """4. validate_entitlement() trả về False cho mọi tập locked / VIP / unavailable."""
        free_ep = Episode(num=1, title="Tập 1", url="u1", locked=False, access_state=ACCESS_STATE_FREE)
        vip_ep = Episode(num=2, title="Tập 2", url="u2", locked=True, access_state=ACCESS_STATE_REQUIRES_VIP)
        unavail_ep = Episode(num=3, title="Tập 3", url="u3", locked=True, access_state=ACCESS_STATE_UNAVAILABLE)

        self.assertTrue(self.provider.validate_entitlement(free_ep))
        self.assertFalse(self.provider.validate_entitlement(vip_ep))
        self.assertFalse(self.provider.validate_entitlement(unavail_ep))


if __name__ == "__main__":
    unittest.main()
