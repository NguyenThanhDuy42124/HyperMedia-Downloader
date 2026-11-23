"""
tests/test_miniapp_no_network_on_locked.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Kiểm thử Spy & Network Guard chứng minh tính toàn vẹn bảo mật cho Douyin MiniApp:
1. Tập locked tuyệt đối không gọi endpoint play_url hoặc CDN stream.
2. DownloadWorker chặn đứng việc tải tập locked/VIP với ValueError.
3. Cookie tuyệt đối không được gửi ra ngoài domain allowlist (chỉ ma.zijieapi.com và lizhibj.cn).
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

from tests.miniapp_douyin_adapter import (
    MiniAppDouyinClient,
    MiniAppDouyinProvider,
    COOKIE_ALLOWED_DOMAINS,
)
from providers.base import (
    ACCESS_STATE_FREE,
    ACCESS_STATE_REQUIRES_VIP,
    Episode,
    Series,
)
from download_worker import DownloadWorker


class TestMiniAppNoNetworkOnLocked(unittest.TestCase):

    def setUp(self):
        self.cookie = "uid_tt=test_user; sessionid=test_session"
        self.client = MiniAppDouyinClient(cookie=self.cookie)
        self.provider = MiniAppDouyinProvider(cookie=self.cookie)

    def test_locked_episode_never_calls_play_url_or_network(self):
        """Khẳng định hàm get_play_url trả về None ngay lập tức và 0 network nếu is_free=False."""
        with patch.object(self.client.session, "get") as mock_get:
            res = self.client.get_play_url(
                app_id="tt5b4d2df0c47bdd2201",
                episode_id="999888",
                is_free=False,  # Tập bị khóa
                token="duolai_test_tok",
            )
            self.assertIsNone(res)
            mock_get.assert_not_called()

    def test_provider_resolve_returns_none_for_locked_episode(self):
        """Khẳng định provider.resolve_episode_stream() trả về None cho tập locked và 0 network."""
        locked_ep = Episode(
            num=4,
            title="Tập 4 VIP",
            url="douyin_miniapp:tt5b4d2df0c47bdd2201:1234?ep_id=4004&ep=4",
            episode_id="4004",
            episode_number=4,
            access_state=ACCESS_STATE_REQUIRES_VIP,
            locked=True,
            extra={"app_id": "tt5b4d2df0c47bdd2201", "episode_id": "4004", "is_free": False},
        )

        with patch.object(self.provider.client.session, "get") as mock_get, \
             patch("requests.get") as mock_req_get:

            stream = self.provider.resolve_episode_stream(locked_ep)
            self.assertIsNone(stream)
            mock_get.assert_not_called()
            mock_req_get.assert_not_called()

    def test_download_worker_strictly_rejects_locked_miniapp_episode(self):
        """DownloadWorker chặn tải tập locked với ValueError rõ ràng, không gọi YoutubeDL."""
        locked_ep = Episode(
            num=5,
            title="Tập 5 VIP",
            url="douyin_miniapp:tt5b4d2df0c47bdd2201:1234?ep_id=5005&ep=5",
            episode_id="5005",
            episode_number=5,
            access_state=ACCESS_STATE_REQUIRES_VIP,
            access_reason="Tập này yêu cầu mua VIP trên MiniApp Douyin.",
            locked=True,
            extra={"app_id": "tt5b4d2df0c47bdd2201", "episode_id": "5005", "is_free": False},
        )
        series = Series(
            name="MiniApp Locked Series",
            platform="douyin_miniapp",
            series_id="douyin_miniapp:tt5b4d2df0c47bdd2201:1234",
            episode_count=5,
            accessible_count=4,
            episodes=[locked_ep],
        )

        worker = DownloadWorker(url=locked_ep.url, options={"output_path": "downloads"})

        with patch("providers.detect_provider") as mock_det, \
             patch("yt_dlp.YoutubeDL") as mock_ydl:
            mock_p = MiniAppDouyinProvider(cookie=self.cookie)
            mock_p.load_series = MagicMock(return_value=series)
            mock_det.return_value = mock_p

            with self.assertRaises(ValueError) as ctx:
                worker._download_drama_episode("downloads")

            self.assertIn("không thể tải", str(ctx.exception))
            mock_ydl.assert_not_called()

    def test_cookie_domain_allowlist_enforcement(self):
        """Khẳng định cookie không bao giờ được gửi đến các domain bên ngoài allowlist."""
        safe_urls = [
            "https://ma.zijieapi.com/api/apps/v3/login",
            "https://xiaoguofanxing.lizhibj.cn/api/duolai/login",
        ]
        unsafe_urls = [
            "https://api.thirdparty-analytics.com/track",
            "https://evil-server.net/collect",
            "https://google.com/search",
        ]

        for u in safe_urls:
            self.assertTrue(self.client.check_cookie_domain_safe(u), f"URL phải an toàn: {u}")

        for u in unsafe_urls:
            self.assertFalse(self.client.check_cookie_domain_safe(u), f"URL không được phép nhận cookie: {u}")


if __name__ == "__main__":
    unittest.main()
