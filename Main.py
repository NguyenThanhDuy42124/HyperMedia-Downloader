import sys
import os
import yt_dlp
import shutil
import time
import subprocess

from PySide6.QtWidgets import (
    QApplication,
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLineEdit,
    QPushButton,
    QLabel,
    QComboBox,
    QListWidget,
    QListWidgetItem,
    QProgressBar,
    QMessageBox,
    QFrame,
    QFileDialog,
    QRadioButton,
    QButtonGroup,
    QSpinBox,
    QDialog,
    QTextEdit,
    QTabWidget,
)
from PySide6.QtCore import Qt, QThread, Signal, QSize, QTimer
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkRequest, QNetworkReply

# ===== GLOBAL CONSTANTS =====
DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

BROWSER_MAP = {"Chrome": "chrome", "Edge": "edge", "Firefox": "firefox"}
AUTO_BROWSERS = ["chrome", "edge", "firefox"]

RESOLUTION_MAP = {"8K": 4320, "4K": 2160, "2K": 1440, "1440": 1440, "1080": 1080,
                  "720": 720, "480": 480, "360": 360}


# ===== SITE HELPERS =====
def detect_site(url):
    """Return dict of http_headers appropriate for the target site."""
    u = (url or "").lower()
    if "bilibili.com" in u or "b23.tv" in u:
        return {
            "Referer": "https://www.bilibili.com/",
            "Origin": "https://www.bilibili.com",
        }
    if "youtube.com" in u or "youtu.be" in u:
        return {
            "Referer": "https://www.youtube.com/",
            "Origin": "https://www.youtube.com",
        }
    return {}


def is_bilibili_url(url):
    u = (url or "").lower()
    return "bilibili.com" in u or "b23.tv" in u


def patch_bilibili_extractor():
    """Monkey-patch yt-dlp's BiliBili extractor to bypass HTTP 412 anti-bot.

    Bilibili's risk-control sometimes returns 412 on x/player/wbi/playurl even
    with a valid browser UA. The community-confirmed workaround is retrying the
    same signed query against the legacy (non-wbi) endpoint.
    """
    try:
        from yt_dlp.extractor.bilibili import BiliBiliIE
    except Exception as e:
        print(f"[PATCH] Không tìm thấy extractor BiliBili: {e}")
        return

    original = getattr(BiliBiliIE, "_download_playinfo", None)
    if original is None or getattr(original, "_bili_412_patched", False):
        return

    def _download_playinfo(self, bvid, cid, headers=None, query=None, fatal=True):
        try:
            return original(self, bvid, cid, headers=headers, query=query, fatal=fatal)
        except Exception as e:
            err_str = str(e) or ""
            if "412" in err_str or "Precondition Failed" in err_str:
                print("[PATCH] BiliBili 412, thử lại với endpoint playurl cũ...")
                params = {
                    "bvid": bvid,
                    "cid": cid,
                    "fnval": 4048,
                    **getattr(self, "_dm_params", {}),
                    **(query or {}),
                }
                if getattr(self, "is_logged_in", False):
                    params.pop("try_look", None)
                qn = params.get("qn")
                note = (
                    f"Downloading video format {qn} for cid {cid}"
                    if qn
                    else "Downloading video formats for cid {cid}"
                )
                try:
                    return self._download_json(
                        "https://api.bilibili.com/x/player/playurl", bvid,
                        query=self._sign_wbi(params, bvid),
                        headers=headers, note=note)["data"]
                except Exception:
                    raise e
            raise

    _download_playinfo._bili_412_patched = True
    BiliBiliIE._download_playinfo = _download_playinfo
    print("[PATCH] Đã áp dụng fix HTTP 412 cho BiliBili")


def patch_bilibili_space_titles():
    """Monkey-patch BilibiliSpaceVideoIE so flat-mode scan keeps titles/thumbnails.

    The stock extractor only yields url_result (id + url) for each video, so
    scanning a space page with extract_flat=True makes every item show
    'Unknown'. The space API already returns title/pic, we just attach them.
    """
    try:
        from yt_dlp.extractor import bilibili as _b
        from yt_dlp.utils import unescapeHTML
    except Exception as e:
        print(f"[PATCH] Không tìm thấy extractor BilibiliSpaceVideoIE: {e}")
        return

    IE = _b.BilibiliSpaceVideoIE
    if getattr(IE, "_bili_space_titles_patched", False):
        return

    def _real_extract(self, url):
        playlist_id, is_video_url = self._match_valid_url(url).group("id", "video")
        if not is_video_url:
            self.to_screen(
                "A channel URL was given. Only the channel's videos will be downloaded. "
                'To download audios, add a "/upload/audio" to the URL'
            )

        def fetch_page(page_idx):
            query = {
                "keyword": "",
                "mid": playlist_id,
                "order": _b.traverse_obj(_b.parse_qs(url), ("order", 0)) or "pubdate",
                "order_avoided": "true",
                "platform": "web",
                "pn": page_idx + 1,
                "ps": 30,
                "tid": 0,
                "web_location": "333.1387",
                "special_type": "",
                "index": 0,
                **self._dm_params,
            }
            try:
                response = self._download_json(
                    "https://api.bilibili.com/x/space/wbi/arc/search",
                    playlist_id,
                    query=self._sign_wbi(query, playlist_id),
                    note=f"Downloading space page {page_idx}",
                    headers={
                        "Referer": url,
                        "Origin": "https://space.bilibili.com",
                        "Accept-Language": "en,zh-CN;q=0.9,zh;q=0.8",
                    },
                )
            except _b.ExtractorError as e:
                if isinstance(e.cause, _b.HTTPError) and e.cause.status == 412:
                    raise _b.ExtractorError(
                        "Request is blocked by server (412), please wait and try later.",
                        expected=True,
                    )
                raise
            status_code = response["code"]
            if status_code == -401:
                raise _b.ExtractorError(
                    "Request is blocked by server (401), please wait and try later.",
                    expected=True,
                )
            elif status_code == -352:
                raise _b.ExtractorError("Request is rejected by server (352)", expected=True)
            elif status_code != 0:
                raise _b.ExtractorError(
                    f'Request failed ({status_code}): {response.get("message") or "Unknown error"}'
                )
            return response["data"]

        def get_metadata(page_data):
            page_size = page_data["page"]["ps"]
            entry_count = page_data["page"]["count"]
            return {
                "page_count": _b.math.ceil(entry_count / page_size),
                "page_size": page_size,
            }

        def get_entries(page_data):
            for entry in _b.traverse_obj(page_data, ("list", "vlist", ..., {dict})):
                if _b.traverse_obj(entry, ("meta", "attribute")) == 156:
                    yield self.url_result(
                        f'https://space.bilibili.com/{entry["mid"]}/lists/{entry["meta"]["id"]}?type=season',
                        _b.BilibiliCollectionListIE,
                        f'{entry["mid"]}_{entry["meta"]["id"]}',
                    )
                else:
                    bvid = entry["bvid"]
                    r = self.url_result(
                        f"https://www.bilibili.com/video/{bvid}", _b.BiliBiliIE, bvid
                    )
                    if entry.get("title"):
                        r["title"] = unescapeHTML(entry["title"])
                    if entry.get("pic"):
                        r["thumbnail"] = entry["pic"]
                    yield r

        _, paged_list = self._extract_playlist(fetch_page, get_metadata, get_entries)
        return self.playlist_result(paged_list, playlist_id)

    _real_extract._bili_space_titles_patched = True
    IE._real_extract = _real_extract
    print("[PATCH] Đã áp dụng fix title/thumbnail cho trang space Bilibili")


# ===== GLOBAL FUNCTIONS =====
def get_icon_path():
    """Get correct icon path for both script and exe"""
    if getattr(sys, "frozen", False):
        # Running as exe - icon is in the same dir as exe
        base_path = os.path.dirname(sys.executable)
    else:
        # Running as script
        base_path = os.getcwd()

    # Try ico first, then png
    ico_path = os.path.join(base_path, "icon", "icon.ico")
    png_path = os.path.join(base_path, "icon", "icon.png")

    if os.path.exists(ico_path):
        return ico_path
    elif os.path.exists(png_path):
        return png_path
    else:
        return None


# ===== THUMBNAIL LOADER =====
class ThumbnailLoader(QThread):
    finished = Signal(bytes)

    def __init__(self, url, parent=None):
        super().__init__(parent)
        self.url = url

    def run(self):
        try:
            import requests

            response = requests.get(self.url, timeout=10)
            if response.status_code == 200:
                self.finished.emit(response.content)
            else:
                self.finished.emit(b"")
        except Exception as e:
            print(f"[THUMBNAIL ERROR] {e}")
            self.finished.emit(b"")


# --- CLASS LOGGER ---
class MyLogger:
    def __init__(self):
        self.warnings = []

    def debug(self, msg):
        pass

    def warning(self, msg):
        self.warnings.append(str(msg))
        print(f"[YTDLP Warning] {msg}")

    def error(self, msg):
        print(f"[YTDLP Error] {msg}")


# ===== WORKER DOWNLOAD (FIXED) =====
class DownloadWorker(QThread):
    # ĐỔI TÊN SIGNAL ĐỂ TRÁNH XUNG ĐỘT VỚI QTHREAD
    task_progress = Signal(int)
    task_finished = Signal()  # Đổi từ finished -> task_finished
    task_error = Signal(str)  # Đổi từ error -> task_error
    task_stopped = Signal()  # Đổi từ stopped -> task_stopped
    status_update = Signal(str)  # Thêm signal cho status

    def __init__(self, url, options, parent=None):
        super().__init__(parent)  # Thêm parent để quản lý bộ nhớ tốt hơn
        self.url = url
        self.options = options or {}
        self._is_running = True
        self.cookies_file_path = os.path.join(os.getcwd(), "cookies", "cookies.txt")

    def stop(self):
        self._is_running = False

    def get_ffmpeg_path(self):
        if getattr(sys, "frozen", False):
            return os.path.join(sys._MEIPASS, "ffmpeg.exe")
        return os.path.join(os.getcwd(), "ffmpeg.exe")

    def get_base_opts(self, out_path):
        self._logger = MyLogger()
        opts = {
            "outtmpl": f"{out_path}/%(title)s.%(ext)s",
            "progress_hooks": [self.progress_hook],
            "quiet": True,
            "no_warnings": False,
            "logger": self._logger,
            "ffmpeg_location": self.get_ffmpeg_path(),
            "windowsfilenames": True,
            "restrictfilenames": True,
            "retries": 10,
            "socket_timeout": 30,
            "user_agent": DEFAULT_UA,
            "http_headers": detect_site(self.url),
        }
        return opts

    def _check_warnings_for_issues(self):
        """Check logged warnings for known issues and return descriptive error or None."""
        if not hasattr(self, '_logger'):
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
                # Prefer H.264 source, but keep fallbacks when a format is missing
                if resolution:
                    fmt = (
                        f"bestvideo[vcodec^=avc1][height<={resolution}]+bestaudio[ext=m4a]/"
                        f"bestvideo[height<={resolution}]+bestaudio/"
                        f"best[height<={resolution}]/best"
                    )
                else:
                    fmt = "bestvideo[vcodec^=avc1]+bestaudio[ext=m4a]/bestvideo+bestaudio/best"
                ydl_opts.update({"format": fmt, "merge_output_format": "mp4"})
                # Force re-encode to ensure H.264
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
        elif file_type == "av1":
            # Keep AV1
            ydl_opts.update({
                "format": "bestvideo[vcodec^=av01]+bestaudio/bestvideo+bestaudio/best",
                "merge_output_format": "webm",
            })

    def download_with_format_fallback(self, opts):
        """Try download with requested format, fallback to lower heights if unavailable."""
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                ydl.download([self.url])
        except Exception as e:
            err_str = str(e) or ""
            # Check if it's a format issue (including n-challenge causing no formats)
            is_format_issue = (
                "Requested format is not available" in err_str
                or "Only images are available" in err_str
            )
            if is_format_issue and self.options.get("file_type", "mp4") != "mp3":
                # Check if n-challenge failed — this means NO video formats exist
                issue = self._check_warnings_for_issues()
                if issue == "n_challenge" or issue == "no_formats":
                    raise yt_dlp.utils.DownloadError(
                        "YouTube n-challenge failed: Cần cài Deno (https://deno.com) "
                        "và chạy: pip install yt-dlp[default]. "
                        "Xem https://github.com/yt-dlp/yt-dlp/wiki/EJS"
                    )
                # Step down through the known available heights, honouring the
                # user's selection (do NOT jump straight to 'best', which may be
                # a restricted/premium format).
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
        """Check if cookies file exists and has valid-looking content (YouTube or BiliBili)."""
        if not os.path.exists(self.cookies_file_path):
            return False, "not_found"
        try:
            with open(self.cookies_file_path, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
            # Check minimum viable cookie file
            if len(content.strip()) < 50:
                return False, "empty"
            has_youtube = ".youtube.com" in content
            has_bilibili = ".bilibili.com" in content
            if not has_youtube and not has_bilibili:
                return False, "no_known_site"
            # Check for essential auth cookies (YouTube or BiliBili)
            has_auth = any(
                k in content
                for k in ["SID", "SSID", "LOGIN_INFO", "SESSDATA", "bili_jct", "DedeUserID"]
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
        """Try downloading using cookies read directly from the user's browser."""
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
        # Bọc toàn bộ trong try/except lớn để không bao giờ crash thread
        try:
            out_path = self.options.get("output_path", "downloads")
            if not os.path.exists(out_path):
                os.makedirs(out_path)

            browser_setting = self.options.get("browser", "Auto")
            success = False
            auth_error_encountered = False

            # 1. THỬ ANONYMOUS (không cookies)
            if not self._is_running:
                return
            self.status_update.emit("Đang thử tải anonymous...")
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
                # Check for n-challenge failure (fatal - no JS runtime)
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
                    # Lỗi khác (mạng, link sai...)
                    self.task_error.emit(f"Lỗi: {err_str[:200]}")
                    return

            if success:
                self.task_finished.emit()
                return

            if browser_setting == "None":
                self.task_error.emit("Video cần đăng nhập. Chọn Auto hoặc import cookies.")
                return

            # 2. THỬ FILE COOKIES.TXT (FALLBACK)
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

                        # Check if cookies were flagged as expired despite download success
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
                        # Check for specific issues
                        issue = self._check_warnings_for_issues()
                        if issue == "expired_cookies":
                            print("[Download] cookies.txt hết hạn, thử cookie trình duyệt...")
                        elif err_str and any(x in err_str for x in ["members-only", "Join this channel"]):
                            self.task_error.emit("Video dành cho thành viên. Cần tài khoản có membership.")
                            return
                        elif "n-challenge" in err_str or "Deno" in err_str:
                            self.task_error.emit(err_str[:200])
                            return
                        else:
                            print(f"[Download] cookies.txt thất bại: {err_str[:150]}")
                elif cookies_status in ("not_found", "empty", "no_auth_cookies", "no_known_site"):
                    pass  # fall through to browser cookies below
                else:
                    print(f"[Download] cookies.txt lỗi: {cookies_status}")

                # 3. THỬ COOKIE TỪ TRÌNH DUYỆT
                if browser_setting != "None":
                    browsers = self._resolve_browsers(browser_setting)
                    if self._try_browser_cookies(out_path, browsers):
                        self.task_finished.emit()
                        return

                # Hết cách
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
            # Catch-all crash protector
            print(f"[CRITICAL WORKER ERROR] {e}")
            self.task_error.emit(str(e)[:200] or "Lỗi không xác định")

    def progress_hook(self, d):
        if not self._is_running:
            raise yt_dlp.utils.DownloadError("Stopped by user")
        if d["status"] == "downloading":
            try:
                total = d.get("total_bytes") or d.get("total_bytes_estimate")
                if total:
                    pct = int(d.get("downloaded_bytes", 0) / total * 100)
                    self.task_progress.emit(pct)
            except:
                pass


# ===== WORKER SCAN =====
class ScanWorker(QThread):
    found_item = Signal(str, str, str, list)  # title, url, thumb, heights
    finished = Signal(str)
    error = Signal(str)

    def __init__(self, url, mode, limit, browser="None", parent=None):
        super().__init__(parent)
        self.url = url
        self.mode = mode
        self.limit = limit
        self.browser = browser

    @staticmethod
    def is_playlist_url(url):
        u = (url or "").lower()
        return any(
            k in u
            for k in [
                "list=",
                "/playlist",
                "/set/",
                "/series",
                "/medialist",
                "/favlist",
                "space.bilibili.com",
                "youtube.com/@",
            ]
        )

    def _get_cookie_sources(self):
        """Build cookie-based ydl option dicts (cookies.txt + browser cookies)."""
        sources = []
        c_file = os.path.join(os.getcwd(), "cookies", "cookies.txt")
        if os.path.exists(c_file):
            sources.append({"cookiefile": c_file})
        browsers = AUTO_BROWSERS
        if self.browser in BROWSER_MAP:
            browsers = [BROWSER_MAP[self.browser]]
        for b in browsers:
            sources.append({"cookiesfrombrowser": (b,)})
        return sources

    @staticmethod
    def _fix_thumb(th, url, video_id):
        if th:
            return th
        if "youtube.com" in (url or "") or "youtu.be" in (url or ""):
            if video_id:
                return f"https://img.youtube.com/vi/{video_id}/maxresdefault.jpg"
        return ""

    def run(self):
        try:
            ydl_opts = {
                "quiet": True,
                "no_warnings": True,
                "user_agent": DEFAULT_UA,
                "http_headers": detect_site(self.url),
            }

            # Single video -> full extract (real format/resolution list).
            # Playlist/channel -> flat extract (fast listing).
            if self.mode == 2 or self.is_playlist_url(self.url):
                ydl_opts["extract_flat"] = True
                if self.limit > 0:
                    ydl_opts["playlistend"] = self.limit
            else:
                ydl_opts["noplaylist"] = True

            # Try anonymous first, then cookies.txt / browser cookies
            info = None
            last_err = None
            for source in [None] + self._get_cookie_sources():
                if info is not None:
                    break
                try:
                    opts = dict(ydl_opts)
                    if source:
                        opts.update(source)
                    with yt_dlp.YoutubeDL(opts) as ydl:
                        info = ydl.extract_info(self.url, download=False)
                except Exception as e:
                    last_err = e
                    err_str = str(e) or ""
                    retryable = any(
                        x in err_str
                        for x in ["Sign in", "Private", "403", "login",
                                  "members-only", "HTTP Error", "412", "352", "Precondition"]
                    )
                    print(f"[DEBUG] Scan attempt {source or 'anonymous'} thất bại: {err_str[:100]}")
                    if source is None and not retryable:
                        # Non-auth error on anonymous attempt -> give up
                        break
                    # Otherwise try next cookie source

            if info is None:
                if last_err:
                    err_str = str(last_err) or ""
                    if is_bilibili_url(self.url) and any(
                        x in err_str for x in ["412", "352", "blocked", "rejected"]
                    ):
                        self.error.emit(
                            "Bilibili chặn quét trang (412/352). Hãy đăng nhập "
                            "bilibili.com trong trình duyệt rồi export cookies "
                            "mới và Import vào tool."
                        )
                    else:
                        raise last_err
                else:
                    self.error.emit("Không thể lấy thông tin video. Video có thể bị xóa, private, hoặc cần đăng nhập/cookies hợp lệ.")
                return

            # Extract unique heights (real format options for this video)
            heights = []
            if "formats" in info and info["formats"]:
                heights = sorted(set(f.get("height") for f in info["formats"] if f.get("height")), reverse=True)

            if "entries" in info and info["entries"]:
                for entry in info["entries"]:
                    if entry:
                        t = entry.get("title", "Unknown")
                        u = entry.get("url") or entry.get("webpage_url") or self.url
                        video_id = entry.get("id", "")
                        th = self._fix_thumb(entry.get("thumbnail", ""), u, video_id)
                        print(f"[DEBUG] Found video: {t[:50]}... URL: {u} THUMB: {th}")
                        self.found_item.emit(t, u, th, heights)
            else:
                t = info.get("title", "Unknown")
                u = info.get("webpage_url", self.url)
                video_id = info.get("id", "")
                th = self._fix_thumb(info.get("thumbnail", ""), u, video_id)
                print(f"[DEBUG] Single video: {t[:50]}... URL: {u} THUMB: {th}")
                self.found_item.emit(t, u, th, heights)
            self.finished.emit("Quét xong!")
        except Exception as e:
            self.error.emit(str(e))


# ===== ITEM WIDGET =====
class VideoItemWidget(QWidget):
    def __init__(self, title, thumb_url, url, heights):
        super().__init__()
        self.url = url
        self.thumb_url = thumb_url
        self.heights = heights or [1080, 720, 480, 360]  # fallback
        self.setStyleSheet("background: #2d2d2d; border-radius: 8px;")
        layout = QHBoxLayout(self)

        self.btn_check = QPushButton("✅")
        self.btn_check.setCheckable(True)
        self.btn_check.setChecked(True)
        self.btn_check.setFixedSize(40, 40)
        self.btn_check.toggled.connect(
            lambda c: self.btn_check.setText("✅" if c else "⬜")
        )
        self.btn_check.setStyleSheet(
            "QPushButton{background:transparent;border:none;font-size:24px;color:#fff} QPushButton:!checked{color:#555}"
        )
        layout.addWidget(self.btn_check)

        self.thumb = QLabel("Loading...")
        self.thumb.setFixedSize(120, 68)
        self.thumb.setStyleSheet(
            "background:#000;color:#555;qproperty-alignment:AlignCenter;"
        )
        self.thumb.setScaledContents(True)
        layout.addWidget(self.thumb)

        # Load thumbnail
        if thumb_url:
            self.load_thumbnail(thumb_url)

        info = QVBoxLayout()
        self.title_lbl = QLabel(title)
        self.title_lbl.setStyleSheet("font-weight:bold;color:white;")
        self.title_lbl.setWordWrap(True)
        info.addWidget(self.title_lbl)

        sets = QHBoxLayout()
        self.type_cb = QComboBox()
        self.type_cb.addItems(["mp4", "mp3", "av1"])
        self.res_cb = QComboBox()
        # Dynamic options based on heights
        options = ["best"]
        for h in sorted(self.heights, reverse=True):
            if h >= 360:  # Only include reasonable resolutions
                options.append(str(h))
        self.res_cb.addItems(options)
        # Default to the best AVAILABLE height (not "best") so restricted
        # premium/quality formats don't fail silently on the first try.
        if len(options) > 1:
            self.res_cb.setCurrentText(options[1])
        else:
            self.res_cb.setCurrentText("best")
        self.bitrate_cb = QComboBox()
        self.bitrate_cb.addItems(["320", "256", "192", "128"])
        self.codec_cb = QComboBox()
        self.codec_cb.addItems(["H.264", "VA1"])
        self.type_cb.currentTextChanged.connect(self.on_type_changed)

        for c in [self.type_cb, self.res_cb, self.bitrate_cb, self.codec_cb]:
            c.setStyleSheet("background:#3e3e3e;color:white;border-radius:3px;")
            c.setFixedWidth(70)

        sets.addWidget(QLabel("Loại:"))
        sets.addWidget(self.type_cb)
        self.res_label = QLabel("Chất lượng:")
        sets.addWidget(self.res_label)
        sets.addWidget(self.res_cb)
        self.bitrate_label = QLabel("Bitrate:")
        sets.addWidget(self.bitrate_label)
        sets.addWidget(self.bitrate_cb)
        self.codec_label = QLabel("Codec:")
        sets.addWidget(self.codec_label)
        sets.addWidget(self.codec_cb)
        sets.addStretch()
        info.addLayout(sets)

        self.status_lbl = QLabel("Sẵn sàng")
        self.status_lbl.setStyleSheet("color:#aaa;font-size:11px;")
        info.addWidget(self.status_lbl)

        self.progress = QProgressBar()
        self.progress.setFixedHeight(4)
        self.progress.setTextVisible(False)
        self.progress.setStyleSheet(
            "QProgressBar{background:#444;border:none} QProgressBar::chunk{background:#2196F3}"
        )
        info.addWidget(self.progress)

        layout.addLayout(info)

        # Set initial state
        self.on_type_changed("mp4")

    def on_type_changed(self, text):
        if text == "mp4":
            self.res_label.show()
            self.res_cb.show()
            self.bitrate_label.hide()
            self.bitrate_cb.hide()
            self.codec_label.show()
            self.codec_cb.show()
            self.res_cb.setEnabled(True)
            self.res_cb.setStyleSheet(
                "background:#3e3e3e;color:white;border-radius:3px;"
            )
            self.codec_cb.setEnabled(True)
            self.codec_cb.setStyleSheet(
                "background:#3e3e3e;color:white;border-radius:3px;"
            )
        elif text == "mp3":
            self.res_label.hide()
            self.res_cb.hide()
            self.bitrate_label.show()
            self.bitrate_cb.show()
            self.codec_label.hide()
            self.codec_cb.hide()
            self.bitrate_cb.setEnabled(True)
            self.bitrate_cb.setStyleSheet(
                "background:#3e3e3e;color:white;border-radius:3px;"
            )
        elif text == "av1":
            self.res_label.hide()
            self.res_cb.hide()
            self.bitrate_label.hide()
            self.bitrate_cb.hide()
            self.codec_label.hide()
            self.codec_cb.hide()

    def get_options(self, path, browser):
        file_type = self.type_cb.currentText()
        base = {
            "output_path": path,
            "browser": browser,
            "available_heights": list(self.heights),
        }
        if file_type == "mp3":
            base.update({"file_type": file_type, "bitrate": self.bitrate_cb.currentText()})
        elif file_type == "mp4":
            base.update(
                {
                    "file_type": file_type,
                    "resolution": self.res_cb.currentText(),
                    "codec": self.codec_cb.currentText(),
                }
            )
        elif file_type == "av1":
            base.update({"file_type": file_type})
        else:
            # Fallback to mp4
            base.update({"file_type": "mp4", "resolution": "best", "codec": "H.264"})
        return base

    def load_thumbnail(self, url):
        """Load thumbnail image from URL using requests in thread"""
        if not url:
            self.thumb.setText("No URL")
            self.thumb.setStyleSheet(
                "background:#000;color:#555;qproperty-alignment:AlignCenter;"
            )
            return

        # Use thread to load thumbnail
        self.thumb_loader = ThumbnailLoader(url, self)
        self.thumb_loader.finished.connect(self.on_thumbnail_loaded)
        self.thumb_loader.start()

    def on_thumbnail_loaded(self, image_data):
        """Handle thumbnail download completion"""
        if image_data:
            pixmap = QPixmap()
            if pixmap.loadFromData(image_data):
                self.thumb.setPixmap(pixmap)
                self.thumb.setStyleSheet("background:#000;")
                print("[DEBUG] Thumbnail loaded successfully")
            else:
                self.thumb.setText("Invalid Img")
                self.thumb.setStyleSheet(
                    "background:#000;color:#ff6b6b;qproperty-alignment:AlignCenter;"
                )
                print("[DEBUG] Failed to load pixmap from data")
        else:
            self.thumb.setText("No Img")
            self.thumb.setStyleSheet(
                "background:#000;color:#555;qproperty-alignment:AlignCenter;"
            )
            print("[DEBUG] No image data received")


# ===== HELP DIALOG =====
class HelpDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Hướng dẫn")
        self.resize(600, 500)
        layout = QVBoxLayout(self)
        txt = QTextEdit()
        txt.setReadOnly(True)
        txt.setText("""
        <h2>Hướng dẫn sử dụng</h2>
        <p><b>1. Auto Mode (Khuyên dùng):</b><br>
        Tool sẽ tự thử tải không cần đăng nhập trước. Nếu YouTube/BiliBili bắt xác thực, tool sẽ thử lấy cookie từ trình duyệt hoặc file <i>cookies/cookies.txt</i>.</p>
        
        <p><b>2. Hỗ trợ BiliBili:</b><br>
        - Dán link bilibili (BV/av, 番剧, 直播...) vào ô link rồi bấm Quét.<br>
        - Để đọc TOÀN BỘ danh sách video trên trang space (vd: space.bilibili.com/xxx/upload/video), đặt ô <i>Giới hạn</i> = 0 (Toàn bộ) rồi bấm Quét. Tool sẽ lấy hết video theo từng trang.<br>
        - Trang space thường bị Bilibili chặn (412/352) khi quét ẩn danh, nên phải đăng nhập bilibili.com và export cookies mới rồi Import vào tool.<br>
        - Nếu gặp lỗi HTTP 412, hãy đăng nhập bilibili.com trong trình duyệt rồi chọn Cookie: Chrome/Edge/Firefox (hoặc Auto).<br>
        - Hoặc export cookies bilibili ra file <i>cookies.txt</i> rồi import vào tool.<br>
        - Chất lượng tối đa bị giới hạn khi chưa đăng nhập (VD: 1080P 高码率/4K cần VIP) - hãy chọn chất lượng thấp hơn trong dropdown.</p>

        <p><b>3. Khắc phục lỗi:</b><br>
        - Nếu gặp lỗi "Sign in", hãy tải extension "Get cookies.txt LOCALLY", export file khi đang ở trang YouTube, rồi import vào tool.<br>
        - Nếu app báo lỗi DPAPI, hãy import file cookies thủ công.</p>
        <h2>Lưu ý</h2><br>

        <p>author by @daotacvosi</p>
        """)
        layout.addWidget(txt)


# ===== MAIN APP =====
class YoutubeDownloaderApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("YouTube Downloader Pro - Fixed")
        # Set app icon
        icon_path = self.get_icon_path()
        if icon_path and os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))
        self.resize(900, 700)
        self.save_folder = os.path.join(os.getcwd(), "downloads")
        self.current_worker = None
        self.is_downloading = False
        self.stop_requested = False
        self._workers = []  # Track all workers

        self.init_ui()
        self.auto_setup()

    def get_icon_path(self):
        """Get correct icon path for both script and exe"""
        return get_icon_path()

    def auto_setup(self):
        if not os.path.exists("cookies"):
            os.makedirs("cookies")
        # Install deps automatically silently - only when running as script, not exe
        if not getattr(sys, "frozen", False):  # Only install when running as .py script
            try:
                deps_marker = os.path.join("cookies", ".deps_2026.7.4")
                if not os.path.exists(deps_marker):
                    subprocess.check_call(
                        [
                            sys.executable,
                            "-m",
                            "pip",
                            "install",
                            "--quiet",
                            "yt-dlp[default]>=2026.7.4",
                            "PySide6",
                            "requests",
                        ],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
                    with open(deps_marker, "w") as f:
                        f.write("1")
            except:
                pass

    def init_ui(self):
        w = QWidget()
        self.setCentralWidget(w)
        layout = QVBoxLayout(w)

        # 1. Top Panel
        top = QHBoxLayout()
        self.btn_help = QPushButton("📖 Hướng dẫn")
        self.btn_help.clicked.connect(lambda: HelpDialog(self).exec())
        top.addWidget(self.btn_help)

        top.addWidget(QLabel("Cookie:"))
        self.browser_cb = QComboBox()
        self.browser_cb.addItems(["Auto (Tự tìm)", "None", "Chrome", "Edge", "Firefox"])
        top.addWidget(self.browser_cb)

        btn_imp = QPushButton("📥 Import Cookies")
        btn_imp.clicked.connect(self.import_cookies)
        top.addWidget(btn_imp)

        top.addWidget(QLabel("Giới hạn:"))
        self.limit_sb = QSpinBox()
        self.limit_sb.setRange(0, 1000)
        self.limit_sb.setValue(10)
        self.limit_sb.setSpecialValueText("Toàn bộ")  # 0 = quét toàn bộ danh sách
        self.limit_sb.setToolTip(
            "Số video tối đa sẽ quét. Chọn 0 (Toàn bộ) để đọc hết danh sách của trang.\n"
            "Lưu ý: với trang Bilibili space, cần cookies hợp lệ."
        )
        self.limit_sb.setFixedWidth(90)
        top.addWidget(self.limit_sb)

        top.addWidget(QLabel("Status:"))
        self.status_label = QLabel("Sẵn sàng")
        self.status_label.setStyleSheet("color:#2196F3;font-weight:bold;")
        top.addWidget(self.status_label)

        top.addStretch()
        layout.addLayout(top)

        # 2. Input
        inp_lay = QHBoxLayout()
        self.url_inp = QLineEdit()
        self.url_inp.setPlaceholderText("Link YouTube...")
        self.scan_btn = QPushButton("🔍 Quét")
        self.scan_btn.clicked.connect(self.start_scan)
        inp_lay.addWidget(self.url_inp)
        inp_lay.addWidget(self.scan_btn)
        layout.addLayout(inp_lay)

        # Toolbar
        toolbar = QHBoxLayout()
        btn_folder = QPushButton("📂 Thư mục")
        btn_folder.clicked.connect(self.select_folder)
        self.lbl_path = QLabel(self.save_folder)
        self.lbl_path.setStyleSheet("font-style:italic;color:#888;")
        btn_all = QPushButton("Chọn hết")
        btn_all.clicked.connect(lambda: self.toggle_all(True))
        btn_none = QPushButton("Bỏ chọn")
        btn_none.clicked.connect(lambda: self.toggle_all(False))
        btn_del = QPushButton("Xóa chọn")
        btn_del.setStyleSheet("color:#ff5252;")
        btn_del.clicked.connect(self.remove_selected)
        btn_clear = QPushButton("💥 Xóa sạch")
        btn_clear.setStyleSheet("background:#b71c1c;color:white;font-weight:bold;")
        btn_clear.clicked.connect(self.clear_all)

        for b in [btn_folder, btn_all, btn_none, btn_del, btn_clear]:
            if not b.styleSheet():
                b.setStyleSheet("background:#444;color:white;")
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            toolbar.addWidget(b)
        toolbar.addWidget(self.lbl_path)
        layout.addLayout(toolbar)

        # Bulk edit tools
        bulk_layout = QHBoxLayout()
        bulk_layout.addWidget(QLabel("Sửa hàng loạt:"))
        self.bulk_type_cb = QComboBox()
        self.bulk_type_cb.addItems(["mp4", "mp3", "av1"])
        self.bulk_res_cb = QComboBox()
        self.bulk_res_cb.addItems(["best", "4K", "2K", "1080", "720", "480", "360"])  # Keep static for bulk, as it's general
        self.bulk_bitrate_cb = QComboBox()
        self.bulk_bitrate_cb.addItems(["320", "256", "192", "128"])
        self.bulk_codec_cb = QComboBox()
        self.bulk_codec_cb.addItems(["H.264", "VA1"])
        self.bulk_type_cb.currentTextChanged.connect(self.on_bulk_type_changed)

        for c in [
            self.bulk_type_cb,
            self.bulk_res_cb,
            self.bulk_bitrate_cb,
            self.bulk_codec_cb,
        ]:
            c.setStyleSheet("background:#3e3e3e;color:white;border-radius:3px;")
            c.setFixedWidth(70)

        bulk_layout.addWidget(QLabel("Loại:"))
        bulk_layout.addWidget(self.bulk_type_cb)
        self.bulk_res_label = QLabel("Chất lượng:")
        bulk_layout.addWidget(self.bulk_res_label)
        bulk_layout.addWidget(self.bulk_res_cb)
        self.bulk_bitrate_label = QLabel("Bitrate:")
        bulk_layout.addWidget(self.bulk_bitrate_label)
        bulk_layout.addWidget(self.bulk_bitrate_cb)
        self.bulk_codec_label = QLabel("Codec:")
        bulk_layout.addWidget(self.bulk_codec_label)
        bulk_layout.addWidget(self.bulk_codec_cb)

        btn_apply_bulk = QPushButton("Sửa hàng loạt")
        btn_apply_bulk.setStyleSheet("background:#FF9800;color:white;font-weight:bold;")
        btn_apply_bulk.clicked.connect(self.apply_bulk_changes)
        bulk_layout.addWidget(btn_apply_bulk)

        bulk_layout.addStretch()
        layout.addLayout(bulk_layout)
        self.list_widget = QListWidget()
        layout.addWidget(self.list_widget)

        # 4. Actions
        act_lay = QHBoxLayout()
        self.btn_dl = QPushButton("TẢI XUỐNG")
        self.btn_dl.clicked.connect(self.start_download)
        self.btn_dl.setFixedHeight(40)
        self.btn_dl.setStyleSheet("background:#4CAF50;color:white;font-weight:bold;")

        act_lay.addWidget(self.btn_dl)
        layout.addLayout(act_lay)

    def import_cookies(self):
        f, _ = QFileDialog.getOpenFileName(
            self, "Chọn file cookies", "", "Text (*.txt);;All (*)"
        )
        if f:
            try:
                # Validate cookie file before import
                with open(f, "r", encoding="utf-8", errors="ignore") as cf:
                    content = cf.read()

                if len(content.strip()) < 50:
                    msg = QMessageBox(self)
                    msg.setIcon(QMessageBox.Icon.Warning)
                    msg.setWindowTitle("Lỗi")
                    msg.setText("File cookies trống hoặc quá ngắn!")
                    msg.exec()
                    return

                if ".youtube.com" not in content and ".bilibili.com" not in content:
                    msg = QMessageBox(self)
                    msg.setIcon(QMessageBox.Icon.Warning)
                    msg.setWindowTitle("Lỗi")
                    msg.setText(
                        "File không chứa cookies YouTube hoặc BiliBili!\n"
                        "Hãy xuất cookies từ trang youtube.com hoặc bilibili.com."
                    )
                    msg.exec()
                    return

                has_auth = any(
                    x in content
                    for x in ["SID", "LOGIN_INFO", "SSID", "SESSDATA", "bili_jct", "DedeUserID"]
                )

                if not os.path.exists("cookies"):
                    os.makedirs("cookies")
                shutil.copy(f, "cookies/cookies.txt")

                if has_auth:
                    msg = QMessageBox(self)
                    msg.setIcon(QMessageBox.Icon.Information)
                    msg.setWindowTitle("OK")
                    msg.setText("Đã import cookies thành công!\nCookies có chứa thông tin đăng nhập.")
                    msg.exec()
                else:
                    msg = QMessageBox(self)
                    msg.setIcon(QMessageBox.Icon.Warning)
                    msg.setWindowTitle("Cảnh báo")
                    msg.setText(
                        "Đã import cookies nhưng KHÔNG tìm thấy cookie đăng nhập.\n"
                        "Hãy đăng nhập YouTube/BiliBili trong trình duyệt rồi xuất lại."
                    )
                    msg.exec()
            except Exception as e:
                msg = QMessageBox(self)
                msg.setIcon(QMessageBox.Icon.Warning)
                msg.setWindowTitle("Lỗi")
                msg.setText(str(e))
                msg.exec()

    def start_scan(self):
        url = self.url_inp.text()
        if not url:
            return
        self.scan_btn.setEnabled(False)
        self.scan_btn.setText("Đang quét...")

        br = self.browser_cb.currentText()
        br = "Auto" if "Auto" in br else br

        self.scan_worker = ScanWorker(url, 0, self.limit_sb.value(), br, parent=self)
        self.scan_worker.found_item.connect(self.add_item)
        self.scan_worker.finished.connect(
            lambda: [self.scan_btn.setEnabled(True), self.scan_btn.setText("🔍 Quét")]
        )
        self.scan_worker.error.connect(self.on_scan_error)
        self.scan_worker.start()

    def on_scan_error(self, e):
        msg = QMessageBox(self)
        msg.setIcon(QMessageBox.Icon.Warning)
        msg.setWindowTitle("Lỗi")
        msg.setText(e)
        msg.exec()
        self.scan_btn.setEnabled(True)
        self.scan_btn.setText("🔍 Quét")

    def add_item(self, t, u, th, heights):
        item = QListWidgetItem(self.list_widget)
        item.setSizeHint(QSize(100, 100))
        w = VideoItemWidget(t, th, u, heights)
        self.list_widget.setItemWidget(item, w)

    def start_download(self):
        if self.list_widget.count() == 0:
            return

        # Kiểm tra có video nào được chọn không
        selected_count = 0
        for i in range(self.list_widget.count()):
            w = self.list_widget.itemWidget(self.list_widget.item(i))
            if w and w.btn_check.isChecked():
                selected_count += 1

        if selected_count == 0:
            msg = QMessageBox(self)
            msg.setIcon(QMessageBox.Icon.Warning)
            msg.setWindowTitle("Cảnh báo")
            msg.setText("Hãy chọn video muốn tải")
            msg.exec()
            return

        self.is_downloading = True
        self.stop_requested = False
        self.btn_dl.setEnabled(False)
        self.status_label.setText("Bắt đầu tải...")
        self.process_queue(0)

    # Bỏ stop_download vì không có nút dừng

    def reset_ui(self):
        self.is_downloading = False
        self.btn_dl.setEnabled(True)
        self.current_worker = None
        self.status_label.setText("Sẵn sàng")

    def process_queue(self, idx):
        if self.stop_requested or idx >= self.list_widget.count():
            self.reset_ui()
            if not self.stop_requested:
                msg = QMessageBox(self)
                msg.setIcon(QMessageBox.Icon.Information)
                msg.setWindowTitle("Xong")
                msg.setText("Hoàn tất!")
                msg.exec()
            return

        item = self.list_widget.item(idx)
        w = self.list_widget.itemWidget(item)

        if not w.btn_check.isChecked() or w.status_lbl.text() == "Hoàn tất":
            self.process_queue(idx + 1)
            return

        w.status_lbl.setText("Đang tải...")
        w.status_lbl.setStyleSheet("color:blue")

        br = self.browser_cb.currentText()
        br = "Auto" if "Auto" in br else br

        # --- FIX: Tạo Worker với parent=self và dùng signal mới ---
        self.current_worker = DownloadWorker(
            w.url, w.get_options(self.save_folder, br), parent=self
        )
        self.current_worker.task_progress.connect(w.progress.setValue)
        self.current_worker.status_update.connect(self.status_label.setText)

        # Logic khi xong
        def on_done():
            w.status_lbl.setText("Hoàn tất")
            w.status_lbl.setStyleSheet("color:green")
            w.progress.setValue(100)
            w.btn_check.setChecked(False)
            self.next_step(idx)

        def on_err(e):
            w.status_lbl.setText("Lỗi")
            w.status_lbl.setToolTip(str(e))
            w.status_lbl.setStyleSheet("color:red")
            print(f"Item error: {e}")
            self.next_step(idx)

        def on_stop():
            w.status_lbl.setText("Đã dừng")
            w.status_lbl.setStyleSheet("color:orange")
            self.reset_ui()

        self.current_worker.task_finished.connect(on_done)
        self.current_worker.task_error.connect(on_err)
        self.current_worker.task_stopped.connect(on_stop)

        # QUAN TRỌNG: Kết nối signal gốc finished để tự xóa worker an toàn
        self.current_worker.finished.connect(self.current_worker.deleteLater)

        self.current_worker.start()

    def next_step(self, idx):
        # Đợi một chút để worker cũ dọn dẹp xong hoàn toàn
        self.current_worker = None
        QTimer.singleShot(100, lambda: self.process_queue(idx + 1))

    def on_bulk_type_changed(self, text):
        if text == "mp4":
            self.bulk_res_label.show()
            self.bulk_res_cb.show()
            self.bulk_bitrate_label.hide()
            self.bulk_bitrate_cb.hide()
            self.bulk_codec_label.show()
            self.bulk_codec_cb.show()
        elif text == "mp3":
            self.bulk_res_label.hide()
            self.bulk_res_cb.hide()
            self.bulk_bitrate_label.show()
            self.bulk_bitrate_cb.show()
            self.bulk_codec_label.hide()
            self.bulk_codec_cb.hide()
        elif text == "av1":
            self.bulk_res_label.hide()
            self.bulk_res_cb.hide()
            self.bulk_bitrate_label.hide()
            self.bulk_bitrate_cb.hide()
            self.bulk_codec_label.hide()
            self.bulk_codec_cb.hide()

    def apply_bulk_changes(self):
        selected_type = self.bulk_type_cb.currentText()
        selected_res = (
            self.bulk_res_cb.currentText() if selected_type == "mp4" else None
        )
        selected_bitrate = (
            self.bulk_bitrate_cb.currentText() if selected_type == "mp3" else None
        )
        selected_codec = (
            self.bulk_codec_cb.currentText() if selected_type == "mp4" else None
        )

        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            w = self.list_widget.itemWidget(item)
            if w and w.btn_check.isChecked():
                w.type_cb.setCurrentText(selected_type)
                if selected_type == "mp4" and selected_res:
                    w.res_cb.setCurrentText(selected_res)
                elif selected_type == "mp3" and selected_bitrate:
                    w.bitrate_cb.setCurrentText(selected_bitrate)
                if selected_type == "mp4" and selected_codec:
                    w.codec_cb.setCurrentText(selected_codec)
                w.on_type_changed(selected_type)

    def closeEvent(self, event):
        self.stop_requested = True
        if self.current_worker and self.current_worker.isRunning():
            self.current_worker.stop()
            if not self.current_worker.wait(2000):  # Chờ tối đa 2 giây
                self.current_worker.terminate()  # Buộc dừng nếu vẫn chạy
                self.current_worker.wait(1000)  # Chờ terminate
        event.accept()

    def select_folder(self):
        d = QFileDialog.getExistingDirectory(self, "Chọn thư mục", self.save_folder)
        if d:
            self.save_folder = d
            self.lbl_path.setText(d)

    def toggle_all(self, state):
        for i in range(self.list_widget.count()):
            w = self.list_widget.itemWidget(self.list_widget.item(i))
            if w:
                w.btn_check.setChecked(state)

    def remove_selected(self):
        for i in range(self.list_widget.count() - 1, -1, -1):
            w = self.list_widget.itemWidget(self.list_widget.item(i))
            if w and w.btn_check.isChecked() and "Hoàn tất" not in w.status_lbl.text():
                self.list_widget.takeItem(i)

    def clear_all(self):
        if self.is_downloading:
            msg = QMessageBox(self)
            msg.setIcon(QMessageBox.Icon.Warning)
            msg.setWindowTitle("Cảnh báo")
            msg.setText("Vui lòng đợi tải xong.")
            msg.exec()
            return
        self.list_widget.clear()


if __name__ == "__main__":
    patch_bilibili_extractor()
    patch_bilibili_space_titles()
    app = QApplication(sys.argv)
    # Set app icon for taskbar
    icon_path = get_icon_path()
    if icon_path:
        app.setWindowIcon(QIcon(icon_path))
    window = YoutubeDownloaderApp()
    window.show()
    sys.exit(app.exec())
