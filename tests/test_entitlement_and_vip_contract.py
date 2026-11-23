"""
tests/test_entitlement_and_vip_contract.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Bộ kiểm thử toàn diện xác thực quyền VIP và Entitlement Contract:
1. Tài khoản chưa đăng nhập (guest mode): Các tập ngoài accessible_cnt bị khóa requires_vip.
2. Tài khoản free (đăng nhập không có gói VIP): Không mở khóa sai, hiển thị lý do không xác minh được.
3. Tài khoản VIP (backend xác nhận): Mở khóa với ACCESS_STATE_AUTHORIZED, stream được cấp phép.
4. Cookie hết hạn: Không mở khóa VIP, giữ trạng thái requires_vip an toàn.
5. Entitlement API lỗi (HTTP 500 / timeout): Tự động fail-closed, không bao giờ fake stream.
6. Episode được cấp quyền nhưng resolver thất bại: Trả về None, DownloadWorker báo lỗi rõ ràng.
7. Kiểm tra riêng 4 nền tảng: Hongguo, MiniApp Douyin, DramaBox, KissKH.
8. Tiêu chuẩn bảo mật: Không ghi cookie/token/UID đầy đủ vào log.
"""

import json
import os
import sys
import time
import unittest
from unittest.mock import MagicMock, patch

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from providers.base import (
    ACCESS_STATE_FREE,
    ACCESS_STATE_AUTHORIZED,
    ACCESS_STATE_REQUIRES_VIP,
    ACCESS_STATE_REQUIRES_LOGIN,
    Episode,
    Series,
)
from providers.hongguo_provider import HongguoProvider
from providers.miniapp_douyin_provider import MiniAppDouyinProvider
from providers.miniapp_douyin_client import MiniAppDouyinClient
from providers.dramabox_provider import DramaBoxProvider
from providers.kisskh_provider import KisskhProvider


class TestEntitlementAndVIPContract(unittest.TestCase):

    def setUp(self):
        self.hongguo = HongguoProvider()
        # Xóa sạch cookie để đảm bảo phiên cô lập cho từng test
        self.hongguo.session.cookies.clear()

        self.miniapp = MiniAppDouyinProvider()
        self.dramabox = DramaBoxProvider()
        self.kisskh = KisskhProvider()

    def test_hongguo_unauthenticated_account_locks_vip_episodes(self):
        """1. Tài khoản chưa đăng nhập: Các tập vượt quá accessible_episode_cnt phải bị khóa requires_vip."""
        status_code, status_msg = self.hongguo.get_session_status()
        self.assertEqual(status_code, "anonymous")
        self.assertIn("Chưa đăng nhập", status_msg)

        # Mock phản hồi Modern.js EdenX SSR detail_page
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = json.dumps({
            "seriesDetail": {
                "series_id": "7503745441910017049",
                "series_name": "谁说宗门不能当江湖",
                "accessible_episode_cnt": 5,
                "vid_list": [f"vid_{i}" for i in range(1, 72)],
                "user_info": None,
            }
        })

        with patch.object(self.hongguo.session, "get", return_value=mock_resp):
            series = self.hongguo.load_series("https://hongguoduanju.com/detail?series_id=7503745441910017049")

        self.assertEqual(series.episode_count, 71)
        self.assertEqual(series.accessible_count, 5)

        # 5 tập đầu miễn phí
        for ep in series.episodes[:5]:
            self.assertEqual(ep.access_state, ACCESS_STATE_FREE)
            self.assertFalse(ep.locked)

        # Từ tập 6 đến 71 bị khóa VIP
        for ep in series.episodes[5:]:
            self.assertEqual(ep.access_state, ACCESS_STATE_REQUIRES_VIP)
            self.assertTrue(ep.locked)
            self.assertIn("yêu cầu quyền VIP", ep.access_reason)

        # Thử resolve tập 6 bị khóa -> phải trả về None
        stream = self.hongguo.resolve_episode_stream(series.episodes[5])
        self.assertIsNone(stream)

    def test_hongguo_free_logged_in_account_blocks_unpurchased_episodes(self):
        """2. Tài khoản đã đăng nhập nhưng không có VIP: Các tập > 5 vẫn bị khóa và ghi rõ lý do."""
        self.hongguo.session.cookies.set("sessionid", "mock_session_12345", domain=".hongguoduanju.com")
        self.hongguo.session.cookies.set("uid_tt", "98765432101", domain=".hongguoduanju.com")

        status_code, status_msg = self.hongguo.get_session_status()
        self.assertEqual(status_code, "valid")
        self.assertIn("987***101", status_msg)  # Đã che UID
        self.assertNotIn("98765432101", status_msg)  # Không log UID gốc

        # Mock backend trả về user_info thường (không có VIP)
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = json.dumps({
            "seriesDetail": {
                "series_id": "7503745441910017049",
                "series_name": "谁说宗门不能当江湖",
                "accessible_episode_cnt": 5,
                "vid_list": [f"vid_{i}" for i in range(1, 72)],
                "user_info": {"user_id": "98765432101", "is_vip": 0},
            }
        })

        with patch.object(self.hongguo.session, "get", return_value=mock_resp):
            series = self.hongguo.load_series("https://hongguoduanju.com/detail?series_id=7503745441910017049")

        self.assertEqual(series.accessible_count, 5)
        ep6 = series.episodes[5]
        self.assertEqual(ep6.access_state, ACCESS_STATE_REQUIRES_VIP)
        self.assertTrue(ep6.locked)
        self.assertIn("Không xác minh được quyền VIP", ep6.access_reason)

        # Resolver chặn cứng tập chưa mua
        self.assertIsNone(self.hongguo.resolve_episode_stream(ep6))

    def test_hongguo_vip_purchased_account_unlocks_authorized_episodes(self):
        """3. Tài khoản đã mua VIP: Backend xác nhận quyền sở hữu -> Mở khóa với ACCESS_STATE_AUTHORIZED."""
        self.hongguo.session.cookies.set("sessionid", "valid_vip_session_token", domain=".hongguoduanju.com")
        self.hongguo.session.cookies.set("uid_tt", "11223344556", domain=".hongguoduanju.com")

        # Backend xác nhận quyền VIP qua user_info.is_vip = 1 hoặc accessible_episode_cnt = 71
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = json.dumps({
            "seriesDetail": {
                "series_id": "7503745441910017049",
                "series_name": "谁说宗门不能当江湖",
                "accessible_episode_cnt": 71,  # Backend mở khóa toàn bộ tập cho tài khoản VIP
                "vid_list": [f"vid_{i}" for i in range(1, 72)],
                "user_info": {"user_id": "11223344556", "is_vip": 1},
                "user_has_vip": True,
            }
        })

        with patch.object(self.hongguo.session, "get", return_value=mock_resp):
            series = self.hongguo.load_series("https://hongguoduanju.com/detail?series_id=7503745441910017049")

        self.assertEqual(series.episode_count, 71)
        self.assertEqual(series.accessible_count, 71)

        ep6 = series.episodes[5]
        self.assertFalse(ep6.locked)
        self.assertTrue(self.hongguo.validate_entitlement(ep6))

        # Mock player_page trả về stream hợp lệ cho tập VIP được cấp phép
        mock_player = MagicMock()
        mock_player.status_code = 200
        mock_player.text = json.dumps({
            "videoPlayInfo": {
                "video_url": "https://v.zjcdn.com/hongguo_vip/stream_ep6.mp4",
            }
        })

        with patch.object(self.hongguo.session, "get", return_value=mock_player):
            stream_url = self.hongguo.resolve_episode_stream(ep6)

        self.assertEqual(stream_url, "https://v.zjcdn.com/hongguo_vip/stream_ep6.mp4")
        self.assertEqual(ep6.direct_url, "https://v.zjcdn.com/hongguo_vip/stream_ep6.mp4")

    def test_hongguo_expired_cookie_fails_safe(self):
        """4. Cookie hết hạn: Không mở khóa VIP, giữ nguyên trạng thái requires_vip."""
        now = time.time()
        # Cookie đã hết hạn từ 3600 giây trước
        self.hongguo.session.cookies.set("sessionid", "expired_token", domain=".hongguoduanju.com", expires=now - 3600)

        status_code, status_msg = self.hongguo.get_session_status()
        self.assertEqual(status_code, "expired")
        self.assertIn("hết hạn", status_msg)

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = json.dumps({
            "seriesDetail": {
                "series_id": "7503745441910017049",
                "series_name": "谁说宗门不能当江湖",
                "accessible_episode_cnt": 5,
                "vid_list": [f"vid_{i}" for i in range(1, 72)],
            }
        })

        with patch.object(self.hongguo.session, "get", return_value=mock_resp):
            series = self.hongguo.load_series("https://hongguoduanju.com/detail?series_id=7503745441910017049")

        # Tập 6 vẫn bị khóa an toàn
        ep6 = series.episodes[5]
        self.assertTrue(ep6.locked)
        self.assertEqual(ep6.access_state, ACCESS_STATE_REQUIRES_VIP)
        self.assertIsNone(self.hongguo.resolve_episode_stream(ep6))

    def test_entitlement_api_error_fails_closed(self):
        """5. Entitlement API gặp lỗi HTTP 500 hoặc mất mạng: Fail-closed an toàn, không tạo link rác."""
        self.hongguo.session.cookies.set("sessionid", "valid_token", domain=".hongguoduanju.com")

        ep = Episode(
            num=6,
            title="Tập 6",
            url="https://hongguoduanju.com/player/7503745441910017049?vid=vid_6&ep=6",
            locked=False,
            access_state=ACCESS_STATE_AUTHORIZED,
            series_id="hongguo:7503745441910017049",
            episode_id="vid_6",
        )

        mock_err = MagicMock()
        mock_err.status_code = 500

        with patch.object(self.hongguo.session, "get", return_value=mock_err):
            stream = self.hongguo.resolve_episode_stream(ep)

        self.assertIsNone(stream)

    def test_authorized_episode_with_failed_stream_resolver_in_worker(self):
        """6. Tập được cấp quyền nhưng stream resolver thất bại: DownloadWorker raise ValueError rõ ràng."""
        from download_worker import DownloadWorker

        # Tạo series và episode đã được authorized
        ep = Episode(
            num=6,
            title="Tập 6",
            url="https://hongguoduanju.com/player/7503745441910017049?vid=vid_6&ep=6",
            locked=False,
            access_state=ACCESS_STATE_AUTHORIZED,
            series_id="hongguo:7503745441910017049",
            episode_id="vid_6",
        )
        series = Series(
            name="Test Authorized Series",
            platform="hongguo",
            series_id="hongguo:7503745441910017049",
            episode_count=10,
            accessible_count=10,
            episodes=[ep],
        )

        worker = DownloadWorker(
            "https://hongguoduanju.com/player/7503745441910017049?vid=vid_6&ep=6",
            options={
                "is_drama": True,
                "drama_series": series,
                "item_index": 6,
                "episode_id": "vid_6",
            }
        )

        # Mock provider.resolve_episode_stream trả về None (do backend thu hồi quyền hoặc lỗi CDN)
        with patch("providers.detect_provider") as mock_detect_p:
            mock_p = MagicMock()
            mock_p.display_name = "Hongguo"
            mock_p.resolve_episode_stream.return_value = None
            mock_detect_p.return_value = mock_p

            with self.assertRaises(ValueError) as ctx:
                worker._download_drama_episode("dummy.mp4")

            self.assertIn("Không thể lấy URL phát trực tiếp cho Tập 6", str(ctx.exception))

    def test_miniapp_douyin_entitlement_and_check_contract(self):
        """7. MiniApp Douyin: Kiểm tra client.check_entitlement và trạng thái phiên DPAPI."""
        client = MiniAppDouyinClient(cookie="mock_douyin_cookie")

        # Mock mint token và play_url
        with patch.object(client, "mint_token", return_value=("mock_tok_abc", "OK")):
            with patch.object(client, "get_play_url") as mock_play:
                mock_play.return_value = ("https://duolai.cdn.com/stream.mp4", None)
                ok, stream = client.check_entitlement("tt5b4d2df0c47bdd2201", "101")
                self.assertTrue(ok)
                self.assertEqual(stream, "https://duolai.cdn.com/stream.mp4")

                # Khi chưa mua VIP -> server trả lỗi
                mock_play.return_value = (None, "Tập phim yêu cầu quyền VIP trên ứng dụng gốc")
                ok2, err_msg = client.check_entitlement("tt5b4d2df0c47bdd2201", "102")
                self.assertFalse(ok2)
                self.assertIn("yêu cầu quyền VIP", err_msg)

        # Kiểm tra session status
        status, _ = self.miniapp.get_session_status()
        self.assertIn(status, ("valid", "anonymous", "expired", "none", "COOKIE_STORED", "AUTHENTICATED", "NO_SESSION"))

    def test_dramabox_unsupported_vip_contract(self):
        """8. DramaBox: Xác nhận trạng thái unsupported, không cho phép bypass hay giả mạo VIP."""
        status_code, msg = self.dramabox.get_session_status()
        self.assertEqual(status_code, "unsupported")
        self.assertIn("chưa hỗ trợ API tài khoản VIP trên Web PC", msg)

        self.assertFalse(self.dramabox.authenticate({"token": "fake_token"}))
        self.assertFalse(self.dramabox.refresh_session())

        # Kiểm tra tập free vs tập VIP
        ep_free = Episode(num=1, title="Tập 1", url="https://dramaboxdb.com/movie/1/drama", access_state=ACCESS_STATE_FREE, locked=False)
        ep_locked = Episode(num=6, title="Tập 6", url="https://dramaboxdb.com/movie/1/drama", access_state=ACCESS_STATE_REQUIRES_VIP, locked=True)

        self.assertTrue(self.dramabox.validate_entitlement(ep_free))
        self.assertFalse(self.dramabox.validate_entitlement(ep_locked))

    def test_kisskh_free_platform_contract(self):
        """9. KissKH: Nền tảng miễn phí 100%, tất cả tập hợp lệ đều được validate_entitlement chấp thuận."""
        status_code, msg = self.kisskh.get_session_status()
        self.assertEqual(status_code, "free_platform")
        self.assertIn("miễn phí 100%", msg)

        self.assertFalse(self.kisskh.authenticate({}))
        self.assertFalse(self.kisskh.refresh_session())

        ep = Episode(num=10, title="Tập 10", url="https://kisskh.co/Drama/10", access_state=ACCESS_STATE_FREE, locked=False)
        self.assertTrue(self.kisskh.validate_entitlement(ep))

    def test_security_zero_secrets_in_session_status(self):
        """10. Tiêu chuẩn bảo mật: Không rò rỉ session token hoặc UID nguyên bản qua log/status."""
        sensitive_session = "VERY_SECRET_BYTEDANCE_SESSION_TOKEN_123456789"
        sensitive_uid = "88990011223344"

        self.hongguo.session.cookies.set("sessionid", sensitive_session, domain=".hongguoduanju.com")
        self.hongguo.session.cookies.set("uid_tt", sensitive_uid, domain=".hongguoduanju.com")

        status_code, msg = self.hongguo.get_session_status()
        self.assertEqual(status_code, "valid")
        # Token bí mật tuyệt đối không được xuất hiện
        self.assertNotIn(sensitive_session, msg)
        # UID đầy đủ tuyệt đối không được xuất hiện
        self.assertNotIn(sensitive_uid, msg)
        # Chỉ hiển thị dạng đã che (Masked)
        self.assertIn("889***344", msg)


if __name__ == "__main__":
    unittest.main()
