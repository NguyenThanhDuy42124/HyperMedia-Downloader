"""
tests.test_drama_integration
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Unit test suite verifying the DramaDownloader adapter layer, episode selection parser,
provider routing, subtitle converter, and download worker integration contract.
"""

import os
import sys
import unittest
from unittest.mock import MagicMock, patch

# Thêm đường dẫn gốc vào sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import providers
from providers.base import (
    parse_episode_selection,
    vtt_to_srt,
    Series,
    Episode,
    Subtitle,
    ACCESS_STATE_FREE,
    ACCESS_STATE_REQUIRES_LOGIN,
    ACCESS_STATE_REQUIRES_VIP,
    ACCESS_STATE_UNAVAILABLE,
    ACCESS_STATE_ERROR,
    VALID_ACCESS_STATES,
)
from providers.dramabox_provider import DramaBoxProvider
from providers.kisskh_provider import KisskhProvider
from site_utils import is_drama_url, detect_site


class TestDramaIntegration(unittest.TestCase):

    def test_provider_detection_and_routing(self):
        """Kiểm tra nhận diện URL đúng provider và không can thiệp vào URL khác."""
        cases = [
            ("https://www.dramaboxdb.com/movie/42000028173/drama", "dramabox"),
            ("dramabox:42000028173", "dramabox"),
            ("https://kisskh.co/Drama/?id=9000", "kisskh"),
            ("kisskh:9000", "kisskh"),
            ("https://kisskh.co/Drama/Speed-and-Love?id=10606", "kisskh"),
        ]
        for url, expected_id in cases:
            p = providers.detect_provider(url)
            self.assertIsNotNone(p, f"Không nhận diện được: {url}")
            self.assertEqual(p.platform_id, expected_id)
            self.assertTrue(is_drama_url(url))

        # Phải trả về None đối với YouTube và Bilibili
        non_drama = [
            "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            "https://www.bilibili.com/video/BV1xx411c7mD",
            "https://v.douyin.com/test1234/",
        ]
        for url in non_drama:
            self.assertIsNone(providers.detect_provider(url))
            self.assertFalse(is_drama_url(url))

    def test_parse_episode_selection(self):
        """Kiểm tra parser khoảng tập (1-5, 8, 10-12) và xử lý ngoại lệ."""
        # 1. Khoảng chuẩn
        self.assertEqual(parse_episode_selection("1-5, 8, 10-12", 20), [1, 2, 3, 4, 5, 8, 10, 11, 12])

        # 2. Khoảng ngược (5-1 -> 1,2,3,4,5)
        self.assertEqual(parse_episode_selection("5-2", 10), [2, 3, 4, 5])

        # 3. Số vượt quá max_ep bị loại bỏ
        self.assertEqual(parse_episode_selection("1-3, 99, 100", 5), [1, 2, 3])

        # 4. Trùng lặp tự gộp (set deduplication)
        self.assertEqual(parse_episode_selection("1, 1, 2, 2, 3-4, 4-5", 10), [1, 2, 3, 4, 5])

        # 5. Chuỗi rỗng hoặc rác không gây lỗi crash
        self.assertEqual(parse_episode_selection("", 10), [])
        self.assertEqual(parse_episode_selection("abc, def, --, ,", 10), [])
        self.assertEqual(parse_episode_selection("   ", 10), [])

    def test_vtt_to_srt_conversion(self):
        """Kiểm tra chuyển đổi phụ đề WebVTT sang SRT SubRip."""
        sample_vtt = """WEBVTT
NOTE This is a comment

00:00:01.200 --> 00:00:03.500
Xin chào thế giới!

00:00:04.100 --> 00:00:07.800
<font color="#ffff00">Phim ngắn chất lượng cao</font>
"""
        srt = vtt_to_srt(sample_vtt)
        self.assertIn("1\n00:00:01,200 --> 00:00:03,500\nXin chào thế giới!", srt)
        self.assertIn("2\n00:00:04,100 --> 00:00:07,800\nPhim ngắn chất lượng cao", srt)
        self.assertNotIn("WEBVTT", srt)
        self.assertNotIn("<font", srt)

    def test_dramabox_id_extraction(self):
        """Kiểm tra trích xuất ID từ các định dạng link DramaBox."""
        p = DramaBoxProvider()
        self.assertEqual(p._extract_id("https://www.dramaboxdb.com/movie/42000028173/drama"), "42000028173")
        self.assertEqual(p._extract_id("dramabox:42000012345"), "42000012345")
        self.assertEqual(p._extract_id("https://www.dramaboxdb.com/ep/42000099999/1"), "42000099999")

    def test_kisskh_id_extraction(self):
        """Kiểm tra trích xuất ID từ link KissKH."""
        p = KisskhProvider()
        self.assertEqual(p._extract_id("https://kisskh.co/Drama/?id=9000"), "9000")
        self.assertEqual(p._extract_id("kisskh:10606"), "10606")
        self.assertEqual(p._extract_id("https://kisskh.co/Drama/Speed-and-Love?id=10606"), "10606")

    def test_header_isolation(self):
        """Đảm bảo headers của DramaBox và KissKH độc lập, không dùng cookie YouTube/Bilibili."""
        headers_db = detect_site("https://www.dramaboxdb.com/movie/123/drama")
        self.assertIn("dramaboxdb.com", headers_db.get("Referer", ""))

        headers_kk = detect_site("https://kisskh.co/Drama/?id=9000")
        self.assertIn("kisskh.co", headers_kk.get("Referer", ""))

        # Không chứa cookie header mặc định
        self.assertNotIn("Cookie", headers_db)
        self.assertNotIn("Cookie", headers_kk)

    def test_dramabox_load_series_mock(self):
        """Kiểm tra nạp metadata series DramaBox với dữ liệu mock."""
        mock_html = """
        <html>
        <script id="__NEXT_DATA__" type="application/json">
        {
            "props": {
                "pageProps": {
                    "bookInfo": {
                        "bookName": "Test Drama Series",
                        "cover": "https://img.test/cover.jpg",
                        "introduction": "Test intro"
                    },
                    "chapterList": [
                        {"id": 101, "name": "Tập 1", "index": 0, "unlock": true, "mp4": "https://cdn.test/1.mp4"},
                        {"id": 102, "name": "Tập 2", "index": 1, "unlock": false, "mp4": ""}
                    ]
                }
            }
        }
        </script>
        </html>
        """
        p = DramaBoxProvider()
        with patch.object(p.session, "get") as mock_get:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.text = mock_html
            mock_get.return_value = mock_resp

            series = p.load_series("https://www.dramaboxdb.com/movie/42000011111/drama")
            self.assertEqual(series.name, "Test Drama Series")
            self.assertEqual(series.episode_count, 2)
            self.assertEqual(series.accessible_count, 1)
            self.assertFalse(series.episodes[0].locked)
            self.assertEqual(series.episodes[0].access_state, ACCESS_STATE_FREE)
            self.assertTrue(series.episodes[1].locked)
            self.assertEqual(series.episodes[1].access_state, ACCESS_STATE_REQUIRES_VIP)
            self.assertEqual(series.episodes[0].direct_url, "https://cdn.test/1.mp4")

    def test_episode_access_state_contract(self):
        """Xác minh hợp đồng Domain Model Episode với các trường truy cập VIP chuẩn hóa."""
        # 1. Khởi tạo mặc định: free, unlocked
        ep_free = Episode(num=1, title="Tập 1", url="https://test/1")
        self.assertEqual(ep_free.access_state, ACCESS_STATE_FREE)
        self.assertFalse(ep_free.locked)
        self.assertEqual(ep_free.episode_number, 1)

        # 2. Đồng bộ khi locked=True -> requires_vip
        ep_locked = Episode(num=2, title="Tập 2", url="https://test/2", locked=True)
        self.assertEqual(ep_locked.access_state, ACCESS_STATE_REQUIRES_VIP)
        self.assertTrue(ep_locked.locked)

        # 3. Đồng bộ khi access_state=requires_login -> locked=True
        ep_login = Episode(num=3, title="Tập 3", url="https://test/3", access_state=ACCESS_STATE_REQUIRES_LOGIN)
        self.assertTrue(ep_login.locked)

        # 4. Đồng bộ khi access_state=unavailable -> locked=True
        ep_unavail = Episode(num=4, title="Tập 4", url="https://test/4", access_state=ACCESS_STATE_UNAVAILABLE)
        self.assertTrue(ep_unavail.locked)

        # 5. to_dict phải chứa đầy đủ 9 trường mới
        d = ep_locked.to_dict()
        required_keys = [
            "provider_id", "series_id", "episode_id", "episode_number",
            "access_state", "access_reason", "direct_url", "subtitle", "expires_at",
        ]
        for k in required_keys:
            self.assertIn(k, d, f"Thiếu trường {k} trong to_dict()")

        # 6. Tự động liên kết phụ đề đầu tiên vào subtitle
        ep_sub = Episode(
            num=5,
            title="Tập 5",
            url="https://test/5",
            subtitles=[Subtitle(lang="vi", name="Tiếng Việt", url="https://test/vi.vtt")],
        )
        self.assertEqual(ep_sub.subtitle, "https://test/vi.vtt")

    def test_drama_dialog_access_state_presentation(self):
        """Kiểm tra DramaEpisodeDialog hiển thị đúng badge, tooltip và trạng thái disable cho tập VIP/Locked."""
        from PySide6.QtWidgets import QApplication
        from drama_dialog import DramaEpisodeDialog

        app = QApplication.instance()
        if not app:
            app = QApplication(["-platform", "offscreen"])

        eps = [
            Episode(num=1, title="Tập 1", url="https://test/1", access_state=ACCESS_STATE_FREE),
            Episode(
                num=2,
                title="Tập 2",
                url="https://test/2",
                access_state=ACCESS_STATE_REQUIRES_VIP,
                access_reason="Cần mua gói VIP",
            ),
            Episode(num=3, title="Tập 3", url="https://test/3", access_state=ACCESS_STATE_UNAVAILABLE),
        ]
        series = Series(
            name="Dialog Test Series",
            platform="dramabox",
            series_id="dramabox:123",
            episode_count=3,
            accessible_count=1,
            episodes=eps,
        )

        dlg = DramaEpisodeDialog(series)
        try:
            # Tập 1: Free -> Checked và Enabled
            cb1 = dlg.episode_checkboxes[1]
            self.assertTrue(cb1.isEnabled())
            self.assertTrue(cb1.isChecked())
            self.assertIn("[Free]", cb1.text())

            # Tập 2: VIP -> Disabled và Unchecked, có tooltip cảnh báo VIP
            cb2 = dlg.episode_checkboxes[2]
            self.assertFalse(cb2.isEnabled())
            self.assertFalse(cb2.isChecked())
            self.assertIn("[VIP]", cb2.text())
            self.assertIn("VIP", cb2.toolTip())

            # Tập 3: Khóa -> Disabled và Unchecked
            cb3 = dlg.episode_checkboxes[3]
            self.assertFalse(cb3.isEnabled())
            self.assertFalse(cb3.isChecked())
            self.assertIn("[Khóa]", cb3.text())

            # Nút "Chỉ chọn tập miễn phí"
            dlg._deselect_all()
            self.assertFalse(cb1.isChecked())
            dlg._select_free_only()
            self.assertTrue(cb1.isChecked())
            self.assertFalse(cb2.isChecked())
            self.assertFalse(cb3.isChecked())

            # Nút "Chọn tất cả" chỉ chọn các tập enabled
            dlg._deselect_all()
            dlg._select_all()
            self.assertTrue(cb1.isChecked())
            self.assertFalse(cb2.isChecked())
            self.assertFalse(cb3.isChecked())
        finally:
            dlg.close()


if __name__ == "__main__":
    unittest.main()
