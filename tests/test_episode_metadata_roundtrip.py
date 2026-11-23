"""
tests/test_episode_metadata_roundtrip.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Kiểm thử bảo toàn metadata qua hàng đợi UI, serialize/deserialize session và retry:
- Queue serialize/deserialize (save_session / load_session) không làm mất provider, episode_id, access_state, output_dir, exact_file_stem.
- _on_drama_episodes_queued -> VideoListModel -> _build_options giữ nguyên metadata và KHÔNG dùng index queue thay cho episode_id/episode_number.
- Retry queue item giữ nguyên episode identity.
"""

import os
import sys
import tempfile
import unittest
from unittest.mock import patch

os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import session_store
from models import VideoListModel


class TestEpisodeMetadataRoundtrip(unittest.TestCase):

    def test_01_session_serialize_deserialize_preserves_drama_metadata(self):
        """2. Queue serialize/deserialize không mất provider, episode_id, access_state và lọc bỏ Cookie nhạy cảm."""
        with tempfile.TemporaryDirectory() as td:
            sess_file = os.path.join(td, "session.json")
            with patch.object(session_store, "_session_path", return_value=sess_file):
                original_items = [
                    {
                        "title": "Phim Hongguo - Tập 3",
                        "url": "https://hongguoduanju.com/player/7503745441910017049?vid=ep_7503_3&ep=3",
                        "thumb_url": "https://img.test/p.jpg",
                        "provider": "hongguo",
                        "provider_id": "hongguo",
                        "platform": "hongguo",
                        "source_name": "Hongguo / Fanqie",
                        "series_id": "hongguo:7503745441910017049",
                        "series_name": "Phim Hongguo",
                        "episode_id": "ep_7503_3",
                        "episode_number": 3,
                        "access_state": "free",
                        "locked": False,
                        "source_url": "https://hongguoduanju.com/player/7503745441910017049?vid=ep_7503_3&ep=3",
                        "output_dir": os.path.join(td, "HongGuo", "Phim Hongguo"),
                        "exact_file_stem": "03 - Tập 3",
                        "headers": {"Referer": "https://hongguoduanju.com/", "Cookie": "secret=123", "Authorization": "Bearer abc"},
                        "extra": {"vid": "ep_7503_3", "series_id": "7503745441910017049"},
                    }
                ]
                session_store.save_session(original_items)
                loaded = session_store.load_session()

            self.assertEqual(len(loaded), 1)
            item = loaded[0]
            self.assertEqual(item["provider"], "hongguo")
            self.assertEqual(item["platform"], "hongguo")
            self.assertEqual(item["series_id"], "hongguo:7503745441910017049")
            self.assertEqual(item["episode_id"], "ep_7503_3")
            self.assertEqual(item["episode_number"], 3)
            self.assertEqual(item["access_state"], "free")
            self.assertFalse(item["locked"])
            self.assertEqual(item["exact_file_stem"], "03 - Tập 3")
            self.assertEqual(item["extra"]["vid"], "ep_7503_3")
            self.assertEqual(item["headers"].get("Referer"), "https://hongguoduanju.com/")
            self.assertNotIn("Cookie", item["headers"])
            self.assertNotIn("Authorization", item["headers"])

    def test_02_queue_model_and_retry_preserve_episode_identity(self):
        """12. _on_drama_episodes_queued -> model -> retry giữ nguyên provider, episode_id và episode_number (không dùng row index)."""
        from main_window import YoutubeDownloaderApp

        with tempfile.TemporaryDirectory() as td:
            # Dùng YoutubeDownloaderApp nhẹ bằng mock save_folder + model để kiểm tra roundtrip thực tế
            win = YoutubeDownloaderApp.__new__(YoutubeDownloaderApp)
            win.save_folder = td
            win.model = VideoListModel()
            win.thumb_pool = type("P", (), {"request": lambda *a, **k: None})()
            win._custom_metadata = {}
            win._active = {}
            win._pending_uids = []
            win._retry_counts = {}
            win._is_downloading = False
            win._stop_requested = False

            # Dummy UI widgets used by _on_drama_episodes_queued / _build_options / retry_single_item
            win.tabs = type("T", (), {"setCurrentIndex": lambda *a: None})()
            win.status_label = type("L", (), {"setText": lambda *a: None})()
            win.video_list = type("V", (), {"scrollTo": lambda *a: None})()
            win.view = type("VW", (), {"viewport": lambda *a: type("VP", (), {"update": lambda *a: None})()})()
            win.chk_av1_trick = type("C", (), {"isChecked": lambda *a: False})()
            win.chk_prefix = type("C", (), {"isChecked": lambda *a: False})()
            win.chk_allow_dup = type("C", (), {"isChecked": lambda *a: True})()
            win.chk_skip = type("C", (), {"isChecked": lambda *a: False})()
            win.browser_cb = type("B", (), {"currentText": lambda *a: "Auto"})()
            win.threads_sb = type("S", (), {"value": lambda *a: 4})()
            win.chunk_cb = type("B", (), {"currentText": lambda *a: "Tự động (10MB)"})()
            win.parallel_sb = type("S", (), {"value": lambda *a: 2})()

            # Giả lập: item 0 là YouTube, item 1 trong queue là Tập 5 của Hongguo!
            win.add_item("YT Video", "https://youtube.com/watch?v=abc", "", [])
            win._on_drama_episodes_queued([
                {
                    "title": "Phim X - Tập 5",
                    "url": "https://hongguoduanju.com/player/750999?vid=vid_ep5&ep=5",
                    "thumb": "",
                    "heights": [],
                    "provider": "hongguo",
                    "provider_id": "hongguo",
                    "platform": "hongguo",
                    "source_name": "Hongguo / Fanqie",
                    "series_id": "hongguo:750999",
                    "series_name": "Phim X",
                    "episode_id": "vid_ep5",
                    "episode_number": 5,
                    "access_state": "free",
                    "locked": False,
                    "output_dir": os.path.join(td, "HongGuo", "Phim X"),
                    "exact_file_stem": "05 - Tập 5",
                    "headers": {"Referer": "https://hongguoduanju.com/"},
                    "extra": {"vid": "vid_ep5", "series_id": "750999"},
                }
            ], "Phim X")

            uids = win.model.uids()
            self.assertEqual(len(uids), 2)
            ep5_uid = uids[1]  # row index = 1 (sẽ là 2 nếu tính 1-based!), nhưng episode_number phải là 5!
            item = win.model.get(ep5_uid)
            opts = win._build_options(item)

            self.assertEqual(opts["provider"], "hongguo")
            self.assertEqual(opts["episode_id"], "vid_ep5")
            self.assertEqual(opts["episode_number"], 5)
            self.assertEqual(opts["access_state"], "free")
            self.assertEqual(opts["extra"]["vid"], "vid_ep5")

            # Retry không làm mất identity tập 5
            with patch.object(win, "_start_queue"):
                win.retry_single_item(ep5_uid)
            retried_item = win.model.get(ep5_uid)
            retried_opts = win._build_options(retried_item)
            self.assertEqual(retried_opts["provider"], "hongguo")
            self.assertEqual(retried_opts["episode_id"], "vid_ep5")
            self.assertEqual(retried_opts["episode_number"], 5)


if __name__ == "__main__":
    unittest.main()
