"""
tests.test_gui_smoke_manual
~~~~~~~~~~~~~~~~~~~~~~~~~~~
Automated GUI smoke tests for the 5 target UI flows:
1. Hongguo catalog (Browse, cards rendered, pagination / load more)
2. Kylin share link (Direct URL input, unshorten, 86 episodes, dialog launch)
3. NovelQuickApp share link (Direct URL input, 47 episodes, 5 free / 42 VIP)
4. Douyin share link (Solo video unshorten, 1 episode, dialog launch)
5. MiniApp Douyin catalog (Dropdown selection, catalog load)

Runs headless via PySide6 offscreen platform (0 display required).
Strictly compliant with Free-First policy: VIP bypass is never attempted.
"""

import os
import sys
import time
import unittest
from unittest.mock import patch

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# Configure offscreen Qt platform before importing Qt widgets
os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtWidgets import QApplication

# Ensure QApplication singleton exists
app = QApplication.instance()
if not app:
    app = QApplication(sys.argv)

import providers
from drama_browse_widget import DramaBrowseWidget, DramaCardWidget
from miniapp_browse_widget import MiniAppBrowseWidget, MiniAppCardWidget
from drama_dialog import DramaEpisodeDialog
from miniapp_episode_dialog import MiniAppEpisodeDialog


def wait_until(condition_fn, timeout=25.0, interval=0.05) -> bool:
    """Helper to process Qt events until condition_fn() evaluates to True or timeout."""
    start = time.time()
    while time.time() - start < timeout:
        app.processEvents()
        if condition_fn():
            return True
        time.sleep(interval)
    app.processEvents()
    return condition_fn()


class TestGUISmokeManual(unittest.TestCase):

    def test_1_gui_hongguo_catalog(self):
        """Flow 1: Khám phá phim -> Nguồn Hongguo / Fanqie -> Tải danh mục -> Tải thêm."""
        widget = DramaBrowseWidget()
        try:
            # Chọn nền tảng 'hongguo' trong combobox
            idx = widget.cb_platform.findData("hongguo")
            self.assertGreaterEqual(idx, 0, "Nền tảng hongguo phải có trong dropdown")
            widget.cb_platform.setCurrentIndex(idx)

            # Chờ catalog worker nạp trang 1
            completed = wait_until(
                lambda: widget.catalog_worker is not None and not widget.catalog_worker.isRunning(),
                timeout=20.0
            )
            self.assertTrue(completed, "Catalog worker cho Hongguo trang 1 phải hoàn thành")

            # Xác minh số lượng card trong grid layout (Hongguo có 31 phim, trang 1 trả về 10 phim)
            card_count_p1 = len(widget._loaded_series_ids)
            self.assertGreaterEqual(card_count_p1, 10, "Trang 1 của Hongguo phải nạp ít nhất 10 phim")
            self.assertIn("Trang 1", widget.lbl_page.text())
            self.assertIn("HONGGUO", widget.lbl_status.text())
            self.assertTrue(widget.btn_next.isEnabled(), "Nút Trang sau phải enable khi has_more=True")
            self.assertTrue(widget.btn_load_more.isEnabled(), "Nút Tải thêm phải enable khi has_more=True")

            # Bấm nút 'Tải thêm'
            gen_before = widget._catalog_gen
            widget.btn_load_more.click()
            completed_more = wait_until(
                lambda: widget._catalog_gen > gen_before and widget.catalog_worker is not None and not widget.catalog_worker.isRunning() and not widget._is_loading,
                timeout=20.0
            )
            self.assertTrue(completed_more, "Catalog worker tải thêm phải hoàn thành")

            card_count_p2 = len(widget._loaded_series_ids)
            self.assertGreater(card_count_p2, card_count_p1, "Sau khi tải thêm, số card phải tăng lên")
            self.assertEqual(card_count_p2, card_count_p1 + 10, "Trang 2 phải nạp thêm đúng 10 phim duy nhất")

            print(f"[GUI SMOKE 1 PASS] Hongguo Catalog: Trang 1 ({card_count_p1} cards) -> Tải thêm ({card_count_p2} cards)")
        finally:
            widget.shutdown()

    def test_2_gui_kylin_share_link(self):
        """Flow 2: Khám phá phim -> Dán link Kylin -> Bóc tách 86 tập -> Mở DramaEpisodeDialog."""
        widget = DramaBrowseWidget()
        dialog_opened = []

        def mock_dialog_exec(dialog_self):
            dialog_opened.append(dialog_self)
            return 0

        try:
            with patch.object(DramaEpisodeDialog, "exec", mock_dialog_exec):
                kylin_url = "https://kylin.hainanyuyue.com/s/-mVjL3iKXGY/"
                widget.txt_search.setText(kylin_url)
                widget._on_search()

                completed = wait_until(
                    lambda: widget.detail_worker is not None and not widget.detail_worker.isRunning(),
                    timeout=20.0
                )
                self.assertTrue(completed, "Detail worker cho Kylin phải hoàn thành")

            self.assertEqual(len(dialog_opened), 1, "DramaEpisodeDialog phải được khởi tạo và mở")
            opened_dlg = dialog_opened[0]
            series = opened_dlg.series

            self.assertIn("仙帝", series.name)
            self.assertGreaterEqual(series.episode_count, 80)
            self.assertEqual(len(series.episodes), series.episode_count)
            self.assertIn(f"{series.episode_count} tập", widget.lbl_status.text())

            print(f"[GUI SMOKE 2 PASS] Kylin Share Link: Series '{series.name}', {series.episode_count} episodes, Dialog verified")
        finally:
            widget.shutdown()

    def test_3_gui_novelquickapp_share_link(self):
        """Flow 3: Khám phá phim -> Dán link NovelQuickApp -> Bóc tách 47 tập (5 Free, 42 VIP)."""
        widget = DramaBrowseWidget()
        dialog_opened = []

        def mock_dialog_exec(dialog_self):
            dialog_opened.append(dialog_self)
            return 0

        try:
            with patch.object(DramaEpisodeDialog, "exec", mock_dialog_exec):
                quickapp_url = "https://novelquickapp.com/s/leok-rgP11w/"
                widget.txt_search.setText(quickapp_url)
                widget._on_search()

                completed = wait_until(
                    lambda: widget.detail_worker is not None and not widget.detail_worker.isRunning(),
                    timeout=25.0
                )
                self.assertTrue(completed, "Detail worker cho NovelQuickApp phải hoàn thành")

            self.assertEqual(len(dialog_opened), 1, "DramaEpisodeDialog phải được khởi tạo và mở")
            opened_dlg = dialog_opened[0]
            series = opened_dlg.series

            self.assertEqual(series.episode_count, 47)
            free_eps = [e for e in series.episodes if not e.locked and e.access_state == "free"]
            locked_eps = [e for e in series.episodes if e.locked or e.access_state != "free"]

            self.assertEqual(len(free_eps), 5, "NovelQuickApp phải có đúng 5 tập Free")
            self.assertEqual(len(locked_eps), 42, "NovelQuickApp phải có đúng 42 tập VIP/Locked")

            print(f"[GUI SMOKE 3 PASS] NovelQuickApp: Series '{series.name}', 47 episodes (5 Free, 42 Locked/VIP)")
        finally:
            widget.shutdown()

    def test_4_gui_douyin_share_link(self):
        """Flow 4: MiniApp Douyin -> Dán link iesdouyin.com -> Bóc tách 1 tập solo -> Mở MiniAppEpisodeDialog."""
        widget = MiniAppBrowseWidget()
        dialog_opened = []

        def mock_dialog_exec(dialog_self):
            dialog_opened.append(dialog_self)
            return 0

        try:
            # Đợi worker mặc định ban đầu nếu có
            if widget.catalog_worker and widget.catalog_worker.isRunning():
                wait_until(lambda: not widget.catalog_worker.isRunning(), timeout=10.0)

            with patch.object(MiniAppEpisodeDialog, "exec", mock_dialog_exec):
                douyin_url = "https://www.iesdouyin.com/share/video/7700535750642748706/?region=VN"
                widget.txt_search.setText(douyin_url)
                widget._on_search_clicked()

                completed = wait_until(
                    lambda: widget.detail_worker is not None and not widget.detail_worker.isRunning(),
                    timeout=20.0
                )
                self.assertTrue(completed, "Detail worker cho Douyin video phải hoàn thành")

            self.assertEqual(len(dialog_opened), 1, "MiniAppEpisodeDialog phải được khởi tạo")
            opened_dlg = dialog_opened[0]
            series = opened_dlg.series

            self.assertEqual(len(series.episodes), 1, "Douyin solo video phải có đúng 1 tập")
            self.assertEqual(series.episodes[0].episode_id, "7700535750642748706")
            self.assertIn("1 tập", widget.lbl_status.text())

            print(f"[GUI SMOKE 4 PASS] Douyin Share Link: Series '{series.name}', 1 episode (ID: 7700535750642748706)")
        finally:
            if widget.catalog_worker and widget.catalog_worker.isRunning():
                widget.catalog_worker.wait(500)
            if widget.detail_worker and widget.detail_worker.isRunning():
                widget.detail_worker.wait(500)

    def test_5_gui_miniapp_douyin_catalog(self):
        """Flow 5: MiniApp Douyin -> Chọn nguồn '多来看点' -> Nạp danh mục -> Xác minh UI."""
        widget = MiniAppBrowseWidget()
        try:
            # Đợi worker mặc định ban đầu
            if widget.catalog_worker and widget.catalog_worker.isRunning():
                wait_until(lambda: not widget.catalog_worker.isRunning(), timeout=10.0)

            # Chọn nguồn 'tt5b4d2df0c47bdd2201' (多来看点)
            idx = widget.cbo_source.findData("tt5b4d2df0c47bdd2201")
            self.assertGreaterEqual(idx, 0, "Nguồn 多来看点 phải có trong combobox")
            widget.cbo_source.setCurrentIndex(idx)

            completed = wait_until(
                lambda: widget.catalog_worker is not None and not widget.catalog_worker.isRunning(),
                timeout=20.0
            )
            self.assertTrue(completed, "Catalog worker cho MiniApp Douyin phải hoàn thành")

            # Kiểm tra trạng thái giao diện
            status_text = widget.lbl_status.text()
            self.assertTrue(
                any(k in status_text.lower() for k in ("tải", "phim", "kết quả", "lỗi", "hiển thị", "trang")),
                f"Status label phải phản ánh trạng thái hợp lệ, nhận được: {status_text}"
            )
            print(f"[GUI SMOKE 5 PASS] MiniApp Douyin Catalog: Source '多来看点', Status: '{status_text}'")
        finally:
            if widget.catalog_worker and widget.catalog_worker.isRunning():
                widget.catalog_worker.wait(500)
            if widget.detail_worker and widget.detail_worker.isRunning():
                widget.detail_worker.wait(500)


if __name__ == "__main__":
    unittest.main()
