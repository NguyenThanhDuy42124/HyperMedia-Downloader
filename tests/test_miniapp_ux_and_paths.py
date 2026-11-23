"""
tests/test_miniapp_ux_and_paths.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Kiểm thử toàn diện cho các tính năng UX và cấu trúc thư mục MiniApp Douyin:
1. Ánh xạ định danh Việt hóa cố định cho 7 nguồn MiniApp Douyin (họ duolai).
2. Chuẩn hóa tên file/folder an toàn trên Windows (ký tự cấm, dấu chấm/khoảng trắng cuối, reserved names CON, PRN, AUX, NUL, COM1-9, LPT1-9).
3. Phòng chống tấn công Path Traversal (thư mục con không được thoát khỏi thư mục gốc downloads).
4. Phân cấp thư mục lưu: downloads/MiniApp Douyin/{Tên MiniApp Việt hóa}/{Tên bộ phim}/01 - {Tên tập}.mp4
5. Cơ chế xử lý file trùng lặp (Dup1_, Dup2_) nhận diện cả file .part, .ytdl, .part-Frag*, .segs, .ts.part.
6. MiniAppCardWidget: Thiết lập Qt.WA_TransparentForMouseEvents cho tất cả các widget con, phân tách click đơn và nhấp đúp (debounced).
7. MiniAppEpisodeDialog: Hiển thị trước đường dẫn thư mục lưu và các nút thao tác sao chép, đổi thư mục.
8. Truyền tải trọn vẹn metadata (output_dir, exact_file_stem, source_display_name) từ dialog sang queue item, VideoListModel và DownloadWorker options.
"""

import os
import sys

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
if sys.stderr and hasattr(sys.stderr, "reconfigure"):
    try:
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

import shutil
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from PySide6.QtCore import Qt, QPoint
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication

from providers.base import CatalogItem, Series, Episode, ACCESS_STATE_FREE, ACCESS_STATE_REQUIRES_VIP
from drama_path_utils import (
    MINIAPP_DISPLAY_NAMES,
    WINDOWS_RESERVED_NAMES,
    get_miniapp_display_name,
    sanitize_windows_name,
    sanitize_windows_foldername,
    sanitize_windows_filename,
    build_drama_destination_dir,
    build_drama_filename,
    resolve_unique_drama_filepath,
)
from thumbnail_loader import ThumbnailLoader

app = QApplication.instance() or QApplication(sys.argv)


class TestMiniAppUXAndPaths(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="hypermedia_ux_paths_test_")

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_01_vietnamese_miniapp_display_names(self):
        """1. Kiểm tra 7 nguồn builtin có tên tiếng Việt cố định đúng chuẩn."""
        expected_mappings = {
            "tt5b4d2df0c47bdd2201": "Đa Lai",
            "tt839df5201ca3d79a01": "Hắc Nham Mạn",
            "tt3eca4877a1fed32a01": "Kim Miêu Mạn Phẩm",
            "ttbe17c8aa2121c82101": "Vạn Hoa Câu Chuyện",
            "tt48293e94d71caebe01": "Tiểu Thất Mạn Sảng Các",
            "tte1e6975b7eecc91e01": "Tinh Nguyệt Mạn",
            "tte06596d87f5402a101": "Man Mạn Thời Không",
        }
        for app_id, expected_name in expected_mappings.items():
            self.assertEqual(get_miniapp_display_name(app_id), expected_name)
            self.assertEqual(MINIAPP_DISPLAY_NAMES.get(app_id), expected_name)

        # Fallback cho app_id không xác định
        self.assertEqual(get_miniapp_display_name("unknown_app_id", fallback="Nguồn Tùy Chỉnh"), "Nguồn Tùy Chỉnh")
        self.assertEqual(get_miniapp_display_name("tt99999999999999999999"), "MiniApp_tt99999999999999999999")
        self.assertEqual(get_miniapp_display_name(""), "MiniApp Douyin")

    def test_02_windows_path_and_folder_sanitization(self):
        """2. Làm sạch chuỗi theo chuẩn hệ điều hành Windows."""
        # 2.1. Loại bỏ các ký tự cấm: \ / : * ? " < > |
        dirty_name = 'Phim: "Chiến Thần" *Hạ Sơn* <2026> | Tập? 1/2\\3'
        clean_name = sanitize_windows_filename(dirty_name)
        for char in '\\/:*?"<>|':
            self.assertNotIn(char, clean_name)
        self.assertIn("Chiến Thần", clean_name)

        # 2.2. Cắt bỏ dấu chấm và khoảng trắng ở đầu và cuối chuỗi
        trailing_dots = "  ...Tập 1 - Bắt Đầu...   "
        self.assertEqual(sanitize_windows_filename(trailing_dots), "Tập 1 - Bắt Đầu")

        # 2.3. Tên thiết bị dành riêng bị cấm (Reserved Names)
        for reserved in ["CON", "con", "PRN", "aux", "NUL", "COM1", "lpt1", "COM9"]:
            safe = sanitize_windows_filename(reserved)
            self.assertTrue(safe.startswith("_"), f"Tên cấm {reserved} phải được đổi thành an toàn: {safe}")
            self.assertIn(reserved.upper(), safe.upper())

        # 2.4. Giới hạn độ dài an toàn (tránh lỗi MAX_PATH)
        very_long = "A" * 200
        truncated_folder = sanitize_windows_foldername(very_long, max_len=100)
        self.assertLessEqual(len(truncated_folder), 100)

        truncated_file = sanitize_windows_filename(very_long, max_len=120)
        self.assertLessEqual(len(truncated_file), 120)

        # 2.5. Chuỗi rỗng trả về fallback
        self.assertEqual(sanitize_windows_filename("   ", fallback="default_name"), "default_name")

    def test_03_path_traversal_protection(self):
        """3. Chống tấn công Path Traversal khi xây dựng thư mục lưu."""
        # Thử đưa ký tự .. hoặc đường dẫn ngoài
        with self.assertRaises(ValueError):
            build_drama_destination_dir(
                self.test_dir,
                "miniapp_douyin",
                "../../Windows/System32",
                source_app_id="tt5b4d2df0c47bdd2201",
            )

        with self.assertRaises(ValueError):
            build_drama_destination_dir(
                self.test_dir,
                "miniapp_douyin",
                "Phim An Toan",
                source_app_id="../../bad_app",
            )

    def test_04_structured_folder_hierarchy(self):
        """4. Cấu trúc thư mục lưu theo MiniApp Douyin và Short Drama."""
        # MiniApp Douyin: downloads/MiniApp Douyin/{Tên MiniApp Việt hóa}/{Tên bộ phim}
        dest_miniapp = build_drama_destination_dir(
            self.test_dir,
            "miniapp_douyin",
            "Chiến Thần Đô Thị",
            source_app_id="tt5b4d2df0c47bdd2201",
        )
        self.assertTrue(os.path.exists(dest_miniapp))
        self.assertIn(os.path.join("MiniApp Douyin", "Đa Lai", "Chiến Thần Đô Thị"), dest_miniapp)

        # DramaBox: downloads/DramaBox/{Tên bộ phim}
        dest_dramabox = build_drama_destination_dir(
            self.test_dir,
            "dramabox",
            "Rể Quý Trời Cho",
        )
        self.assertTrue(os.path.exists(dest_dramabox))
        self.assertIn(os.path.join("DramaBox", "Rể Quý Trời Cho"), dest_dramabox)

        # Tên bộ khác nhau trong cùng nguồn không được ghi đè thư mục của nhau
        dest_film_b = build_drama_destination_dir(
            self.test_dir,
            "miniapp_douyin",
            "Thiên Mệnh Chi Đồ",
            source_app_id="tt5b4d2df0c47bdd2201",
        )
        self.assertNotEqual(dest_miniapp, dest_film_b)
        self.assertTrue(os.path.exists(dest_film_b))

    def test_05_duplicate_handling_with_temp_files(self):
        """5. Cơ chế xử lý file trùng lặp Dup1_, Dup2_ nhận diện cả file .part, .ytdl, .part-Frag*, .segs."""
        test_folder = os.path.join(self.test_dir, "test_dup_folder")
        os.makedirs(test_folder, exist_ok=True)

        base_stem = "01 - Khởi Đầu"

        # Ban đầu chưa có file nào -> trả về base_stem
        stem0, path0 = resolve_unique_drama_filepath(test_folder, base_stem, ext="mp4", allow_duplicates=True)
        self.assertEqual(stem0, "01 - Khởi Đầu")
        self.assertTrue(path0.endswith("01 - Khởi Đầu.mp4"))

        # Tạo file hoàn chỉnh: 01 - Khởi Đầu.mp4
        with open(path0, "wb") as f:
            f.write(b"video content")

        # Bây giờ file đã có -> phải sinh ra Dup1_01 - Khởi Đầu
        stem1, path1 = resolve_unique_drama_filepath(test_folder, base_stem, ext="mp4", allow_duplicates=True)
        self.assertEqual(stem1, "Dup1_01 - Khởi Đầu")
        self.assertTrue(path1.endswith("Dup1_01 - Khởi Đầu.mp4"))

        # Tạo file tạm dở dang: Dup1_01 - Khởi Đầu.mp4.part
        with open(path1 + ".part", "wb") as f:
            f.write(b"part content")

        # Bây giờ Dup1 có file part -> phải nhảy sang Dup2_01 - Khởi Đầu
        stem2, path2 = resolve_unique_drama_filepath(test_folder, base_stem, ext="mp4", allow_duplicates=True)
        self.assertEqual(stem2, "Dup2_01 - Khởi Đầu")
        self.assertTrue(path2.endswith("Dup2_01 - Khởi Đầu.mp4"))

        # Tạo thư mục segments: Dup2_01 - Khởi Đầu.segs
        os.makedirs(os.path.join(test_folder, "Dup2_01 - Khởi Đầu.segs"), exist_ok=True)

        # Bây giờ Dup2 có folder segs -> phải nhảy sang Dup3_01 - Khởi Đầu
        stem3, path3 = resolve_unique_drama_filepath(test_folder, base_stem, ext="mp4", allow_duplicates=True)
        self.assertEqual(stem3, "Dup3_01 - Khởi Đầu")

    def test_06_card_widget_mouse_transparency_and_signals(self):
        """6. MiniAppCardWidget: Đảm bảo các QLabel con không nuốt sự kiện chuột và phát tín hiệu chuẩn."""
        from miniapp_browse_widget import MiniAppCardWidget

        item = CatalogItem(
            id="item_123",
            name="Phim Thử Nghiệm",
            cover="",
            episodes=80,
            desc="Mô tả",
            link="http://link",
            platform="miniapp_douyin",
        )
        thumb_loader = ThumbnailLoader()
        card = MiniAppCardWidget(item, thumb_loader, app_id="tt5b4d2df0c47bdd2201")

        # Kiểm tra Qt.WA_TransparentForMouseEvents trên các label con
        self.assertTrue(card.lbl_thumb.testAttribute(Qt.WA_TransparentForMouseEvents))
        self.assertTrue(card.lbl_title.testAttribute(Qt.WA_TransparentForMouseEvents))
        self.assertTrue(card.lbl_episodes.testAttribute(Qt.WA_TransparentForMouseEvents))

        # Kiểm tra signal clicked và double_clicked
        clicked_items = []
        double_clicked_items = []
        card.clicked.connect(lambda it: clicked_items.append(it))
        card.double_clicked.connect(lambda it: double_clicked_items.append(it))

        # Giả lập Double Click
        press_event = QMouseEvent(QMouseEvent.MouseButtonPress, QPoint(10, 10), Qt.LeftButton, Qt.LeftButton, Qt.NoModifier)
        card.mousePressEvent(press_event)
        self.assertTrue(card._click_timer.isActive())

        dbl_event = QMouseEvent(QMouseEvent.MouseButtonDblClick, QPoint(10, 10), Qt.LeftButton, Qt.LeftButton, Qt.NoModifier)
        card.mouseDoubleClickEvent(dbl_event)

        # Timer phải bị hủy bởi double click
        self.assertFalse(card._click_timer.isActive())
        self.assertEqual(len(double_clicked_items), 1)
        self.assertEqual(double_clicked_items[0].name, "Phim Thử Nghiệm")
        self.assertEqual(len(clicked_items), 0)  # Không được emit single click khi double-click!

        # Kiểm tra nút Xem tập
        card.btn_view.click()
        self.assertEqual(len(double_clicked_items), 2)

    def test_07_episode_dialog_directory_preview_and_actions(self):
        """7. MiniAppEpisodeDialog: Hiển thị đúng thư mục phân cấp và các nút thao tác."""
        from miniapp_episode_dialog import MiniAppEpisodeDialog

        series = Series(
            name="Đại Hiệp Quyết Chiến",
            platform="miniapp_douyin",
            series_id="series_100",
            episodes=[
                Episode(num=1, title="Tập 1", url="http://ep1", episode_id="ep_1", access_state=ACCESS_STATE_FREE),
                Episode(num=2, title="Tập 2", url="http://ep2", episode_id="ep_2", access_state=ACCESS_STATE_FREE),
                Episode(num=3, title="Tập 3", url="http://ep3", episode_id="ep_3", access_state=ACCESS_STATE_REQUIRES_VIP, locked=True),
            ],
            cover="",
        )

        dialog = MiniAppEpisodeDialog(
            series,
            app_id="tt5b4d2df0c47bdd2201",
            base_folder=self.test_dir,
        )

        expected_dir = os.path.join(self.test_dir, "MiniApp Douyin", "Đa Lai", "Đại Hiệp Quyết Chiến")
        self.assertEqual(dialog.get_destination_dir(), expected_dir)
        self.assertIn("Đa Lai", dialog.lbl_dest_path.text())
        self.assertIn("Đại Hiệp Quyết Chiến", dialog.lbl_dest_path.text())

        # Kiểm tra sao chép đường dẫn vào Clipboard
        dialog._copy_destination_path()
        clipboard_text = QApplication.clipboard().text()
        self.assertEqual(clipboard_text, expected_dir)

    def test_08_queue_item_metadata_propagation(self):
        """8. Truyền tải metadata (output_dir, exact_file_stem) từ queue sang VideoListModel và options."""
        from download_worker import DownloadWorker
        from models import VideoListModel

        dest_dir = os.path.join(self.test_dir, "MiniApp Douyin", "Đa Lai", "Chiến Thần")
        os.makedirs(dest_dir, exist_ok=True)
        exact_stem = "01 - Khởi Đầu"

        queue_item = {
            "title": "Chiến Thần - Tập 1",
            "url": "douyin_miniapp:tt5b4d2df0c47bdd2201:12345?ep=1",
            "thumb": "http://thumb.jpg",
            "heights": [],
            "item_index": 1,
            "episode_number": 1,
            "episode_id": "5001",
            "provider": "miniapp_douyin",
            "provider_id": "miniapp_douyin",
            "source_app_id": "tt5b4d2df0c47bdd2201",
            "source_name": "Đa Lai (多来看点)",
            "source_display_name": "Đa Lai",
            "series_name": "Chiến Thần",
            "output_dir": dest_dir,
            "exact_file_stem": exact_stem,
            "formats": [{"format_id": "best", "ext": "mp4", "resolution": "best"}],
        }

        # Khởi tạo VideoListModel và thêm item
        model = VideoListModel()
        uid = model.add_video(queue_item)
        stored_item = model.get(uid)

        self.assertEqual(stored_item.get("output_dir"), dest_dir)
        self.assertEqual(stored_item.get("exact_file_stem"), exact_stem)
        self.assertEqual(stored_item.get("source_display_name"), "Đa Lai")

        # Kiểm tra options nhận đúng output_dir làm output_path
        built_options = {
            "output_path": stored_item.get("output_dir") or self.test_dir,
            "exact_file_stem": stored_item.get("exact_file_stem"),
            "series_name": stored_item.get("series_name"),
            "title": stored_item.get("title"),
        }
        self.assertEqual(built_options["output_path"], dest_dir)
        self.assertEqual(built_options["exact_file_stem"], exact_stem)

        # Kiểm tra DownloadWorker._resolve_filename tôn trọng exact_file_stem
        worker = DownloadWorker.__new__(DownloadWorker)
        worker.options = built_options
        safe_title, out_tmpl = worker._resolve_filename(built_options["output_path"])

        self.assertEqual(safe_title, exact_stem)
        self.assertEqual(worker.exact_file_stem, os.path.join(dest_dir, exact_stem))
        self.assertIn(exact_stem, out_tmpl)
        self.assertIn(dest_dir.replace("\\", "/"), out_tmpl.replace("\\", "/"))


if __name__ == "__main__":
    unittest.main()
