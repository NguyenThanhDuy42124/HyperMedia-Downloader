"""
tests/test_responsive_ui_and_provider_priority.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Kiểm tra tự động các tối ưu hóa giao diện:
1. Hongguo được ưu tiên lên đầu (vị trí số 1 trong danh sách Provider).
2. Layout card phim tự động co giãn/dàn trải theo độ rộng màn hình (Responsive Grid).
3. Hộp thoại chọn tập phân bổ dạng lưới 5 cột (Decimal Decade: 1-5, 6-10...) dàn trải đều.
4. Toàn bộ các ứng dụng/nền tảng phim ngắn tuân thủ kiến trúc Free-first mức độ miễn phí.
"""

import os
import sys
import unittest
from unittest.mock import MagicMock, patch

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# Configure offscreen Qt platform before importing Qt widgets
os.environ["QT_QPA_PLATFORM"] = "offscreen"

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from PySide6.QtWidgets import QApplication

app = QApplication.instance()
if not app:
    app = QApplication(sys.argv)

import providers
from providers.base import (
    Series,
    Episode,
    ACCESS_STATE_FREE,
    ACCESS_STATE_REQUIRES_VIP,
)
from drama_browse_widget import DramaBrowseWidget, CatalogWorker
from miniapp_browse_widget import MiniAppBrowseWidget, MiniAppCatalogWorker
from drama_dialog import DramaEpisodeDialog
from miniapp_episode_dialog import MiniAppEpisodeDialog


class TestResponsiveUIAndProviderPriority(unittest.TestCase):

    def test_hongguo_is_first_active_provider(self):
        """Xác minh Hongguo đứng vị trí đầu tiên trong danh sách ACTIVE_PROVIDERS."""
        active = providers.get_active_providers()
        self.assertGreater(len(active), 0)
        self.assertEqual(active[0].platform_id, "hongguo", "Hongguo phải là provider đầu tiên trong ACTIVE_PROVIDERS")

    def test_drama_browse_widget_defaults_to_hongguo(self):
        """Xác minh DramaBrowseWidget tự động chọn Hongguo làm nguồn mặc định ở vị trí đầu."""
        with patch.object(CatalogWorker, "start"):
            widget = DramaBrowseWidget()
            try:
                self.assertEqual(widget.cb_platform.itemData(0), "hongguo")
                self.assertEqual(widget.cb_platform.currentData(), "hongguo")
            finally:
                widget.shutdown()

    def test_drama_browse_widget_responsive_columns(self):
        """Xác minh hàm tính toán số cột card co giãn dàn trải theo chiều rộng màn hình."""
        with patch.object(CatalogWorker, "start"):
            widget = DramaBrowseWidget()
            try:
                # Giả lập màn hình hẹp (800px)
                widget.scroll_area.viewport().resize(800, 600)
                cols_narrow = widget._calculate_columns()
                self.assertGreaterEqual(cols_narrow, 4)

                # Giả lập màn hình rộng Full HD (1800px)
                widget.scroll_area.viewport().resize(1800, 900)
                cols_wide = widget._calculate_columns()
                self.assertGreater(cols_wide, cols_narrow, "Màn hình rộng phải hiển thị nhiều cột card hơn để dàn trải")
                self.assertLessEqual(cols_wide, 10)
            finally:
                widget.shutdown()

    def test_miniapp_browse_widget_responsive_columns(self):
        """Xác minh MiniAppBrowseWidget cũng co giãn số cột card tự động theo chiều rộng màn hình."""
        with patch.object(MiniAppCatalogWorker, "start"):
            widget = MiniAppBrowseWidget()
            try:
                widget.scroll_area.viewport().resize(800, 600)
                cols_narrow = widget._calculate_columns()
                self.assertGreaterEqual(cols_narrow, 4)

                widget.scroll_area.viewport().resize(1800, 900)
                cols_wide = widget._calculate_columns()
                self.assertGreater(cols_wide, cols_narrow)
            finally:
                if hasattr(widget, "shutdown"):
                    widget.shutdown()

    def test_drama_episode_dialog_5_column_layout(self):
        """Xác minh DramaEpisodeDialog dàn trải tập theo lưới 5 cột chuẩn thập phân."""
        eps = [
            Episode(num=i, title=f"Tập {i}", url=f"https://test/{i}",
                    access_state=ACCESS_STATE_FREE if i <= 5 else ACCESS_STATE_REQUIRES_VIP,
                    locked=i > 5)
            for i in range(1, 16)
        ]
        series = Series(
            name="Test Series",
            platform="hongguo",
            series_id="hg:123",
            episode_count=15,
            accessible_count=5,
            episodes=eps,
        )
        dialog = DramaEpisodeDialog(series)
        try:
            # Mặc định kích thước 840px -> 5 cột
            cols = dialog._calculate_columns()
            self.assertGreaterEqual(cols, 5, "Mặc định phải có ít nhất 5 cột để 5 tập Free nằm gọn hàng 1")

            # Xác nhận 5 tập Free (tập 1-5) đều được checked và enabled
            for i in range(1, 6):
                cb = dialog.episode_checkboxes[i]
                self.assertTrue(cb.isEnabled())
                self.assertTrue(cb.isChecked())
                self.assertIn("[Free]", cb.text())

            # Xác nhận tập 6-15 bị disabled
            for i in range(6, 16):
                cb = dialog.episode_checkboxes[i]
                self.assertFalse(cb.isEnabled())
                self.assertFalse(cb.isChecked())
                self.assertIn("[VIP]", cb.text())
        finally:
            dialog.deleteLater()

    def test_resize_1280_to_1920_and_back_to_1024_no_card_recreation(self):
        """Xác minh resize giữa 1280px -> 1920px -> 1024px cập nhật số cột và không tạo lại card."""
        from providers.base import CatalogItem, CatalogResult
        from drama_browse_widget import DramaCardWidget

        with patch.object(CatalogWorker, "start"):
            widget = DramaBrowseWidget()
            try:
                # Giả lập nạp 12 phim mẫu
                items = [CatalogItem(id=f"id_{i}", name=f"Phim {i}", platform="hongguo", cover=f"http://img/{i}.jpg", episodes=50) for i in range(12)]
                widget._on_catalog_ready(widget._catalog_gen, CatalogResult(items=items, total=12, platform="hongguo", page=1, has_more=False))

                self.assertEqual(len(widget._cards), 12)
                initial_card_instances = [id(c) for c in widget._cards]

                # Resize sang 1280px
                widget.resize(1280, 800)
                widget.scroll_area.viewport().resize(1240, 700)
                widget._relayout_cards()
                cols_1280 = widget._calculate_columns()
                self.assertGreaterEqual(cols_1280, 5)

                # Resize sang 1920px (Full HD)
                widget.resize(1920, 1080)
                widget.scroll_area.viewport().resize(1880, 950)
                widget._relayout_cards()
                cols_1920 = widget._calculate_columns()
                self.assertGreater(cols_1920, cols_1280, "Ở 1920px số cột phải lớn hơn 1280px")

                # Resize ngược về 1024px
                widget.resize(1024, 768)
                widget.scroll_area.viewport().resize(980, 650)
                widget._relayout_cards()
                cols_1024 = widget._calculate_columns()
                self.assertLess(cols_1024, cols_1920, "Ở 1024px số cột phải giảm xuống")
                self.assertGreaterEqual(cols_1024, 4)

                # Đảm bảo các card object hoàn toàn giữ nguyên, không bị tạo lại
                final_card_instances = [id(c) for c in widget._cards]
                self.assertEqual(initial_card_instances, final_card_instances, "Card không được phép bị hủy và tạo lại khi resize")
            finally:
                widget.shutdown()

    def test_load_more_appends_and_relayouts_without_duplicates(self):
        """Xác minh bấm Tải thêm append card mới, chống trùng ID và cập nhật status hiển thị."""
        from providers.base import CatalogItem, CatalogResult

        with patch.object(CatalogWorker, "start"):
            widget = DramaBrowseWidget()
            try:
                # Trang 1: 10 phim
                items_p1 = [CatalogItem(id=f"id_{i}", name=f"Phim {i}", platform="hongguo") for i in range(1, 11)]
                widget._on_catalog_ready(widget._catalog_gen, CatalogResult(items=items_p1, total=31, platform="hongguo", page=1, has_more=True))
                self.assertEqual(len(widget._cards), 10)

                # Trang 2: nạp tiếp 10 phim (có 1 phim trùng id_10)
                items_p2 = [CatalogItem(id="id_10", name="Phim 10 Trùng", platform="hongguo")] + [
                    CatalogItem(id=f"id_{i}", name=f"Phim {i}", platform="hongguo") for i in range(11, 21)
                ]
                widget._is_append = True
                widget._on_catalog_ready(widget._catalog_gen, CatalogResult(items=items_p2, total=31, platform="hongguo", page=2, has_more=True))

                # Tổng số card thực tế phải là 20 (chống trùng id_10)
                self.assertEqual(len(widget._loaded_series_ids), 20)
                self.assertEqual(len(widget._cards), 20)
                self.assertIn("20 / 31", widget.lbl_status.text())
            finally:
                widget.shutdown()

    def test_poster_loading_and_error_states(self):
        """Xác minh trạng thái Đang tải ảnh... và Không có ảnh trên poster, không để ô đen trống."""
        from providers.base import CatalogItem
        from drama_browse_widget import DramaCardWidget
        from miniapp_browse_widget import MiniAppCardWidget
        from thumbnail_loader import ThumbnailLoader

        loader = ThumbnailLoader()
        try:
            # 1. DramaCardWidget có cover -> Đang tải ảnh...
            item_with_cover = CatalogItem(id="c1", name="Phim Có Cover", platform="hongguo", cover="http://example.com/cover.jpg")
            card1 = DramaCardWidget(item_with_cover, loader)
            self.assertEqual(card1.lbl_thumb.text(), "Đang tải ảnh...")

            # 2. DramaCardWidget không có cover -> Không có ảnh
            item_no_cover = CatalogItem(id="c2", name="Phim Không Cover", platform="hongguo", cover="")
            card2 = DramaCardWidget(item_no_cover, loader)
            self.assertEqual(card2.lbl_thumb.text(), "Không có ảnh")

            # 3. Callback trả về None (tải lỗi) -> Chuyển sang Không có ảnh
            card1._on_thumb_loaded(None)
            self.assertEqual(card1.lbl_thumb.text(), "Không có ảnh")

            # 4. MiniAppCardWidget kiểm tra tương đương
            m_item_cover = CatalogItem(id="m1", name="MiniApp Phim", platform="miniapp_douyin", cover="http://example.com/m.jpg")
            m_card1 = MiniAppCardWidget(m_item_cover, loader)
            self.assertEqual(m_card1.lbl_thumb.text(), "Đang tải ảnh...")

            m_item_no_cover = CatalogItem(id="m2", name="MiniApp No Cover", platform="miniapp_douyin", cover="")
            m_card2 = MiniAppCardWidget(m_item_no_cover, loader)
            self.assertEqual(m_card2.lbl_thumb.text(), "Không có ảnh")

            m_card1._on_thumb_loaded(None)
            self.assertEqual(m_card1.lbl_thumb.text(), "Không có ảnh")
        finally:
            loader.shutdown()

    def test_first_render_columns_respects_visible_geometry(self):
        """Xác minh lần mở đầu khi widget có kích thước thực tế sẽ render đúng số cột theo viewport chứ không kẹt ở 4 cột."""
        from providers.base import CatalogItem, CatalogResult

        with patch.object(CatalogWorker, "start"):
            widget = DramaBrowseWidget()
            try:
                # Giả lập widget hiển thị trên màn hình rộng 1920x1080
                widget.resize(1920, 1080)
                widget.scroll_area.viewport().resize(1880, 950)

                # Nạp 10 phim
                items = [CatalogItem(id=f"p_{i}", name=f"Phim {i}", platform="hongguo") for i in range(1, 11)]
                widget._on_catalog_ready(widget._catalog_gen, CatalogResult(items=items, total=10, platform="hongguo", page=1, has_more=False))

                # Kích hoạt showEvent
                widget.show()
                cols = widget._calculate_columns()
                self.assertGreater(cols, 4, "Lần render đầu trên màn hình rộng phải tính được số cột > 4, không được kẹt ở 4 cột")
                self.assertEqual(widget._current_cols, cols, "_current_cols phải khớp với số cột thực tế đã tính")
            finally:
                widget.shutdown()

    def test_all_providers_free_level_guard(self):
        """Xác minh toàn bộ các provider đều từ chối tập khóa và chỉ cho phép tải tập free."""
        active = providers.get_active_providers()
        for p in active:
            # Tạo tập giả lập bị khóa
            locked_ep = Episode(
                num=99,
                title="Tập Khóa",
                url="https://test/locked",
                access_state=ACCESS_STATE_REQUIRES_VIP,
                locked=True,
                provider_id=p.platform_id,
            )
            stream_url = p.resolve_episode_stream(locked_ep)
            self.assertIsNone(stream_url, f"Provider '{p.display_name}' không được resolve stream cho tập bị khóa")


if __name__ == "__main__":
    unittest.main()
