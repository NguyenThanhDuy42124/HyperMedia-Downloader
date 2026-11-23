"""
tests/test_miniapp_contract.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Kiểm thử hợp đồng (Contract Tests) cho Douyin MiniApp adapter:
1. Browse catalog thành công bằng JSON fixture mô phỏng API /video/recommend.
2. Chọn collection và lấy playlist tập từ /video/play_list.
3. Mã hóa l_sign và giải mã r_sign AES-128-CBC chuẩn xác.
4. Episode ID giữ nguyên định danh ổn định từ API, không dùng vị trí queue hay ordinal index.
5. Không fallback nhầm sang episode khác khi gọi ID cụ thể.
"""

import os
import sys
import unittest
from unittest.mock import MagicMock, patch

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from tests.miniapp_douyin_adapter import (
    MiniAppDouyinClient,
    MiniAppDouyinProvider,
    duolai_encrypt,
    duolai_decrypt,
    BUILTIN_MINIAPP_SOURCES,
)
from providers.base import ACCESS_STATE_FREE, ACCESS_STATE_REQUIRES_VIP


class TestMiniAppContract(unittest.TestCase):

    def setUp(self):
        self.client = MiniAppDouyinClient(cookie="uid_tt=test_user_123; sessionid=test_sess_456")
        self.provider = MiniAppDouyinProvider(cookie="uid_tt=test_user_123; sessionid=test_sess_456")

    def test_aes_128_cbc_encryption_and_decryption(self):
        """Kiểm tra mã hóa l_sign và giải mã r_sign khớp đối xứng 100%."""
        payload = {"collection_id": "12270", "page": 1, "pagesize": 20, "system": "AND"}
        token = "duolai_1234567890abcdef12345678"
        device_id = "test-device-uuid-112233"
        ts = "1794200000"

        hex_enc = duolai_encrypt(payload, token, device_id, ts)
        self.assertIsInstance(hex_enc, str)
        self.assertGreater(len(hex_enc), 32)

        decrypted_json_str = duolai_decrypt(hex_enc, token, device_id, ts)
        import json
        dec_obj = json.loads(decrypted_json_str)
        self.assertEqual(dec_obj, payload)

    def test_browse_catalog_with_mock_fixture(self):
        """Duyệt catalog đề xuất thành công và bóc tách CatalogItem hợp lệ."""
        mock_fixture = {
            "code": 0,
            "data": [
                {
                    "id": "12270",
                    "name": "Trấn Quốc Thần Soái",
                    "cover_url": "https://p3.douyinpic.com/cover1.jpg",
                    "episode_count": 80,
                    "describe": "Phim ngắn quân thần bảo vệ tổ quốc",
                },
                {
                    "id": "12271",
                    "name": "Thiên Kim Thần Bí",
                    "cover_url": "https://p3.douyinpic.com/cover2.jpg",
                    "episode_count": 65,
                    "describe": "Hào môn thị phi",
                },
            ]
        }

        with patch.object(self.client.session, "get") as mock_get:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = mock_fixture
            mock_get.return_value = mock_resp

            app_id = BUILTIN_MINIAPP_SOURCES[0]["app_id"]
            res = self.client.browse_catalog(app_id=app_id, page=1)

            self.assertIsNone(res.error)
            self.assertEqual(len(res.items), 2)
            self.assertEqual(res.items[0].id, "12270")
            self.assertEqual(res.items[0].name, "Trấn Quốc Thần Soái")
            self.assertEqual(res.items[0].link, f"douyin_miniapp:{app_id}:12270")
            self.assertEqual(res.items[1].episodes, 65)

    def test_load_series_and_playlist_episode_identity(self):
        """Nạp playlist từ fixture, kiểm tra Episode ID bền vững và không dùng index thứ tự."""
        mock_playlist_fixture = {
            "code": 0,
            "data": [
                {"id": 998801, "sequence_no": 1, "is_free": "T"},
                {"id": 998802, "sequence_no": 2, "is_free": "T"},
                {"id": 998803, "sequence_no": 3, "is_free": "F"},
                {"id": 998805, "sequence_no": 5, "is_free": "F"},  # Danh sách khuyết tập 4
            ]
        }

        app_id = "tt5b4d2df0c47bdd2201"
        cid = "12270"
        url = f"douyin_miniapp:{app_id}:{cid}"

        with patch.object(self.provider.client.session, "get") as mock_get:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = mock_playlist_fixture
            mock_get.return_value = mock_resp

            series = self.provider.load_series(url)

            self.assertEqual(series.episode_count, 4)
            self.assertEqual(series.accessible_count, 2)

            # Khẳng định episode_id khớp đúng API ID (998801, 998802, 998803, 998805), không phải [1, 2, 3, 4]
            self.assertEqual(series.episodes[0].episode_id, "998801")
            self.assertEqual(series.episodes[1].episode_id, "998802")
            self.assertEqual(series.episodes[2].episode_id, "998803")
            self.assertEqual(series.episodes[3].episode_id, "998805")
            self.assertEqual(series.episodes[3].num, 5)  # Giữ nguyên sequence_no 5


if __name__ == "__main__":
    unittest.main()
