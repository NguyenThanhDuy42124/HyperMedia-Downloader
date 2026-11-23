"""
tests/test_youtube_clean_machine_smoke.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Smoke test YouTube n-sig / cipher solving on a clean machine simulation:
PATH is stripped of Node, Deno, and Bun, leaving only embedded QuickJS (qjs.exe).
"""

import os
import shutil
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app_constants import get_js_runtime


class BaseCleanMachineTestCase(unittest.TestCase):
    def setUp(self):
        # Lưu lại PATH gốc
        self._orig_path = os.environ.get("PATH", "")
        # Lọc sạch Node, Deno, Bun khỏi PATH để mô phỏng 100% môi trường máy khách sạch
        filtered = [
            p for p in self._orig_path.split(os.pathsep)
            if not any(k in p.lower() for k in ["node", "deno", "bun", "nvm"])
        ]
        os.environ["PATH"] = os.pathsep.join(filtered)

    def tearDown(self):
        os.environ["PATH"] = self._orig_path


class TestPythonCleanMachineRuntimeSmoke(BaseCleanMachineTestCase):
    """Kiểm thử Python runtime trên môi trường máy sạch (Zero Node/Deno/Bun, chỉ dùng qjs nhúng)."""

    def test_clean_machine_detects_embedded_qjs(self):
        # 1. Xác nhận Node/Deno/Bun hoàn toàn vắng mặt trong PATH
        self.assertIsNone(shutil.which("node"), "Node vẫn còn trong PATH mô phỏng")
        self.assertIsNone(shutil.which("deno"), "Deno vẫn còn trong PATH mô phỏng")
        self.assertIsNone(shutil.which("bun"), "Bun vẫn còn trong PATH mô phỏng")

        # 2. get_js_runtime() phải tìm thấy qjs.exe nhúng kèm ứng dụng
        runtime = get_js_runtime()
        self.assertIsNotNone(runtime, "Không tìm thấy QuickJS runtime nhúng sẵn")
        self.assertIn("quickjs", runtime)
        self.assertTrue(os.path.exists(runtime["quickjs"]["path"]))

    def test_youtube_quickjs_extractor_initialization(self):
        import yt_dlp

        warnings = []
        class WarningCollector:
            def debug(self, msg): pass
            def info(self, msg): pass
            def warning(self, msg): warnings.append(msg)
            def error(self, msg): pass

        runtime = get_js_runtime()
        ydl_opts = {
            "js_runtimes": runtime,
            "logger": WarningCollector(),
            "quiet": True,
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ie = ydl.get_info_extractor("Youtube")
            ie.initialize()
            providers = ie._jsc_director.providers
            self.assertTrue(
                providers["QuickJS"].is_available(),
                "QuickJS JSC provider không khả dụng trên môi trường máy sạch!"
            )
            # Khẳng định không có cảnh báo 'No supported JavaScript runtime could be found'
            self.assertFalse(
                any("No supported JavaScript runtime could be found" in w for w in warnings),
                f"Phát hiện cảnh báo thiếu JS runtime: {warnings}"
            )


class TestYouTubeLiveNetworkRangeProbe(BaseCleanMachineTestCase):
    """Kiểm thử trực tiếp qua mạng: giải mã cipher/n-sig và gửi HTTP Range 0-1024 tới Google CDN."""

    def test_youtube_stream_bytes_download_clean_machine(self):
        """Kiểm tra giải mã chữ ký và gửi request HTTP Range tới GoogleVideo CDN thành công (200/206, không bị 403)."""
        import yt_dlp
        import requests

        runtime = get_js_runtime()
        ydl_opts = {
            "js_runtimes": runtime,
            "quiet": True,
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            # Dùng clip YouTube công khai chuẩn để test stream URL
            info = ydl.extract_info("https://www.youtube.com/watch?v=jNQXAC9IVRw", download=False)
            candidates = [f for f in info.get("formats", []) if f.get("url") and f.get("vcodec") != "none"]
            self.assertTrue(len(candidates) > 0, "Không tìm thấy định dạng video hợp lệ")

            resp = None
            last_err = None
            for fmt in candidates[:3]:
                stream_url = fmt["url"]
                headers = fmt.get("http_headers", {}).copy()
                headers["Range"] = "bytes=0-1024"
                try:
                    resp = requests.get(stream_url, headers=headers, timeout=15)
                    if resp.status_code in (200, 206):
                        break
                except requests.exceptions.RequestException as err:
                    last_err = err
                    continue

            if resp is None:
                if last_err:
                    raise last_err
                self.fail("Không thể kết nối đến stream URL sau khi thử các định dạng")

            self.assertIn(
                resp.status_code,
                (200, 206),
                f"Google CDN từ chối giải mã n-sig với HTTP {resp.status_code}"
            )
            self.assertGreater(len(resp.content), 0, "Không nhận được dữ liệu stream")


# Alias for backwards compatibility
class TestYouTubeCleanMachineSmoke(TestPythonCleanMachineRuntimeSmoke, TestYouTubeLiveNetworkRangeProbe):
    pass


if __name__ == "__main__":
    unittest.main()
