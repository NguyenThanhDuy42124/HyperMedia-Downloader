"""
tests/test_qthread_real_concurrency_lifecycle.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Kiểm thử toàn diện 12 kịch bản Race Condition & Thread Lifecycle với QThread thật:
1. Đang load Hongguo -> chọn DramaBox (Chỉ render DramaBox, 0 card Hongguo).
2. Đang load DramaBox -> chọn KissKH (Chỉ render KissKH, 0 card DramaBox).
3. Đang load catalog -> nhập query mới (Chỉ render kết quả tìm kiếm).
4. Đang load catalog -> bấm Refresh (Nạp lại thành công danh mục mới).
5. Đang load MiniApp -> sync cookie (Tự động kích hoạt nạp lại với phiên bảo mật).
6. Worker trả kết quả trước finished (Xác nhận isRunning() == True khi emit results_ready/error và False sau finished).
7. Pending request chỉ chạy sau finished (Pending request không chạy trong results_ready mà chạy sau finished).
8. Kết quả nguồn cũ không ghi đè nguồn mới (Stale result bị drop hoàn toàn).
9. Đổi nguồn 3 lần liên tục chỉ chạy request cuối (Hongguo -> DramaBox -> KissKH -> Chỉ chạy KissKH).
10. Lỗi worker cũ không làm mất request mới (Worker cũ lỗi không hiển thị Error State đè lên request mới).
11. Tải thêm không bị biến thành request reset (Append=True giữ nguyên card cũ và nối tiếp card mới).
12. Retry sau lỗi thực sự chạy lại (Nút Thử lại kích hoạt worker mới thành công).
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

os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import QApplication

app = QApplication.instance()
if not app:
    app = QApplication(sys.argv)

import providers
from providers.base import CatalogItem, CatalogResult
from drama_browse_widget import DramaBrowseWidget, CatalogWorker
from miniapp_browse_widget import MiniAppBrowseWidget, MiniAppCatalogWorker


class FastMockProvider:
    def __init__(self, platform_id, delay=0.03, should_error=False):
        self.platform_id = platform_id
        self.display_name = platform_id.upper()
        self.supports_catalog = True
        self.delay = delay
        self.should_error = should_error

    def get_catalog(self, page=1, query="", **kwargs):
        if self.delay > 0:
            time.sleep(self.delay)
        if self.should_error:
            return CatalogResult(
                items=[],
                total=0,
                platform=self.platform_id,
                page=page,
                error=f"Lỗi mạng máy chủ {self.platform_id}: Timeout 504",
                has_more=False,
            )

        q_txt = f" [{query}]" if query else ""
        items = [
            CatalogItem(
                id=f"{self.platform_id}_{page}_{i}",
                name=f"{self.platform_id.upper()} P{page}{q_txt} #{i}",
                platform=self.platform_id,
                cover="",
                episodes=10,
            )
            for i in range(3)
        ]
        return CatalogResult(
            items=items,
            total=10,
            has_more=True,
            platform=self.platform_id,
            page=page,
        )


class InspectedWorker(QThread):
    results_ready = Signal(int, object)
    error = Signal(int, str)

    def __init__(self, generation, platform_id, should_error=False, delay=0.03, hold=0.04, parent=None):
        super().__init__(parent)
        self.generation = generation
        self.platform_id = platform_id
        self.should_error = should_error
        self.delay = delay
        self.hold = hold

    def run(self):
        if self.delay > 0:
            time.sleep(self.delay)
        if self.should_error:
            self.error.emit(self.generation, f"Lỗi worker mô phỏng {self.platform_id}")
        else:
            res = CatalogResult(
                items=[CatalogItem(id="i1", name="Phim", platform=self.platform_id, cover="")],
                total=1,
                has_more=False,
                platform=self.platform_id,
            )
            self.results_ready.emit(self.generation, res)
        # Giữ luồng tiếp tục chạy trong khi slot ở main thread được kích hoạt
        if self.hold > 0:
            time.sleep(self.hold)


def wait_until(condition_fn, timeout_sec=4.0):
    start = time.time()
    while not condition_fn():
        app.processEvents()
        time.sleep(0.005)
        if time.time() - start > timeout_sec:
            raise TimeoutError(f"Hết thời gian chờ điều kiện ({timeout_sec}s)")


class TestQThreadRealConcurrencyLifecycle(unittest.TestCase):

    def setUp(self):
        self.mock_providers = {
            "hongguo": FastMockProvider("hongguo", delay=0.04),
            "dramabox": FastMockProvider("dramabox", delay=0.04),
            "kisskh": FastMockProvider("kisskh", delay=0.04),
            "miniapp_douyin": FastMockProvider("miniapp_douyin", delay=0.04),
        }
        self.orig_get_provider = providers.get_provider
        providers.get_provider = lambda pid: self.mock_providers.get(pid, FastMockProvider(pid))

    def tearDown(self):
        providers.get_provider = self.orig_get_provider

    def test_01_switching_hongguo_to_dramabox_real_qthread(self):
        """Kịch bản 1: Đang load Hongguo -> đổi sang DramaBox với QThread thật."""
        widget = DramaBrowseWidget()
        try:
            self.assertTrue(widget.catalog_worker.isRunning() or widget._is_loading)

            # Người dùng chuyển combobox sang DramaBox khi Hongguo đang chạy
            dramabox_idx = widget.cb_platform.findData("dramabox")
            widget.cb_platform.setCurrentIndex(dramabox_idx)
            widget._on_platform_changed()

            self.assertIsNotNone(widget._pending_catalog_request)
            self.assertEqual(widget._pending_catalog_request["source_id"], "dramabox")

            wait_until(lambda: not widget._is_loading and len(widget._cards) > 0)

            for c in widget._cards:
                self.assertEqual(c.item.platform, "dramabox")
            self.assertIn("DRAMABOX", widget.lbl_status.text().upper())
            print("[QTHREAD TEST 1 PASS] Đang load Hongguo -> DramaBox: Chạy mượt mà, hiển thị 100% card DramaBox.")
        finally:
            widget.shutdown()

    def test_02_switching_dramabox_to_kisskh_real_qthread(self):
        """Kịch bản 2: Đang load DramaBox -> đổi sang KissKH với QThread thật."""
        widget = DramaBrowseWidget()
        try:
            wait_until(lambda: not widget._is_loading)

            widget.cb_platform.setCurrentIndex(widget.cb_platform.findData("dramabox"))
            widget._on_platform_changed()
            self.assertTrue(widget._is_loading)

            widget.cb_platform.setCurrentIndex(widget.cb_platform.findData("kisskh"))
            widget._on_platform_changed()

            self.assertEqual(widget._pending_catalog_request["source_id"], "kisskh")

            wait_until(lambda: not widget._is_loading and len(widget._cards) > 0)

            for c in widget._cards:
                self.assertEqual(c.item.platform, "kisskh")
            print("[QTHREAD TEST 2 PASS] Đang load DramaBox -> KissKH: Chuyển nguồn chính xác.")
        finally:
            widget.shutdown()

    def test_03_typing_query_while_catalog_loading_real_qthread(self):
        """Kịch bản 3: Đang load catalog -> nhập query mới."""
        widget = DramaBrowseWidget()
        try:
            widget.txt_search.setText("chiến thần")
            widget._on_search()

            self.assertIsNotNone(widget._pending_catalog_request)
            self.assertEqual(widget._pending_catalog_request["query"], "chiến thần")

            wait_until(lambda: not widget._is_loading and len(widget._cards) > 0)

            self.assertEqual(widget.current_query, "chiến thần")
            for c in widget._cards:
                self.assertIn("chiến thần", c.item.name)
            print("[QTHREAD TEST 3 PASS] Tìm kiếm khi đang load: Bỏ qua catalog chung, nạp đúng kết quả tìm kiếm.")
        finally:
            widget.shutdown()

    def test_04_refresh_while_catalog_loading_real_qthread(self):
        """Kịch bản 4: Đang load catalog -> bấm Refresh."""
        widget = DramaBrowseWidget()
        try:
            self.assertTrue(widget._is_loading or widget.catalog_worker.isRunning())

            widget._on_refresh()
            self.assertIsNotNone(widget._pending_catalog_request)

            wait_until(lambda: not widget._is_loading and len(widget._cards) > 0)
            self.assertFalse(widget._is_loading)
            print("[QTHREAD TEST 4 PASS] Bấm Refresh khi đang load: Tái nạp thành công.")
        finally:
            widget.shutdown()

    def test_05_miniapp_sync_cookie_while_worker_running_real_qthread(self):
        """Kịch bản 5: Đang load MiniApp -> nhận tín hiệu đồng bộ cookie."""
        with patch("providers.miniapp_douyin_provider.MiniAppDouyinProvider.get_catalog", return_value=FastMockProvider("miniapp_douyin").get_catalog()):
            widget = MiniAppBrowseWidget()
            try:
                self.assertTrue(widget._is_busy or widget.catalog_worker.isRunning())

                widget.on_cookie_synced("douyin.com", 5, "Chrome")
                self.assertIsNotNone(widget._pending_catalog_request)

                wait_until(lambda: not widget._is_busy and len(widget._cards) > 0)
                self.assertFalse(widget._is_busy)
                print("[QTHREAD TEST 5 PASS] MiniApp cookie sync khi đang bận: Tự động nạp lại với phiên mới.")
            finally:
                widget.shutdown()

    def test_06_worker_emits_results_ready_before_finished_isRunning_is_true(self):
        """Kịch bản 6: Xác nhận worker trả kết quả trước finished và isRunning() == True lúc đó."""
        # 1. Kiểm tra với results_ready
        w_ok = InspectedWorker(1, "hongguo", should_error=False, delay=0.02, hold=0.04)
        is_running_at_ready = []
        is_running_at_finished = []

        w_ok.results_ready.connect(lambda g, r: is_running_at_ready.append(w_ok.isRunning()))
        w_ok.finished.connect(lambda: is_running_at_finished.append(w_ok.isRunning()))
        w_ok.start()

        wait_until(lambda: len(is_running_at_finished) > 0)
        self.assertTrue(len(is_running_at_ready) > 0)
        self.assertTrue(is_running_at_ready[0], "Worker PHẢI có isRunning() == True khi emit results_ready!")
        self.assertFalse(is_running_at_finished[0], "Worker PHẢI có isRunning() == False sau khi finished!")

        # 2. Kiểm tra với error
        w_err = InspectedWorker(2, "hongguo", should_error=True, delay=0.02, hold=0.04)
        is_running_at_err = []
        is_running_at_err_fin = []

        w_err.error.connect(lambda g, e: is_running_at_err.append(w_err.isRunning()))
        w_err.finished.connect(lambda: is_running_at_err_fin.append(w_err.isRunning()))
        w_err.start()

        wait_until(lambda: len(is_running_at_err_fin) > 0)
        self.assertTrue(len(is_running_at_err) > 0)
        self.assertTrue(is_running_at_err[0], "Worker PHẢI có isRunning() == True khi emit error!")
        self.assertFalse(is_running_at_err_fin[0], "Worker PHẢI có isRunning() == False sau error finished!")

        print("[QTHREAD TEST 6 PASS] Worker trả kết quả/lỗi trước finished và isRunning() == True chính xác.")

    def test_07_pending_request_runs_strictly_after_finished(self):
        """Kịch bản 7: Pending request chỉ chạy sau khi worker cũ phát signal finished."""
        widget = DramaBrowseWidget()
        try:
            events = []

            wait_until(lambda: not widget._is_loading)

            # Bắt đầu worker 1 có hold time sau emit
            w1 = InspectedWorker(widget._catalog_gen, "hongguo", delay=0.02, hold=0.04, parent=widget)
            gen1 = widget._catalog_gen
            widget.catalog_worker = w1
            widget._is_loading = True

            def on_ready(g, r):
                # Tại thời điểm results_ready, w1 vẫn đang chạy và pending request VẪN CHƯA BỊ XÓA
                events.append(("results_ready", g, w1.isRunning(), widget._pending_catalog_request is not None))
                widget._on_catalog_ready(g, r)

            def on_fin():
                events.append(("finished_before_handler", gen1, w1.isRunning()))
                widget._on_catalog_worker_finished(gen1)
                events.append(("finished_after_handler", gen1, widget.catalog_worker != w1))

            w1.results_ready.connect(on_ready)
            w1.finished.connect(on_fin)
            w1.start()

            # Ngay lập tức yêu cầu R2 (DramaBox)
            widget.request_catalog_reload(source_id="dramabox", reason="R2")
            events.append(("pending_enqueued", widget._catalog_gen))

            wait_until(lambda: not widget._is_loading and len(widget._cards) > 0)

            event_names = [e[0] for e in events]
            self.assertIn("results_ready", event_names)
            self.assertIn("finished_before_handler", event_names)

            # 1. results_ready xảy ra TRƯỚC finished
            idx_ready = event_names.index("results_ready")
            idx_fin = event_names.index("finished_before_handler")
            self.assertLess(idx_ready, idx_fin)

            # 2. Tại results_ready, w1.isRunning() là True VÀ pending request VẪN CÒN ĐANG CHỜ
            self.assertTrue(events[idx_ready][2], "w1.isRunning() phải là True tại results_ready")
            self.assertTrue(events[idx_ready][3], "Pending request phải chưa bị chạy trước finished!")

            print("[QTHREAD TEST 7 PASS] Pending request không chạy trong results_ready, chạy chuẩn xác sau finished.")
        finally:
            widget.shutdown()

    def test_08_stale_source_results_never_overwrite_new_source(self):
        """Kịch bản 8: Kết quả nguồn cũ bị trễ không bao giờ ghi đè nguồn mới."""
        self.mock_providers["hongguo"] = FastMockProvider("hongguo", delay=0.08)
        self.mock_providers["dramabox"] = FastMockProvider("dramabox", delay=0.02)

        widget = DramaBrowseWidget()
        try:
            widget.request_catalog_reload(source_id="dramabox", reason="Sang DramaBox")

            wait_until(lambda: not widget._is_loading and len(widget._cards) > 0)

            for c in widget._cards:
                self.assertEqual(c.item.platform, "dramabox")
            print("[QTHREAD TEST 8 PASS] Kết quả nguồn cũ bị loại bỏ hoàn toàn, không đè lên nguồn mới.")
        finally:
            widget.shutdown()

    def test_09_switching_source_three_times_rapidly_only_executes_latest(self):
        """Kịch bản 9: Đổi nguồn 3 lần liên tục (Hongguo -> DramaBox -> KissKH), chỉ chạy nguồn cuối."""
        widget = DramaBrowseWidget()
        try:
            self.assertTrue(widget._is_loading)

            # Đổi nhanh 1: DramaBox
            widget.request_catalog_reload(source_id="dramabox", reason="Đổi DramaBox")
            # Đổi nhanh 2: KissKH
            widget.request_catalog_reload(source_id="kisskh", reason="Đổi KissKH")

            self.assertEqual(widget._pending_catalog_request["source_id"], "kisskh")

            wait_until(lambda: not widget._is_loading and len(widget._cards) > 0)

            for c in widget._cards:
                self.assertEqual(c.item.platform, "kisskh")
            print("[QTHREAD TEST 9 PASS] Đổi nguồn 3 lần liên tục: Bỏ qua trung gian, nạp chuẩn nguồn cuối cùng (KissKH).")
        finally:
            widget.shutdown()

    def test_10_old_worker_error_does_not_drop_new_request(self):
        """Kịch bản 10: Lỗi từ worker cũ không làm mất request mới và không hiện popup/error state lỗi cũ."""
        self.mock_providers["hongguo"] = FastMockProvider("hongguo", delay=0.04, should_error=True)
        self.mock_providers["dramabox"] = FastMockProvider("dramabox", delay=0.03, should_error=False)

        widget = DramaBrowseWidget()
        widget.show()
        try:
            widget.request_catalog_reload(source_id="dramabox", reason="Sang DramaBox")

            wait_until(lambda: not widget._is_loading and len(widget._cards) > 0)

            self.assertFalse(widget.empty_state.isVisible())
            for c in widget._cards:
                self.assertEqual(c.item.platform, "dramabox")
            print("[QTHREAD TEST 10 PASS] Lỗi từ worker cũ không ảnh hưởng request mới.")
        finally:
            widget.shutdown()

    def test_11_load_more_preserves_page_and_append_mode(self):
        """Kịch bản 11: Tải thêm bảo tồn chế độ append và nối tiếp card."""
        widget = DramaBrowseWidget()
        try:
            wait_until(lambda: not widget._is_loading and len(widget._cards) == 3)
            self.assertEqual(len(widget._cards), 3)

            widget._has_more = True
            widget._on_load_more()

            wait_until(lambda: not widget._is_loading and len(widget._cards) == 6)
            self.assertEqual(len(widget._cards), 6)
            self.assertEqual(widget.current_page, 2)
            print("[QTHREAD TEST 11 PASS] Tải thêm hoạt động chuẩn xác, append 3 card mới thành 6 card.")
        finally:
            widget.shutdown()

    def test_12_retry_after_error_really_executes(self):
        """Kịch bản 12: Retry sau lỗi thực sự khởi chạy lại worker thành công."""
        self.mock_providers["hongguo"] = FastMockProvider("hongguo", delay=0.02, should_error=True)

        widget = DramaBrowseWidget()
        widget.show()
        try:
            wait_until(lambda: not widget._is_loading and widget.empty_state.isVisible())
            self.assertTrue(widget.empty_state.isVisible())

            # Sửa provider thành công
            self.mock_providers["hongguo"] = FastMockProvider("hongguo", delay=0.02, should_error=False)

            # Bấm Thử lại trên giao diện lỗi
            widget.empty_state.btn_action.click()

            wait_until(lambda: not widget._is_loading and len(widget._cards) > 0)
            self.assertFalse(widget.empty_state.isVisible())
            self.assertGreater(len(widget._cards), 0)
            print("[QTHREAD TEST 12 PASS] Nút Thử lại hoạt động và nạp lại phim thành công.")
        finally:
            widget.shutdown()


if __name__ == "__main__":
    unittest.main()
