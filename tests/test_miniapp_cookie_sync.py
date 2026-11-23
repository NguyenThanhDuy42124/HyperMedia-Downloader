"""
tests/test_miniapp_cookie_sync.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Kiểm thử luồng đồng bộ cookie MiniApp Douyin từ Extension:
1. Message MINIAPP_DOUYIN_COOKIE_SYNC chấp nhận domain douyin.com hợp lệ.
2. Từ chối payload sai domain hoặc thiếu trường bắt buộc.
3. Mã hóa và giải mã phiên bảo mật (Windows DPAPI / Safe Storage).
4. File lưu trên đĩa không chứa plain text cookie hay token nhạy cảm.
5. Không làm rò rỉ token hoặc cookie ra log/stdout (hàm mask_sensitive).
6. Hỗ trợ xóa phiên chủ động từ UI (clear_douyin_session).
"""

import io
import json
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from providers.miniapp_douyin_client import (
    clear_douyin_session,
    dpapi_protect,
    dpapi_unprotect,
    get_douyin_session_path,
    get_douyin_session_status,
    load_douyin_session,
    mask_sensitive,
    save_douyin_session,
)


class TestMiniAppCookieSync(unittest.TestCase):
    def setUp(self):
        # Dọn dẹp phiên trước mỗi test để đảm bảo môi trường sạch
        clear_douyin_session()

    def tearDown(self):
        clear_douyin_session()

    def test_01_accept_valid_douyin_domain(self):
        """1. Chấp nhận payload với domain douyin.com hợp lệ."""
        valid_payload = {
            "provider": "miniapp_douyin",
            "domain": "douyin.com",
            "cookies": [
                {"name": "sessionid", "value": "test_sess_token_12345"},
                {"name": "passport_csrf_token", "value": "csrf_token_abc"},
            ],
            "captured_at": 1700000000,
        }
        ok, msg = save_douyin_session(valid_payload)
        self.assertTrue(ok, f"Phải lưu thành công: {msg}")

        sess = load_douyin_session()
        self.assertIsNotNone(sess)
        self.assertEqual(sess["domain"], "douyin.com")
        self.assertIn("sessionid=test_sess_token_12345", sess["cookie_str"])

    def test_02_reject_invalid_domain_or_missing_fields(self):
        """2. Từ chối domain nằm ngoài allowlist hoặc dữ liệu rỗng."""
        # Domain không hợp lệ
        bad_domains = [
            "evil-hacker.com",
            "youtube.com",
            "bilibili.com",
            "douyin.com.fake.site",
            "",
        ]
        for bad_d in bad_domains:
            payload = {
                "provider": "miniapp_douyin",
                "domain": bad_d,
                "cookies": [{"name": "sessionid", "value": "123"}],
            }
            ok, msg = save_douyin_session(payload)
            self.assertFalse(ok, f"Phải từ chối domain: {bad_d}")

        # Dữ liệu cookie rỗng
        empty_cookie_payload = {
            "provider": "miniapp_douyin",
            "domain": "douyin.com",
            "cookies": [],
        }
        ok, msg = save_douyin_session(empty_cookie_payload)
        self.assertFalse(ok, "Phải từ chối khi cookies rỗng")

    def test_03_dpapi_encryption_on_disk(self):
        """3. File lưu trên đĩa phải được mã hóa DPAPI, tuyệt đối không có plain text."""
        raw_secret = "super_secret_auth_cookie_token_99999"
        payload = {
            "provider": "miniapp_douyin",
            "domain": "douyin.com",
            "cookies": [{"name": "sessionid", "value": raw_secret}],
        }
        ok, _ = save_douyin_session(payload)
        self.assertTrue(ok)

        sess_file = get_douyin_session_path()
        self.assertTrue(os.path.exists(sess_file))

        with open(sess_file, "rb") as f:
            disk_bytes = f.read()

        # Kiểm tra nội dung thô trên ổ đĩa không được chứa chuỗi nhạy cảm plain text
        self.assertNotIn(
            raw_secret.encode("utf-8"),
            disk_bytes,
            "CẢNH BÁO BẢO MẬT: Token nhạy cảm xuất hiện dưới dạng plain text trên file đĩa!",
        )

        # Giải mã qua DPAPI phải khôi phục đầy đủ
        sess = load_douyin_session()
        self.assertIsNotNone(sess)
        self.assertIn(raw_secret, sess["cookie_str"])

    def test_04_mask_sensitive_tokens(self):
        """4. Hàm mask_sensitive() phải che giấu token và sessionid trước khi in ra log."""
        log_sample = (
            "Request headers: sessionid=abcdef1234567890; "
            "token=duolai_abcdef0123456789abcdef; "
            "uid_tt=9876543210"
        )
        masked = mask_sensitive(log_sample)

        self.assertNotIn("abcdef1234567890", masked)
        self.assertNotIn("duolai_abcdef0123456789abcdef", masked)
        self.assertIn("sessionid=***REDACTED***", masked)
        self.assertIn("duolai_***REDACTED***", masked)
        self.assertIn("uid_tt=***REDACTED***", masked)

    def test_05_clear_session_and_status(self):
        """5. Kiểm tra tính năng xóa phiên chủ động từ UI."""
        payload = {
            "provider": "miniapp_douyin",
            "domain": "douyin.com",
            "cookies": [{"name": "sessionid", "value": "test12345"}],
        }
        save_douyin_session(payload)
        code, msg = get_douyin_session_status()
        self.assertIn(code, ("valid", "COOKIE_STORED"))

        # Xóa phiên
        deleted = clear_douyin_session()
        self.assertTrue(deleted)

        code_after, msg_after = get_douyin_session_status()
        self.assertIn(code_after, ("none", "NO_SESSION"))
        self.assertIsNone(load_douyin_session())

    def test_06_local_server_miniapp_cookie_sync_route(self):
        """6. Kiểm tra xử lý message MINIAPP_DOUYIN_COOKIE_SYNC trong LocalServer."""
        from local_server import LocalServer
        server = LocalServer()

        received_signal = []
        server.miniapp_cookie_synced.connect(lambda d, c, b: received_signal.append((d, c, b)))

        # Dùng mock handler để mô phỏng HTTP POST
        handler_cls = server._create_handler()
        mock_handler = MagicMock()
        mock_handler.headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/131.0"}

        valid_data = {
            "action": "MINIAPP_DOUYIN_COOKIE_SYNC",
            "provider": "miniapp_douyin",
            "domain": "douyin.com",
            "cookies": [{"name": "sessionid", "value": "sync_val_111"}],
        }

        # Gọi trực tiếp method xử lý sync
        handler_cls._handle_miniapp_cookie_sync(mock_handler, valid_data)

        # Kiểm tra phản hồi 200 và signal phát ra
        mock_handler.send_response.assert_called_with(200)
        self.assertEqual(len(received_signal), 1)
        self.assertEqual(received_signal[0][0], "douyin.com")
        self.assertEqual(received_signal[0][1], 1)

        # Kiểm tra từ chối domain sai
        bad_handler = MagicMock()
        bad_data = {
            "action": "MINIAPP_DOUYIN_COOKIE_SYNC",
            "provider": "miniapp_douyin",
            "domain": "phishing.com",
            "cookies": [{"name": "sessionid", "value": "sync_val_111"}],
        }
        handler_cls._handle_miniapp_cookie_sync(bad_handler, bad_data)
        bad_handler.send_response.assert_called_with(400)


if __name__ == "__main__":
    unittest.main()
