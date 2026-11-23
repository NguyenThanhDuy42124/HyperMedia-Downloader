"""
tests/test_exe_clean_machine_smoke.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Kiểm thử khởi chạy trực tiếp file EXE đóng gói (dist_verified/HyperMedia_Downloader_Pro.exe)
từ thư mục làm việc bên ngoài workspace (tempdir), trong môi trường PATH được lọc sạch
100% Node.js, Deno, Bun và NVM.

Xác minh:
1. Tiến trình EXE khởi chạy thành công.
2. Thư mục _MEIPASS của tiến trình được giải nén hợp lệ trên hệ thống.
3. Runtime qjs.exe và ffmpeg.exe nằm đúng bên trong _MEIPASS.
4. Tài nguyên giải mã yt_dlp_ejs (core.min.js, lib.min.js) hiện diện trong _MEIPASS.
5. QuickJS nhúng bên trong _MEIPASS thực thi mã JavaScript thành công.
"""

import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")


class TestExeCleanMachineSmoke(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        # Đường dẫn file EXE đã đóng gói (ưu tiên bản build mới trong dist, fallback dist_verified)
        repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        dist_candidate = os.path.join(repo_root, "dist", "HyperMedia_Downloader_Pro.exe")
        verified_candidate = os.path.join(repo_root, "dist_verified", "HyperMedia_Downloader_Pro.exe")
        if os.path.exists(dist_candidate):
            cls.exe_path = dist_candidate
        elif os.path.exists(verified_candidate):
            cls.exe_path = verified_candidate
        else:
            raise unittest.SkipTest(f"Không tìm thấy file EXE tại dist hoặc dist_verified")

    def test_exe_clean_machine_launch_and_runtime_in_meipass(self):
        # 1. Chuẩn bị môi trường sạch: Lọc triệt để Node, Deno, Bun khỏi PATH
        orig_path = os.environ.get("PATH", "")
        filtered_path = os.pathsep.join([
            p for p in orig_path.split(os.pathsep)
            if p and not any(k in p.lower() for k in ["node", "deno", "bun", "nvm"])
        ])
        clean_env = os.environ.copy()
        clean_env["PATH"] = filtered_path

        # 2. Đặt CWD hoàn toàn bên ngoài workspace (thư mục temp của hệ điều hành)
        external_cwd = tempfile.gettempdir()

        # 3. Khởi chạy tiến trình EXE độc lập
        proc = subprocess.Popen(
            [self.exe_path],
            cwd=external_cwd,
            env=clean_env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        pid = proc.pid
        self.assertIsNotNone(pid, "Tiến trình EXE không thể khởi chạy")

        try:
            # Chờ bootloader PyInstaller bung nén đầy đủ _MEIPASS (tối đa 6 giây)
            temp_root = tempfile.gettempdir()
            mei_prefix = f"_MEI{pid}"
            deadline = time.time() + 6.0
            meipass_dir = None

            while time.time() < deadline:
                matching_dirs = [
                    os.path.join(temp_root, d) for d in os.listdir(temp_root)
                    if d.startswith(mei_prefix)
                ]
                if matching_dirs:
                    candidate = sorted(matching_dirs, key=lambda p: os.path.getmtime(p), reverse=True)[0]
                    if os.path.exists(os.path.join(candidate, "qjs.exe")) and \
                       os.path.exists(os.path.join(candidate, "yt_dlp_ejs", "yt", "solver", "core.min.js")):
                        meipass_dir = candidate
                        break
                time.sleep(0.3)

            self.assertIsNotNone(
                meipass_dir,
                f"Không tìm thấy hoặc chưa bung xong thư mục _MEIPASS khớp với PID {pid} (tiền tố {mei_prefix})"
            )
            print(f"\n[EXE SMOKE] Đã định vị thư mục _MEIPASS thực tế của PID {pid}: {meipass_dir}")

            # 5. Kiểm tra runtime qjs.exe và ffmpeg.exe nằm đúng trong _MEIPASS
            qjs_in_mei = os.path.join(meipass_dir, "qjs.exe")
            ffmpeg_in_mei = os.path.join(meipass_dir, "ffmpeg.exe")

            self.assertTrue(os.path.exists(qjs_in_mei), f"qjs.exe không tồn tại trong _MEIPASS: {qjs_in_mei}")
            self.assertTrue(os.path.exists(ffmpeg_in_mei), f"ffmpeg.exe không tồn tại trong _MEIPASS: {ffmpeg_in_mei}")
            print(f"[EXE SMOKE] Xác nhận qjs.exe: {qjs_in_mei} (kích thước: {os.path.getsize(qjs_in_mei)} bytes)")
            print(f"[EXE SMOKE] Xác nhận ffmpeg.exe: {ffmpeg_in_mei} (kích thước: {os.path.getsize(ffmpeg_in_mei)} bytes)")

            # 6. Kiểm tra các solver scripts của yt_dlp_ejs nằm trong _MEIPASS
            core_js = os.path.join(meipass_dir, "yt_dlp_ejs", "yt", "solver", "core.min.js")
            lib_js = os.path.join(meipass_dir, "yt_dlp_ejs", "yt", "solver", "lib.min.js")
            self.assertTrue(os.path.exists(core_js), f"core.min.js không có trong _MEIPASS: {core_js}")
            self.assertTrue(os.path.exists(lib_js), f"lib.min.js không có trong _MEIPASS: {lib_js}")

            # 7. Thực thi QuickJS nhúng bên trong _MEIPASS với clean environment
            res = subprocess.check_output(
                [qjs_in_mei, "-e", "console.log('QuickJS-Execution-Verified-' + (21 * 2))"],
                text=True,
                env=clean_env,
                timeout=5,
            )
            self.assertIn("QuickJS-Execution-Verified-42", res.strip(), f"Kết quả chạy QuickJS không đúng: {res}")
            print(f"[EXE SMOKE] QuickJS thực thi trực tiếp từ _MEIPASS thành công: {res.strip()}")

            # 8. Kiểm tra TLS CA bundle certifi/cacert.pem nằm hợp lệ trong _MEIPASS
            ca_cert_mei = os.path.join(meipass_dir, "certifi", "cacert.pem")
            self.assertTrue(os.path.exists(ca_cert_mei), f"certifi/cacert.pem không tồn tại trong _MEIPASS: {ca_cert_mei}")
            self.assertGreater(os.path.getsize(ca_cert_mei), 10000, f"cacert.pem có kích thước bất thường: {ca_cert_mei}")
            print(f"[EXE SMOKE] Xác nhận certifi/cacert.pem: {ca_cert_mei} (kích thước: {os.path.getsize(ca_cert_mei)} bytes)")

        finally:
            # Dọn dẹp an toàn tiến trình EXE sau khi kiểm thử xong
            try:
                proc.terminate()
                proc.wait(timeout=3)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass


if __name__ == "__main__":
    unittest.main()
