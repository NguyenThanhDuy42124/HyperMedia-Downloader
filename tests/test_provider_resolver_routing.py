"""
tests/test_provider_resolver_routing.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Kiểm thử phân tuyến URI/URL và tách biệt resolver giữa các provider:
- Hongguo/Kylin/NovelQuickApp/MiniApp Douyin URI được is_drama_url() & detect_provider() nhận diện đúng.
- normalize_url() KHÔNG viết lại drama URL chứa video_id= sang aweme.snssdk.com (không rơi vào nhánh yt-dlp).
- DownloadWorker.run() đưa toàn bộ drama task (theo URL hoặc provider metadata) vào _download_drama_episode(), không qua nhánh YouTube/yt-dlp.
- Hai provider khác nhau không dùng nhầm resolver.
"""

import os
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import providers
from providers.base import ACCESS_STATE_FREE, Episode
from site_utils import is_drama_url, normalize_url, detect_site
from download_worker import DownloadWorker


class TestProviderResolverRouting(unittest.TestCase):

    def test_01_uri_and_domain_routing(self):
        """Kiểm tra nhận diện các URI & domain Hongguo, Kylin, NovelQuickApp, MiniApp Douyin, DramaBox, KissKH."""
        cases = [
            ("hongguo:7503745441910017049", "hongguo"),
            ("hongguo:7503745441910017049?ep_id=7503780574541122622", "hongguo"),
            ("https://kylin.hainanyuyue.com/s/-mVjL3iKXGY/", "hongguo"),
            ("https://novelquickapp.com/s/leok-rgP11w/", "hongguo"),
            ("douyin_miniapp:tt5b4d2df0c47bdd2201:4120?ep_id=ep1&ep=1", "miniapp_douyin"),
            ("dramabox:42000028173", "dramabox"),
            ("https://kisskh.co/Drama/?id=9987&ep_id=172365&ep=1", "kisskh"),
        ]
        for uri, expected_pid in cases:
            self.assertTrue(is_drama_url(uri), f"Phải nhận diện drama URL: {uri}")
            p = providers.detect_provider(uri)
            self.assertIsNotNone(p, f"detect_provider trả về None cho {uri}")
            self.assertEqual(p.platform_id, expected_pid)

    def test_02_normalize_url_never_corrupts_drama_video_id_url(self):
        """8. URL drama chứa video_id= (Kylin/NovelQuickApp/Hongguo) không bị normalize_url biến thành snssdk/Douyin."""
        drama_urls = [
            "https://novelquickapp.com/hongguo/ug/pages/video-animation-share?video_id=7637909835178052670",
            "https://hainanyuyue.com/share/video-animation-share?encrypt_did=abc&video_id=7671508506402376729#ep=2&vid=767151",
            "https://hongguoduanju.com/player/7503745441910017049?vid=7503780574541122622&ep=1",
            "hongguo:7503745441910017049?ep_id=7503780574541122622",
            "douyin_miniapp:tt5b4d2df0c47bdd2201:4120?ep_id=999&ep=1",
        ]
        for u in drama_urls:
            norm = normalize_url(u)
            self.assertEqual(norm, u, f"normalize_url đã làm biến dạng drama URL: {u} -> {norm}")
            self.assertTrue(is_drama_url(norm))
            self.assertNotIn("aweme.snssdk.com", norm)

    def test_03_drama_url_routes_to_drama_branch_not_ytdlp_general(self):
        """8. DownloadWorker.run() điều hướng URL drama vào _download_drama_episode(), không qua YouTube/Douyin general branch."""
        with tempfile.TemporaryDirectory() as td:
            url = "https://novelquickapp.com/hongguo/ug/pages/video-animation-share?video_id=7637909835178052670"
            w = DownloadWorker(url, {"output_path": td, "provider": "hongguo", "episode_id": "v1", "access_state": "free"})

            with patch.object(w, "_download_drama_episode") as mock_drama, \
                 patch.object(w, "download_with_format_fallback") as mock_general_ytdlp:
                w.run()

            mock_drama.assert_called_once()
            mock_general_ytdlp.assert_not_called()

    def test_04_two_providers_never_use_wrong_resolver(self):
        """14. Hai provider khác nhau (Hongguo vs DramaBox vs KissKH vs MiniApp Douyin) không gọi nhầm resolver của nhau."""
        hg_p = providers.get_provider("hongguo")
        db_p = providers.get_provider("dramabox")
        kk_p = providers.get_provider("kisskh")
        ma_p = providers.get_provider("miniapp_douyin")

        ep_hg = Episode(num=1, title="HG1", url="https://hongguoduanju.com/player/1?vid=v1", episode_id="v1", access_state=ACCESS_STATE_FREE, extra={"vid": "v1", "series_id": "1"})
        ep_db = Episode(num=1, title="DB1", url="https://www.dramaboxdb.com/movie/2/drama?ch_id=c1", episode_id="c1", access_state=ACCESS_STATE_FREE, extra={"book_id": "2", "chapter_id": "c1"})

        with patch.object(hg_p, "resolve_episode_stream", return_value="https://cdn.hg/1.mp4") as m_hg, \
             patch.object(db_p, "resolve_episode_stream", return_value="https://cdn.db/1.mp4") as m_db, \
             patch.object(kk_p, "resolve_episode_stream") as m_kk, \
             patch.object(ma_p, "resolve_episode_stream") as m_ma:
            self.assertEqual(providers.resolve_episode_stream(ep_hg, platform_hint="hongguo"), "https://cdn.hg/1.mp4")
            m_hg.assert_called_once()
            m_db.assert_not_called()
            m_kk.assert_not_called()
            m_ma.assert_not_called()

            m_hg.reset_mock()
            self.assertEqual(providers.resolve_episode_stream(ep_db, platform_hint="dramabox"), "https://cdn.db/1.mp4")
            m_db.assert_called_once()
            m_hg.assert_not_called()

        # Headers độc lập theo site
        h_ky = detect_site("https://kylin.hainanyuyue.com/s/test/")
        h_hg = detect_site("https://hongguoduanju.com/player/1?vid=v1")
        h_db = detect_site("https://www.dramaboxdb.com/movie/2/drama")
        self.assertIn("hainanyuyue.com", h_ky.get("Referer", ""))
        self.assertIn("hongguoduanju.com", h_hg.get("Referer", ""))
        self.assertIn("dramaboxdb.com", h_db.get("Referer", ""))


if __name__ == "__main__":
    unittest.main()
