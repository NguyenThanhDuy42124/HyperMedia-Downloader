"""
tests/test_miniapp_selection.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Kiểm thử lựa chọn tập phim và giao diện chọn tập cho MiniApp Douyin:
1. Phân loại tập Free vs VIP: tập Free cho phép chọn, tập VIP bị khóa (disabled, unchecked).
2. Kiểm tra tính năng 'Chọn tất cả tập Free' (select_free_only).
3. Kiểm tra lọc dải tập (ví dụ: '1-6') không cho phép chọn tập VIP.
4. Kiểm tra tính năng 'Bỏ chọn' (deselect_all).
5. Xác nhận MiniAppEpisodeDialog chỉ phát ra các tập Free hợp lệ kèm episode_id ổn định.
"""

import os
import sys
import unittest
from unittest.mock import MagicMock, patch

from PySide6.QtWidgets import QApplication

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from providers.base import (
    ACCESS_STATE_FREE,
    ACCESS_STATE_REQUIRES_VIP,
    Episode,
    Series,
    parse_episode_selection,
)
from providers.miniapp_douyin_provider import MiniAppDouyinProvider
from miniapp_episode_dialog import MiniAppEpisodeDialog


class TestMiniAppSelection(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(sys.argv)

    def setUp(self):
        self.provider = MiniAppDouyinProvider()
        # Series giả lập gồm 6 tập: tập 1, 2, 3, 5 là Free; tập 4, 6 là VIP
        self.mock_playlist = [
            {"id": "5001", "sequence_no": 1, "is_free": "T"},
            {"id": "5002", "sequence_no": 2, "is_free": "T"},
            {"id": "5003", "sequence_no": 3, "is_free": "T"},
            {"id": "5004", "sequence_no": 4, "is_free": "F"},
            {"id": "5005", "sequence_no": 5, "is_free": "T"},
            {"id": "5006", "sequence_no": 6, "is_free": "F"},
        ]

    def test_01_range_parsing(self):
        """1. Kiểm tra parse_episode_selection với cú pháp dải '1-3, 5'."""
        selected = parse_episode_selection("1-3, 5", max_ep=6)
        self.assertEqual(selected, [1, 2, 3, 5])

    def test_02_dialog_free_vs_vip_enforcement(self):
        """2. Dialog phân loại tập: Free enabled, VIP disabled và không thể tick."""
        with patch.object(self.provider.client, "load_playlist", return_value=(self.mock_playlist, None)):
            series = self.provider.load_series("douyin_miniapp:tt_app:12345")
            self.assertEqual(series.accessible_count, 4)

            dialog = MiniAppEpisodeDialog(series)

            # Tập 1, 2, 3, 5 phải enabled
            for num in [1, 2, 3, 5]:
                cb = dialog.episode_checkboxes[num]
                self.assertTrue(cb.isEnabled(), f"Tập Free {num} phải enabled")
                self.assertIn("[Free]", cb.text())

            # Tập 4, 6 phải disabled (VIP/Khóa)
            for num in [4, 6]:
                cb = dialog.episode_checkboxes[num]
                self.assertFalse(cb.isEnabled(), f"Tập VIP {num} phải disabled")
                self.assertFalse(cb.isChecked(), f"Tập VIP {num} không được phép checked")
                self.assertIn("[VIP]", cb.text())

    def test_03_select_free_only(self):
        """3. Nút 'Chọn tất cả tập Free' chỉ tick đúng các tập Free."""
        with patch.object(self.provider.client, "load_playlist", return_value=(self.mock_playlist, None)):
            series = self.provider.load_series("douyin_miniapp:tt_app:12345")
            dialog = MiniAppEpisodeDialog(series)

            # Bỏ chọn toàn bộ trước
            dialog._deselect_all()
            for cb in dialog.episode_checkboxes.values():
                self.assertFalse(cb.isChecked())

            # Bấm chọn tất cả tập Free
            dialog._select_free_only()

            # Kiểm tra trạng thái
            for num in [1, 2, 3, 5]:
                self.assertTrue(dialog.episode_checkboxes[num].isChecked())
            for num in [4, 6]:
                self.assertFalse(dialog.episode_checkboxes[num].isChecked())

    def test_04_range_filter_ignores_locked_episodes(self):
        """4. Áp dụng range '1-6' bỏ qua tập bị khóa, chỉ tick tập Free."""
        with patch.object(self.provider.client, "load_playlist", return_value=(self.mock_playlist, None)):
            series = self.provider.load_series("douyin_miniapp:tt_app:12345")
            dialog = MiniAppEpisodeDialog(series)

            dialog.txt_range.setText("1-6")
            dialog._apply_range_filter()

            self.assertTrue(dialog.episode_checkboxes[1].isChecked())
            self.assertTrue(dialog.episode_checkboxes[2].isChecked())
            self.assertTrue(dialog.episode_checkboxes[3].isChecked())
            self.assertFalse(dialog.episode_checkboxes[4].isChecked())  # Bị khóa!
            self.assertTrue(dialog.episode_checkboxes[5].isChecked())
            self.assertFalse(dialog.episode_checkboxes[6].isChecked())  # Bị khóa!

    def test_05_confirm_emits_only_free_episodes_with_stable_ids(self):
        """5. Bấm xác nhận phát tín hiệu danh sách tập Free kèm episode_id ổn định."""
        with patch.object(self.provider.client, "load_playlist", return_value=(self.mock_playlist, None)):
            series = self.provider.load_series("douyin_miniapp:tt_app:12345")
            dialog = MiniAppEpisodeDialog(series)

            dialog._select_free_only()

            emitted = []
            dialog.episodes_selected.connect(lambda eps: emitted.extend(eps))
            dialog._on_confirm()

            self.assertEqual(len(emitted), 4)
            self.assertEqual([e.num for e in emitted], [1, 2, 3, 5])
            self.assertEqual([e.episode_id for e in emitted], ["5001", "5002", "5003", "5005"])
            for e in emitted:
                self.assertEqual(e.access_state, ACCESS_STATE_FREE)
                self.assertFalse(e.locked)


if __name__ == "__main__":
    unittest.main()
