import glob
import os
import sys
import time

def safe_print(*args, **kwargs):
    try:
        print(*args, **kwargs)
    except Exception:
        try:
            msg = " ".join(str(a) for a in args)
            clean_msg = msg.encode("ascii", "backslashreplace").decode("ascii")
            print(clean_msg, **kwargs)
        except Exception:
            pass

from PySide6.QtCore import QThread, Signal

import yt_dlp

import random

from app_constants import (
    AUTO_BROWSERS,
    BROWSER_MAP,
    DEFAULT_UA,
    get_random_user_agent,
    get_js_runtime,
    RESOLUTION_MAP,
    cookies_file,
)
from logger import MyLogger, app_logger
from site_utils import detect_site, is_bilibili_url, is_youtube_url, normalize_url

try:
    from bilibili_patch import patch_bilibili_anti_throttling, patch_bilibili_extractor
    patch_bilibili_extractor()
    patch_bilibili_anti_throttling()
except Exception as e:
    pass


class DownloadWorker(QThread):
    task_progress = Signal(int)
    task_finished = Signal()
    task_error = Signal(str)
    task_stopped = Signal()
    status_update = Signal(str)
    cookie_refresh_requested = Signal(str, str)  # (domain, reason)

    def __init__(self, url, options, parent=None):
        super().__init__(parent)
        self.url = url
        self.options = options or {}
        self._is_running = True
        self.cookies_file_path = cookies_file()

    def stop(self):
        self._is_running = False

    def get_ffmpeg_path(self):
        import sys

        if getattr(sys, "frozen", False):
            return os.path.join(sys._MEIPASS, "ffmpeg.exe")
        return os.path.join(os.getcwd(), "ffmpeg.exe")

    def on_stdout_progress(self, line):
        if not self._is_running or not line:
            return
        import re
        if "Got error:" in line:
            # 1. Bắt lỗi HTTP 503 hoặc RemoteDisconnected (Máy chủ CDN từ chối / Token chết)
            if any(k in line for k in ["HTTP Error 503", "RemoteDisconnected", "Connection aborted", "Service Unavailable"]):
                self._server_err_count = getattr(self, "_server_err_count", 0) + 1
                if self._server_err_count == 2:
                    dom = "bilibili.com" if is_bilibili_url(self.url) else "all"
                    self.cookie_refresh_requested.emit(dom, "cdn_503_or_disconnect")
                if self._server_err_count >= 3:
                    safe_print(
                        f"[SERVER 503 DETECTOR] Máy chủ CDN từ chối phục vụ ({line[:80].strip()}) ({self._server_err_count} lần)! "
                        f"Dừng ngay để tránh kẹt hàng đợi và chuyển sang tập tiếp theo..."
                    )
                    self._is_running = False
                    return

            # 2. Bắt lỗi kẹt lặp lại cùng một vị trí byte
            if "bytes read" in line:
                m_err = re.search(r"Got error:\s*(\d+)\s+bytes read", line)
                if m_err:
                    b_read = int(m_err.group(1))
                    if getattr(self, "_last_stuck_bytes", None) == b_read:
                        self._stuck_repeat_count = getattr(self, "_stuck_repeat_count", 0) + 1
                    else:
                        self._last_stuck_bytes = b_read
                        self._stuck_repeat_count = 1

                    if self._stuck_repeat_count >= 5:
                        safe_print(
                            f"[STUCK DETECTOR] Bilibili CDN liên tục ngắt kết nối tại {b_read} bytes ({self._stuck_repeat_count} lần)! "
                            f"Tự động dừng phiên hiện tại để nhường lượt cho tập khác & kích hoạt Fallback..."
                        )
                        self._is_running = False
                        return
            return

        m = re.search(r"\[download\]\s+([\d\.]+)%\s+of\s+~?\s*([\d\.\w]+)\s+at\s+([\d\.\w/]+)\s+ETA\s+([\d:]+)", line)
        if m:
            pct_str, total_str, speed_str, eta_str = m.groups()
            try:
                pct = float(pct_str)
                self.task_progress.emit(int(pct))
            except ValueError:
                pass
            n_threads = self.options.get("num_threads", 16)
            status_msg = f"TH:{n_threads}|TIME:00:00:00|DL:Đang tải / {total_str}|SPD:{speed_str}|ETA:Còn ~{eta_str}"
            self.status_update.emit(status_msg)

    def get_base_opts(self, out_path):
        self._logger = MyLogger(callback=self.on_stdout_progress)
        num_threads = self.options.get("num_threads", 16)
        chunk_mode = self.options.get("chunk_mode", "Tự động (10MB)")

        chunk_size_map = {
            "Tự động (10MB)": 10485760,
            "Nhỏ (2MB)": 2097152,
            "Vừa (5MB)": 5242880,
            "Lớn (20MB)": 20971520,
            "Tắt Chunking (Đơn luồng)": None,
        }
        chunk_size = chunk_size_map.get(chunk_mode, 10485760)

        selected_ua = get_random_user_agent()
        site_headers = detect_site(self.url)
        site_headers["User-Agent"] = selected_ua

        custom_title = (self.options.get("title") or "").strip()
        if custom_title and custom_title != "Unknown" and len(custom_title) > 0:
            safe_title = "".join(c for c in custom_title if c not in r'\/:*?"<>|').strip()
            # Cắt ngắn nếu quá dài tránh lỗi MAX_PATH trên Windows
            safe_title = safe_title[:150]
            out_tmpl = f"{out_path}/{safe_title}.%(ext)s"
        else:
            out_tmpl = f"{out_path}/%(title)s.%(ext)s"

        opts = {
            "outtmpl": out_tmpl,
            "progress_hooks": [self.progress_hook],
            "quiet": True,
            "no_warnings": False,
            "logger": self._logger,
            "ffmpeg_location": self.get_ffmpeg_path(),
            "windowsfilenames": True,
            "retries": 10,
            "fragment_retries": 10,
            "extractor_retries": 5,
            "socket_timeout": 45 if is_bilibili_url(self.url) else 30,
            "continuedl": True,
            "retry_sleep_functions": {
                "http": lambda n: (min(10.0, 1.5 + random.uniform(0.5, 1.5) * min(n, 5)) if is_bilibili_url(self.url) else min(15.0, 1.5 * min(n, 10) + random.uniform(1.0, 3.0))),
                "fragment": lambda n: (min(8.0, 1.2 + random.uniform(0.5, 1.5) * min(n, 5)) if is_bilibili_url(self.url) else min(10.0, 1.0 * min(n, 10) + random.uniform(0.5, 2.0))),
                "extractor": lambda n: min(15.0, 2.0 * min(n, 5) + random.uniform(1.0, 2.5)),
            },
            "user_agent": selected_ua,
            "http_headers": site_headers,
            "concurrent_fragment_downloads": 6 if is_bilibili_url(self.url) else num_threads,
            "skip_unavailable_fragments": True,
            "buffersize": 4 * 1024 * 1024 if is_bilibili_url(self.url) else 2 * 1024 * 1024,
        }
        if is_bilibili_url(self.url):
            # Config E: 6 luồng song song + chunk 8MB tối ưu cho Video lớn
            # Với luồng audio nhỏ (~1MB), yt-dlp nếu gặp lỗi fragment sẽ tự retry đơn luồng
            opts["http_chunk_size"] = 8 * 1024 * 1024
        elif chunk_size is not None:
            # Random jitter 10MB +- 64KB cho YouTube/Douyin
            jittered_chunk = max(1048576, chunk_size + random.randint(-65536, 65536))
            opts["http_chunk_size"] = jittered_chunk

        if self.options.get("skip_existing"):
            opts["overwrites"] = False

        opts["source_address"] = "0.0.0.0"
        js_runtime = get_js_runtime()
        if js_runtime:
            opts["js_runtimes"] = js_runtime
        if is_youtube_url(self.url):
            opts["extractor_args"] = {
                "youtube": {
                    "player_client": ["web_embedded", "android"]
                }
            }
        elif is_bilibili_url(self.url):
            # fnval=4048: bắt buộc để Bilibili API trả DASH stream thay vì MP4 đơn bị cap 720P
            # DASH mode cho phép tải hình (30080 = 1080P H264) + tiếng (30280 = 192kbps AAC) riêng biệt
            opts["extractor_args"] = {
                "bilibili": {
                    "fnval": [4048]
                }
            }
        return opts

    def _check_warnings_for_issues(self):
        if not hasattr(self, "_logger"):
            return None
        warns = " ".join(self._logger.warnings)
        if "cookies are no longer valid" in warns or "cookies have been rotated" in warns:
            return "expired_cookies"
        if "n challenge solving failed" in warns:
            return "n_challenge"
        if "Only images are available" in warns:
            return "no_formats"
        return None

    def apply_format_options(self, ydl_opts):
        if self.options.get("format_id"):
            ydl_opts["format"] = self.options["format_id"]
            ydl_opts["merge_output_format"] = "mp4"
            print(f"[Download] Áp dụng Format ID tùy chọn: {self.options['format_id']}")
            return

        file_type = self.options.get("file_type", "mp4")

        def parse_resolution(value):
            if not value or value == "best":
                return None
            try:
                return int(value)
            except ValueError:
                return RESOLUTION_MAP.get(value)

        if file_type == "mp3":
            bitrate = self.options.get("bitrate", "320")
            ydl_opts.update(
                {
                    "format": "bestaudio/best",
                    "postprocessors": [
                        {
                            "key": "FFmpegExtractAudio",
                            "preferredcodec": "mp3",
                            "preferredquality": bitrate,
                        }
                    ],
                }
            )
        elif file_type == "mp4":
            resolution = parse_resolution(self.options.get("resolution", "best"))
            codec = self.options.get("codec", "H.264")
            if codec == "H.264":
                if resolution:
                    fmt = (
                        f"bestvideo[vcodec^=avc1][height<={resolution}]+bestaudio[ext=m4a]/"
                        f"bestvideo[height<={resolution}]+bestaudio/"
                        f"best[height<={resolution}]/best"
                    )
                else:
                    fmt = "bestvideo[vcodec^=avc1]+bestaudio[ext=m4a]/bestvideo+bestaudio/best"
                ydl_opts.update({"format": fmt, "merge_output_format": "mp4"})
                ydl_opts["postprocessors"] = ydl_opts.get("postprocessors", []) + [
                    {"key": "FFmpegVideoConvertor", "preferedformat": "mp4"}
                ]
            elif codec == "HEVC":
                if resolution:
                    fmt = (
                        f"bestvideo[vcodec^=hvc1][height<={resolution}]+bestaudio[ext=m4a]/"
                        f"bestvideo[height<={resolution}]+bestaudio/"
                        f"best[height<={resolution}]/best"
                    )
                else:
                    fmt = "bestvideo[vcodec^=hvc1]+bestaudio[ext=m4a]/bestvideo+bestaudio/best"
                ydl_opts.update({"format": fmt, "merge_output_format": "mp4"})
                ydl_opts["postprocessors"] = ydl_opts.get("postprocessors", []) + [
                    {"key": "FFmpegVideoConvertor", "preferedformat": "mp4"}
                ]
            else:  # VA1
                if resolution:
                    fmt = (
                        f"bestvideo[vcodec^=av01][height<={resolution}]+bestaudio/"
                        f"bestvideo[height<={resolution}]+bestaudio/"
                        f"best[height<={resolution}]/best"
                    )
                else:
                    fmt = "bestvideo[vcodec^=av01]+bestaudio/bestvideo+bestaudio/best"
                ydl_opts.update({"format": fmt, "merge_output_format": "mp4"})
        elif file_type == "av1" or self.options.get("av1_smart_trick"):
            resolution = parse_resolution(self.options.get("resolution", "best"))
            res_fmt = f"[height<={resolution}]" if resolution else ""
            fmt = f"bestvideo[vcodec^=av01]{res_fmt}+bestaudio/bestvideo{res_fmt}+bestaudio/best"
            safe_print("[AV1 SMART TRICK] Tải luồng AV1 siêu nhẹ (Miễn Phí Khỏi VIP) -> FFmpeg tự recode MP4...")
            ydl_opts.update({
                "format": fmt,
                "merge_output_format": "mp4",
                "postprocessors": [
                    {"key": "FFmpegVideoConvertor", "preferedformat": "mp4"}
                ]
            })

        # Anti-Bot Bypass Headers & Buffer Tuning
        site_headers = detect_site(self.url)
        if "User-Agent" not in site_headers:
            site_headers["User-Agent"] = DEFAULT_UA
        ydl_opts.update({
            "http_headers": site_headers,
            "buffersize": 1048576,
            "nocheckcertificate": True,
        })

    def _cleanup_my_part_files(self, out_path):
        """Chỉ dọn dẹp các file .part dở dang của chính video này, tuyệt đối không xóa nhầm file của các tác vụ tải song song khác."""
        try:
            target_hints = []
            title = self.options.get("title") or getattr(self, "title", "")
            if title:
                safe_title = "".join(c for c in title if c not in r'\/:*?"<>|').strip()[:30]
                if len(safe_title) >= 3:
                    target_hints.append(safe_title.lower())

            import re
            m = re.search(r'(BV[0-9a-zA-Z]{10}|\d{15,22}|[a-zA-Z0-9_-]{11})', self.url)
            if m:
                target_hints.append(m.group(1).lower())

            if not target_hints:
                return

            for pf in glob.glob(os.path.join(out_path, "*.part")):
                fname = os.path.basename(pf).lower()
                if any(hint in fname for hint in target_hints):
                    try:
                        os.remove(pf)
                    except OSError:
                        pass
        except Exception:
            pass

    def download_with_format_fallback(self, opts):
        n_threads = opts.get("concurrent_fragment_downloads", 1)
        out_path = self.options.get("output_path", "downloads")
        if n_threads > 1:
            safe_print(f"[LUỒNG TẢI] Kích hoạt {n_threads} luồng tải song song (Anti-Bot Mode)...")
        else:
            safe_print("[LUỒNG TẢI] Kích hoạt chế độ Đơn Luồng Ổn Định 100% (Anti-Drop CDN Mode)...")

        # Tự động dọn dẹp file .part dở dang của CHÍNH VIDEO NÀY để tránh kẹt continuedl
        self._cleanup_my_part_files(out_path)

        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                ydl.download([self.url])
        except Exception as e:
            err_str = str(e) or ""
            is_bilibili = "bilibili.com" in self.url.lower()
            if is_bilibili and ("702450" in err_str or "bytes read" in err_str or "more expected" in err_str or "Giving up after" in err_str):
                self.cookie_refresh_requested.emit("bilibili.com", "bilibili_702450_or_cdn_block")
                safe_print("[AV1 AUTO-FALLBACK] Bilibili báo 702450 (Chặn luồng VIP H.264)! Tự động chuyển sang luồng 1080P AV1 Miễn Phí...")
                av1_opts = dict(opts)
                av1_opts.pop("http_chunk_size", None)
                av1_opts["concurrent_fragment_downloads"] = 1
                av1_opts["format"] = "bestvideo[vcodec^=av01]+bestaudio/bestvideo+bestaudio/best"
                av1_opts["merge_output_format"] = "mp4"
                av1_opts["overwrites"] = True
                av1_opts["postprocessors"] = [
                    {"key": "FFmpegVideoConvertor", "preferedformat": "mp4"}
                ]
                self._cleanup_my_part_files(out_path)
                try:
                    with yt_dlp.YoutubeDL(av1_opts) as ydl:
                        ydl.download([self.url])
                    return
                except Exception as av1_err:
                    safe_print(f"[AV1 FALLBACK ERROR] Luồng AV1 cũng không tải được: {av1_err}")
                    raise av1_err

            is_socket_drop = "bytes read" in err_str or "more expected" in err_str or "Giving up after" in err_str
            if is_socket_drop and (opts.get("http_chunk_size") or opts.get("concurrent_fragment_downloads", 1) > 1):
                safe_print("[FALLBACK] CDN ngắt kết nối đa luồng. Tự động chuyển sang Đơn Luồng Trực Tiếp 100% Ổn Định...")
                safe_opts = dict(opts)
                safe_opts.pop("http_chunk_size", None)
                safe_opts["concurrent_fragment_downloads"] = 1
                safe_opts["overwrites"] = True
                self._cleanup_my_part_files(out_path)
                with yt_dlp.YoutubeDL(safe_opts) as ydl:
                    ydl.download([self.url])
                return

            is_youtube = is_youtube_url(self.url)
            if is_youtube and ("403" in err_str or "Forbidden" in err_str or "Requested format" in err_str or "n_challenge" in err_str):
                safe_print("[YOUTUBE AUTO-FALLBACK] YouTube hạn chế stream (HTTP 403 hoặc Cipher)! Kích hoạt luồng web_embedded/android fallback...")
                yt_opts = dict(opts)
                yt_opts["extractor_args"] = {"youtube": {"player_client": ["web_embedded", "android"]}}
                yt_opts["source_address"] = "0.0.0.0"
                js_runtime = get_js_runtime()
                if js_runtime:
                    yt_opts["js_runtimes"] = js_runtime
                yt_opts["format"] = "bestvideo[height<=1080]+bestaudio/bestvideo+bestaudio/best"
                yt_opts["merge_output_format"] = "mp4"
                self._cleanup_my_part_files(out_path)
                try:
                    with yt_dlp.YoutubeDL(yt_opts) as ydl:
                        ydl.download([self.url])
                    return
                except Exception as yt_err:
                    safe_print(f"[YOUTUBE FALLBACK ERROR] {yt_err}")

            is_format_issue = (
                "Requested format is not available" in err_str
                or "Only images are available" in err_str
            )
            if is_format_issue and self.options.get("file_type", "mp4") != "mp3":
                heights = sorted(
                    set(self.options.get("available_heights") or []), reverse=True
                )
                selected = self.options.get("resolution")
                target = None
                if selected and selected != "best":
                    try:
                        target = int(selected)
                    except ValueError:
                        target = RESOLUTION_MAP.get(selected)

                chain = []
                for h in heights:
                    if h < 360:
                        continue
                    if target is None or h <= target:
                        chain.append(f"bestvideo[height<={h}]+bestaudio")
                if not chain:
                    chain = ["bestvideo+bestaudio"]
                chain.append("best")

                self.status_update.emit(
                    f"Chất lượng {selected or 'best'} không khả dụng, thử hạ xuống..."
                )
                print(f"[Download] Format fallback: {chain}")
                relaxed = dict(opts)
                relaxed["format"] = "/".join(chain)
                relaxed.pop("merge_output_format", None)
                relaxed.pop("postprocessors", None)
                self._logger = MyLogger()
                relaxed["logger"] = self._logger
                with yt_dlp.YoutubeDL(relaxed) as ydl:
                    ydl.download([self.url])
                return
            raise

    def _validate_cookies_file(self):
        if not os.path.exists(self.cookies_file_path):
            return False, "not_found"
        try:
            with open(self.cookies_file_path, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
            if len(content.strip()) < 50:
                return False, "empty"
            has_youtube = ".youtube.com" in content
            has_bilibili = ".bilibili.com" in content
            has_douyin = ".douyin.com" in content
            if not has_youtube and not has_bilibili and not has_douyin:
                return False, "no_known_site"
            has_auth = any(
                k in content
                for k in ["SID", "SSID", "LOGIN_INFO", "SESSDATA", "bili_jct", "DedeUserID", "sessionid", "ttwid", "passport_csrf_token", "s_v_web_id"]
            )
            if not has_auth:
                return False, "no_auth_cookies"
            return True, "ok"
        except Exception as e:
            return False, f"read_error: {e}"

    def _resolve_browsers(self, browser_setting):
        if browser_setting in BROWSER_MAP:
            return [BROWSER_MAP[browser_setting]]
        return list(AUTO_BROWSERS)

    def _try_browser_cookies(self, out_path, browsers):
        for b in browsers:
            if not self._is_running:
                return False
            self.status_update.emit(f"Đang thử cookie từ {b}...")
            print(f"[Download] Thử cookiesfrombrowser: {b}")
            try:
                opts = self.get_base_opts(out_path)
                self.apply_format_options(opts)
                opts["cookiesfrombrowser"] = (b,)
                self.download_with_format_fallback(opts)
                return True
            except Exception as e:
                if "Stopped by user" in str(e):
                    self.task_stopped.emit()
                    return False
                issue = self._check_warnings_for_issues()
                if issue == "expired_cookies":
                    continue
                print(f"[Download] Browser '{b}' thất bại: {str(e)[:120]}")
                continue
        return False

    def run(self):
        try:
            self.url = normalize_url(self.url)
            out_path = self.options.get("output_path", "downloads")
            if not os.path.exists(out_path):
                os.makedirs(out_path)

            if self.options.get("skip_existing") and self._file_exists(out_path):
                self.status_update.emit("File đã có sẵn, bỏ qua...")
                self.task_finished.emit()
                return

            browser_setting = self.options.get("browser", "Auto")
            success = False
            auth_error_encountered = False

            if not self._is_running:
                return

            cookies_valid, cookies_status = self._validate_cookies_file()

            # Douyin 1080p Direct Unlocker
            if "douyin.com" in self.url:
                req_res = str(self.options.get("resolution", "best")).lower()
                fmt_id = str(self.options.get("format_id", ""))
                if req_res in ("best", "1080", "2k", "4k", "") or "douyin_1080p" in fmt_id:
                    import re, requests
                    vid = None
                    if "douyin_1080p_" in fmt_id:
                        vid = fmt_id.replace("douyin_1080p_", "")
                    if not vid:
                        try:
                            with yt_dlp.YoutubeDL({"cookiefile": self.cookies_file_path if cookies_valid else None, "quiet": True}) as ydl:
                                inf = ydl.extract_info(self.url, download=False)
                                for f in inf.get("formats", []):
                                    u_str = f.get("url", "") or f.get("format_id", "")
                                    m = re.search(r'video_id=([a-zA-Z0-9_-]+)', u_str) or re.search(r'(v0[0-9a-zA-Z]+)', u_str)
                                    if m:
                                        vid = m.group(1)
                                        break
                        except Exception:
                            pass
                    if vid:
                        direct_1080_url = f"https://aweme.snssdk.com/aweme/v1/play/?video_id={vid}&ratio=1080p&line=0"
                        try:
                            chk = requests.head(direct_1080_url, headers={
                                "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1"
                            }, allow_redirects=True, timeout=4)
                            if chk.status_code == 200:
                                safe_print(f"[Douyin 1080p UNLOCK] Tìm thấy luồng Full HD 1080p gốc ({vid})! Đang tải...")
                                opts = self.get_base_opts(out_path)
                                self.apply_format_options(opts)
                                opts["http_headers"] = {
                                    "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1"
                                }
                                if cookies_valid:
                                    opts["cookiefile"] = self.cookies_file_path
                                # Đặt tên file đầu ra theo title video
                                video_title = self.options.get("title", "") or f"douyin_{vid}"
                                safe_title = "".join(c for c in video_title if c not in r'\/:*?"<>|').strip()
                                opts["outtmpl"] = os.path.join(out_path, f"{safe_title}.%(ext)s")
                                with yt_dlp.YoutubeDL(opts) as ydl:
                                    ydl.download([direct_1080_url])
                                self.task_finished.emit()
                                return
                        except Exception as e:
                            safe_print(f"[Douyin 1080p] Luồng 1080p không khả dụng, fallback: {e}")

            # Douyin: uu tien cookies de dat dung chat luong VIP da chon.
            # Bilibili: KHONG dung cookie cho tai khoan free - Bilibili cap free account xuong 480P
            # trong khi anonymous duoc 1080P. Chi dung cookie neu la VIP (se detect qua format check).
            if "douyin.com" in self.url and cookies_valid:
                init_msg = f"TH:16|TIME:00:00:00|DL:Đang chuẩn bị...|SPD:Kết nối 16 luồng VIP...|ETA:Đang giải mã..."
                self.status_update.emit(init_msg)
                print(f"[Download] Dùng cookies cho {self.url} (VIP quality)...")
                try:
                    opts = self.get_base_opts(out_path)
                    self.apply_format_options(opts)
                    opts["cookiefile"] = self.cookies_file_path
                    self.download_with_format_fallback(opts)
                    self.task_finished.emit()
                    return
                except Exception as e:
                    err_str = str(e) or ""
                    if "Stopped by user" in err_str:
                        self.task_stopped.emit()
                        return
                    issue = self._check_warnings_for_issues()
                    if issue == "expired_cookies" or "cookies are no longer valid" in err_str or "702450" in err_str:
                        dom = "bilibili.com" if is_bilibili_url(self.url) else "all"
                        self.cookie_refresh_requested.emit(dom, "expired_cookies")
                        print(f"[Download] cookies.txt hết hạn ({dom}), đã gửi yêu cầu Extension làm mới...")
                    else:
                        print(f"[Download] cookies.txt thất bại, thử anonymous...: {err_str[:120]}")
            elif is_bilibili_url(self.url) and cookies_valid:
                # Kiem tra nhanh: cookie co cho 1080P khong? (neu co = VIP, neu khong = free account)
                try:
                    check_opts = {"quiet": True, "extractor_args": {"bilibili": {"fnval": [4048]}},
                                  "cookiefile": self.cookies_file_path}
                    with yt_dlp.YoutubeDL(check_opts) as _ydl:
                        _info = _ydl.extract_info(self.url, download=False)
                        _heights = [f.get("height", 0) for f in _info.get("formats", []) if f.get("height")]
                        _has_1080p = any(h >= 1080 for h in _heights)
                except Exception:
                    _has_1080p = False

                if _has_1080p:
                    # VIP cookie -> su dung de mo khoa 4K/1080P60
                    print(f"[Download] Bilibili VIP cookie xac nhan - dung cookie cho {self.url}")
                    opts = self.get_base_opts(out_path)
                    self.apply_format_options(opts)
                    opts["cookiefile"] = self.cookies_file_path
                    try:
                        self.download_with_format_fallback(opts)
                        self.task_finished.emit()
                        return
                    except Exception as e:
                        err_str = str(e) or ""
                        if "Stopped by user" in err_str:
                            self.task_stopped.emit()
                            return
                        print(f"[Download] Bilibili VIP cookie that bai, thu anonymous: {err_str[:120]}")
                else:
                    # Free account cookie lam giam chat luong -> bo cookie, dung anonymous
                    print("[Download] Bilibili: tai khoan free phat hien (cookie giam chat luong). Dung anonymous de lay 1080P...")
                    # Tiep tuc xuong anonymous flow ben duoi

            init_msg = f"TH:16|TIME:00:00:00|DL:Đang chuẩn bị...|SPD:Khởi tạo 16 luồng...|ETA:Đang lấy link..."
            self.status_update.emit(init_msg)
            print("[Download] Thử tải Anonymous (Không cookies)...")
            try:
                opts = self.get_base_opts(out_path)
                self.apply_format_options(opts)
                self.download_with_format_fallback(opts)
                success = True
            except Exception as e:
                err_str = str(e) or ""
                if "Stopped by user" in err_str:
                    self.task_stopped.emit()
                    return
                if "n-challenge" in err_str or "Deno" in err_str:
                    self.task_error.emit(err_str[:200])
                    return
                if err_str and any(
                    x in err_str
                    for x in ["Sign in", "Private video", "403", "login",
                              "members-only", "Join this channel", "HTTP Error"]
                ):
                    print(f"[Download] Cần xác thực: {err_str[:80]}...")
                    auth_error_encountered = True
                else:
                    self.task_error.emit(f"Lỗi: {err_str[:200]}")
                    return

            if success:
                self.task_finished.emit()
                return

            if browser_setting == "None":
                self.task_error.emit("Video cần đăng nhập. Chọn Auto hoặc import cookies.")
                return

            if auth_error_encountered:
                if not self._is_running:
                    return

                cookies_tried = False
                cookies_valid, cookies_status = self._validate_cookies_file()
                if cookies_valid:
                    cookies_tried = True
                    self.status_update.emit("Đang dùng file cookies.txt...")
                    print("[Download] Dùng file cookies.txt")
                    try:
                        opts = self.get_base_opts(out_path)
                        self.apply_format_options(opts)
                        opts["cookiefile"] = self.cookies_file_path
                        self.download_with_format_fallback(opts)
                        issue = self._check_warnings_for_issues()
                        if issue == "expired_cookies":
                            print("[WARNING] Cookies expired but download succeeded (public video)")
                        self.task_finished.emit()
                        return
                    except Exception as e:
                        if "Stopped by user" in str(e):
                            self.task_stopped.emit()
                            return
                        err_str = str(e) or ""
                        issue = self._check_warnings_for_issues()
                        if issue == "expired_cookies":
                            print("[Download] cookies.txt hết hạn, thử cookie trình duyệt...")
                        elif err_str and any(
                            x in err_str for x in ["members-only", "Join this channel"]
                        ):
                            self.task_error.emit(
                                "Video dành cho thành viên. Cần tài khoản có membership."
                            )
                            return
                        elif "n-challenge" in err_str or "Deno" in err_str:
                            self.task_error.emit(err_str[:200])
                            return
                        else:
                            print(f"[Download] cookies.txt thất bại: {err_str[:150]}")
                elif cookies_status in ("not_found", "empty", "no_auth_cookies", "no_known_site"):
                    pass
                else:
                    print(f"[Download] cookies.txt lỗi: {cookies_status}")

                if browser_setting != "None":
                    browsers = self._resolve_browsers(browser_setting)
                    if self._try_browser_cookies(out_path, browsers):
                        self.task_finished.emit()
                        return

                if cookies_tried:
                    self.task_error.emit(
                        "Không thể tải video dù đã dùng cookies.\n"
                        "Hãy đăng nhập và xuất lại cookies mới rồi import vào tool."
                    )
                else:
                    self.task_error.emit(
                        "Video cần đăng nhập (hoặc bị chặn).\n"
                        "Hãy import cookies: extension 'Get cookies.txt LOCALLY' "
                        "(YouTube) hoặc xuất cookies bilibili từ trình duyệt."
                    )
                return

        except Exception as e:
            print(f"[CRITICAL WORKER ERROR] {e}")
            app_logger().exception("Worker crash")
            self.task_error.emit(str(e)[:200] or "Lỗi không xác định")

    def _file_exists(self, out_path):
        """Ước lượng tên file theo outtmpl giống yt-dlp; trả True nếu đã có."""
        from yt_dlp.utils import sanitize_filename

        title = sanitize_filename(self.options.get("title") or "", restricted=False)
        if not title:
            return False
        file_type = self.options.get("file_type", "mp4")
        exts = {
            "mp3": ["mp3"],
            "mp4": ["mp4", "mkv", "webm"],
            "av1": ["webm", "mkv", "mp4"],
        }.get(file_type, ["mp4", "mp3", "mkv", "webm"])
        for ext in exts:
            if os.path.exists(os.path.join(out_path, f"{title}.{ext}")):
                return True
        return False

    def progress_hook(self, d):
        if not self._is_running:
            raise yt_dlp.utils.DownloadError("Stopped by user")
        if d.get("status") == "downloading":
            try:
                downloaded = d.get("downloaded_bytes", 0)
                total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
                speed = d.get("speed") or 0
                eta = d.get("eta") or 0
                info_dict = d.get("info_dict") or {}
                duration = info_dict.get("duration")

                if total > 0:
                    pct = int(downloaded / total * 100)
                    if not hasattr(self, "_max_pct"):
                        self._max_pct = 0
                    if pct > self._max_pct:
                        self._max_pct = pct
                    self.task_progress.emit(self._max_pct)

                def fmt_size(b):
                    if not b:
                        return "0 MB"
                    mb = b / (1024 * 1024)
                    return f"{mb / 1024:.2f} GB" if mb >= 1024 else f"{mb:.1f} MB"

                def fmt_speed(s):
                    if not s:
                        return "0.00 MB/s"
                    return f"{s / (1024 * 1024):.2f} MB/s"

                def fmt_time(sec):
                    if not sec or sec < 0:
                        return "00:00:00"
                    m, s = divmod(int(sec), 60)
                    h, m = divmod(m, 60)
                    return f"{h:02d}:{m:02d}:{s:02d}"

                curr_time = time.time()
                if not hasattr(self, "_last_bytes"):
                    self._last_bytes = downloaded
                    self._last_speed_time = curr_time
                    instant_speed = speed
                else:
                    dt = curr_time - self._last_speed_time
                    if dt >= 0.5:
                        d_bytes = downloaded - self._last_bytes
                        instant_speed = (d_bytes / dt) if (dt > 0 and d_bytes >= 0) else speed
                        self._last_bytes = downloaded
                        self._last_speed_time = curr_time
                        self._cached_instant_speed = instant_speed
                    else:
                        instant_speed = getattr(self, "_cached_instant_speed", speed)

                if not hasattr(self, "_max_downloaded"):
                    self._max_downloaded = 0
                if downloaded > self._max_downloaded:
                    self._max_downloaded = downloaded
                dl_str = fmt_size(self._max_downloaded)
                tot_str = fmt_size(total) if total > 0 else "Chưa rõ"

                eta_str = ""
                if total > downloaded and instant_speed > 0:
                    remaining_bytes = total - downloaded
                    rem_sec = int(remaining_bytes / instant_speed)
                    if rem_sec >= 3600:
                        rh, rm = divmod(rem_sec, 3600)
                        rm, _ = divmod(rm, 60)
                        eta_str = f"Còn ~{rh}h{rm:02d}p"
                    elif rem_sec >= 60:
                        rm, rs = divmod(rem_sec, 60)
                        eta_str = f"Còn ~{rm}p{rs:02d}s"
                    else:
                        eta_str = f"Còn ~{rem_sec}s"
                elif eta and eta > 0:
                    rem_sec = int(eta)
                    m, s = divmod(rem_sec, 60)
                    h, m = divmod(m, 60)
                    eta_str = f"Còn ~{h}h{m:02d}p" if h > 0 else f"Còn ~{m}p{s:02d}s"
                else:
                    eta_str = "Còn ~--"

                spd_str = fmt_speed(instant_speed)
                time_ratio = fmt_time(duration) if duration else "00:00:00"

                n_threads = self.options.get("num_threads", 16)
                status_msg = f"TH:{n_threads}|TIME:{time_ratio}|DL:{dl_str} / {tot_str}|SPD:{spd_str}|ETA:{eta_str}"

                curr_time = time.time()
                if not hasattr(self, "_last_log_time") or (curr_time - self._last_log_time) >= 0.5:
                    self._last_log_time = curr_time
                    self.status_update.emit(status_msg)
            except Exception as e:
                print(f"[PROGRESS HOOK ERROR] {e}")
