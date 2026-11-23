"""
tests/test_catalog_provider_classification_and_race_guard.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Kiểm thử toàn diện 15 kịch bản:
1. Dropdown chỉ chứa provider có supports_catalog=True.
2. Provider URL-only không hiển thị như nguồn browse bình thường.
3. Khi include_planned=True, provider URL-only bị disabled kèm hậu tố và chống chọn.
4. BaseDramaProvider.get_catalog() trả lỗi tường minh khi supports_catalog=False.
5. Đổi nguồn khi worker đang chạy tăng generation và xếp hàng request.
6. Tìm kiếm mới khi worker đang chạy xếp hàng request.
7. Chỉ render kết quả của nguồn/query mới nhất (drop stale worker).
8. Kết quả stale không ghi đè status label hay grid.
9. Đồng bộ cookie khi worker bận xếp hàng làm mới và tự kích hoạt khi worker xong.
10. KissKH thất bại toàn bộ trả CatalogResult.error.
11. KissKH thất bại cục bộ trả partial result kèm cảnh báo.
12. MiniApp Douyin dữ liệu không đúng định dạng trả explicit error.
13. DramaBox thiếu cấu trúc bắt buộc trả lỗi format schema.
14. Hongguo thiếu loaderData/page trả lỗi format schema.
15. Catalog rỗng hợp lệ hiển thị Empty State phân biệt đúng loại, không hiện Error State.
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

import providers
from providers.base import (
    BaseDramaProvider,
    CatalogItem,
    CatalogResult,
    Series,
    Episode,
)
from drama_browse_widget import DramaBrowseWidget, CatalogWorker
from miniapp_browse_widget import MiniAppBrowseWidget, MiniAppCatalogWorker


class TestCatalogProviderClassificationAndRaceGuard(unittest.TestCase):

    def test_01_dropdown_only_contains_supports_catalog_providers(self):
        """Dropdown 'Khám Phá Phim' mặc định chỉ chứa provider có supports_catalog=True."""
        with patch.object(CatalogWorker, "start"):
            widget = DramaBrowseWidget()
            try:
                widget.populate_platforms(include_planned=False)
                count = widget.cb_platform.count()
                self.assertGreaterEqual(count, 3)

                for idx in range(count):
                    pid = widget.cb_platform.itemData(idx)
                    p_obj = providers.get_provider(pid)
                    self.assertIsNotNone(p_obj)
                    self.assertTrue(
                        getattr(p_obj, "supports_catalog", False),
                        f"Provider {pid} trong dropdown browse phải có supports_catalog=True",
                    )
            finally:
                widget.shutdown()

    def test_02_url_only_providers_excluded_from_active_browse_dropdown(self):
        """Các provider URL-only không xuất hiện trong dropdown browse mặc định."""
        url_only_ids = [p.platform_id for p in providers.get_url_only_providers()]
        self.assertGreater(len(url_only_ids), 0)

        with patch.object(CatalogWorker, "start"):
            widget = DramaBrowseWidget()
            try:
                widget.populate_platforms(include_planned=False)
                dropdown_ids = [widget.cb_platform.itemData(i) for i in range(widget.cb_platform.count())]
                for u_id in url_only_ids:
                    self.assertNotIn(u_id, dropdown_ids, f"URL-only provider {u_id} không được có trong dropdown browse")
            finally:
                widget.shutdown()

    def test_03_planned_providers_disabled_with_suffix_when_included(self):
        """Khi include_planned=True, provider URL-only/planned bị disabled kèm hậu tố và chống click."""
        with patch.object(CatalogWorker, "start"):
            widget = DramaBrowseWidget()
            try:
                widget.populate_platforms(include_planned=True)
                has_disabled = False
                for idx in range(widget.cb_platform.count()):
                    label = widget.cb_platform.itemText(idx)
                    pid = widget.cb_platform.itemData(idx)
                    p_obj = providers.get_provider(pid)
                    item = widget.cb_platform.model().item(idx)

                    if p_obj and not getattr(p_obj, "supports_catalog", False):
                        has_disabled = True
                        self.assertIn("Sắp hỗ trợ duyệt danh mục", label)
                        self.assertFalse(item.isEnabled())

                self.assertTrue(has_disabled)

                # Kiểm tra cơ chế chống chọn provider disabled
                valid_idx = 0
                widget.cb_platform.setCurrentIndex(valid_idx)
                widget._last_valid_platform_idx = valid_idx

                # Thử kích hoạt đổi sang item disabled
                for idx in range(widget.cb_platform.count()):
                    item = widget.cb_platform.model().item(idx)
                    if item and not item.isEnabled():
                        widget.cb_platform.setCurrentIndex(idx)
                        widget._on_platform_changed()
                        # Widget phải tự hoàn trả về valid_idx
                        self.assertEqual(widget.cb_platform.currentIndex(), valid_idx)
                        break
            finally:
                widget.shutdown()

    def test_04_base_provider_get_catalog_returns_explicit_error_for_unsupported(self):
        """BaseDramaProvider.get_catalog() trả về CatalogResult.error khi supports_catalog=False."""
        class DummyUnsupportedProvider(BaseDramaProvider):
            platform_id = "unsupported_dummy"
            display_name = "Dummy"
            supports_catalog = False

            def can_handle(self, url: str) -> bool:
                return False

            def get_series(self, url_or_id: str) -> Series:
                return Series(series_id="1", name="Dummy")

            def load_series(self, url_or_id: str) -> Series:
                return Series(series_id="1", name="Dummy")

            def resolve_episode_url(self, episode: Episode) -> str:
                return ""

        p = DummyUnsupportedProvider()
        res = p.get_catalog()
        self.assertIsNotNone(res.error)
        self.assertIn("chưa hỗ trợ duyệt danh mục", res.error)
        self.assertEqual(len(res.items), 0)

    def test_05_source_change_while_worker_running_increments_gen_and_queues_request(self):
        """Đổi nguồn khi worker đang chạy tăng generation và xếp hàng pending request."""
        with patch.object(CatalogWorker, "start"):
            widget = DramaBrowseWidget()
            try:
                widget._is_loading = True
                old_gen = widget._catalog_gen

                widget.request_catalog_reload(source_id="dramabox", query="", page=1, reason="Đổi sang DramaBox")
                self.assertGreater(widget._catalog_gen, old_gen)
                self.assertIsNotNone(widget._pending_catalog_request)
                self.assertEqual(widget._pending_catalog_request["source_id"], "dramabox")
            finally:
                widget.shutdown()

    def test_06_new_search_while_worker_running_queues_pending_request(self):
        """Tìm kiếm mới khi worker đang chạy xếp hàng request tìm kiếm."""
        with patch.object(CatalogWorker, "start"):
            widget = DramaBrowseWidget()
            try:
                widget._is_loading = True
                widget.request_catalog_reload(query="Chủ tịch", page=1, reason="Tìm kiếm mới")
                self.assertIsNotNone(widget._pending_catalog_request)
                self.assertEqual(widget._pending_catalog_request["query"], "Chủ tịch")
            finally:
                widget.shutdown()

    def test_07_only_latest_source_or_query_is_rendered(self):
        """Chỉ render kết quả của request mới nhất, kết quả worker cũ (stale) bị hủy bỏ."""
        with patch.object(CatalogWorker, "start"):
            widget = DramaBrowseWidget()
            try:
                widget._catalog_gen = 2

                # Giả lập worker gen 1 (cũ) trả kết quả 5 card
                stale_items = [CatalogItem(id=f"stale_{i}", name=f"Stale {i}", platform="hongguo") for i in range(5)]
                widget._on_catalog_ready(1, CatalogResult(items=stale_items, total=5, platform="hongguo"))
                self.assertEqual(len(widget._cards), 0, "Kết quả từ gen cũ không được add vào grid")

                # Giả lập worker gen 2 (hiện tại) trả kết quả 3 card
                fresh_items = [CatalogItem(id=f"fresh_{i}", name=f"Fresh {i}", platform="dramabox") for i in range(3)]
                widget._on_catalog_ready(2, CatalogResult(items=fresh_items, total=3, platform="dramabox"))
                self.assertEqual(len(widget._cards), 3, "Kết quả từ gen hiện tại phải được hiển thị")
            finally:
                widget.shutdown()

    def test_08_stale_result_does_not_overwrite_status_or_empty_state(self):
        """Lỗi hoặc kết quả từ worker cũ không được ghi đè status label hay giao diện."""
        with patch.object(CatalogWorker, "start"):
            widget = DramaBrowseWidget()
            try:
                widget._catalog_gen = 5
                widget.lbl_status.setText("Đang tải danh mục mới...")

                # Worker gen 3 trả lỗi cũ
                widget._on_catalog_error(3, "Lỗi mạng cũ")
                self.assertEqual(widget.lbl_status.text(), "Đang tải danh mục mới...")
            finally:
                widget.shutdown()

    def test_09_cookie_sync_queues_refresh_and_executes_after_worker_finishes(self):
        """Đồng bộ cookie khi worker bận xếp hàng làm mới và tự động thực thi sau khi worker xong."""
        with patch.object(CatalogWorker, "start"):
            widget = DramaBrowseWidget()
            try:
                widget._is_loading = True
                widget.on_cookie_synced()

                self.assertIsNotNone(widget._pending_catalog_request)
                self.assertIn("Phiên đã thay đổi", widget._pending_catalog_request.get("reason", ""))

                # Giả lập worker hiện tại kết thúc
                current_gen = widget._catalog_gen
                fresh_items = [CatalogItem(id="item1", name="Movie 1", platform="hongguo")]
                widget._on_catalog_ready(current_gen, CatalogResult(items=fresh_items, total=1, platform="hongguo"))
                widget._on_catalog_worker_finished(current_gen)

                # Sau khi worker hoàn tất, pending request phải được kích hoạt và reset pending
                self.assertIsNone(widget._pending_catalog_request)
            finally:
                widget.shutdown()

    def test_10_kisskh_all_mirrors_fail_returns_error(self):
        """KissKH khi tất cả mirror API thất bại trả về CatalogResult.error rõ ràng."""
        from providers.kisskh_provider import KisskhProvider
        provider = KisskhProvider()

        with patch.object(provider, "_request_api", side_effect=RuntimeError("Tất cả mirror đều trả về HTTP 503")):
            res = provider.get_catalog(page=1)
            self.assertIsNotNone(res.error)
            self.assertEqual(len(res.items), 0)

    def test_11_kisskh_partial_failure_returns_partial_results_with_warning(self):
        """KissKH khi trang 1 thành công nhưng trang 2 lỗi vẫn giữ kết quả trang 1 và cảnh báo."""
        from providers.kisskh_provider import KisskhProvider
        provider = KisskhProvider()

        def mock_request(endpoint):
            if "page=1" in endpoint:
                return {"data": [{"id": 101, "title": "KissKH Drama 1", "thumbnail": ""}], "totalCount": 50}
            raise RuntimeError("Mirror timeout on page 2")

        with patch.object(provider, "_request_api", side_effect=mock_request):
            res = provider.get_catalog(page=1)
            self.assertEqual(len(res.items), 1)
            self.assertIsNotNone(res.error, "Phải chứa thông báo cảnh báo lỗi trang 2")

    def test_12_miniapp_malformed_json_returns_explicit_error(self):
        """MiniApp Douyin phản hồi JSON không đúng cấu trúc (không phải dict/list) trả về lỗi rõ ràng."""
        from providers.miniapp_douyin_client import MiniAppDouyinClient
        client = MiniAppDouyinClient()

        mock_resp1 = MagicMock()
        mock_resp1.status_code = 200
        mock_resp1.json.return_value = "Invalid string payload"

        with patch.object(client.session, "get", return_value=mock_resp1):
            items, has_more, err = client.browse_catalog("test_app", page=1)
            self.assertIsNotNone(err)
            self.assertIn("không đúng định dạng", err)

        mock_resp2 = MagicMock()
        mock_resp2.status_code = 200
        mock_resp2.json.return_value = {"data": "not_a_list"}

        with patch.object(client.session, "get", return_value=mock_resp2):
            items, has_more, err = client.browse_catalog("test_app", page=1)
            self.assertIsNotNone(err)
            self.assertIn("không phải là list hoặc dict", err)

    def test_13_dramabox_missing_required_structure_returns_schema_error(self):
        """DramaBox khi thiếu bigList và smallData trong JSON __NEXT_DATA__ trả lỗi schema."""
        from providers.dramabox_provider import DramaBoxProvider
        provider = DramaBoxProvider()

        # HTML có __NEXT_DATA__ nhưng thiếu bigList và smallData
        mock_html = """
        <html>
        <script id="__NEXT_DATA__" type="application/json">
        {"props": {"pageProps": {"otherData": 123}}}
        </script>
        </html>
        """
        mock_resp = MagicMock()
        mock_resp.text = mock_html
        mock_resp.status_code = 200

        with patch.object(provider.session, "get", return_value=mock_resp):
            res = provider.get_catalog(page=1)
            self.assertIsNotNone(res.error)
            self.assertIn("Dữ liệu danh mục từ nguồn đã thay đổi", res.error)

    def test_14_hongguo_missing_loaderdata_returns_schema_error(self):
        """Hongguo khi thiếu loaderData/page trong _ROUTER_DATA trả lỗi format."""
        from providers.hongguo_provider import HongguoProvider
        provider = HongguoProvider()

        # HTML có _ROUTER_DATA nhưng loaderData không phải dict
        mock_html = """
        <html>
        <script>
        window._ROUTER_DATA = {"loaderData": "invalid_string_not_dict"};
        </script>
        </html>
        """
        mock_resp = MagicMock()
        mock_resp.text = mock_html
        mock_resp.status_code = 200

        with patch.object(provider.session, "get", return_value=mock_resp):
            res = provider.get_catalog(page=1)
            self.assertIsNotNone(res.error)
            self.assertIn("Dữ liệu danh mục từ nguồn đã thay đổi", res.error)

    def test_15_valid_empty_catalog_shows_empty_state_not_error(self):
        """Catalog rỗng hợp lệ (không lỗi API) phải hiển thị Empty State chứ không hiện Error State."""
        with patch.object(CatalogWorker, "start"):
            widget = DramaBrowseWidget()
            try:
                # 1. Trường hợp không tìm kiếm, danh mục rỗng
                widget.current_query = ""
                widget._on_catalog_ready(widget._catalog_gen, CatalogResult(items=[], total=0, platform="hongguo", error=None))
                self.assertFalse(widget.empty_state.isHidden())
                self.assertEqual(widget.lbl_status.text(), "Chưa có phim phù hợp")

                # 2. Trường hợp có tìm kiếm nhưng không có kết quả khớp
                widget.current_query = "Phim Không Tồn Tại 123456"
                widget._on_catalog_ready(widget._catalog_gen, CatalogResult(items=[], total=0, platform="hongguo", error=None))
                self.assertFalse(widget.empty_state.isHidden())
                self.assertEqual(widget.lbl_status.text(), "Không có phim phù hợp với từ khóa")
            finally:
                widget.shutdown()


if __name__ == "__main__":
    unittest.main()
