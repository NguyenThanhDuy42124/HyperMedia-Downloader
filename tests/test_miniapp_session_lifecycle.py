"""
tests/test_miniapp_session_lifecycle.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Kiểm thử toàn diện 17 kịch bản vòng đời phiên MiniApp Douyin (Cookie Sync & Session Lifecycle):
 1. Yêu cầu đồng bộ gửi kèm request_id duy nhất.
 2. Extension phản hồi thành công và phát tín hiệu miniapp_sync_received.
 3. Extension không phản hồi -> Timeout 8s kích hoạt SESSION_STATE_SYNC_TIMEOUT.
 4. Nhận 0 cookie -> Xử lý thất bại tức thì, không treo chờ 8s.
 5. Lưu phiên DPAPI thành công và phát tín hiệu miniapp_sync_saved.
 6. Xử lý an toàn khi payload DPAPI lỗi / corrupt.
 7. Có cookie nhưng mint token thất bại (expired_cookie / mint_invalid_response).
 8. Mint token thành công -> Chuyển trạng thái SESSION_STATE_AUTHENTICATED.
 9. load_playlist() dừng ngay khi không có token (CẤM fallback token rỗng gọi API).
10. Playlist HTTP 401 hiển thị lỗi thân thiện, bật btn_reauth, không block UI.
11. Playlist thành công sau khi đồng bộ hợp lệ và giải mã dữ liệu.
12. Log Drawer ghi nhận đầy đủ các mốc vòng đời phiên.
13. Không rò rỉ cookie, token, sessionid hay uid_tt trong log (che giấu qua sanitize_log_text & mask_sensitive).
14. Badge KHÔNG hiển thị "Đã kết nối" khi mới chỉ lưu cookie mà chưa validate token.
15. Danh mục phim công khai (public catalog) hoạt động bình thường khi chưa đăng nhập.
16. Đồng bộ phiên khi danh mục đang tải không làm mất yêu cầu danh mục.
17. Không xảy ra vòng lặp vô tận (infinite retry loop) khi gặp lỗi 401.
"""

import os
import sys
import time
import json
import unittest
from unittest.mock import MagicMock, patch

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication

app = QApplication.instance()
if not app:
    app = QApplication(sys.argv)

from local_server import LocalServer
from providers.miniapp_douyin_client import (
    MiniAppDouyinClient,
    clear_douyin_session,
    save_douyin_session,
    load_douyin_session,
    get_douyin_session_status,
    mask_sensitive,
    SESSION_STATE_NO_SESSION,
    SESSION_STATE_COOKIE_STORED,
    SESSION_STATE_SYNC_REQUESTED,
    SESSION_STATE_SYNC_RECEIVED,
    SESSION_STATE_AUTHENTICATING,
    SESSION_STATE_AUTHENTICATED,
    SESSION_STATE_SESSION_EXPIRED,
    SESSION_STATE_AUTH_FAILED,
    SESSION_STATE_SYNC_TIMEOUT,
)
from providers.miniapp_douyin_provider import MiniAppDouyinProvider
from miniapp_browse_widget import MiniAppBrowseWidget
from ca_bundle_utils import sanitize_log_text


class TestMiniAppSessionLifecycle(unittest.TestCase):
    def setUp(self):
        clear_douyin_session()
        self.widget = MiniAppBrowseWidget()
        self.widget.show()

    def tearDown(self):
        if hasattr(self, "widget") and self.widget:
            self.widget.shutdown()
            self.widget.deleteLater()
        clear_douyin_session()

    def test_01_sync_request_sent_with_request_id(self):
        """1. Yêu cầu đồng bộ gửi kèm request_id duy nhất và emit miniapp_sync_started."""
        server = LocalServer()
        started_events = []
        server.miniapp_sync_started.connect(lambda req_id, br: started_events.append((req_id, br)))

        server.request_miniapp_douyin_cookie_refresh(force=True, request_id="req_sync_test_01")
        self.assertEqual(server._current_miniapp_sync_id, "req_sync_test_01")
        self.assertEqual(len(started_events), 1)
        self.assertEqual(started_events[0][0], "req_sync_test_01")

    def test_02_extension_response_received_successfully(self):
        """2. Extension phản hồi thành công và phát tín hiệu miniapp_sync_received."""
        server = LocalServer()
        received_events = []
        server.miniapp_sync_received.connect(lambda req_id, count, br: received_events.append((req_id, count, br)))

        handler_cls = server._create_handler()
        mock_handler = MagicMock()
        mock_handler.headers = {"User-Agent": "Mozilla/5.0 Chrome/131.0"}

        data = {
            "provider": "miniapp_douyin",
            "domain": "douyin.com",
            "sync_request_id": "req_sync_test_02",
            "cookies": [{"name": "sessionid", "value": "test_tok_123"}],
        }

        handler_cls._handle_miniapp_cookie_sync(mock_handler, data)
        mock_handler.send_response.assert_called_with(200)
        self.assertEqual(len(received_events), 1)
        self.assertEqual(received_events[0][0], "req_sync_test_02")
        self.assertEqual(received_events[0][1], 1)

    def test_03_extension_no_response_timeout_8s(self):
        """3. Extension không phản hồi -> Timeout 8s kích hoạt SESSION_STATE_SYNC_TIMEOUT."""
        self.widget._is_syncing = True
        self.widget.btn_sync.setEnabled(False)
        self.widget.set_session_state(SESSION_STATE_SYNC_REQUESTED)

        # Kích hoạt timeout trực tiếp
        self.widget._on_sync_timer_timeout()

        self.assertFalse(self.widget._is_syncing)
        self.assertTrue(self.widget.btn_sync.isEnabled())
        self.assertEqual(self.widget._session_state, SESSION_STATE_SYNC_TIMEOUT)
        self.assertIn("Không nhận được phản hồi", self.widget.lbl_status.text())

    def test_04_zero_cookies_received_handled_as_failed(self):
        """4. Nhận 0 cookie -> Xử lý thất bại tức thì, không treo chờ 8s."""
        self.widget._is_syncing = True
        self.widget.btn_sync.setEnabled(False)

        # Giả lập nhận 0 cookie từ Extension
        self.widget.on_miniapp_sync_received("req_04", 0, "Chrome")

        self.assertFalse(self.widget._is_syncing)
        self.assertTrue(self.widget.btn_sync.isEnabled())
        self.assertEqual(self.widget._session_state, SESSION_STATE_AUTH_FAILED)
        self.assertIn("Không tìm thấy cookie", self.widget.lbl_status.text())

    def test_05_dpapi_save_succeeds(self):
        """5. Lưu phiên DPAPI thành công và phát tín hiệu miniapp_sync_saved."""
        server = LocalServer()
        saved_events = []
        server.miniapp_sync_saved.connect(lambda req_id, count: saved_events.append((req_id, count)))

        handler_cls = server._create_handler()
        mock_handler = MagicMock()
        mock_handler.headers = {"User-Agent": "Mozilla/5.0 Chrome/131.0"}

        data = {
            "provider": "miniapp_douyin",
            "domain": "douyin.com",
            "sync_request_id": "req_05",
            "cookies": [{"name": "sessionid", "value": "valid_sess_123"}],
        }

        handler_cls._handle_miniapp_cookie_sync(mock_handler, data)
        self.assertEqual(len(saved_events), 1)
        self.assertEqual(saved_events[0][0], "req_05")
        self.assertEqual(saved_events[0][1], 1)

        # Kiểm tra file đã được lưu trong DPAPI
        sess = load_douyin_session()
        self.assertIsNotNone(sess)
        self.assertIn("sessionid=valid_sess_123", sess["cookie_str"])

    def test_06_dpapi_save_fails_corrupt_data(self):
        """6. Xử lý an toàn khi payload DPAPI lỗi / corrupt."""
        ok, msg = save_douyin_session(None)
        self.assertFalse(ok)
        self.assertTrue("không hợp lệ" in msg.lower() or "dict" in msg.lower())

        ok2, msg2 = save_douyin_session({"provider": "unknown_provider"})
        self.assertFalse(ok2)

        ok3, msg3 = save_douyin_session({"provider": "miniapp_douyin", "domain": "malicious.com"})
        self.assertFalse(ok3)

    def test_07_cookies_present_but_token_minting_fails(self):
        """7. Có cookie nhưng mint token thất bại (expired_cookie / mint_invalid_response)."""
        save_douyin_session({
            "provider": "miniapp_douyin",
            "domain": "douyin.com",
            "cookies": [{"name": "sessionid", "value": "expired_session_123"}],
        })

        client = MiniAppDouyinClient()

        # Mock ma.zijieapi.com trả về không có code (cookie hết hạn)
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"data": {"code": ""}}

        with patch.object(client.session, "get", return_value=mock_resp):
            tok, msg = client.mint_token("1128", force=True)
            self.assertIsNone(tok)
            self.assertIn("expired_cookie", msg)

            ok, val_msg = client.validate_session("1128")
            self.assertFalse(ok)
            self.assertIn("expired_cookie", val_msg)

    def test_08_token_minting_succeeds(self):
        """8. Mint token thành công -> Chuyển trạng thái SESSION_STATE_AUTHENTICATED."""
        save_douyin_session({
            "provider": "miniapp_douyin",
            "domain": "douyin.com",
            "cookies": [{"name": "sessionid", "value": "live_session_999"}],
        })

        client = MiniAppDouyinClient()

        # Mock zijieapi (code) và lizhibj (token)
        mock_r1 = MagicMock()
        mock_r1.status_code = 200
        mock_r1.json.return_value = {"data": {"code": "mock_code_123"}}

        mock_r2 = MagicMock()
        mock_r2.status_code = 200
        mock_r2.json.return_value = {"data": {"token": "duolai_test_minted_token"}}

        with patch.object(client.session, "get", return_value=mock_r1):
            with patch.object(client.session, "post", return_value=mock_r2):
                tok, msg = client.mint_token("1128", force=True)
                self.assertEqual(tok, "duolai_test_minted_token")
                self.assertEqual(msg, "OK")

                ok, val_msg = client.validate_session("1128")
                self.assertTrue(ok)

                # Test widget transition
                self.widget._on_validation_done("req_08", True, "OK")
                self.assertEqual(self.widget._session_state, SESSION_STATE_AUTHENTICATED)
                self.assertEqual(self.widget.lbl_session.text(), "Đã kết nối")

    def test_09_load_playlist_aborts_on_empty_token(self):
        """9. load_playlist() dừng ngay khi không có token (CẤM fallback token rỗng gọi API)."""
        client = MiniAppDouyinClient()

        # Mock mint_token trả về None
        with patch.object(client, "mint_token", return_value=(None, "missing_cookie: Thiếu cookie Douyin")):
            with patch.object(client.session, "get") as mock_get:
                eps, err = client.load_playlist("tt001", "col_123")
                self.assertEqual(eps, [])
                self.assertIn("Không thể xác thực phiên MiniApp Douyin", err)
                # Đảm bảo KHÔNG gọi session.get với token rỗng
                mock_get.assert_not_called()

    def test_10_playlist_http_401_triggers_reauth_ui(self):
        """10. Playlist HTTP 401 hiển thị lỗi thân thiện, bật btn_reauth, không block UI."""
        client = MiniAppDouyinClient()

        # Mock mint_token thành công nhưng API play_list trả 401
        with patch.object(client, "mint_token", return_value=("mock_token_abc", "OK")):
            mock_resp = MagicMock()
            mock_resp.status_code = 401
            with patch.object(client.session, "get", return_value=mock_resp):
                eps, err = client.load_playlist("tt001", "col_123")
                self.assertEqual(eps, [])
                self.assertIn("playlist_http_401", err)

                # Widget tiếp nhận lỗi 401
                self.widget._detail_gen = 5
                self.widget._on_series_error(5, err)

                self.assertEqual(self.widget._session_state, SESSION_STATE_SESSION_EXPIRED)
                self.assertFalse(self.widget.btn_reauth.isHidden())
                self.assertTrue(self.widget.btn_retry.isHidden())
                self.assertIn("Phiên cần xác thực lại", self.widget.lbl_status.text())

    def test_11_playlist_succeeds_after_valid_sync(self):
        """11. Playlist thành công sau khi đồng bộ hợp lệ và giải mã dữ liệu."""
        client = MiniAppDouyinClient()

        raw_playlist_data = [
            {"episode_id": "ep1", "num": 1, "title": "Tập 1", "is_free": 1},
            {"episode_id": "ep2", "num": 2, "title": "Tập 2", "is_free": 1},
        ]

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"data": raw_playlist_data}

        with patch.object(client, "mint_token", return_value=("valid_tok", "OK")):
            with patch.object(client.session, "get", return_value=mock_resp):
                eps, err = client.load_playlist("tt001", "col_123")
                self.assertIsNone(err)
                self.assertEqual(len(eps), 2)
                self.assertEqual(eps[0]["title"], "Tập 1")

    def test_12_log_drawer_receives_all_lifecycle_events(self):
        """12. Log Drawer ghi nhận đầy đủ các mốc vòng đời phiên."""
        log_records = []
        with patch.object(self.widget.log_drawer, "log_info", side_effect=lambda m: log_records.append(m)):
            with patch.object(self.widget.log_drawer, "log_error", side_effect=lambda m: log_records.append(m)):
                self.widget.log_info("[INFO] Bắt đầu đồng bộ phiên Douyin")
                self.widget.log_info("[INFO] Đã gửi yêu cầu Extension, request_id=test_12")
                self.widget.on_miniapp_sync_saved("test_12", 2)
                self.widget._on_validation_done("test_12", True, "OK")

        text = "\n".join(log_records)
        self.assertIn("Bắt đầu đồng bộ phiên Douyin", text)
        self.assertIn("request_id=test_12", text)
        self.assertIn("Session DPAPI đã lưu thành công", text)
        self.assertIn("Mint token thành công", text)
        self.assertIn("Session MiniApp đã xác thực", text)

    def test_13_zero_cookie_token_leakage_in_logs(self):
        """13. Không rò rỉ cookie, token, sessionid hay uid_tt trong log (che giấu qua sanitize_log_text & mask_sensitive)."""
        raw_log = (
            "Sent: sessionid=secret_session_val; "
            "token=duolai_sensitive_token_999; "
            "uid_tt=123456789; "
            "passport_csrf_token=csrf_secret; "
            "Authorization: Bearer duolai_auth_token"
        )
        cleaned = sanitize_log_text(raw_log)
        self.assertNotIn("secret_session_val", cleaned)
        self.assertNotIn("duolai_sensitive_token_999", cleaned)
        self.assertNotIn("123456789", cleaned)
        self.assertNotIn("csrf_secret", cleaned)
        self.assertNotIn("duolai_auth_token", cleaned)
        self.assertIn("sessionid=***", cleaned)
        self.assertIn("token=***", cleaned)

        # Kiểm tra thêm qua mask_sensitive
        masked_ms = mask_sensitive(raw_log)
        self.assertNotIn("secret_session_val", masked_ms)
        self.assertNotIn("duolai_sensitive_token_999", masked_ms)
        self.assertIn("sessionid=***REDACTED***", masked_ms)

    def test_14_badge_does_not_display_connected_before_token_validation(self):
        """14. Badge KHÔNG hiển thị 'Đã kết nối' khi mới chỉ lưu cookie mà chưa validate token."""
        save_douyin_session({
            "provider": "miniapp_douyin",
            "domain": "douyin.com",
            "cookies": [{"name": "sessionid", "value": "unvalidated_sess"}],
        })

        client = MiniAppDouyinClient()
        code, msg = get_douyin_session_status(client=client, check_mint=False)
        self.assertEqual(code, SESSION_STATE_COOKIE_STORED)
        self.assertNotEqual(code, SESSION_STATE_AUTHENTICATED)

        self.widget.set_session_state(code)
        self.assertEqual(self.widget.lbl_session.text(), "Đã lưu cookie")
        self.assertNotEqual(self.widget.lbl_session.text(), "Đã kết nối")

    def test_15_public_catalog_works_without_session(self):
        """15. Danh mục phim công khai (public catalog) hoạt động bình thường khi chưa đăng nhập."""
        clear_douyin_session()
        client = MiniAppDouyinClient()

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "data": [
                {"collection_id": "c1", "title": "Phim Public 1", "cover": "http://img1.jpg"},
                {"collection_id": "c2", "title": "Phim Public 2", "cover": "http://img2.jpg"},
            ]
        }

        with patch.object(client.session, "get", return_value=mock_resp):
            items, has_more, err = client.browse_catalog("tt_demo", page=1)
            self.assertIsNone(err)
            self.assertEqual(len(items), 2)
            self.assertEqual(items[0]["title"], "Phim Public 1")

    def test_16_syncing_while_catalog_loading_preserves_requests(self):
        """16. Đồng bộ phiên khi danh mục đang tải không làm mất yêu cầu danh mục."""
        self.widget.request_catalog_reload(page=1, append=False, reason="Test concurrent sync")
        self.assertTrue(self.widget.catalog_worker.isRunning())

        # Kích hoạt sync khi catalog worker đang chạy
        with patch.object(self.widget, "_connect_server_signals"):
            mock_server = MagicMock()
            mock_server.is_extension_connected.return_value = True
            with patch("miniapp_browse_widget.getattr", return_value=mock_server):
                self.widget._on_sync_clicked()
                self.assertTrue(self.widget._is_syncing)

        # Catalog worker vẫn đang chạy bình thường
        self.assertIsNotNone(self.widget.catalog_worker)

    def test_17_no_infinite_retry_loop_on_401(self):
        """17. Không xảy ra vòng lặp vô tận (infinite retry loop) khi gặp lỗi 401."""
        self.widget._detail_gen = 1
        with patch.object(self.widget, "_fetch_series_detail") as mock_fetch:
            # Gặp lỗi 401
            self.widget._on_series_error(1, "playlist_http_401: Phiên không hợp lệ hoặc hết hạn (HTTP 401)")
            # Xác nhận dừng lại ở UI hướng dẫn, không tự động trigger retry fetch
            mock_fetch.assert_not_called()
            self.assertFalse(self.widget.btn_reauth.isHidden())


if __name__ == "__main__":
    unittest.main()
