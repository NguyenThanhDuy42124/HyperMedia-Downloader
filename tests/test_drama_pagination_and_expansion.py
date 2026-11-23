"""
tests/test_drama_pagination_and_expansion.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Kiểm thử chuyên sâu cho:
1. DramaBox parser: hỗ trợ smallData dạng list và dict, phân trang xác định client-side, deduplication.
2. KissKH catalog: gộp 2 trang API (20 phim/trang UI), totalCount, has_more, deduplication.
3. DramaBrowseWidget: nút 'Tải thêm' (append mode không xóa card cũ), status 'Đang hiển thị X / Y', stale generation guard.
4. Đăng ký Active Providers mở rộng (11 providers) và tuân thủ hợp đồng Free-first (khóa tuyệt đối tập VIP, không bypass).
"""

import os
import sys
import json
import unittest
from unittest.mock import MagicMock, patch

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from providers.base import (
    BaseDramaProvider,
    CatalogItem,
    CatalogResult,
    Series,
    Episode,
    ACCESS_STATE_FREE,
    ACCESS_STATE_REQUIRES_VIP,
)
from providers.dramabox_provider import DramaBoxProvider
from providers.kisskh_provider import KisskhProvider
import providers


class TestDramaPaginationAndExpansion(unittest.TestCase):

    def test_dramabox_smalldata_list_and_dict_parsing(self):
        """DramaBox phải trích xuất đầy đủ phim khi smallData là list hoặc dict."""
        provider = DramaBoxProvider()

        # Giả lập smallData là list (dạng dữ liệu thực tế trên dramaboxdb.com)
        mock_html_list = """
        <html>
        <script id="__NEXT_DATA__" type="application/json">
        {
            "props": {
                "pageProps": {
                    "bigList": [
                        {"bookId": "b1", "bookName": "Big Drama 1", "introduction": "Intro 1", "chapterCount": 50}
                    ],
                    "smallData": [
                        {
                            "title": "Category A",
                            "items": [
                                {"bookId": "s1", "bookName": "Small Drama 1", "introduction": "Intro S1", "chapterCount": 30},
                                {"bookId": "s2", "bookName": "Small Drama 2", "introduction": "Intro S2", "chapterCount": 40}
                            ]
                        },
                        {
                            "title": "Category B",
                            "list": [
                                {"bookId": "s3", "bookName": "Small Drama 3", "introduction": "Intro S3", "chapterCount": 60},
                                {"bookId": "b1", "bookName": "Duplicate B1", "introduction": "Dup", "chapterCount": 50}
                            ]
                        }
                    ]
                }
            }
        }
        </script>
        </html>
        """

        with patch.object(provider.session, "get") as mock_get:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.text = mock_html_list
            mock_get.return_value = mock_resp

            res = provider.get_catalog(page=1)
            self.assertEqual(res.error, None)
            # Tổng số phim sau khi deduplicate: b1, s1, s2, s3 = 4 phim
            self.assertEqual(res.total, 4)
            self.assertEqual(len(res.items), 4)
            ids = [it.id for it in res.items]
            self.assertEqual(ids, ["b1", "s1", "s2", "s3"])

        # Giả lập smallData là dict (fallback)
        mock_html_dict = """
        <html>
        <script id="__NEXT_DATA__" type="application/json">
        {
            "props": {
                "pageProps": {
                    "bigList": [],
                    "smallData": {
                        "sec1": [
                            {"bookId": "d1", "bookName": "Dict Drama 1", "chapterCount": 20}
                        ],
                        "sec2": {
                            "items": [
                                {"bookId": "d2", "bookName": "Dict Drama 2", "chapterCount": 25}
                            ]
                        }
                    }
                }
            }
        }
        </script>
        </html>
        """
        with patch.object(provider.session, "get") as mock_get:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.text = mock_html_dict
            mock_get.return_value = mock_resp

            res = provider.get_catalog(page=1)
            self.assertEqual(res.total, 2)
            self.assertEqual([it.id for it in res.items], ["d1", "d2"])

    def test_dramabox_client_side_pagination(self):
        """DramaBox hỗ trợ phân trang chuẩn xác (10 phim/trang) và không chặn page > 1."""
        provider = DramaBoxProvider()

        # Tạo danh sách 25 phim giả lập
        items_json = []
        for i in range(1, 26):
            items_json.append({"bookId": f"id_{i}", "bookName": f"Drama {i}", "chapterCount": i * 2})

        mock_payload = {
            "props": {
                "pageProps": {
                    "bigList": items_json[:5],
                    "smallData": [{"items": items_json[5:]}],
                }
            }
        }
        mock_html = f'<html><script id="__NEXT_DATA__" type="application/json">{json.dumps(mock_payload)}</script></html>'

        with patch.object(provider.session, "get") as mock_get:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.text = mock_html
            mock_get.return_value = mock_resp

            # Trang 1: 10 phim (id_1 -> id_10), has_more=True
            res1 = provider.get_catalog(page=1)
            self.assertEqual(res1.total, 25)
            self.assertEqual(len(res1.items), 10)
            self.assertEqual(res1.items[0].id, "id_1")
            self.assertEqual(res1.items[-1].id, "id_10")
            self.assertTrue(res1.has_more)

            # Trang 2: 10 phim (id_11 -> id_20), has_more=True
            res2 = provider.get_catalog(page=2)
            self.assertEqual(len(res2.items), 10)
            self.assertEqual(res2.items[0].id, "id_11")
            self.assertEqual(res2.items[-1].id, "id_20")
            self.assertTrue(res2.has_more)

            # Trang 3: 5 phim (id_21 -> id_25), has_more=False
            res3 = provider.get_catalog(page=3)
            self.assertEqual(len(res3.items), 5)
            self.assertEqual(res3.items[0].id, "id_21")
            self.assertEqual(res3.items[-1].id, "id_25")
            self.assertFalse(res3.has_more)

            # Trang 4: 0 phim, has_more=False
            res4 = provider.get_catalog(page=4)
            self.assertEqual(len(res4.items), 0)
            self.assertFalse(res4.has_more)

    def test_kisskh_two_page_merge_and_totalcount(self):
        """KissKH gộp 2 trang API (10 + 10 = 20 phim/trang UI), đọc totalCount, và deduplicate."""
        provider = KisskhProvider()

        # Giả lập trả về từ API kisskh
        def mock_request(endpoint):
            if "page=1" in endpoint:
                return {
                    "totalCount": 13235,
                    "data": [{"id": i, "title": f"Drama {i}", "episodesCount": 16} for i in range(1, 11)],
                }
            elif "page=2" in endpoint:
                # Trang 2 trả về 10 items trong đó id=10 bị trùng với trang 1
                items = [{"id": 10, "title": "Duplicate 10", "episodesCount": 16}]
                items.extend([{"id": i, "title": f"Drama {i}", "episodesCount": 16} for i in range(11, 20)])
                return {
                    "totalCount": 13235,
                    "data": items,
                }
            return {"totalCount": 13235, "data": []}

        with patch.object(provider, "_request_api", side_effect=mock_request):
            res = provider.get_catalog(page=1)
            # Tổng items: 10 trang 1 + 9 items mới trang 2 = 19 items
            self.assertEqual(len(res.items), 19)
            self.assertEqual(res.total, 13235)
            self.assertTrue(res.has_more)
            self.assertEqual(res.items[0].id, "1")
            self.assertEqual(res.items[-1].id, "19")

    def test_active_providers_registration_and_contracts(self):
        """Xác minh 11 providers được kích hoạt trong ACTIVE_PROVIDERS và tuân thủ hợp đồng Free-first."""
        active = providers.get_active_providers()
        active_ids = [p.platform_id for p in active]

        required_ids = [
            "dramabox",
            "kisskh",
            "hongguo",
            "goodshort",
            "shortmax",
            "netshort",
            "freereels",
            "dramawave",
            "raptdrama",
            "flextv",
            "stardusttv",
        ]

        for req in required_ids:
            self.assertIn(req, active_ids, f"Provider '{req}' phải có trong ACTIVE_PROVIDERS")

        # Kiểm tra đầy đủ contract methods trên toàn bộ 11 provider
        for p in active:
            self.assertTrue(callable(getattr(p, "can_handle", None)))
            self.assertTrue(callable(getattr(p, "match_url", None)))
            self.assertTrue(callable(getattr(p, "load_catalog", None)))
            self.assertTrue(callable(getattr(p, "get_catalog", None)))
            self.assertTrue(callable(getattr(p, "search", None)))
            self.assertTrue(callable(getattr(p, "load_series", None)))
            self.assertTrue(callable(getattr(p, "resolve_stream", None)))
            self.assertTrue(callable(getattr(p, "resolve_episode_stream", None)))
            self.assertTrue(callable(getattr(p, "get_subtitle", None)))
            self.assertTrue(callable(getattr(p, "authenticate", None)))
            self.assertTrue(callable(getattr(p, "refresh_session", None)))
            self.assertTrue(callable(getattr(p, "validate_entitlement", None)))

            # Test locked episode protection: resolve_stream PHẢI trả về None và không gọi mạng
            locked_ep = Episode(
                num=5,
                title="Tập 5",
                url="https://example.com/locked",
                direct_url="https://cdn.example.com/locked.mp4",
                locked=True,
                access_state=ACCESS_STATE_REQUIRES_VIP,
                provider_id=p.platform_id,
            )
            self.assertIsNone(
                p.resolve_episode_stream(locked_ep),
                f"{p.display_name} không được phép giải mã tập VIP/locked!",
            )
            self.assertIsNone(
                p.resolve_stream(locked_ep),
                f"{p.display_name} resolve_stream phải trả về None cho tập VIP/locked!",
            )
            self.assertFalse(p.validate_entitlement(locked_ep))

    def test_browse_widget_append_and_status(self):
        """DramaBrowseWidget hỗ trợ nút Tải thêm, append mode giữ card cũ, và cập nhật status hiển thị."""
        from PySide6.QtWidgets import QApplication
        from drama_browse_widget import DramaBrowseWidget, CatalogWorker

        app = QApplication.instance() or QApplication([])

        with patch.object(CatalogWorker, "start"):
            widget = DramaBrowseWidget()

            # Kiểm tra nút tải thêm tồn tại
            self.assertTrue(hasattr(widget, "btn_load_more"))
            self.assertIsNotNone(widget.btn_load_more)

            # Giả lập kết quả nạp trang 1
            res1 = CatalogResult(
                items=[
                    CatalogItem("id1", "Phim 1", "", 10, "Desc 1", "https://link/1", "dramabox"),
                    CatalogItem("id2", "Phim 2", "", 20, "Desc 2", "https://link/2", "dramabox"),
                ],
                total=100,
                platform="dramabox",
                page=1,
                has_more=True,
            )

            widget._catalog_gen = 1
            widget._is_append = False
            widget._on_catalog_ready(1, res1)

            self.assertEqual(len(widget._loaded_series_ids), 2)
            self.assertEqual(widget.grid_layout.count(), 2)
            self.assertIn("Đang hiển thị 2 / 100", widget.lbl_status.text())
            self.assertTrue(widget.btn_load_more.isEnabled())
            self.assertTrue(widget.btn_next.isEnabled())
            self.assertFalse(widget.btn_prev.isEnabled())

            # Giả lập nạp thêm trang 2 (append mode)
            res2 = CatalogResult(
                items=[
                    CatalogItem("id2", "Phim 2 trùng", "", 20, "Desc 2", "https://link/2", "dramabox"),
                    CatalogItem("id3", "Phim 3", "", 30, "Desc 3", "https://link/3", "dramabox"),
                ],
                total=100,
                platform="dramabox",
                page=2,
                has_more=True,
            )

            widget._catalog_gen = 2
            widget._is_append = True
            widget._on_catalog_ready(2, res2)

            # id2 bị lọc trùng, chỉ thêm id3 -> tổng 3 phim
            self.assertEqual(len(widget._loaded_series_ids), 3)
            self.assertEqual(widget.grid_layout.count(), 3)
            self.assertIn("Đang hiển thị 3 / 100", widget.lbl_status.text())

            # Giả lập kết quả cũ (stale generation) phải bị bỏ qua
            old_res = CatalogResult(
                items=[CatalogItem("stale", "Phim Cũ", "", 1, "", "", "dramabox")],
                total=100,
                platform="dramabox",
                page=1,
                has_more=True,
            )
            widget._on_catalog_ready(1, old_res)
            # Số lượng không đổi
            self.assertEqual(len(widget._loaded_series_ids), 3)

            widget.shutdown()
            widget.deleteLater()
            app.processEvents()


if __name__ == "__main__":
    unittest.main()
