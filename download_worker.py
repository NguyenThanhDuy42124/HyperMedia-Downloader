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
from site_utils import detect_site, is_bilibili_url, is_youtube_url, normalize_url, is_drama_url

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
        out_p = self.options.get("output_path") or os.path.join(os.getcwd(), "downloads")
        self._resolve_filename(out_p)

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

    def _resolve_filename(self, out_path, raw_title=None):
        """
        Xác định tên file cuối cùng theo cấu hình:
        1. Tiền tố (Prefix):
           - Prefix Số Đầu: 1 ( Tên phim )
           - Prefix Số Đầu (01): 01 ( Tên phim )
           - Prefix Tập + số: Tập 1 - Tên phim
           - Prefix Tên Film: [Tên Film] - Tập 1 (kết hợp ô nhập tên phim)
        2. Tải trùng: Nếu file đã tồn tại và bật allow_duplicates -> tự thêm tiền tố Dup1_, Dup2_...
        """
        # Nếu options đã định nghĩa sẵn exact_file_stem (từ MiniApp/Drama phân cấp hoặc custom)
        if self.options.get("exact_file_stem"):
            provided = self.options["exact_file_stem"]
            safe_title = os.path.basename(provided)
            self._resolved_title = safe_title
            self.exact_file_stem = os.path.join(out_path, safe_title)
            out_tmpl = f"{out_path}/{safe_title}.%(ext)s"
            return safe_title, out_tmpl

        raw = (raw_title or self.options.get("title") or "").strip()
        item_index = self.options.get("item_index", 1)
        prefix_enabled = self.options.get("prefix_enabled", False)
        prefix_mode = (self.options.get("prefix_mode") or self.options.get("prefix_pattern") or "").strip()
        film_name = (self.options.get("film_name") or "").strip()
        allow_duplicates = self.options.get("allow_duplicates", False)

        has_title = bool(raw and raw != "Unknown")
        target_name = film_name if film_name else raw
        has_name = bool(target_name and target_name != "Unknown")

        if prefix_enabled and prefix_mode:
            idx_str = str(item_index)
            idx_2digit = f"{item_index:02d}"
            p_lower = prefix_mode.lower()

            if "tên film" in p_lower or "ten film" in p_lower:
                # 1. Prefix Tên Film: "Tên Film Bạn Nhập - (Tên Film Bạn Tải)"
                film_prefix = film_name if film_name else "Phim"
                if has_title:
                    title = f"{film_prefix} - ({raw})"
                else:
                    title = f"{film_prefix} - (%(title)s)"
            elif "01" in prefix_mode or "2 số" in p_lower or prefix_mode.startswith("01"):
                # 2. Prefix Số Đầu (01): "01 ( Tên Film Bạn Tải )"
                val = raw if has_title else "%(title)s"
                title = f"{idx_2digit} ( {val} )"
            elif "tập" in p_lower or "tap" in p_lower:
                # 3. Prefix Tập + số: "Tập 1 - Tên Film Bạn Tải"
                val = raw if has_title else "%(title)s"
                title = f"Tập {idx_str} - {val}"
            elif p_lower.startswith("[phim]"):
                val = raw if has_title else "%(title)s"
                title = f"[Phim] {val}"
            elif "{title}" in prefix_mode:
                val = raw if has_title else "%(title)s"
                title = prefix_mode.replace("{title}", val).replace("{index}", idx_str).replace("{i}", idx_str).replace("{0index}", idx_2digit)
            elif "{index}" in prefix_mode or "{i}" in prefix_mode:
                pfx = prefix_mode.replace("{index}", idx_str).replace("{i}", idx_str).replace("{0index}", idx_2digit)
                val = raw if has_title else "%(title)s"
                title = f"{pfx}{val}"
            else:
                # 4. Prefix Số Đầu (1): "1 ( Tên Film Bạn Tải )"
                val = raw if has_title else "%(title)s"
                title = f"{idx_str} ( {val} )"
        else:
            title = raw if has_title else "%(title)s"

        if "%(title)s" in title:
            safe_title = None
            out_tmpl = f"{out_path}/{title}.%(ext)s"
        else:
            safe_title = "".join(c for c in title if c not in r'\/:*?"<>|').strip()[:140]
            if not safe_title:
                safe_title = "video"

            # Xử lý tự động thêm Dup1, Dup2... nếu cho phép tải trùng
            if allow_duplicates:
                exts = ["mp4", "mp3", "mkv", "webm", "part"]
                exists = any(os.path.exists(os.path.join(out_path, f"{safe_title}.{ext}")) for ext in exts)
                if exists:
                    dup_idx = 1
                    while True:
                        cand = f"Dup{dup_idx}_{safe_title}"
                        if not any(os.path.exists(os.path.join(out_path, f"{cand}.{ext}")) for ext in exts):
                            safe_title = cand
                            break
                        dup_idx += 1

            out_tmpl = f"{out_path}/{safe_title}.%(ext)s"

        self._resolved_title = safe_title
        if safe_title:
            self.exact_file_stem = os.path.join(out_path, safe_title)
        else:
            self.exact_file_stem = None
        return safe_title, out_tmpl

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

        safe_title, out_tmpl = self._resolve_filename(out_path)

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
            "concurrent_fragment_downloads": 6 if is_bilibili_url(self.url) else (min(8, max(4, num_threads)) if is_youtube_url(self.url) else num_threads),
            "skip_unavailable_fragments": True,
            "buffersize": 4 * 1024 * 1024 if is_bilibili_url(self.url) else (2 * 1024 * 1024 if is_youtube_url(self.url) else 2 * 1024 * 1024),
        }
        if is_bilibili_url(self.url):
            # Config E: 6 luồng song song + chunk 8MB tối ưu cho Video lớn
            # Với luồng audio nhỏ (~1MB), yt-dlp nếu gặp lỗi fragment sẽ tự retry đơn luồng
            opts["http_chunk_size"] = 8 * 1024 * 1024
        elif is_youtube_url(self.url):
            # YouTube googlevideo CDN: 10MB chunking chống TCP throttling và rớt mạng
            opts["http_chunk_size"] = 10485760
        elif chunk_size is not None:
            # Random jitter 10MB +- 64KB cho Douyin/Khác
            jittered_chunk = max(1048576, chunk_size + random.randint(-65536, 65536))
            opts["http_chunk_size"] = jittered_chunk

        if self.options.get("skip_existing") and not self.options.get("allow_duplicates"):
            opts["overwrites"] = False

        opts["source_address"] = "0.0.0.0"
        js_runtime = get_js_runtime()
        if js_runtime:
            opts["js_runtimes"] = js_runtime
        if is_youtube_url(self.url):
            # YouTube: Dùng client mặc định của yt-dlp cùng player_skip configs và JS Runtime (Node.js)
            # Tránh ép player_client sang ios/android/mweb gây lỗi GVS PO Token và bị giới hạn xuống 360p
            opts["extractor_args"] = {
                "youtube": {
                    "player_skip": ["configs"]
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
        """Chỉ dọn dẹp các file .part theo exact file stem của chính video này, không quét wildcard toàn thư mục."""
        try:
            stem = getattr(self, "exact_file_stem", None)
            if not stem:
                safe_print("[DỌN DẸP BỎ QUA] Worker không có exact_file_stem. Bỏ qua cleanup để bảo đảm an toàn.")
                return

            stems = [stem]
            if " " in stem:
                stems.append(stem.replace(" ", "_"))
            if "_" in stem:
                stems.append(stem.replace("_", " "))

            for s in stems:
                for ext in (".part", ".ytdl", ".temp", ".mp4.part", ".mkv.part", ".webm.part", ".mp3.part"):
                    fpath = s + ext
                    if os.path.exists(fpath):
                        try:
                            os.remove(fpath)
                        except OSError:
                            pass
                import glob
                for frag in glob.glob(glob.escape(s) + "*.part-Frag*"):
                    try:
                        os.remove(frag)
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
                safe_print("[YOUTUBE AUTO-FALLBACK] YouTube hạn chế stream (HTTP 403 hoặc Cipher)! Kích hoạt luồng fallback chuẩn...")
                yt_opts = dict(opts)
                yt_opts["extractor_args"] = {"youtube": {"player_skip": ["configs"]}}
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

    @staticmethod
    def _mask_id(raw_id):
        s = str(raw_id or "").strip()
        if not s:
            return "***"
        return f"{s[:6]}***" if len(s) > 6 else s

    def _resolve_drama_provider(self):
        import providers
        prov = providers.detect_provider(self.url)
        if prov:
            return prov
        hint = self.options.get("provider") or self.options.get("provider_id") or self.options.get("platform")
        if hint:
            return providers.get_provider(str(hint))
        return None

    def _is_drama_task(self):
        if is_drama_url(self.url):
            return True
        hint = self.options.get("provider") or self.options.get("provider_id") or self.options.get("platform")
        if hint:
            import providers
            if providers.get_provider(str(hint)) is not None:
                return True
        return False

    def _reconstruct_episode_from_options(self):
        from providers.base import Episode, Subtitle, ACCESS_STATE_FREE
        direct_ep = self.options.get("drama_episode")
        if isinstance(direct_ep, Episode):
            return direct_ep, True

        ep_id = self.options.get("episode_id")
        ep_num = self.options.get("episode_number")
        acc_state = self.options.get("access_state")
        if not ep_id and ep_num is None and not acc_state:
            return None, False

        subs = []
        for s in (self.options.get("subtitles") or []):
            if isinstance(s, Subtitle):
                subs.append(s)
            elif isinstance(s, dict) and s.get("url"):
                subs.append(Subtitle(lang=s.get("lang", "sub"), name=s.get("name", "sub"), url=s["url"]))
        if not subs and self.options.get("subtitle_url"):
            subs.append(Subtitle(lang="sub", name="sub", url=self.options["subtitle_url"]))

        num_val = int(ep_num) if ep_num else 1
        ep = Episode(
            num=num_val,
            title=self.options.get("title") or f"Tập {num_val}",
            url=self.options.get("source_url") or self.url,
            direct_url=self.options.get("direct_url"),
            locked=bool(self.options.get("locked", False)),
            subtitles=subs,
            extra=dict(self.options.get("extra") or {}),
            provider_id=str(self.options.get("provider_id") or self.options.get("provider") or ""),
            series_id=str(self.options.get("series_id") or ""),
            episode_id=str(ep_id or ""),
            episode_number=num_val,
            access_state=str(acc_state or ACCESS_STATE_FREE),
            expires_at=self.options.get("expires_at"),
        )
        is_complete = bool(ep.episode_id and acc_state and (ep.extra or ep.direct_url))
        return ep, is_complete

    @staticmethod
    def _is_valid_resolved_media_url(stream_url):
        if not stream_url or not isinstance(stream_url, str):
            return False
        u = stream_url.strip()
        if not u.startswith(("http://", "https://")):
            return False
        from urllib.parse import urlparse
        try:
            p = urlparse(u)
            path_l = (p.path or "").lower()
            host_l = (p.netloc or "").lower()
            if host_l.endswith(("hongguoduanju.com", "hainanyuyue.com", "novelquickapp.com")) and (
                path_l.startswith("/detail") or path_l.startswith("/player") or path_l.startswith("/s/")
            ):
                return False
        except Exception:
            return False
        return True

    def download_direct_stream(self, stream_url, final_filepath, headers=None):
        """Tải direct MP4 qua requests hỗ trợ HTTP 200/206 và resume .part an toàn."""
        import requests
        from ca_bundle_utils import get_ca_bundle_path

        out_dir = os.path.dirname(os.path.abspath(final_filepath))
        os.makedirs(out_dir, exist_ok=True)
        part_path = f"{final_filepath}.part"
        existing_size = os.path.getsize(part_path) if os.path.exists(part_path) else 0

        req_headers = dict(headers or {})
        if "User-Agent" not in req_headers:
            req_headers["User-Agent"] = DEFAULT_UA
        if existing_size > 0:
            req_headers["Range"] = f"bytes={existing_size}-"

        resp = requests.get(
            stream_url,
            headers=req_headers,
            stream=True,
            timeout=25,
            verify=get_ca_bundle_path(),
        )
        if resp.status_code not in (200, 206):
            raise RuntimeError(f"HTTP Error {resp.status_code}")

        ct = (resp.headers.get("Content-Type") or "").lower()
        if "text/html" in ct:
            raise RuntimeError(f"URL trả về trang HTML thay vì video ({ct})")

        safe_print(f"[DOWNLOAD] HTTP={resp.status_code}")

        mode = "ab" if (resp.status_code == 206 and existing_size > 0) else "wb"
        downloaded = existing_size if mode == "ab" else 0
        total_bytes = 0
        cl = resp.headers.get("Content-Length")
        if cl and cl.isdigit():
            total_bytes = int(cl) + (existing_size if mode == "ab" else 0)

        start_t = time.time()
        with open(part_path, mode) as f:
            for chunk in resp.iter_content(chunk_size=131072):
                if not self._is_running:
                    raise yt_dlp.utils.DownloadError("Stopped by user")
                if not chunk:
                    continue
                f.write(chunk)
                downloaded += len(chunk)
                if total_bytes > 0:
                    pct = min(100, int(downloaded * 100 / total_bytes))
                    self.task_progress.emit(pct)
                elapsed = max(0.05, time.time() - start_t)
                spd_mb = (downloaded / (1024 * 1024)) / elapsed
                dl_mb = downloaded / (1024 * 1024)
                tot_mb = total_bytes / (1024 * 1024) if total_bytes > 0 else 0
                tot_txt = f"{tot_mb:.1f} MB" if tot_mb > 0 else "Chưa rõ"
                self.status_update.emit(f"TH:1|TIME:00:00:00|DL:{dl_mb:.1f} MB / {tot_txt}|SPD:{spd_mb:.2f} MB/s|ETA:Đang tải")

        if not self._is_running:
            raise yt_dlp.utils.DownloadError("Stopped by user")

        os.replace(part_path, final_filepath)
        return resp.status_code

    def _download_drama_episode(self, out_path):
        """Tải tập phim ngắn từ Drama Provider với resolve-before-download và isolated headers."""
        import providers
        from providers.base import vtt_to_srt
        import re

        if not self._is_running:
            self.task_stopped.emit()
            return

        os.makedirs(out_path, exist_ok=True)

        provider = self._resolve_drama_provider()
        if not provider:
            raise ValueError(f"Không tìm thấy provider phim ngắn cho URL: {self.url}")

        raw_pid = getattr(provider, "platform_id", None)
        pid = raw_pid if (isinstance(raw_pid, str) and raw_pid) else "drama"
        self.status_update.emit(f"Đang làm mới luồng phát từ {provider.display_name}...")

        # Kiểm tra nhanh access guard từ queue metadata trước khi gọi bất kỳ network nào
        reconstructed_ep, is_complete_ep = self._reconstruct_episode_from_options()
        if reconstructed_ep and (reconstructed_ep.locked or reconstructed_ep.access_state not in ("free", "authorized")):
            reason = reconstructed_ep.access_reason or "yêu cầu mua VIP trên ứng dụng gốc"
            raise ValueError(f"Tập {reconstructed_ep.num} không thể tải ({reason})")

        target_ep = None
        series_name = self.options.get("series_name") or ""
        series = self.options.get("drama_series")

        if isinstance(self.options.get("drama_episode"), type(reconstructed_ep)) and self.options.get("drama_episode") is not None:
            target_ep = self.options.get("drama_episode")
        elif is_complete_ep and not series:
            target_ep = reconstructed_ep

        def _load_and_match_episode():
            nonlocal series, series_name
            if not series or not series.episodes:
                series = provider.load_series(self.url)
            if not series or not series.episodes:
                raise ValueError(f"Không thể đọc thông tin series từ: {self.url}")
            series_name = series_name or series.name

            matched = None
            # 1. Khớp theo Stable Episode ID từ URL (?ep_id= / ?ch_id= / ?vid= / #...&vid=) hoặc queue metadata
            m_id = re.search(r"[?&#](?:ep_id|ch_id|vid)=([A-Za-z0-9_-]+)", self.url)
            req_id = m_id.group(1) if m_id else self.options.get("episode_id")
            if req_id:
                for e in series.episodes:
                    extra_id = str(
                        getattr(e, "episode_id", "")
                        or (e.extra or {}).get("episode_id")
                        or (e.extra or {}).get("kk_ep")
                        or (e.extra or {}).get("chapter_id")
                        or (e.extra or {}).get("cid")
                        or (e.extra or {}).get("vid")
                        or ""
                    )
                    if extra_id == str(req_id):
                        matched = e
                        break

            # 2. Khớp theo Số thứ tự tập (?ep= / #ep= hoặc episode_number), KHÔNG dùng queue index nếu đã có provider/req_id
            if not matched and not req_id:
                m_ep = re.search(r"[?&#]ep=(\d+)", self.url)
                req_num = int(m_ep.group(1)) if m_ep else (
                    self.options.get("episode_number")
                    or (None if self.options.get("provider") else self.options.get("item_index"))
                )
                if req_num:
                    for e in series.episodes:
                        if e.num == int(req_num) or getattr(e, "episode_number", None) == int(req_num):
                            matched = e
                            break

            if not matched:
                raise ValueError(
                    f"Không tìm thấy tập phim được yêu cầu (ID: {req_id}, Ep: {self.options.get('episode_number') or self.options.get('item_index')}) "
                    f"trong series '{series.name}'"
                )
            return matched

        if not target_ep:
            target_ep = _load_and_match_episode()

        if target_ep.locked or target_ep.access_state not in ("free", "authorized"):
            reason = target_ep.access_reason or "yêu cầu mua VIP trên ứng dụng gốc"
            raise ValueError(f"Tập {target_ep.num} không thể tải ({reason})")

        if not self._is_running:
            self.task_stopped.emit()
            return

        ep_id_disp = getattr(target_ep, "episode_id", "") or self.options.get("episode_id") or target_ep.num
        safe_print(f"[RESOLVE] provider={pid} episode={self._mask_id(ep_id_disp)}")

        stream_url = provider.resolve_episode_stream(target_ep)
        if (not stream_url or not self._is_valid_resolved_media_url(stream_url)) and is_complete_ep and not series:
            # Thử làm mới metadata series một lần nếu direct/reconstructed episode thiếu info
            try:
                refreshed_ep = _load_and_match_episode()
                if refreshed_ep.locked or refreshed_ep.access_state not in ("free", "authorized"):
                    reason = refreshed_ep.access_reason or "yêu cầu mua VIP trên ứng dụng gốc"
                    raise ValueError(f"Tập {refreshed_ep.num} không thể tải ({reason})")
                target_ep = refreshed_ep
                stream_url = provider.resolve_episode_stream(target_ep)
            except ValueError as ve:
                if "không thể tải" in str(ve):
                    raise
                safe_print(f"[ERROR] provider={pid} phase=resolve reason={ve}")
            except Exception as ref_err:
                safe_print(f"[ERROR] provider={pid} phase=resolve reason={ref_err}")

        if not stream_url or not self._is_valid_resolved_media_url(stream_url):
            raw_reason = getattr(provider, "last_error", None)
            reason = raw_reason if (isinstance(raw_reason, str) and raw_reason) else "empty_or_invalid_stream"
            safe_print(f"[ERROR] provider={pid} phase=resolve reason={reason}")
            raise ValueError(
                f"Không thể phân giải stream tập {target_ep.num} từ {provider.display_name} "
                f"(Không thể lấy URL phát trực tiếp cho Tập {target_ep.num})"
            )

        is_hls = ".m3u8" in stream_url.lower()
        proto = "hls" if is_hls else "mp4"
        safe_print(f"[RESOLVE] protocol={proto} status=resolved")

        display_series = series_name or (series.name if series else "Drama")
        video_title = self.options.get("title") or f"{display_series} - {target_ep.title}"
        base_name, out_tmpl = self._resolve_filename(out_path, raw_title=video_title)

        merged_headers = {}
        merged_headers.update(detect_site(self.url) or {})
        if isinstance(self.options.get("headers"), dict):
            for hk, hv in self.options["headers"].items():
                if hk and hv and str(hk).lower() not in ("cookie", "authorization"):
                    merged_headers[str(hk)] = str(hv)
        # CDN stream_url headers (ví dụ qznovelvod.com -> hongguoduanju.com) ưu tiên khi đã có quy tắc riêng
        stream_site_headers = detect_site(stream_url) or {}
        if stream_site_headers:
            merged_headers.update(stream_site_headers)
        if "User-Agent" not in merged_headers:
            merged_headers["User-Agent"] = DEFAULT_UA

        opts = self.get_base_opts(out_path)
        self.apply_format_options(opts)
        opts["outtmpl"] = out_tmpl
        opts["http_headers"] = merged_headers

        file_type = self.options.get("file_type", "mp4")
        if file_type != "mp3" and not self.options.get("format_id"):
            opts["format"] = "best/mp4"
            opts.pop("postprocessors", None)

        safe_print(f"[DOWNLOAD] url_type={'hls' if is_hls else 'direct'}")
        safe_print(f"[Drama Downloader] Bắt đầu tải {display_series} (Tập {target_ep.num}) -> {base_name}")

        final_mp4 = os.path.abspath(os.path.join(out_path, f"{base_name}.mp4")) if base_name else out_tmpl

        if getattr(provider, "platform_id", "") == "miniapp_douyin" and is_hls and hasattr(provider, "client"):
            app_id = target_ep.extra.get("app_id") or getattr(provider, "default_app_id", "tt5b4d2df0c47bdd2201")
            def _prog(curr, total, speed, msg):
                if not self._is_running:
                    return
                pct = int((curr / total) * 100) if total > 0 else 0
                self.task_progress.emit(pct)
                self.status_update.emit(f"TH:1|TIME:00:00:00|DL:{curr}/{total}|SPD:{speed:.1f} MB/s|ETA:Đang tải HLS")
            ok = provider.client.download_hls_antihook(
                stream_url, final_mp4, app_id=app_id,
                progress_cb=_prog,
                stop_cb=lambda: not self._is_running,
                ffmpeg_bin=self.get_ffmpeg_path(),
            )
            if not ok and not self._is_running:
                self.task_stopped.emit()
                return
            elif not ok:
                safe_print(f"[ERROR] provider={pid} phase=download http=hls_failed")
                raise RuntimeError(f"Tải luồng HLS MiniApp Douyin thất bại cho tập {target_ep.num}")
            safe_print(f"[DOWNLOAD] HTTP=200")
            safe_print(f"[DOWNLOAD] output={final_mp4}")
        elif self.options.get("prefer_direct_requests") and not is_hls and file_type != "mp3":
            try:
                self.download_direct_stream(stream_url, final_mp4, headers=merged_headers)
                safe_print(f"[DOWNLOAD] output={final_mp4}")
            except Exception as dl_err:
                if "Stopped by user" in str(dl_err) or not self._is_running:
                    self.task_stopped.emit()
                    return
                m_http = re.search(r"HTTP Error (\d+)", str(dl_err))
                safe_print(f"[ERROR] provider={pid} phase=download http={m_http.group(1) if m_http else 'error'}")
                raise
        else:
            try:
                with yt_dlp.YoutubeDL(opts) as ydl:
                    ydl.download([stream_url])
                safe_print("[DOWNLOAD] HTTP=200/206")
                safe_print(f"[DOWNLOAD] output={final_mp4}")
            except Exception as dl_err:
                if "Stopped by user" in str(dl_err) or not self._is_running:
                    self.task_stopped.emit()
                    return
                err_txt = str(dl_err)
                m_http = re.search(r"HTTP Error (\d+)", err_txt)
                http_code = m_http.group(1) if m_http else ""
                if http_code in ("403", "404", "401"):
                    safe_print(f"[ERROR] provider={pid} phase=download http={http_code}")
                    raise
                if not is_hls and file_type != "mp3":
                    try:
                        self.download_direct_stream(stream_url, final_mp4, headers=merged_headers)
                        safe_print(f"[DOWNLOAD] output={final_mp4}")
                    except Exception as direct_err:
                        if "Stopped by user" in str(direct_err) or not self._is_running:
                            self.task_stopped.emit()
                            return
                        m_dh = re.search(r"HTTP Error (\d+)", str(direct_err))
                        safe_print(f"[ERROR] provider={pid} phase=download http={m_dh.group(1) if m_dh else 'error'}")
                        raise direct_err
                else:
                    safe_print(f"[ERROR] provider={pid} phase=download http={http_code or 'error'}")
                    raise

        if not self._is_running:
            self.task_stopped.emit()
            return

        # Tải phụ đề kèm theo với kiểm tra đường dẫn an toàn (Path Traversal Protection)
        if target_ep.subtitles:
            for sub in target_ep.subtitles:
                if not self._is_running:
                    self.task_stopped.emit()
                    return
                try:
                    safe_lang = re.sub(r"[^a-zA-Z0-9_-]", "", str(sub.lang or "sub"))[:20] or "sub"
                    abs_out = os.path.abspath(out_path)
                    sub_file = os.path.abspath(os.path.join(abs_out, f"{base_name}.{safe_lang}.srt"))
                    if os.path.commonpath([sub_file, abs_out]) != abs_out:
                        safe_print(f"[SECURITY] Bỏ qua phụ đề do tên không an toàn (path traversal): {sub_file}")
                        continue

                    sub_resp = provider.session.get(sub.url, timeout=10)
                    if sub_resp.status_code == 200:
                        content = sub_resp.text
                        if "WEBVTT" in content:
                            content = vtt_to_srt(content)
                        with open(sub_file, "w", encoding="utf-8") as sf:
                            sf.write(content)
                        safe_print(f"[Drama Downloader] Đã lưu phụ đề: {sub_file}")
                    else:
                        msg = f"Cảnh báo: Tải phụ đề [{safe_lang}] thất bại (HTTP {sub_resp.status_code})"
                        safe_print(f"[Drama Subtitle] {msg}")
                        self.status_update.emit(msg)
                except Exception as sub_err:
                    msg = f"Cảnh báo: Lỗi tải phụ đề {sub.lang}: {sub_err}"
                    safe_print(f"[Drama Subtitle] {msg}")
                    self.status_update.emit(msg)

        if not self._is_running:
            self.task_stopped.emit()
            return

        self.task_finished.emit()

    def run(self):
        try:
            is_drama = self._is_drama_task()
            if not is_drama:
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

            # === Phim ngắn (Short Drama Downloader: Hongguo, DramaBox, KissKH, MiniApp Douyin, v.v.) ===
            if is_drama or is_drama_url(self.url):
                self._download_drama_episode(out_path)
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
                                # Đặt tên file đầu ra theo title video (hỗ trợ Prefix và Dup1, Dup2...)
                                video_title = self.options.get("title", "") or f"douyin_{vid}"
                                _, out_tmpl = self._resolve_filename(out_path, raw_title=video_title)
                                opts["outtmpl"] = out_tmpl
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
            elif is_youtube_url(self.url) and cookies_valid:
                # YouTube: Dùng cookies trực tiếp giúp bypass bot-check / sign-in, mở khóa video 1080p+, tốc độ tối đa
                init_msg = "TH:8|TIME:00:00:00|DL:Đang chuẩn bị...|SPD:Kết nối Google CDN (Cookies)...|ETA:Đang giải mã..."
                self.status_update.emit(init_msg)
                print(f"[Download] Dùng cookies YouTube cho {self.url}...")
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
                    if issue == "expired_cookies" or "cookies are no longer valid" in err_str:
                        self.cookie_refresh_requested.emit("youtube.com", "expired_cookies")
                        print("[Download] cookies.txt YouTube hết hạn, chuyển sang anonymous...")
                    else:
                        print(f"[Download] cookies.txt YouTube lỗi ({err_str[:120]}), chuyển sang anonymous...")

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
            if "Stopped by user" in str(e) or not self._is_running:
                self.task_stopped.emit()
                return
            print(f"[CRITICAL WORKER ERROR] {e}")
            app_logger().exception("Worker crash")
            self.task_error.emit(str(e)[:200] or "Lỗi không xác định")

    def _file_exists(self, out_path):
        """Ước lượng tên file theo outtmpl giống yt-dlp; trả True nếu đã có."""
        if self.options.get("allow_duplicates"):
            return False
        from yt_dlp.utils import sanitize_filename

        title = getattr(self, "_resolved_title", None)
        if not title:
            raw = self.options.get("title")
            if raw:
                title, _ = self._resolve_filename(out_path, raw_title=raw)
            if not title:
                title = sanitize_filename(raw or "", restricted=False)
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
