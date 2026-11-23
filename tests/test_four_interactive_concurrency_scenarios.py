"""
tests/test_four_interactive_concurrency_scenarios.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Kiểm tra chi tiết 4 kịch bản tương tác người dùng:
1. Đang load Hongguo -> đổi sang DramaBox (Drop Hongguo, chỉ render DramaBox).
2. Đang load catalog -> nhập từ khóa mới (Drop search cũ, chỉ render kết quả từ khóa mới).
3. Đang load MiniApp -> đồng bộ cookie (Hàng đợi reload kích hoạt ngay sau worker cũ).
4. Resize cửa sổ khi grid đang tải ảnh (Giữ nguyên card instance, cập nhật responsive columns, ảnh nạp đúng vị trí).
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
from PySide6.QtGui import QPixmap
app = QApplication.instance()
if not app:
    app = QApplication(sys.argv)

from providers.base import CatalogItem, CatalogResult
from drama_browse_widget import DramaBrowseWidget, CatalogWorker, DramaCardWidget
from miniapp_browse_widget import MiniAppBrowseWidget, MiniAppCatalogWorker


class TestFourInteractiveConcurrencyScenarios(unittest.TestCase):

    def test_scenario_01_switching_source_while_loading_hongguo_to_dramabox(self):
        """Kịch bản 1: Đang load Hongguo -> đổi sang DramaBox. Drop kết quả Hongguo cũ, chỉ hiển thị DramaBox."""
        with patch.object(CatalogWorker, "start"):
            widget = DramaBrowseWidget()
            try:
                # Bước 1: Bắt đầu nạp Hongguo (gen 1)
                widget._load_catalog(is_append=False)
                hongguo_gen = widget._catalog_gen
                self.assertEqual(widget.cb_platform.currentData(), "hongguo")
                self.assertTrue(widget._is_loading)

                # Bước 2: Người dùng đổi combobox sang DramaBox trong khi worker Hongguo đang chạy
                dramabox_idx = widget.cb_platform.findData("dramabox")
                self.assertGreaterEqual(dramabox_idx, 0)
                widget.cb_platform.setCurrentIndex(dramabox_idx)
                widget._on_platform_changed()

                # Kiểm tra generation tăng và DramaBox được xếp hàng
                self.assertGreater(widget._catalog_gen, hongguo_gen)
                queued_gen = widget._catalog_gen
                self.assertIsNotNone(widget._pending_catalog_request)
                self.assertEqual(widget._pending_catalog_request["source_id"], "dramabox")

                # Bước 3: Worker Hongguo (cũ - gen 1) trả kết quả về sau
                stale_hongguo_items = [
                    CatalogItem(id="hg_1", name="Phim Hongguo Cũ", platform="hongguo", cover="http://img/hg1.jpg"),
                    CatalogItem(id="hg_2", name="Phim Hongguo Cũ 2", platform="hongguo", cover="http://img/hg2.jpg"),
                ]
                widget._on_catalog_ready(hongguo_gen, CatalogResult(items=stale_hongguo_items, total=2, platform="hongguo"))
                widget._on_catalog_worker_finished(hongguo_gen)

                # Xác minh: Kết quả cũ bị drop hoàn toàn, không có card Hongguo nào lọt vào grid
                self.assertEqual(len(widget._cards), 0)
                self.assertEqual(len(widget._loaded_series_ids), 0)

                # Sau khi worker cũ xong, pending request tự động kích hoạt worker cho DramaBox
                dramabox_active_gen = widget._catalog_gen
                self.assertEqual(dramabox_active_gen, queued_gen)
                self.assertTrue(widget._is_loading)

                # Bước 4: Worker DramaBox trả kết quả về
                fresh_dramabox_items = [
                    CatalogItem(id="db_1", name="Love Is A Dangerous Game", platform="dramabox", cover="http://img/db1.jpg", episodes=43),
                    CatalogItem(id="db_2", name="Deny Me, Dragon King", platform="dramabox", cover="http://img/db2.jpg", episodes=50),
                    CatalogItem(id="db_3", name="Tempest: The Last Mecha", platform="dramabox", cover="http://img/db3.jpg", episodes=58),
                ]
                widget._on_catalog_ready(dramabox_active_gen, CatalogResult(items=fresh_dramabox_items, total=3, platform="dramabox"))

                # Xác minh: Chỉ có duy nhất 3 card DramaBox trong grid
                self.assertEqual(len(widget._cards), 3)
                self.assertEqual(widget._cards[0].item.name, "Love Is A Dangerous Game")
                self.assertEqual(widget._cards[1].item.name, "Deny Me, Dragon King")
                self.assertEqual(widget._cards[2].item.name, "Tempest: The Last Mecha")
                self.assertIn("DRAMABOX", widget.lbl_status.text())
                print("[SCENARIO 1 PASS] Đổi nguồn Hongguo -> DramaBox: Bỏ qua kết quả cũ thành công, hiển thị chính xác 3 card DramaBox.")
            finally:
                widget.shutdown()

    def test_scenario_02_new_search_query_while_catalog_loading(self):
        """Kịch bản 2: Đang load catalog -> nhập từ khóa mới. Drop kết quả chung, chỉ hiển thị kết quả tìm kiếm."""
        with patch.object(CatalogWorker, "start"):
            widget = DramaBrowseWidget()
            try:
                # Bước 1: Đang nạp danh mục chung (query rỗng)
                widget.request_catalog_reload(source_id="hongguo", query="", page=1)
                initial_gen = widget._catalog_gen
                self.assertTrue(widget._is_loading)

                # Bước 2: Người dùng gõ từ khóa 'Chiến Thần' và nhấn Enter
                widget.txt_search.setText("Chiến Thần")
                widget._on_search()

                self.assertGreater(widget._catalog_gen, initial_gen)
                self.assertIsNotNone(widget._pending_catalog_request)
                self.assertEqual(widget._pending_catalog_request["query"], "Chiến Thần")

                # Bước 3: Worker ban đầu (query rỗng) trả về 10 phim tổng hợp
                general_items = [CatalogItem(id=f"gen_{i}", name=f"Phim Tổng Hợp {i}", platform="hongguo") for i in range(10)]
                widget._on_catalog_ready(initial_gen, CatalogResult(items=general_items, total=10, platform="hongguo"))
                widget._on_catalog_worker_finished(initial_gen)

                # Xác minh: Toàn bộ phim tổng hợp bị bỏ qua
                self.assertEqual(len(widget._cards), 0)

                # Bước 4: Worker tìm kiếm từ khóa mới trả về 2 phim khớp
                search_gen = widget._catalog_gen
                search_items = [
                    CatalogItem(id="ct_1", name="Chiến Thần Trở Lại", platform="hongguo"),
                    CatalogItem(id="ct_2", name="Chiến Thần Ở Rể", platform="hongguo"),
                ]
                widget._on_catalog_ready(search_gen, CatalogResult(items=search_items, total=2, platform="hongguo"))

                # Xác minh: Chỉ có 2 phim đúng từ khóa xuất hiện
                self.assertEqual(len(widget._cards), 2)
                self.assertEqual(widget._cards[0].item.name, "Chiến Thần Trở Lại")
                self.assertEqual(widget._cards[1].item.name, "Chiến Thần Ở Rể")
                print("[SCENARIO 2 PASS] Tìm kiếm khi đang load: Bỏ qua catalog chung, hiển thị đúng 2 phim tìm kiếm.")
            finally:
                widget.shutdown()

    def test_scenario_03_miniapp_cookie_sync_during_catalog_load(self):
        """Kịch bản 3: Đang load MiniApp -> nhận tín hiệu đồng bộ cookie. Tự động kích hoạt làm mới sau khi worker cũ xong."""
        with patch.object(MiniAppCatalogWorker, "start"):
            widget = MiniAppBrowseWidget()
            try:
                # Bước 1: MiniApp đang tải danh mục
                widget.request_catalog_reload(source_id=widget.get_selected_app_id(), page=1)
                initial_gen = widget._catalog_gen
                self.assertTrue(widget._is_busy)

                # Bước 2: Extension phát tín hiệu đồng bộ cookie mới
                widget.on_cookie_synced(domain="douyin.com", count=15, browser="Chrome")

                self.assertGreater(widget._catalog_gen, initial_gen)
                self.assertIsNotNone(widget._pending_catalog_request)
                self.assertIn("Phiên đã thay đổi", widget._pending_catalog_request.get("reason", ""))
                self.assertIn("Phiên đã thay đổi", widget.lbl_status.text())

                # Bước 3: Worker cũ (chưa có cookie mới) trả về kết quả hoặc lỗi 401
                widget._on_catalog_error(initial_gen, "Lỗi phiên cũ 401")
                widget._on_catalog_worker_finished(initial_gen)

                # Sau khi worker cũ kết thúc, pending request được tự động kích hoạt
                self.assertIsNone(widget._pending_catalog_request)
                refreshed_gen = widget._catalog_gen
                self.assertEqual(refreshed_gen, widget._catalog_gen)

                # Bước 4: Worker mới trả về danh mục với phiên mới
                auth_items = [
                    CatalogItem(id="ma_1", name="MiniApp Phim Mới 1", platform="miniapp_douyin"),
                    CatalogItem(id="ma_2", name="MiniApp Phim Mới 2", platform="miniapp_douyin"),
                ]
                widget._on_catalog_ready(refreshed_gen, CatalogResult(items=auth_items, total=2, platform="miniapp_douyin"))

                self.assertEqual(len(widget._cards), 2)
                self.assertEqual(widget._cards[0].item.name, "MiniApp Phim Mới 1")
                print("[SCENARIO 3 PASS] Đồng bộ cookie khi worker MiniApp đang bận: Tự động kích hoạt nạp lại với phiên mới thành công.")
            finally:
                if hasattr(widget, "shutdown"):
                    widget.shutdown()

    def test_scenario_04_window_resize_during_thumbnail_loading(self):
        """Kịch bản 4: Resize cửa sổ khi grid đang tải ảnh. Giữ nguyên card instance, cập nhật responsive columns và nhận ảnh chuẩn xác."""
        with patch.object(CatalogWorker, "start"):
            widget = DramaBrowseWidget()
            try:
                # Nạp 8 phim có URL poster
                items = [
                    CatalogItem(id=f"card_{i}", name=f"Drama Poster {i}", platform="dramabox", cover=f"http://cdn/cover_{i}.jpg")
                    for i in range(8)
                ]
                widget._on_catalog_ready(widget._catalog_gen, CatalogResult(items=items, total=8, platform="dramabox"))

                self.assertEqual(len(widget._cards), 8)
                initial_card_ids = [id(c) for c in widget._cards]

                # Bước 1: Màn hình 1000px -> số cột tương ứng
                widget.resize(1000, 700)
                widget.scroll_area.viewport().resize(960, 600)
                widget._relayout_cards(force=True)
                cols_1000 = widget._calculate_columns()
                self.assertGreaterEqual(cols_1000, 4)

                # Bước 2: Resize mở rộng lên 1600px (Full Width)
                widget.resize(1600, 900)
                widget.scroll_area.viewport().resize(1550, 800)
                widget._relayout_cards(force=True)
                cols_1600 = widget._calculate_columns()
                self.assertGreater(cols_1600, cols_1000, "1600px phải có nhiều cột hơn 1000px để dàn trải đều")

                # Xác minh: Tất cả card instance được giữ nguyên 100%, không bị hủy hay tạo lại
                self.assertEqual([id(c) for c in widget._cards], initial_card_ids)

                # Bước 3: Giả lập ảnh poster tải về sau khi resize
                dummy_pixmap = QPixmap(152, 195)
                self.assertFalse(dummy_pixmap.isNull())

                for card in widget._cards:
                    card._on_thumb_loaded(dummy_pixmap)
                    self.assertFalse(card.lbl_thumb.pixmap().isNull(), "Card phải hiển thị đúng pixmap đã nạp")

                # Bước 4: Resize thu hẹp về 800px
                widget.resize(800, 600)
                widget.scroll_area.viewport().resize(760, 500)
                widget._relayout_cards(force=True)
                cols_800 = widget._calculate_columns()
                self.assertLess(cols_800, cols_1600)
                self.assertGreaterEqual(cols_800, 4)

                # Xác minh: Card instance vẫn nguyên vẹn và pixmap không bị mất
                self.assertEqual([id(c) for c in widget._cards], initial_card_ids)
                for card in widget._cards:
                    self.assertFalse(card.lbl_thumb.pixmap().isNull(), "Pixmap không được phép bị mất khi resize")

                print(f"[SCENARIO 4 PASS] Resize khi tải ảnh: Columns co giãn chuẩn (800px={cols_800} cols, 1000px={cols_1000} cols, 1600px={cols_1600} cols), 100% card & pixmap nguyên vẹn.")
            finally:
                widget.shutdown()


if __name__ == "__main__":
    unittest.main()
