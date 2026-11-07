# -*- coding: utf-8 -*-
"""
====================================================================
QA AUTOMATED TEST SUITE & PLATFORM REGRESSION VERIFIER
====================================================================
Mục đích:
- Kiểm thử hồi quy (Regression Testing) toàn diện cho:
  1. YouTube (YTB): Tốc độ, bypass throttling, client config, chunk size, cookies fallback.
  2. Bilibili: DASH 1080p fnval=4048, Config E (6 luồng / 8MB chunk), Anti-bot isolation.
  3. Douyin: Nhận diện URL, Direct 1080p unlock, Jitter chunking, Cookie headers.
  4. Hệ thống đặt tiền tố (Prefix): 1 ( Tên phim ), 01 ( Tên phim ), Tập 1, Custom pattern.
  5. Hệ thống tải trùng: Dup1, Dup2, DupN tự động, bảo toàn file gốc, không xóa nhầm file .part.
  6. Cách ly dọn dẹp file tạm: Không ảnh hưởng đến các tác vụ tải song song khác.

Cách chạy:
  - Chạy nhanh offline (mặc định):
      env\\Scripts\\python.exe qa_test_suite.py
  - Chạy kiểm thử trực tuyến (Live Network Probes):
      env\\Scripts\\python.exe qa_test_suite.py --live
====================================================================
"""

import sys
import os

# Đảm bảo UTF-8 an toàn trên mọi terminal Windows
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if sys.stderr and hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import shutil
import tempfile
import unittest
import argparse
from unittest.mock import MagicMock

# Đảm bảo import được các module trong thư mục dự án
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
if CURRENT_DIR not in sys.path:
    sys.path.insert(0, CURRENT_DIR)

from site_utils import is_youtube_url, is_bilibili_url, detect_site, normalize_url
from download_worker import DownloadWorker


class TestFilenameAndPrefix(unittest.TestCase):
    """Kiểm tra logic đặt tiền tố (Prefix) và định dạng tên file an toàn."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="qa_prefix_")

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_preset_1_ten_phim(self):
        """Mẫu '1 ( Tên phim )' với item_index = 1 và 5."""
        w1 = DownloadWorker("https://www.youtube.com/watch?v=dQw4w9WgXcQ", {
            "title": "Tay Du Ky 1986",
            "item_index": 1,
            "prefix_enabled": True,
            "prefix_pattern": "1 ( Tên phim )",
            "allow_duplicates": False,
        })
        title, tmpl = w1._resolve_filename(self.tmpdir)
        self.assertEqual(title, "1 ( Tay Du Ky 1986 )")
        self.assertTrue(tmpl.endswith("1 ( Tay Du Ky 1986 ).%(ext)s"))

        w5 = DownloadWorker("https://www.youtube.com/watch?v=dQw4w9WgXcQ", {
            "title": "Tay Du Ky 1986",
            "item_index": 5,
            "prefix_enabled": True,
            "prefix_pattern": "1 ( Tên phim )",
            "allow_duplicates": False,
        })
        title5, _ = w5._resolve_filename(self.tmpdir)
        self.assertEqual(title5, "5 ( Tay Du Ky 1986 )")

    def test_preset_01_ten_phim(self):
        """Mẫu '01 ( Tên phim )' phải có số 0 ở đầu nếu < 10."""
        w_pad = DownloadWorker("https://www.youtube.com/watch?v=dQw4w9WgXcQ", {
            "title": "Tay Du Ky 1986",
            "item_index": 3,
            "prefix_enabled": True,
            "prefix_pattern": "01 ( Tên phim )",
            "allow_duplicates": False,
        })
        title_pad, _ = w_pad._resolve_filename(self.tmpdir)
        self.assertEqual(title_pad, "03 ( Tay Du Ky 1986 )")

        w_nopad = DownloadWorker("https://www.youtube.com/watch?v=dQw4w9WgXcQ", {
            "title": "Tay Du Ky 1986",
            "item_index": 12,
            "prefix_enabled": True,
            "prefix_pattern": "01 ( Tên phim )",
            "allow_duplicates": False,
        })
        title_nopad, _ = w_nopad._resolve_filename(self.tmpdir)
        self.assertEqual(title_nopad, "12 ( Tay Du Ky 1986 )")

    def test_preset_tap_va_phim(self):
        """Mẫu 'Tập 1 - Tên phim' và '[Phim] Tên phim'."""
        w_tap = DownloadWorker("https://www.youtube.com/watch?v=dQw4w9WgXcQ", {
            "title": "Hoan Chau Cach Cach",
            "item_index": 7,
            "prefix_enabled": True,
            "prefix_pattern": "Tập 1 - Tên phim",
            "allow_duplicates": False,
        })
        title_tap, _ = w_tap._resolve_filename(self.tmpdir)
        self.assertEqual(title_tap, "Tập 7 - Hoan Chau Cach Cach")

        w_phim = DownloadWorker("https://www.youtube.com/watch?v=dQw4w9WgXcQ", {
            "title": "Avengers Endgame",
            "item_index": 1,
            "prefix_enabled": True,
            "prefix_pattern": "[Phim] Tên phim",
            "allow_duplicates": False,
        })
        title_phim, _ = w_phim._resolve_filename(self.tmpdir)
        self.assertEqual(title_phim, "[Phim] Avengers Endgame")

    def test_custom_pattern_substitution(self):
        """Pattern tùy biến với {index}, {0index}, {title}."""
        w_custom = DownloadWorker("https://www.youtube.com/watch?v=dQw4w9WgXcQ", {
            "title": "Anime_Ep",
            "item_index": 2,
            "prefix_enabled": True,
            "prefix_pattern": "EP_{0index}_{title}",
            "allow_duplicates": False,
        })
        title_custom, _ = w_custom._resolve_filename(self.tmpdir)
        self.assertEqual(title_custom, "EP_02_Anime_Ep")

    def test_prefix_modes_with_film_name_box(self):
        """Kiểm tra 3 chế độ Prefix Số Đầu, Prefix Tập + số, Prefix Tên Film kết hợp ô nhập Tên Film."""
        # 1. Prefix Tên Film với tên phim 'Tay Du Ky': 'Tên Film Bạn Nhập - (Tên Film Bạn Tải)'
        w_film = DownloadWorker("https://www.youtube.com/watch?v=1", {
            "title": "Tap 1 HD",
            "item_index": 1,
            "prefix_enabled": True,
            "prefix_mode": "Prefix Tên Film",
            "film_name": "Tay Du Ky",
            "allow_duplicates": False,
        })
        t_film, _ = w_film._resolve_filename(self.tmpdir)
        self.assertEqual(t_film, "Tay Du Ky - (Tap 1 HD)")

        # 2. Prefix Số Đầu: số ở đầu '1 ( Tên Film Bạn Tải )'
        w_so = DownloadWorker("https://www.youtube.com/watch?v=1", {
            "title": "Tap 1 HD",
            "item_index": 1,
            "prefix_enabled": True,
            "prefix_mode": "Prefix Số Đầu",
            "allow_duplicates": False,
        })
        t_so, _ = w_so._resolve_filename(self.tmpdir)
        self.assertEqual(t_so, "1 ( Tap 1 HD )")

        # 3. Prefix Tập + số: 'Tập 1 - Tên Film Bạn Tải'
        w_tap = DownloadWorker("https://www.youtube.com/watch?v=1", {
            "title": "Tap 1 HD",
            "item_index": 1,
            "prefix_enabled": True,
            "prefix_mode": "Prefix Tập + số",
            "allow_duplicates": False,
        })
        t_tap, _ = w_tap._resolve_filename(self.tmpdir)
        self.assertEqual(t_tap, "Tập 1 - Tap 1 HD")

    def test_forbidden_windows_characters(self):
        """Loại bỏ triệt để các ký tự cấm trên Windows: / \\ : * ? \" < > |."""
        dirty_title = 'Phim: Hay/Dở "Cực*Đỉnh"? <Test>|OK'
        w = DownloadWorker("https://www.youtube.com/watch?v=dQw4w9WgXcQ", {
            "title": dirty_title,
            "item_index": 1,
            "prefix_enabled": False,
            "allow_duplicates": False,
        })
        clean_title, _ = w._resolve_filename(self.tmpdir)
        for char in r'\/:*?"<>|':
            self.assertNotIn(char, clean_title)

    def test_empty_or_unknown_title_fallback(self):
        """Xử lý tiêu đề rỗng hoặc Unknown không bị lỗi."""
        w_empty = DownloadWorker("https://www.youtube.com/watch?v=dQw4w9WgXcQ", {
            "title": "",
            "item_index": 1,
            "prefix_enabled": True,
            "prefix_pattern": "1 ( Tên phim )",
            "allow_duplicates": False,
        })
        _, tmpl = w_empty._resolve_filename(self.tmpdir)
        self.assertIn("1 ( %(title)s )", tmpl)


class TestDuplicateHandling(unittest.TestCase):
    """Kiểm tra tính năng Cho phép tải trùng (Dup1, Dup2...) và không ghi đè."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="qa_dup_")

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_duplicate_naming_sequence(self):
        """Khi file tồn tại, tự sinh Dup1, Dup2... theo chuỗi tăng dần."""
        base_title = "Video_Goc"
        # 1. Chưa có file -> giữ nguyên tên gốc
        w1 = DownloadWorker("https://www.youtube.com/watch?v=1", {
            "title": base_title,
            "allow_duplicates": True,
        })
        t1, _ = w1._resolve_filename(self.tmpdir)
        self.assertEqual(t1, base_title)

        # 2. Tạo file gốc Video_Goc.mp4
        with open(os.path.join(self.tmpdir, f"{base_title}.mp4"), "w") as f:
            f.write("content 0")

        # Worker thứ 2 cùng tên phải tự ra Dup1_Video_Goc
        w2 = DownloadWorker("https://www.youtube.com/watch?v=2", {
            "title": base_title,
            "allow_duplicates": True,
        })
        t2, _ = w2._resolve_filename(self.tmpdir)
        self.assertEqual(t2, f"Dup1_{base_title}")

        # 3. Tạo tiếp file Dup1_Video_Goc.mp4
        with open(os.path.join(self.tmpdir, f"Dup1_{base_title}.mp4"), "w") as f:
            f.write("content 1")

        # Worker thứ 3 phải tự ra Dup2_Video_Goc
        w3 = DownloadWorker("https://www.youtube.com/watch?v=3", {
            "title": base_title,
            "allow_duplicates": True,
        })
        t3, _ = w3._resolve_filename(self.tmpdir)
        self.assertEqual(t3, f"Dup2_{base_title}")

    def test_duplicate_checks_part_files(self):
        """Phát hiện file .part đang tải dở để không ghi đè."""
        base_title = "Dang_Tai_Do"
        with open(os.path.join(self.tmpdir, f"{base_title}.part"), "w") as f:
            f.write("partial")

        w = DownloadWorker("https://www.youtube.com/watch?v=test", {
            "title": base_title,
            "allow_duplicates": True,
        })
        t, _ = w._resolve_filename(self.tmpdir)
        self.assertEqual(t, f"Dup1_{base_title}")

    def test_file_exists_bypass_when_allow_duplicates(self):
        """Khi bật allow_duplicates, _file_exists() luôn trả về False để không bị skip."""
        base_title = "Da_Co_San"
        with open(os.path.join(self.tmpdir, f"{base_title}.mp4"), "w") as f:
            f.write("existed")

        # Case 1: allow_duplicates = False -> _file_exists trả True
        w_skip = DownloadWorker("https://www.youtube.com/watch?v=test", {
            "title": base_title,
            "allow_duplicates": False,
        })
        self.assertTrue(w_skip._file_exists(self.tmpdir))

        # Case 2: allow_duplicates = True -> _file_exists luôn trả False
        w_noskip = DownloadWorker("https://www.youtube.com/watch?v=test", {
            "title": base_title,
            "allow_duplicates": True,
        })
        self.assertFalse(w_noskip._file_exists(self.tmpdir))


class TestYouTubeRegression(unittest.TestCase):
    """Kiểm tra các cấu hình tối ưu của YouTube chống bóp băng thông 50KB/s."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="qa_ytb_")
        self.yt_url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_youtube_url_detection(self):
        """Nhận diện chính xác URL YouTube."""
        self.assertTrue(is_youtube_url("https://www.youtube.com/watch?v=abc12345678"))
        self.assertTrue(is_youtube_url("https://youtu.be/abc12345678"))
        self.assertFalse(is_youtube_url("https://www.bilibili.com/video/BV1xx411c7mD"))
        self.assertFalse(is_youtube_url("https://www.douyin.com/video/7123456789012345678"))

    def test_youtube_base_opts_contract(self):
        """Xác minh các tùy chọn yt-dlp tối ưu cho YouTube."""
        worker = DownloadWorker(self.yt_url, {
            "title": "Rick Astley Never Gonna Give You Up",
            "num_threads": 8,
            "output_path": self.tmpdir,
        })
        opts = worker.get_base_opts(self.tmpdir)

        # 1. Chunking 10MB cho googlevideo CDN
        self.assertEqual(opts.get("http_chunk_size"), 10485760)

        # 2. Concurrency luồng tải song song từ 4 đến 8
        c_frag = opts.get("concurrent_fragment_downloads", 1)
        self.assertTrue(4 <= c_frag <= 8, f"concurrent_fragment_downloads was {c_frag}, expected 4-8")

        # 3. Extractor args phải có player_skip configs và không bị ép client gây lỗi GVS PO Token (cap 360p)
        ext_args = opts.get("extractor_args", {}).get("youtube", {})
        self.assertIn("configs", ext_args.get("player_skip", []))
        self.assertNotIn("player_client", ext_args, "player_client must not be overridden to avoid GVS PO Token 360p cap")

        # 4. Buffersize tối thiểu 2MB
        self.assertGreaterEqual(opts.get("buffersize", 0), 2 * 1024 * 1024)

        # 5. continuedl = True
        self.assertTrue(opts.get("continuedl"))

    def test_youtube_high_res_extraction(self):
        """Kiểm tra yt-dlp với cấu hình chuẩn lấy được độ phân giải >= 1080p, không bị kẹt ở 360p."""
        import yt_dlp
        from app_constants import get_js_runtime
        ydl_opts = {
            "quiet": True,
            "js_runtimes": get_js_runtime(),
            "extractor_args": {"youtube": {"player_skip": ["configs"]}},
        }
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info("https://www.youtube.com/watch?v=cwlToxaWuL8", download=False)
                heights = [f.get("height", 0) for f in info.get("formats", []) if f.get("height")]
                self.assertTrue(any(h >= 1080 for h in heights), f"Max height found was {max(heights) if heights else 0}, expected >= 1080")
        except Exception as e:
            if any(k in str(e) for k in ["Sign in to confirm", "429", "Too Many Requests", "bot"]):
                self.skipTest(f"YouTube live rate limit / bot check: {e}")
            raise


class TestBilibiliRegression(unittest.TestCase):
    """Kiểm tra các cơ chế của Bilibili không bị ảnh hưởng hay hồi quy."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="qa_bili_")
        self.bili_url = "https://www.bilibili.com/video/BV1xx411c7mD"

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_bilibili_url_detection(self):
        """Nhận diện URL Bilibili."""
        self.assertTrue(is_bilibili_url("https://www.bilibili.com/video/BV1xx411c7mD"))
        self.assertTrue(is_bilibili_url("https://b23.tv/xyz123"))
        self.assertFalse(is_bilibili_url("https://www.youtube.com/watch?v=123"))

    def test_bilibili_base_opts_contract(self):
        """Bilibili phải giữ nguyên Config E: 6 luồng, chunk 8MB, fnval 4048 (DASH 1080p)."""
        worker = DownloadWorker(self.bili_url, {
            "title": "Bilibili Test Video",
            "num_threads": 16,
            "output_path": self.tmpdir,
        })
        opts = worker.get_base_opts(self.tmpdir)

        # 1. Config E: chunk size đúng 8MB
        self.assertEqual(opts.get("http_chunk_size"), 8 * 1024 * 1024)

        # 2. Concurrency cố định 6 luồng
        self.assertEqual(opts.get("concurrent_fragment_downloads"), 6)

        # 3. Timeout 45s cho CDN Trung Quốc
        self.assertEqual(opts.get("socket_timeout"), 45)

        # 4. DASH fnval = 4048 bắt buộc để mở khóa 1080P
        ext_args = opts.get("extractor_args", {}).get("bilibili", {})
        self.assertEqual(ext_args.get("fnval"), [4048])

        # 5. Buffersize 4MB
        self.assertEqual(opts.get("buffersize"), 4 * 1024 * 1024)

    def test_bilibili_headers(self):
        """Headers Bilibili phải có Referer và Origin hợp lệ."""
        headers = detect_site(self.bili_url)
        self.assertEqual(headers.get("Referer"), "https://www.bilibili.com/")
        self.assertEqual(headers.get("Origin"), "https://www.bilibili.com")


class TestDouyinRegression(unittest.TestCase):
    """Kiểm tra cơ chế tải Douyin và Direct 1080p Stream Unlocker."""

    def test_douyin_headers(self):
        """Headers của Douyin phải có Referer douyin.com."""
        headers = detect_site("https://www.douyin.com/video/7123456789012345678")
        self.assertEqual(headers.get("Referer"), "https://www.douyin.com/")

    def test_douyin_url_normalization(self):
        """Chuẩn hóa các định dạng URL của Douyin."""
        # 1. URL chứa modal_id (từ tab jingxuan / gợi ý)
        modal_url = "https://www.douyin.com/jingxuan?modal_id=7412345678901234567"
        norm = normalize_url(modal_url)
        self.assertEqual(norm, "https://www.douyin.com/video/7412345678901234567")

        # 2. URL chứa video_id CDN stream -> convert thành link direct 1080p
        cdn_url = "https://example.com/play/?video_id=v0200fg10000abcde12345&ratio=720p"
        norm_cdn = normalize_url(cdn_url)
        self.assertIn("https://aweme.snssdk.com/aweme/v1/play/?video_id=v0200fg10000abcde12345&ratio=1080p&line=0", norm_cdn)

    def test_douyin_prefix_and_duplicate_support(self):
        """Douyin khi tải với prefix và allow_duplicates phải sinh đúng outtmpl."""
        w = DownloadWorker("https://www.douyin.com/video/7123456789012345678", {
            "title": "Phim Douyin Hay",
            "item_index": 2,
            "prefix_enabled": True,
            "prefix_pattern": "1 ( Tên phim )",
            "allow_duplicates": True,
        })
        title, outtmpl = w._resolve_filename("downloads")
        self.assertEqual(title, "2 ( Phim Douyin Hay )")
        self.assertIn("2 ( Phim Douyin Hay ).%(ext)s", outtmpl)


class TestPartFileCleanupIsolation(unittest.TestCase):
    """Kiểm tra hàm _cleanup_my_part_files tuyệt đối KHÔNG xóa nhầm file .part của video khác."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="qa_part_")

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_isolation_no_accidental_delete(self):
        # Giả lập 2 file part của 2 video đang tải song song
        my_part = os.path.join(self.tmpdir, "My_Film_Ep1.mp4.part")
        other_part = os.path.join(self.tmpdir, "Other_Film_Ep5.mp4.part")

        with open(my_part, "w") as f:
            f.write("part 1")
        with open(other_part, "w") as f:
            f.write("part other")

        worker = DownloadWorker("https://www.youtube.com/watch?v=myvideo1234", {
            "title": "My Film Ep1",
            "output_path": self.tmpdir,
        })
        # Gán _resolved_title như worker thực tế
        worker._resolved_title = "My Film Ep1"

        # Kích hoạt dọn dẹp file part của worker này
        worker._cleanup_my_part_files(self.tmpdir)

        # File của worker này bị dọn
        self.assertFalse(os.path.exists(my_part), "File part của video này phải được dọn.")
        # File của video khác TUYỆT ĐỐI KHÔNG BỊ XÓA
        self.assertTrue(os.path.exists(other_part), "File part của video khác không được phép bị xóa!")


class TestCookieAutoSyncContract(unittest.TestCase):
    """Kiểm tra hợp đồng giao tiếp giữa LocalServer và Extension về việc tự động lấy Live Cookies trước khi tải."""

    def test_local_server_cookie_request_dispatch(self):
        """LocalServer phải gửi đúng sự kiện REQUEST_COOKIES với domain='all' và force=True."""
        from local_server import LocalServer
        server = LocalServer()
        port = server.start()
        try:
            self.assertIsNotNone(port, "LocalServer must bind to a port in range 42124-42135")
            sent = server.request_cookie_refresh("all", "auto_pre_download", force=True)
            self.assertTrue(sent)
            events = server.get_and_clear_events(timeout=0.1)
            self.assertEqual(len(events), 1)
            self.assertEqual(events[0]["action"], "REQUEST_COOKIES")
            self.assertEqual(events[0]["domain"], "all")
            self.assertEqual(events[0]["reason"], "auto_pre_download")
        finally:
            server.stop()


def run_live_tests():
    """Kiểm thử trực tiếp qua mạng (Live Info Extraction Probe)."""
    print("\n" + "=" * 60)
    print("BẮT ĐẦU CHẠY KIỂM THỬ TRỰC TUYẾN (LIVE NETWORK PROBES)")
    print("=" * 60)

    import yt_dlp

    sample_urls = [
        ("YouTube", "https://www.youtube.com/watch?v=dQw4w9WgXcQ"),
        ("Bilibili", "https://www.bilibili.com/video/BV1xx411c7mD"),
    ]

    all_ok = True
    for platform, url in sample_urls:
        print(f"\n[LIVE PROBE] Đang thử trích xuất thông tin ({platform}): {url}")
        try:
            worker = DownloadWorker(url, {"title": f"Live_{platform}"})
            opts = worker.get_base_opts(os.getcwd())
            opts["skip_download"] = True
            opts["quiet"] = True

            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=False)
                title = info.get("title", "Unknown")
                formats = len(info.get("formats", []))
                print(f"  -> [OK] Trích xuất thành công: {title[:50]}... ({formats} formats)")
        except Exception as e:
            print(f"  -> [CẢNH BÁO LIVE] Lỗi kết nối {platform}: {e}")
            all_ok = False

    return all_ok


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="QA Test Suite for Downloader Application")
    parser.add_argument("--live", action="store_true", help="Chạy kiểm thử trực tuyến (Live Network Extraction)")
    args, unknown = parser.parse_known_args()

    print("=" * 60)
    print("KHỞI CHẠY BỘ KIỂM THỬ QA TOÀN DIỆN (OFFLINE CONTRACT SUITE)")
    print("=" * 60)

    # Chạy UnitTest suite
    suite = unittest.TestSuite()
    loader = unittest.TestLoader()

    suite.addTests(loader.loadTestsFromTestCase(TestFilenameAndPrefix))
    suite.addTests(loader.loadTestsFromTestCase(TestDuplicateHandling))
    suite.addTests(loader.loadTestsFromTestCase(TestYouTubeRegression))
    suite.addTests(loader.loadTestsFromTestCase(TestBilibiliRegression))
    suite.addTests(loader.loadTestsFromTestCase(TestDouyinRegression))
    suite.addTests(loader.loadTestsFromTestCase(TestPartFileCleanupIsolation))
    suite.addTests(loader.loadTestsFromTestCase(TestCookieAutoSyncContract))

    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    if not result.wasSuccessful():
        print("\n[THẤT BẠI] Có bài kiểm thử không vượt qua!")
        sys.exit(1)

    print(f"\n[THÀNH CÔNG] Toàn bộ {result.testsRun} bài kiểm thử Contract & Regression đều ĐẠT (PASS)!")

    if args.live:
        live_ok = run_live_tests()
        if not live_ok:
            print("\n[LƯU Ý] Kiểm thử trực tuyến gặp sự cố mạng/chặn kết nối.")
            sys.exit(2)
        else:
            print("\n[THÀNH CÔNG] Kiểm thử trực tuyến Live Network cũng đã hoàn tất xuất sắc!")

    sys.exit(0)
