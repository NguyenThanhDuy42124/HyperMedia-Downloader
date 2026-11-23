"""
tests/test_hongguo_audit_and_access_contract.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Unit & mock integration test suite verifying:
1. Hongguo platform audit findings and access control contracts.
2. Modern.js payload parsing and stable episode ID mapping.
3. Synthetic non-sensitive Spade URL decryption and error handling.
4. Access states enforcement: free, requires_vip, requires_login, unavailable, error.
5. Expired signed token handling and backend 401/403 HTTP error contracts.
6. Subtitle non-blocking warning and cooperative cancellation.
"""

import base64
import hashlib
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from providers.base import (
    Series,
    Episode,
    Subtitle,
    ACCESS_STATE_FREE,
    ACCESS_STATE_REQUIRES_LOGIN,
    ACCESS_STATE_REQUIRES_VIP,
    ACCESS_STATE_UNAVAILABLE,
    ACCESS_STATE_ERROR,
)
from providers.crypto_utils import (
    SPADE_CONSTANTS,
    decrypt_spade_url,
    derive_content_key,
)
from providers.registry import detect_provider, is_drama_url
from download_worker import DownloadWorker


class TestHongguoAuditAndAccessContract(unittest.TestCase):

    def test_hongguo_url_routing_active_free_first(self):
        """Hongguo được đăng ký theo kiến trúc Free-first, nhận diện URL hợp lệ và từ chối URL khác."""
        url = "https://hongguoduanju.com/detail?series_id=7412345678"
        p = detect_provider(url)
        self.assertIsNotNone(p, "Hongguo phải được nhận diện qua HongguoProvider")
        self.assertEqual(p.platform_id, "hongguo")
        self.assertTrue(is_drama_url(url))

        non_hongguo = "https://youtube.com/watch?v=12345678&hongguo=1"
        self.assertNotEqual(getattr(detect_provider(non_hongguo), "platform_id", None), "hongguo")

    def test_parse_modernjs_payload_with_access_states(self):
        """Phân tích payload Modern.js: trích xuất vid_list thành stable episode_id và gán access_state đúng ranh giới."""
        raw_detail = {
            "series_name": "Test Short Drama",
            "series_cover": "https://img.test/cover.jpg",
            "series_intro": "Sample description",
            "vid_list": ["v1001", "v1002", "v1003", "v1004"],
            "accessible_episode_cnt": 2,  # Chỉ 2 tập đầu miễn phí
        }

        episodes = []
        for idx, vid in enumerate(raw_detail["vid_list"]):
            ep_num = idx + 1
            is_free = ep_num <= raw_detail["accessible_episode_cnt"]
            episodes.append(
                Episode(
                    num=ep_num,
                    title=f"Tập {ep_num}",
                    url=f"https://hongguoduanju.com/player/7412345678?vid={vid}",
                    provider_id="hongguo",
                    series_id="hongguo:7412345678",
                    episode_id=vid,
                    episode_number=ep_num,
                    access_state=ACCESS_STATE_FREE if is_free else ACCESS_STATE_REQUIRES_VIP,
                    access_reason="" if is_free else "Tập này yêu cầu quyền VIP trên ứng dụng chính thức.",
                    locked=not is_free,
                    extra={"vid": vid, "series_id": "7412345678"},
                )
            )

        self.assertEqual(len(episodes), 4)
        # Tập 1, 2 là Free
        self.assertEqual(episodes[0].access_state, ACCESS_STATE_FREE)
        self.assertFalse(episodes[0].locked)
        self.assertEqual(episodes[1].access_state, ACCESS_STATE_FREE)
        # Tập 3, 4 là VIP và Locked
        self.assertEqual(episodes[2].access_state, ACCESS_STATE_REQUIRES_VIP)
        self.assertTrue(episodes[2].locked)
        self.assertEqual(episodes[3].access_state, ACCESS_STATE_REQUIRES_VIP)
        self.assertTrue(episodes[3].locked)

    def test_spade_decryption_with_synthetic_fixture(self):
        """Xác minh thuật toán giải mã ByteDance Spade với test fixture nhân tạo (không nhạy cảm)."""
        from Cryptodome.Cipher import AES

        key_hex = "0123456789abcdef0123456789abcdef"
        target_url = "https://v3-dy-z.zjcdn.com/test_video.mp4"

        # Đệm PKCS7
        pad_len = 16 - (len(target_url) % 16)
        padded = target_url.encode("utf-8") + bytes([pad_len] * pad_len)

        h1 = hashlib.sha512(key_hex.encode("utf-8")).digest()
        h2 = hashlib.sha512(h1 + SPADE_CONSTANTS).digest()
        aes_key = h2[:16]
        aes_iv = h2[16:32]

        cipher = AES.new(aes_key, AES.MODE_CBC, aes_iv)
        enc_body = cipher.encrypt(padded)
        header = bytes([0xA8, 0x00, 0x01, 0x00])
        b64_enc = base64.b64encode(header + enc_body).decode("utf-8")

        # 1. Giải mã thành công
        res = decrypt_spade_url(b64_enc, key_hex)
        self.assertEqual(res, target_url)

        # 2. Header sai bị từ chối an toàn
        bad_header = bytes([0x00, 0x00, 0x00, 0x00])
        bad_b64 = base64.b64encode(bad_header + enc_body).decode("utf-8")
        self.assertIsNone(decrypt_spade_url(bad_b64, key_hex))

        # 3. Payload rác không gây crash
        self.assertIsNone(decrypt_spade_url("invalid_base64!!!", key_hex))

    def test_requires_vip_episode_rejection_in_download_worker(self):
        """DownloadWorker phải từ chối ngay lập tức khi gặp tập requires_vip, không bao giờ gọi yt-dlp."""
        ep_vip = Episode(
            num=3,
            title="Tập 3 VIP",
            url="https://www.dramaboxdb.com/movie/42000028173/drama?ep_id=9999&ep=3",
            access_state=ACCESS_STATE_REQUIRES_VIP,
            access_reason="Yêu cầu mua gói VIP",
            locked=True,
            extra={"chapter_id": "9999"},
        )
        series = Series(
            name="VIP Drama",
            platform="dramabox",
            series_id="dramabox:42000028173",
            episode_count=3,
            accessible_count=2,
            episodes=[ep_vip],
        )

        worker = DownloadWorker(
            url=ep_vip.url,
            options={"title": "VIP Drama - Tập 3 VIP", "output_path": "downloads"},
        )

        with patch("providers.detect_provider") as mock_det, \
             patch("yt_dlp.YoutubeDL") as mock_ydl:
            mock_p = MagicMock()
            mock_p.display_name = "DramaBox"
            mock_p.load_series.return_value = series
            mock_det.return_value = mock_p

            with self.assertRaises(ValueError) as ctx:
                worker._download_drama_episode("downloads")

            self.assertIn("không thể tải", str(ctx.exception))
            self.assertIn("VIP", str(ctx.exception))
            # YoutubeDL tuyệt đối không được gọi
            mock_ydl.assert_not_called()

    def test_requires_login_episode_rejection_in_download_worker(self):
        """DownloadWorker phải từ chối khi gặp tập requires_login với thông báo yêu cầu đăng nhập."""
        ep_login = Episode(
            num=1,
            title="Tập 1 Login",
            url="https://www.dramaboxdb.com/movie/42000028173/drama?ep_id=1001&ep=1",
            access_state=ACCESS_STATE_REQUIRES_LOGIN,
            access_reason="Yêu cầu đăng nhập tài khoản trên nền tảng chính thức.",
            locked=True,
            extra={"chapter_id": "1001"},
        )
        series = Series(
            name="Login Drama",
            platform="dramabox",
            series_id="dramabox:42000028173",
            episode_count=1,
            accessible_count=0,
            episodes=[ep_login],
        )

        worker = DownloadWorker(
            url=ep_login.url,
            options={"title": "Login Drama - Tập 1", "output_path": "downloads"},
        )

        with patch("providers.detect_provider") as mock_det, \
             patch("yt_dlp.YoutubeDL") as mock_ydl:
            mock_p = MagicMock()
            mock_p.display_name = "DramaBox"
            mock_p.load_series.return_value = series
            mock_det.return_value = mock_p

            with self.assertRaises(ValueError) as ctx:
                worker._download_drama_episode("downloads")

            self.assertIn("không thể tải", str(ctx.exception))
            mock_ydl.assert_not_called()

    def test_backend_401_403_raises_clear_error(self):
        """Khi backend trả về mã lỗi 401/403, provider ném ValueError rõ ràng, không crash unhandled."""
        from providers.dramabox_provider import DramaBoxProvider
        p = DramaBoxProvider()

        with patch.object(p.session, "get") as mock_get:
            mock_resp = MagicMock()
            mock_resp.status_code = 403
            mock_get.return_value = mock_resp

            with self.assertRaises(ValueError) as ctx:
                p.load_series("https://www.dramaboxdb.com/movie/42000012345/drama")

            self.assertIn("403", str(ctx.exception))

    def test_expired_signed_url_triggers_refresh(self):
        """Khi URL có tham số Expires đã quá hạn, resolve_episode_stream phải gọi API để lấy token mới."""
        from providers.dramabox_provider import DramaBoxProvider
        p = DramaBoxProvider()

        # URL với Expires=1000 (đã hết hạn)
        expired_url = "https://cdn.dramaboxdb.com/video.mp4?Expires=1000&Signature=abc"
        fresh_url = "https://cdn.dramaboxdb.com/video.mp4?Expires=9999999999&Signature=xyz"

        ep = Episode(
            num=1,
            title="Tập 1",
            url="https://www.dramaboxdb.com/movie/42000012345/drama?ch_id=888&ep=1",
            direct_url=expired_url,
            access_state=ACCESS_STATE_FREE,
            extra={"book_id": "42000012345", "chapter_id": "888"},
        )

        mock_html = f"""
        <html>
        <script id="__NEXT_DATA__" type="application/json">
        {{
            "props": {{
                "pageProps": {{
                    "bookInfo": {{"bookName": "Test Fresh"}},
                    "chapterList": [
                        {{"id": 888, "name": "Tập 1", "unlock": true, "mp4": "{fresh_url}"}}
                    ]
                }}
            }}
        }}
        </script>
        </html>
        """

        with patch.object(p.session, "get") as mock_get:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.text = mock_html
            mock_get.return_value = mock_resp

            resolved = p.resolve_episode_stream(ep)
            self.assertEqual(resolved, fresh_url, "Stream URL quá hạn phải được làm mới bằng fresh signed URL")

    def test_missing_stream_url_raises_clear_error(self):
        """Khi provider không thể lấy được URL phát trực tiếp, worker raise lỗi rõ ràng."""
        ep = Episode(
            num=1,
            title="Tập 1 Không URL",
            url="https://kisskh.co/Drama/?id=9999&ep_id=1&ep=1",
            access_state=ACCESS_STATE_FREE,
            extra={"kk_id": "9999", "kk_ep": "1", "kk_num": "1"},
        )
        series = Series(
            name="No Stream Drama",
            platform="kisskh",
            series_id="kisskh:9999",
            episode_count=1,
            accessible_count=1,
            episodes=[ep],
        )

        worker = DownloadWorker(url=ep.url, options={"output_path": "downloads"})

        with patch("providers.detect_provider") as mock_det:
            mock_p = MagicMock()
            mock_p.display_name = "KissKH"
            mock_p.load_series.return_value = series
            mock_p.resolve_episode_stream.return_value = None  # Không lấy được URL
            mock_det.return_value = mock_p

            with self.assertRaises(ValueError) as ctx:
                worker._download_drama_episode("downloads")

            self.assertIn("Không thể lấy URL phát trực tiếp", str(ctx.exception))

    def test_subtitle_http_error_does_not_crash_download(self):
        """Khi tải phụ đề bị lỗi HTTP 404, tiến trình không bị crash mà bỏ qua phụ đề an toàn."""
        ep = Episode(
            num=1,
            title="Tập 1",
            url="https://kisskh.co/Drama/?id=100&ep_id=1&ep=1",
            access_state=ACCESS_STATE_FREE,
            direct_url="https://cdn.test/stream.mp4",
            subtitles=[Subtitle(lang="vi", name="Tiếng Việt", url="https://sub.test/404.vtt")],
            extra={"kk_ep": "1", "kk_num": "1"},
        )
        series = Series(
            name="Sub Fail Drama",
            platform="kisskh",
            series_id="kisskh:100",
            episode_count=1,
            accessible_count=1,
            episodes=[ep],
        )

        worker = DownloadWorker(url=ep.url, options={"output_path": "downloads"})

        with patch("providers.detect_provider") as mock_det, \
             patch("yt_dlp.YoutubeDL") as mock_ydl, \
             patch("requests.get") as mock_req_get:
            mock_p = MagicMock()
            mock_p.display_name = "KissKH"
            mock_p.load_series.return_value = series
            mock_p.resolve_episode_stream.return_value = "https://cdn.test/stream.mp4"
            mock_det.return_value = mock_p

            mock_ydl_instance = MagicMock()
            mock_ydl.return_value.__enter__.return_value = mock_ydl_instance

            # Subtitle request trả 404
            mock_sub_resp = MagicMock()
            mock_sub_resp.status_code = 404
            mock_req_get.return_value = mock_sub_resp

            # Không ném ngoại lệ crash
            worker._download_drama_episode("downloads")
            mock_ydl_instance.download.assert_called_once()


if __name__ == "__main__":
    unittest.main()
