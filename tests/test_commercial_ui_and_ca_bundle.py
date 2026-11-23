"""
tests/test_commercial_ui_and_ca_bundle.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Kiểm thử tự động cho toàn bộ cải tiến UX/UI thương mại & TLS CA Bundle:
1. Infinite scroll: tự động nạp batch mới khi cuộn gần cuối viewport.
2. Chống request trùng lặp khi cuộn nhanh (Concurrency guard).
3. Append thẻ mới không trùng ID (Deduplication).
4. Dừng khi hết dữ liệu (has_more = False).
5. Hiển thị đúng trạng thái rỗng / lỗi / spinner qua EmptyStateWidget.
6. Nút 'Thử lại' kích hoạt lại luồng nạp sau lỗi.
7. CA bundle helper: trả về path thật hoặc True, không trả path rỗng/hỏng.
8. Requests không bao giờ nhận path certifi sai.
9. Bảo mật: Che giấu tuyệt đối _MEIPASS, cookie, sessionid, token trong log và UI.
10. Progressive disclosure: Ẩn các trường kỹ thuật nội bộ (app_id, raw endpoints) khỏi UI chính.
11. Design system: Chiều cao nút, màu sắc chuẩn mực (Primary blue, Secondary slate, Danger red).
12. Resize giữ nguyên toàn bộ số lượng thẻ phim đã nạp.
"""

import os
import sys
import unittest
from unittest.mock import MagicMock, patch

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from PySide6.QtWidgets import QApplication
app = QApplication.instance()
if not app:
    app = QApplication(sys.argv)

from ca_bundle_utils import (
    get_ca_bundle_path,
    setup_ca_bundle_env,
    sanitize_error_message,
    sanitize_log_text,
)
from empty_state_widget import EmptyStateWidget
from log_drawer_widget import LogDrawerWidget
from drama_browse_widget import DramaBrowseWidget, CatalogWorker
from miniapp_browse_widget import MiniAppBrowseWidget, MiniAppCatalogWorker
from providers.base import CatalogItem, CatalogResult


class TestCommercialUIAndCABundle(unittest.TestCase):

    def test_ca_bundle_helper_safety(self):
        """Xác minh get_ca_bundle_path không bao giờ trả về file path không tồn tại."""
        path_or_bool = get_ca_bundle_path()
        if isinstance(path_or_bool, str):
            self.assertTrue(os.path.isfile(path_or_bool), f"Path CA không tồn tại: {path_or_bool}")
        else:
            self.assertIs(path_or_bool, True, "Fallback CA phải là True")

    def test_setup_ca_bundle_env_cleans_invalid_vars(self):
        """Xác minh setup_ca_bundle_env gỡ bỏ biến môi trường trỏ vào file giả mạo."""
        os.environ["REQUESTS_CA_BUNDLE"] = r"C:\fake_dir\_MEI99999\certifi\cacert.pem"
        setup_ca_bundle_env()
        val = os.environ.get("REQUESTS_CA_BUNDLE")
        if val:
            self.assertTrue(os.path.isfile(val), f"REQUESTS_CA_BUNDLE vẫn trỏ vào path không tồn tại: {val}")

    def test_setup_ca_bundle_env_when_fallback_true_pops_env(self):
        """Xác minh khi get_ca_bundle_path trả về True, setup_ca_bundle_env loại bỏ REQUESTS_CA_BUNDLE, không ghi 'True'."""
        with patch("ca_bundle_utils.get_ca_bundle_path", return_value=True):
            os.environ["REQUESTS_CA_BUNDLE"] = "some_invalid_val"
            os.environ["CURL_CA_BUNDLE"] = "some_invalid_val"
            os.environ["SSL_CERT_FILE"] = "some_invalid_val"
            setup_ca_bundle_env()
            self.assertNotIn("REQUESTS_CA_BUNDLE", os.environ, "Biến REQUESTS_CA_BUNDLE phải bị xóa khi ca_path là True")
            self.assertNotIn("CURL_CA_BUNDLE", os.environ)
            self.assertNotIn("SSL_CERT_FILE", os.environ)

    def test_sanitize_log_and_error_masks_secrets_and_meipass(self):
        """Xác minh lọc sạch _MEIPASS và che token/cookie trong thông điệp."""
        raw_msg = (
            r"Error at C:\Users\Admin\AppData\Local\Temp\_MEI123452\certifi\cacert.pem: "
            r"sessionid=abcdef123456; passport_csrf_token=sec987654; Bearer eyJhbGciOi..."
        )
        sanitized = sanitize_log_text(raw_msg)
        self.assertNotIn("_MEI123452", sanitized)
        self.assertIn("[APP_DIR]", sanitized)
        self.assertIn("sessionid=***", sanitized)
        self.assertIn("passport_csrf_token=***", sanitized)
        self.assertIn("Bearer ***", sanitized)

        # Lỗi TLS kỹ thuật được chuyển thành thông điệp thân thiện
        tls_err = "SSLError(Could not find a suitable TLS CA certificate bundle invalid path: .../cacert.pem)"
        friendly = sanitize_error_message(tls_err)
        self.assertIn("Không thể xác minh chứng chỉ máy chủ", friendly)
        self.assertNotIn("SSLError", friendly)

    def test_empty_state_widget_states(self):
        """Xác minh EmptyStateWidget hiển thị đúng nội dung theo từng trạng thái."""
        widget = EmptyStateWidget()
        widget.show_loading("Đang nạp...", "Vui lòng chờ")
        self.assertIn("Đang nạp...", widget.lbl_title.text())
        self.assertFalse(widget.btn_action.isVisible())

        callback_mock = MagicMock()
        widget.show_error("Máy chủ bận", "Thử lại sau", callback=callback_mock)
        self.assertTrue(widget.btn_action.isVisible())
        self.assertEqual(widget.btn_action.text(), "Thử lại")
        widget.btn_action.click()
        callback_mock.assert_called_once()

    def test_log_drawer_levels_and_clearing(self):
        """Xác minh LogDrawerWidget lưu trữ, lọc và xóa nhật ký chính xác."""
        drawer = LogDrawerWidget("Test Drawer")
        drawer.log_info("Thông tin phiên làm việc")
        drawer.log_warn("Cảnh báo bộ nhớ tạm")
        drawer.log_error("Lỗi HTTP 500")

        self.assertEqual(len(drawer.log_entries), 3)
        drawer.cb_filter.setCurrentText("Lỗi")
        self.assertIn("Lỗi HTTP 500", drawer.txt_log.toHtml())
        self.assertNotIn("Thông tin phiên làm việc", drawer.txt_log.toPlainText())

        drawer.clear_logs()
        self.assertEqual(len(drawer.log_entries), 0)

    def test_drama_infinite_scroll_and_deduplication(self):
        """Xác minh DramaBrowseWidget tự động append batch mới và chống duplicate ID."""
        with patch.object(CatalogWorker, "start"):
            widget = DramaBrowseWidget()
            try:
                # Batch 1
                items_p1 = [
                    CatalogItem(id="p1", name="Phim 1", platform="hongguo"),
                    CatalogItem(id="p2", name="Phim 2", platform="hongguo"),
                ]
                res1 = CatalogResult(items=items_p1, total=4, has_more=True, platform="hongguo")
                widget._on_catalog_ready(widget._catalog_gen, res1)

                self.assertEqual(len(widget._cards), 2)
                self.assertEqual(len(widget._loaded_series_ids), 2)
                self.assertTrue(widget._has_more)
                self.assertFalse(widget.btn_load_more_footer.isHidden(), "Nút tải thêm phải không bị hidden khi has_more=True")

                # Giả lập cuộn gần cuối viewport kích hoạt load batch 2
                widget._is_loading = False
                widget.current_page = 1
                widget.scroll_area.verticalScrollBar().setRange(0, 1000)
                widget._on_scroll_changed(900)  # maximum threshold
                self.assertEqual(widget.current_page, 2, "Trang phải tăng lên 2 khi cuộn")

                # Batch 2 trả về p2 (bị trùng) và p3, p4 (mới)
                items_p2 = [
                    CatalogItem(id="p2", name="Phim 2 trùng", platform="hongguo"),
                    CatalogItem(id="p3", name="Phim 3", platform="hongguo"),
                    CatalogItem(id="p4", name="Phim 4", platform="hongguo"),
                ]
                res2 = CatalogResult(items=items_p2, total=4, has_more=False, platform="hongguo")
                widget._on_catalog_ready(widget._catalog_gen, res2)

                # Tổng số card phải là 4 (p1, p2, p3, p4), không bị duplicate p2
                self.assertEqual(len(widget._cards), 4)
                self.assertEqual(len(widget._loaded_series_ids), 4)
                self.assertFalse(widget._has_more)
                self.assertTrue(widget.btn_load_more_footer.isHidden(), "Hết has_more phải ẩn nút tải thêm")
                self.assertIn("Đã hiển thị 4 / 4 phim", widget.lbl_status.text())
            finally:
                widget.shutdown()

    def test_miniapp_concurrency_guard_and_retry(self):
        """Xác minh MiniAppBrowseWidget chặn request đồng thời khi đang tải và cho phép thử lại."""
        with patch.object(MiniAppCatalogWorker, "start"):
            widget = MiniAppBrowseWidget()
            try:
                widget._is_busy = True
                prev_gen = widget._catalog_gen
                # Khi đang busy, gọi load_catalog không được tăng generation hay gửi request mới
                widget.load_catalog(is_append=True)
                self.assertEqual(widget._catalog_gen, prev_gen, "Không được kích hoạt request mới khi đang busy")

                # Giả lập lỗi và kiểm tra trạng thái Error
                widget._is_busy = False
                res_err = CatalogResult(error="Connection aborted", items=[], total=0, platform="miniapp_douyin")
                widget._on_catalog_ready(widget._catalog_gen, res_err, is_append=False)

                self.assertFalse(widget.empty_state.isHidden())
                self.assertFalse(widget.empty_state.btn_action.isHidden())
            finally:
                if hasattr(widget, "shutdown"):
                    widget.shutdown()

    def test_button_design_system_consistency(self):
        """Xác minh nút bấm tuân thủ kích thước và màu sắc của Design System."""
        with patch.object(CatalogWorker, "start"), patch.object(MiniAppCatalogWorker, "start"):
            drama_w = DramaBrowseWidget()
            miniapp_w = MiniAppBrowseWidget()
            try:
                # Kiểm tra chiều cao nút chính 32-34px
                self.assertEqual(drama_w.btn_search.height(), 34)
                self.assertEqual(drama_w.btn_refresh.height(), 34)
                self.assertEqual(drama_w.btn_load_more_footer.height(), 30)
                self.assertEqual(drama_w.btn_log.height(), 30)

                self.assertEqual(miniapp_w.btn_sync.height(), 32)
                self.assertEqual(miniapp_w.btn_clear_sess.height(), 32)
                self.assertEqual(miniapp_w.btn_search.height(), 34)
                self.assertEqual(miniapp_w.btn_refresh.height(), 34)

                # Nút đồng bộ phiên mang nhãn chuẩn và không dùng màu hồng sặc sỡ
                self.assertEqual(miniapp_w.btn_sync.text(), " Đồng bộ phiên")
                self.assertNotIn("#ec4899", miniapp_w.btn_sync.styleSheet())
            finally:
                drama_w.shutdown()
                if hasattr(miniapp_w, "shutdown"):
                    miniapp_w.shutdown()

    def test_resize_preserves_cards_without_loss(self):
        """Xác minh resize cửa sổ không làm mất thẻ phim đã nạp."""
        with patch.object(CatalogWorker, "start"):
            widget = DramaBrowseWidget()
            try:
                items = [CatalogItem(id=f"c_{i}", name=f"Card {i}", platform="hongguo") for i in range(12)]
                res = CatalogResult(items=items, total=12, has_more=False, platform="hongguo")
                widget._on_catalog_ready(widget._catalog_gen, res)
                self.assertEqual(len(widget._cards), 12)

                # Thay đổi kích thước sang 1280px -> 1920px -> 800px
                widget.resize(1280, 800)
                widget._relayout_cards(force=True)
                self.assertEqual(len(widget._cards), 12)
                self.assertEqual(widget.grid_layout.count(), 12)

                widget.resize(1920, 1080)
                widget._relayout_cards(force=True)
                self.assertEqual(len(widget._cards), 12)
                self.assertEqual(widget.grid_layout.count(), 12)

                widget.resize(800, 600)
                widget._relayout_cards(force=True)
                self.assertEqual(len(widget._cards), 12)
                self.assertEqual(widget.grid_layout.count(), 12)
            finally:
                widget.shutdown()


if __name__ == "__main__":
    unittest.main()
