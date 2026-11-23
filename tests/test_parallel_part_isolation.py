"""
tests/test_parallel_part_isolation.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Kiểm thử cô lập file .part khi chạy nhiều tác vụ song song:
Chứng minh khi một worker bị treo hoặc terminate, hàm cleanup chỉ xóa file của chính nó,
tuyệt đối không xóa nhầm file .part của worker khác đang ghi.
"""

import os
import sys
import shutil
import tempfile
import unittest
from unittest.mock import MagicMock

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")


class MockWorker:
    def __init__(self, is_running=True):
        self._is_running = is_running

    def isRunning(self):
        return self._is_running

    def stop(self):
        self._is_running = False

    def requestInterruption(self):
        pass

    def quit(self):
        pass

    def wait(self, ms):
        return not self._is_running

    def terminate(self):
        self._is_running = False


class DummyApp:
    def __init__(self, save_folder, model=None, active=None):
        self.save_folder = save_folder
        self.model = model or MagicMock()
        self._active = active or {}

    _cleanup_part_files = None  # Will bind after import


class TestParallelPartIsolation(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        from main_window import YoutubeDownloaderApp
        DummyApp._cleanup_part_files = YoutubeDownloaderApp._cleanup_part_files

    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="hypermedia_test_parts_")
        self.part1 = os.path.join(self.test_dir, "Video Number One.mp4.part")
        self.part2 = os.path.join(self.test_dir, "Video Number Two.mp4.part")
        with open(self.part1, "wb") as f:
            f.write(b"data1" * 100)
        with open(self.part2, "wb") as f:
            f.write(b"data2" * 100)

    def tearDown(self):
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_cleanup_with_no_uid_deletes_nothing(self):
        """Khi uid=None, hàm cleanup phải return ngay, tuyệt đối không quét xóa toàn thư mục."""
        app = DummyApp(save_folder=self.test_dir)

        app._cleanup_part_files(uid=None)

        self.assertTrue(os.path.exists(self.part1), "part1 không được bị xóa khi uid=None")
        self.assertTrue(os.path.exists(self.part2), "part2 không được bị xóa khi uid=None")

    def test_parallel_task_terminated_does_not_delete_other_running_part(self):
        """Hai tác vụ song song: Task 1 bị terminate, cleanup(task_1) CHỈ xóa part1, giữ nguyên part2."""
        stem1 = os.path.join(self.test_dir, "Video Number One")
        stem2 = os.path.join(self.test_dir, "Video Number Two")

        mock_model = MagicMock()
        mock_model.get.side_effect = lambda uid: {
            "uid_1": {"title": "Video Number One", "exact_file_stem": stem1, "status": "downloading"},
            "uid_2": {"title": "Video Number Two", "exact_file_stem": stem2, "status": "downloading"},
        }.get(uid)

        worker2 = MockWorker(is_running=True)
        worker2.exact_file_stem = stem2
        worker1 = MockWorker(is_running=False)
        worker1.exact_file_stem = stem1

        app = DummyApp(
            save_folder=self.test_dir,
            model=mock_model,
            active={
                "uid_1": worker1,
                "uid_2": worker2,
            }
        )

        # Gọi cleanup cho uid_1
        app._cleanup_part_files(uid="uid_1")

        # Xác minh: part1 của task 1 đã bị xóa
        self.assertFalse(os.path.exists(self.part1), "File .part của task 1 phải được dọn dẹp sau khi terminate")
        # Xác minh: part2 của task 2 đang chạy VẪN NGUYÊN VẸN 100%
        self.assertTrue(os.path.exists(self.part2), "File .part của task 2 đang chạy tuyệt đối KHÔNG ĐƯỢC bị xóa!")

    def test_cleanup_skips_when_no_exact_file_stem(self):
        """Nếu UID không có exact_file_stem, hàm cleanup phải bỏ qua ngay, không tái tạo bừa bãi."""
        mock_model = MagicMock()
        mock_model.get.side_effect = lambda uid: {
            "uid_orphan": {"title": "Video Number One", "status": "stopped"},
        }.get(uid)

        app = DummyApp(save_folder=self.test_dir, model=mock_model, active={})
        app._cleanup_part_files(uid="uid_orphan")

        self.assertTrue(os.path.exists(self.part1), "File part không được bị xóa nếu UID thiếu exact_file_stem")

    def test_overlapping_title_aborts_cleanup_if_other_worker_active(self):
        """Nếu có worker khác đang chạy với exact_file_stem tương tự, cleanup phải hủy bỏ để bảo vệ an toàn."""
        shared_part = os.path.join(self.test_dir, "Series Tập 1 Phim Hay.mp4.part")
        with open(shared_part, "wb") as f:
            f.write(b"shared_data")

        shared_stem = os.path.join(self.test_dir, "Series Tập 1 Phim Hay")
        mock_model = MagicMock()
        mock_model.get.side_effect = lambda uid: {
            "uid_a": {"title": "Series Tập 1 Phim Hay", "exact_file_stem": shared_stem, "status": "stopped"},
            "uid_b": {"title": "Series Tập 1 Phim Hay", "exact_file_stem": shared_stem, "status": "downloading"},
        }.get(uid)

        worker_b = MockWorker(is_running=True)  # Vẫn đang ghi file
        worker_b.exact_file_stem = shared_stem
        app = DummyApp(
            save_folder=self.test_dir,
            model=mock_model,
            active={
                "uid_a": MockWorker(is_running=False),
                "uid_b": worker_b,
            }
        )

        app._cleanup_part_files(uid="uid_a")

        # Phải bảo toàn file vì uid_b đang chạy
        self.assertTrue(
            os.path.exists(shared_part),
            "Không được xóa file nếu có một tác vụ khác cùng exact stem đang hoạt động"
        )


    def test_similar_substring_file_not_deleted(self):
        """Khắc phục triệt để lỗi wildcard substring: File có tên tương tự không được bị xóa nhầm."""
        similar_part = os.path.join(self.test_dir, "Video Number One Extended.mp4.part")
        with open(similar_part, "wb") as f:
            f.write(b"extended_data")

        stem1 = os.path.join(self.test_dir, "Video Number One")
        mock_model = MagicMock()
        mock_model.get.side_effect = lambda uid: {
            "uid_1": {"title": "Video Number One", "exact_file_stem": stem1},
        }.get(uid)

        app = DummyApp(save_folder=self.test_dir, model=mock_model)
        app._cleanup_part_files(uid="uid_1")

        self.assertFalse(os.path.exists(self.part1), "File exact stem của task 1 phải bị xóa")
        self.assertTrue(os.path.exists(similar_part), "File có tên tương tự (Extended) tuyệt đối KHÔNG ĐƯỢC bị xóa nhầm!")

    def test_two_stopped_tasks_distinct_exact_stems_isolated(self):
        """Hai tác vụ đều đã stopped (không còn worker active), cleanup task 1 không xóa nhầm task 2."""
        ep1_part = os.path.join(self.test_dir, "Tập 1 - Phim Hay.mp4.part")
        ep2_part = os.path.join(self.test_dir, "Tập 2 - Phim Hay.mp4.part")
        with open(ep1_part, "wb") as f:
            f.write(b"ep1")
        with open(ep2_part, "wb") as f:
            f.write(b"ep2")

        stem1 = os.path.join(self.test_dir, "Tập 1 - Phim Hay")
        stem2 = os.path.join(self.test_dir, "Tập 2 - Phim Hay")

        mock_model = MagicMock()
        mock_model.get.side_effect = lambda uid: {
            "uid_ep1": {"title": "Phim Hay", "exact_file_stem": stem1, "status": "stopped"},
            "uid_ep2": {"title": "Phim Hay", "exact_file_stem": stem2, "status": "stopped"},
        }.get(uid)

        # Cả hai tác vụ đều không còn trong _active
        app = DummyApp(save_folder=self.test_dir, model=mock_model, active={})
        app._cleanup_part_files(uid="uid_ep1")

        self.assertFalse(os.path.exists(ep1_part), "ep1_part phải được xóa")
        self.assertTrue(os.path.exists(ep2_part), "ep2_part của task đã stopped KHÔNG ĐƯỢC bị xóa vì exact stem khác nhau!")

    def test_task_hard_killed_while_writing_cleans_own_frag_parts(self):
        """Task bị hard-kill khi đang ghi nhiều fragment: cleanup dọn đúng các file fragment của nó, không đụng task khác."""
        frag_a0 = os.path.join(self.test_dir, "Video A.mp4.part-Frag0")
        frag_a1 = os.path.join(self.test_dir, "Video A.mp4.part-Frag1")
        frag_b0 = os.path.join(self.test_dir, "Video B.mp4.part-Frag0")
        for f in (frag_a0, frag_a1, frag_b0):
            with open(f, "wb") as fp:
                fp.write(b"frag")

        stem_a = os.path.join(self.test_dir, "Video A")
        stem_b = os.path.join(self.test_dir, "Video B")

        mock_model = MagicMock()
        mock_model.get.side_effect = lambda uid: {
            "uid_a": {"title": "Video A", "exact_file_stem": stem_a, "status": "stopped"},
            "uid_b": {"title": "Video B", "exact_file_stem": stem_b, "status": "downloading"},
        }.get(uid)

        worker_b = MockWorker(is_running=True)
        worker_b.exact_file_stem = stem_b

        app = DummyApp(
            save_folder=self.test_dir,
            model=mock_model,
            active={"uid_b": worker_b}
        )

        app._cleanup_part_files(uid="uid_a")

        self.assertFalse(os.path.exists(frag_a0), "Fragment 0 của Task A phải được dọn")
        self.assertFalse(os.path.exists(frag_a1), "Fragment 1 của Task A phải được dọn")
        self.assertTrue(os.path.exists(frag_b0), "Fragment của Task B tuyệt đối không được bị xóa!")

    def test_target_file_exists_leaves_other_task_part_untouched(self):
        """File đích hoàn chỉnh tồn tại nhưng .part của task khác đang tải không được bị xóa."""
        target_finished = os.path.join(self.test_dir, "Video Number One.mp4")
        with open(target_finished, "wb") as f:
            f.write(b"complete_video_data")

        stem1 = os.path.join(self.test_dir, "Video Number One")
        stem2 = os.path.join(self.test_dir, "Video Number Two")

        mock_model = MagicMock()
        mock_model.get.side_effect = lambda uid: {
            "uid_1": {"title": "Video Number One", "exact_file_stem": stem1, "status": "finished"},
            "uid_2": {"title": "Video Number Two", "exact_file_stem": stem2, "status": "downloading"},
        }.get(uid)

        worker2 = MockWorker(is_running=True)
        worker2.exact_file_stem = stem2

        app = DummyApp(save_folder=self.test_dir, model=mock_model, active={"uid_2": worker2})
        app._cleanup_part_files(uid="uid_1")

        self.assertTrue(os.path.exists(target_finished), "File đích đã hoàn thành phải được giữ nguyên")
        self.assertTrue(os.path.exists(self.part2), "File .part của task 2 đang tải tuyệt đối không được bị xóa")

    def test_worker_cleanup_my_part_files_without_stem_skips_deletion(self):
        """Worker._cleanup_my_part_files nếu thiếu exact_file_stem thì bỏ qua, không xóa file tạm nào."""
        from download_worker import DownloadWorker
        worker = DownloadWorker.__new__(DownloadWorker)
        worker.exact_file_stem = None
        worker.options = {"title": "Video Number One"}

        worker._cleanup_my_part_files(self.test_dir)

        self.assertTrue(os.path.exists(self.part1), "File part1 không được bị xóa khi worker thiếu exact_file_stem")
        self.assertTrue(os.path.exists(self.part2), "File part2 không được bị xóa khi worker thiếu exact_file_stem")


if __name__ == "__main__":
    unittest.main()
