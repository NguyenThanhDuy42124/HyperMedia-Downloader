"""
tests/test_miniapp_access_state.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Kiểm thử trạng thái truy cập & Bảo vệ dữ liệu cho Douyin MiniApp:
1. Phân loại chuẩn xác access_state (free vs requires_vip) dựa trên trường is_free.
2. Phân loại lỗi token / cookie hết hạn (HTTP 401, thiếu js_code).
3. Đảm bảo cookie và token không bao giờ bị ghi vào log dưới dạng plain text.
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
    mask_sensitive,
)
from providers.base import ACCESS_STATE_FREE, ACCESS_STATE_REQUIRES_VIP


class TestMiniAppAccessState(unittest.TestCase):

    def setUp(self):
        self.raw_cookie = "uid_tt=123456789abcdef; sessionid=aabbccddeeff001122; passport_csrf_token=sec_999"
        self.client = MiniAppDouyinClient(cookie=self.raw_cookie)
        self.provider = MiniAppDouyinProvider(cookie=self.raw_cookie)

    def test_access_state_mapping_from_is_free(self):
        """Kiểm tra is_free = 'T'/True/1 -> free; 'F'/False/0 -> requires_vip."""
        fixture = {
            "code": 0,
            "data": [
                {"id": 101, "sequence_no": 1, "is_free": "T"},
                {"id": 102, "sequence_no": 2, "is_free": True},
                {"id": 103, "sequence_no": 3, "is_free": 1},
                {"id": 104, "sequence_no": 4, "is_free": "F"},
                {"id": 105, "sequence_no": 5, "is_free": False},
                {"id": 106, "sequence_no": 6, "is_free": 0},
            ]
        }

        with patch.object(self.provider.client.session, "get") as mock_get:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = fixture
            mock_get.return_value = mock_resp

            series = self.provider.load_series("douyin_miniapp:tt5b4d2df0c47bdd2201:888")

            self.assertEqual(len(series.episodes), 6)
            # Tập 1, 2, 3 là Free
            self.assertEqual(series.episodes[0].access_state, ACCESS_STATE_FREE)
            self.assertFalse(series.episodes[0].locked)
            self.assertEqual(series.episodes[1].access_state, ACCESS_STATE_FREE)
            self.assertFalse(series.episodes[1].locked)
            self.assertEqual(series.episodes[2].access_state, ACCESS_STATE_FREE)
            self.assertFalse(series.episodes[2].locked)

            # Tập 4, 5, 6 là VIP
            self.assertEqual(series.episodes[3].access_state, ACCESS_STATE_REQUIRES_VIP)
            self.assertTrue(series.episodes[3].locked)
            self.assertIn("VIP", series.episodes[3].access_reason)
            self.assertEqual(series.episodes[4].access_state, ACCESS_STATE_REQUIRES_VIP)
            self.assertTrue(series.episodes[4].locked)
            self.assertEqual(series.episodes[5].access_state, ACCESS_STATE_REQUIRES_VIP)
            self.assertTrue(series.episodes[5].locked)

    def test_token_minting_error_classification(self):
        """Phân loại lỗi mint token: cookie hết hạn vs lỗi server vs thiếu token."""
        app_id = "tt5b4d2df0c47bdd2201"

        # Trường hợp 1: Cookie hết hạn (không nhận được js_code từ zijieapi)
        with patch.object(self.client.session, "get") as mock_get:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = {"data": {"code": None, "anonymousCode": None}}
            mock_get.return_value = mock_resp

            tok, msg = self.client.mint_token(app_id)
            self.assertIsNone(tok)
            self.assertIn("Cookie hết hạn", msg)

        # Trường hợp 2: Máy chủ login trả về lỗi 401
        with patch.object(self.client.session, "get") as mock_get, \
             patch.object(self.client.session, "post") as mock_post:
            mock_resp1 = MagicMock()
            mock_resp1.status_code = 200
            mock_resp1.json.return_value = {"data": {"code": "valid_js_code_123"}}
            mock_get.return_value = mock_resp1

            mock_resp2 = MagicMock()
            mock_resp2.status_code = 401
            mock_resp2.json.return_value = {"code": 401, "msg": "Tài khoản chưa đăng nhập"}
            mock_post.return_value = mock_resp2

            tok, msg = self.client.mint_token(app_id)
            self.assertIsNone(tok)
            self.assertIn("401", msg)

    def test_cookie_and_token_masking_integrity(self):
        """Khẳng định hàm mask_sensitive che giấu toàn bộ sessionid, uid_tt và duolai token."""
        raw_log = f"User session: {self.raw_cookie} with active token duolai_0123456789abcdef0123456789abcdef"
        masked = mask_sensitive(raw_log)

        # Không được chứa giá trị bí mật thô
        self.assertNotIn("123456789abcdef", masked)
        self.assertNotIn("aabbccddeeff001122", masked)
        self.assertNotIn("sec_999", masked)
        self.assertNotIn("0123456789abcdef0123456789abcdef", masked)

        # Phải chứa dấu hiệu đã che
        self.assertIn("***REDACTED***", masked)


if __name__ == "__main__":
    unittest.main()
