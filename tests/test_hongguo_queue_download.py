"""
tests/test_hongguo_queue_download.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Kiểm thử hợp đồng queue -> resolve -> download cho Hongguo Web, Kylin và NovelQuickApp:
- Hongguo Free episode tạo queue item đầy đủ metadata (không double .mp4, đúng cấu trúc thư mục).
- Hongguo resolver trả direct MP4 (hỗ trợ fallback-play-info, Modern.js player_(series_id)/page, NDJSON, Spade decryption, refresh URL hết hạn, từ chối HTML/detail URL).
- Kylin resolver giữ đúng chapter_id.
- NovelQuickApp resolver giữ đúng video_id.
- Exact stem đúng output path: downloads/HongGuo/{Tên bộ phim}/01 - {Tên tập}.mp4
"""

import base64
import hashlib
import json
import os
import sys
import tempfile
import time
import unittest
from unittest.mock import MagicMock, patch

os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from PySide6.QtWidgets import QApplication
app = QApplication.instance() or QApplication(sys.argv)

from providers.base import ACCESS_STATE_FREE, ACCESS_STATE_REQUIRES_VIP, Episode, Series
from providers.crypto_utils import SPADE_CONSTANTS
from providers.hongguo_provider import HongguoProvider
from drama_browse_widget import DramaBrowseWidget
from download_worker import DownloadWorker


class TestHongguoQueueDownload(unittest.TestCase):

    def test_01_hongguo_free_episode_creates_full_queue_item_and_clean_path(self):
        """1 & 13. Hongguo Free episode tạo queue item đầy đủ và exact_file_stem không bị lỗi .mp4.mp4."""
        with tempfile.TemporaryDirectory() as td:
            widget = DramaBrowseWidget()
            try:
                fake_win = MagicMock()
                fake_win.save_folder = td
                series = Series(
                    name="Thiên Đế Trở Về",
                    platform="hongguo",
                    series_id="hongguo:7503745441910017049",
                    cover="https://img.test/hg.jpg",
                    episode_count=2,
                    accessible_count=1,
                    episodes=[
                        Episode(
                            num=1,
                            title="Tập 1",
                            url="https://hongguoduanju.com/player/7503745441910017049?vid=7503780574541122622&ep=1",
                            thumb="https://img.test/hg.jpg",
                            locked=False,
                            provider_id="hongguo",
                            series_id="hongguo:7503745441910017049",
                            episode_id="7503780574541122622",
                            episode_number=1,
                            access_state=ACCESS_STATE_FREE,
                            extra={"vid": "7503780574541122622", "series_id": "7503745441910017049"},
                        ),
                        Episode(
                            num=2,
                            title="Tập 2 VIP",
                            url="https://hongguoduanju.com/player/7503745441910017049?vid=7503780574541122623&ep=2",
                            locked=True,
                            provider_id="hongguo",
                            series_id="hongguo:7503745441910017049",
                            episode_id="7503780574541122623",
                            episode_number=2,
                            access_state=ACCESS_STATE_REQUIRES_VIP,
                        ),
                    ],
                )

                captured = []
                widget.queue_episodes_requested.connect(lambda items, sname: captured.append((items, sname)))

                with patch.object(widget, "window", return_value=fake_win), \
                     patch("drama_browse_widget.QMessageBox.information"):
                    widget._on_episodes_selected(series.episodes, series)

                self.assertEqual(len(captured), 1)
                q_items, sname = captured[0]
                self.assertEqual(len(q_items), 1)  # Chỉ 1 tập Free, chặn tập VIP
                it = q_items[0]

                self.assertEqual(it["provider"], "hongguo")
                self.assertEqual(it["platform"], "hongguo")
                self.assertEqual(it["series_id"], "hongguo:7503745441910017049")
                self.assertEqual(it["episode_id"], "7503780574541122622")
                self.assertEqual(it["episode_number"], 1)
                self.assertEqual(it["access_state"], "free")
                self.assertFalse(it["locked"])
                self.assertTrue(os.path.isdir(it["output_dir"]))
                self.assertIn("HongGuo", it["output_dir"])
                self.assertEqual(it["exact_file_stem"], "01 - Tập 1")
                self.assertNotIn(".mp4", it["exact_file_stem"])
                self.assertIn("Referer", it["headers"])
                self.assertEqual(it["extra"]["vid"], "7503780574541122622")

                # Kiểm tra DownloadWorker tạo outtmpl chuẩn
                w = DownloadWorker(it["url"], {"output_path": it["output_dir"], "exact_file_stem": it["exact_file_stem"]})
                _, out_tmpl = w._resolve_filename(it["output_dir"])
                self.assertTrue(out_tmpl.endswith("01 - Tập 1.%(ext)s"))
                self.assertNotIn(".mp4.%(ext)s", out_tmpl)
            finally:
                widget.shutdown()

    def test_02_hongguo_resolver_fallback_play_info_direct_mp4(self):
        """3. Hongguo resolver trả direct MP4 từ fallback-play-info và kiểm tra không trả URL HTML."""
        p = HongguoProvider()
        ep = Episode(
            num=1,
            title="Tập 1",
            url="https://hongguoduanju.com/player/7503745441910017049?vid=7503780574541122622&ep=1",
            provider_id="hongguo",
            series_id="hongguo:7503745441910017049",
            episode_id="7503780574541122622",
            access_state=ACCESS_STATE_FREE,
            extra={"vid": "7503780574541122622", "series_id": "7503745441910017049"},
        )

        mock_post_resp = MagicMock()
        mock_post_resp.status_code = 200
        mock_post_resp.json.return_value = {
            "main_url": "https://v11-hgweb.qznovelvod.com/stream/free_ep1.mp4?x-expires=9999999999",
            "url_expire": 9999999999,
        }

        with patch.object(p.session, "post", return_value=mock_post_resp):
            stream = p.resolve_episode_stream(ep)

        self.assertEqual(stream, "https://v11-hgweb.qznovelvod.com/stream/free_ep1.mp4?x-expires=9999999999")
        self.assertEqual(ep.expires_at, 9999999999)

        # Từ chối URL HTML / detail page
        ep_html = Episode(
            num=1,
            title="Tập 1",
            url="https://hongguoduanju.com/player/7503745441910017049?vid=7503780574541122622",
            direct_url="https://hongguoduanju.com/detail?series_id=7503745441910017049",
            provider_id="hongguo",
            series_id="hongguo:7503745441910017049",
            episode_id="7503780574541122622",
            access_state=ACCESS_STATE_FREE,
            extra={"vid": "7503780574541122622", "series_id": "7503745441910017049"},
        )
        with patch.object(p.session, "post", return_value=mock_post_resp):
            refreshed = p.resolve_episode_stream(ep_html)
        self.assertEqual(refreshed, "https://v11-hgweb.qznovelvod.com/stream/free_ep1.mp4?x-expires=9999999999")

    def test_03_hongguo_spade_decryption_and_expired_url_refresh(self):
        """Hongguo resolver giải mã Spade URL và tự refresh nếu direct_url đã hết hạn."""
        from Cryptodome.Cipher import AES

        key_hex = "abcdef0123456789abcdef0123456789"
        target_url = "https://v26-hgweb.qznovelvod.com/fresh_ep1.mp4"
        pad_len = 16 - (len(target_url) % 16)
        padded = target_url.encode("utf-8") + bytes([pad_len] * pad_len)
        h1 = hashlib.sha512(key_hex.encode("utf-8")).digest()
        h2 = hashlib.sha512(h1 + SPADE_CONSTANTS).digest()
        cipher = AES.new(h2[:16], AES.MODE_CBC, h2[16:32])
        b64_enc = base64.b64encode(bytes([0xA8, 0x00, 0x01, 0x00]) + cipher.encrypt(padded)).decode("utf-8")

        p = HongguoProvider()
        ep = Episode(
            num=1,
            title="Tập 1",
            url="https://hongguoduanju.com/player/7500001?vid=v1",
            direct_url="https://v26-hgweb.qznovelvod.com/old_expired.mp4?x-expires=1000000",
            expires_at=int(time.time()) - 100,
            provider_id="hongguo",
            series_id="hongguo:7500001",
            episode_id="v1",
            access_state=ACCESS_STATE_FREE,
            extra={"vid": "v1", "series_id": "7500001"},
        )

        mock_ndjson = MagicMock()
        mock_ndjson.status_code = 200
        mock_ndjson.text = json.dumps({"videoPlayInfo": {"spade_a": "synthetic_spade_a", "encrypted_url": b64_enc}}) + "\n{}"

        with patch.object(p.session, "get", return_value=mock_ndjson), \
             patch("providers.hongguo_provider.derive_content_key", return_value=key_hex):
            fresh = p.resolve_episode_stream(ep)

        self.assertEqual(fresh, target_url)

    def test_04_kylin_resolver_preserves_chapter_id(self):
        """4. Kylin share resolver giữ nguyên đúng chapter_id/cid cho từng tập."""
        p = HongguoProvider()
        cids = ["7671510001", "7671510002", "7671510003"]
        router_data = {
            "loaderData": {
                "video-animation-share_page": {
                    "pageData": {
                        "series_data": {
                            "title": "Kylin Test",
                            "play_url": "https://cdn.kylin.test/ep1.mp4",
                            "chapter_id": cids[0],
                        },
                        "chapter_ids": cids,
                        "used_chapter_id": cids[0],
                    }
                }
            }
        }
        landing = "https://hainanyuyue.com/share/video-animation-share?encrypt_did=xyz"
        mock_share_resp = MagicMock()
        mock_share_resp.status_code = 200
        mock_share_resp.url = landing
        mock_share_resp.text = f"<script>window._ROUTER_DATA = {json.dumps(router_data)};</script>"

        with patch.object(p.session, "get", return_value=mock_share_resp):
            series = p.load_series("https://kylin.hainanyuyue.com/s/test/")

        self.assertEqual(series.episodes[0].episode_id, "7671510001")
        self.assertEqual(series.episodes[1].episode_id, "7671510002")
        self.assertEqual(series.episodes[1].extra["cid"], "7671510002")
        self.assertEqual(series.episodes[1].extra["chapter_id"], "7671510002")

        mock_ep2_resp = MagicMock()
        mock_ep2_resp.status_code = 200
        mock_ep2_resp.text = json.dumps({"pageData": {"series_data": {"play_url": "https://cdn.kylin.test/ep2.mp4"}}})

        with patch.object(p.session, "get", return_value=mock_ep2_resp) as mock_get:
            res_ep2 = p.resolve_episode_stream(series.episodes[1])
            self.assertEqual(res_ep2, "https://cdn.kylin.test/ep2.mp4")
            called_params = mock_get.call_args.kwargs.get("params", {})
            self.assertEqual(called_params.get("vid"), "7671510002")

    def test_05_novelquickapp_resolver_preserves_video_id(self):
        """5. NovelQuickApp resolver giữ nguyên đúng video_id/vid."""
        p = HongguoProvider()
        mock_share = MagicMock(status_code=200, url="https://novelquickapp.com/hongguo/ug/pages/video-animation-share?video_id=7637909835178052670", text="<html></html>")
        mock_detail = MagicMock(
            status_code=200,
            text=json.dumps({
                "seriesDetail": {
                    "series_name": "NovelQuick Test",
                    "vid_list": ["vid_nq_1", "vid_nq_2"],
                    "accessible_episode_cnt": 1,
                }
            }) + "\n{}",
        )

        def fake_get(url, *args, **kwargs):
            if "__loader=detail_page" in url:
                return mock_detail
            return mock_share

        with patch.object(p.session, "get", side_effect=fake_get):
            series = p.load_series("https://novelquickapp.com/s/test/")

        ep1 = series.episodes[0]
        self.assertEqual(ep1.episode_id, "vid_nq_1")
        self.assertEqual(ep1.extra["vid"], "vid_nq_1")
        self.assertEqual(ep1.access_state, ACCESS_STATE_FREE)

        mock_fb = MagicMock(status_code=200)
        mock_fb.json.return_value = {"main_url": "https://cdn.nq.test/vid_nq_1.mp4"}
        with patch.object(p.session, "post", return_value=mock_fb) as mock_post:
            stream = p.resolve_episode_stream(ep1)
            self.assertEqual(stream, "https://cdn.nq.test/vid_nq_1.mp4")
            self.assertEqual(mock_post.call_args.kwargs["json"]["item_id"], "vid_nq_1")


if __name__ == "__main__":
    unittest.main()
