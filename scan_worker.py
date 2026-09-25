"""Worker quét thông tin video/playlist/space."""
import os

from PySide6.QtCore import QThread, Signal

import yt_dlp

from app_constants import AUTO_BROWSERS, BROWSER_MAP, DEFAULT_UA, get_random_user_agent, get_js_runtime, cookies_file
from site_utils import detect_site, is_bilibili_url, is_youtube_url, normalize_url


class ScanWorker(QThread):
    found_item = Signal(str, str, str, list, list)  # title, url, thumb, heights, formats_list
    finished = Signal(str)
    error = Signal(str)

    def __init__(self, url, mode, limit, browser="None", parent=None):
        super().__init__(parent)
        self.url = url
        self.mode = mode
        self.limit = limit
        self.browser = browser

    @staticmethod
    def _extract_formats_data(info):
        formats_data = []
        if not info or "formats" not in info:
            return formats_data
        for f in info.get("formats", []):
            fid = str(f.get("format_id", ""))
            ext = str(f.get("ext", ""))
            h = f.get("height")
            w = f.get("width")
            res = str(f.get("resolution", "") or (f"{w}x{h}" if w and h else (f"{h}p" if h else "")))
            fps = f.get("fps")
            vcodec = str(f.get("vcodec", ""))
            acodec = str(f.get("acodec", ""))
            size = f.get("filesize") or f.get("filesize_approx") or 0
            tbr = f.get("tbr") or 0
            vbr = f.get("vbr") or 0
            abr = f.get("abr") or 0
            formats_data.append({
                "format_id": fid,
                "ext": ext,
                "height": h,
                "width": w,
                "resolution": res,
                "fps": fps,
                "vcodec": vcodec,
                "acodec": acodec,
                "filesize": size,
                "tbr": tbr,
                "vbr": vbr,
                "abr": abr,
            })
        return formats_data

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
        sources = []
        c_file = cookies_file()
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

    @staticmethod
    def _is_douyin_cdn_stream(url):
        """Kiểm tra URL đã là CDN stream Douyin trực tiếp (zjcdn.com / douyinvod.com / snssdk play) -> bypass yt-dlp."""
        u = (url or '').lower()
        return any(d in u for d in ('zjcdn.com', 'douyinvod.com', 'aweme.snssdk.com/aweme/v1/play'))

    def _emit_cdn_stream_item(self):
        """Phát item trực tiếp từ CDN stream URL mà không cần yt-dlp.
        title/thumb sẽ được override bởi _custom_metadata trong main_window nếu Extension đã gửi kèm."""
        import os as _os
        from urllib.parse import urlparse, parse_qs
        parsed = urlparse(self.url)
        qs = parse_qs(parsed.query)
        # Lấy title từ query param hoặc từ path
        title = (
            qs.get('title', [None])[0]
            or _os.path.basename(parsed.path).split('?')[0]
            or 'Douyin Video'
        )
        heights = [1080]
        formats_data = [{
            'format_id': 'cdn-direct',
            'ext': 'mp4',
            'height': 1080,
            'width': 1920,
            'resolution': '1920x1080',
            'fps': None,
            'vcodec': 'h264',
            'acodec': 'aac',
            'filesize': 0,
            'tbr': 0,
            'vbr': 0,
            'abr': 0,
        }]
        print(f'[STREAM BYPASS] CDN stream Douyin detected, bypass yt-dlp: {self.url[:80]}...')
        self.found_item.emit(title, self.url, '', heights, formats_data)
        self.finished.emit('')

    def run(self):
        try:
            self.url = normalize_url(self.url)
            # === CDN Stream Bypass: zjcdn.com / douyinvod.com / snssdk play -> tải thẳng, không yt-dlp ===
            if self._is_douyin_cdn_stream(self.url):
                self._emit_cdn_stream_item()
                return
            selected_ua = get_random_user_agent()
            site_headers = detect_site(self.url)
            site_headers["User-Agent"] = selected_ua

            ydl_opts = {
                "quiet": True,
                "no_warnings": True,
                "user_agent": selected_ua,
                "http_headers": site_headers,
                "source_address": "0.0.0.0",
            }
            js_runtime = get_js_runtime()
            if js_runtime:
                ydl_opts["js_runtimes"] = js_runtime
            if is_youtube_url(self.url):
                ydl_opts["extractor_args"] = {
                    "youtube": {
                        "player_client": ["web_embedded", "android"]
                    }
                }

            if self.mode == 2 or self.is_playlist_url(self.url):
                ydl_opts["extract_flat"] = True
                if self.limit > 0:
                    ydl_opts["playlistend"] = self.limit
            else:
                ydl_opts["noplaylist"] = True

            cookie_sources = self._get_cookie_sources()
            # Ưu tiên cookies trước (cookies.txt / browser), sau cùng mới fallback về Anonymous
            sources_to_try = cookie_sources + [None] if cookie_sources else [None]

            info = None
            last_err = None
            for source in sources_to_try:
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
                                  "members-only", "HTTP Error", "412", "352", "Precondition", 
                                  "Fresh cookies", "Douyin", "cookie", "cookies"]
                    )
                    src_name = "cookies.txt" if (source and "cookiefile" in source) else (str(source) if source else "anonymous")
                    print(f"[DEBUG] Scan attempt {src_name} thất bại: {err_str[:100]}")
                    if source is None and not retryable:
                        break

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
                    elif "douyin.com" in self.url and any(
                        x in err_str for x in ["Fresh cookies", "403", "ArgusSecurityPlugin"]
                    ):
                        self.error.emit(
                            "Douyin Web chặn quét tự động (ArgusSecurityPlugin 403). "
                            "Để tải video này: Bạn hãy mở video trên trình duyệt rồi dùng Extension "
                            "(bấm nút 'Gửi Vào App' hoặc thanh nổi 'Tải Video Này') để tải luồng stream gốc!"
                        )
                    else:
                        raise last_err
                else:
                    self.error.emit(
                        "Không thể lấy thông tin video. Video có thể bị xóa, private, "
                        "hoặc cần đăng nhập/cookies hợp lệ."
                    )
                return

            heights = []
            formats_data = self._extract_formats_data(info)
            if "formats" in info and info["formats"]:
                heights = sorted(
                    set(f.get("height") for f in info["formats"] if f.get("height")),
                    reverse=True,
                )

            if "douyin.com" in self.url:
                import re, requests
                vid = None
                for f in info.get("formats", []):
                    u_str = f.get("url", "") or f.get("format_id", "")
                    m = re.search(r'video_id=([a-zA-Z0-9_-]+)', u_str) or re.search(r'(v0[0-9a-zA-Z]+)', u_str)
                    if m:
                        vid = m.group(1)
                        break
                if vid:
                    try:
                        test_1080_url = f"https://aweme.snssdk.com/aweme/v1/play/?video_id={vid}&ratio=1080p&line=0"
                        h_res = requests.head(test_1080_url, headers={
                            "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1"
                        }, allow_redirects=True, timeout=4)
                        if h_res.status_code == 200:
                            if 1080 not in heights:
                                heights = [1080] + [h for h in heights if h != 1080]
                            formats_data.insert(0, {
                                "format_id": f"douyin_1080p_{vid}",
                                "ext": "mp4",
                                "height": 1080,
                                "width": 1920,
                                "resolution": "1080p (Full HD)",
                                "fps": 30,
                                "vcodec": "h264",
                                "acodec": "aac",
                                "filesize": 0,
                                "tbr": 1157,
                                "vbr": 1157,
                                "abr": 64,
                            })
                    except Exception:
                        pass

            if "entries" in info and info["entries"]:
                for entry in info["entries"]:
                    if entry:
                        t = entry.get("title", "Unknown")
                        u = entry.get("url") or entry.get("webpage_url") or self.url
                        video_id = entry.get("id", "")
                        th = self._fix_thumb(entry.get("thumbnail", ""), u, video_id)
                        e_formats = self._extract_formats_data(entry) or formats_data
                        self.found_item.emit(t, u, th, heights, e_formats)
            else:
                t = info.get("title", "Unknown")
                u = info.get("webpage_url", self.url)
                video_id = info.get("id", "")
                th = self._fix_thumb(info.get("thumbnail", ""), u, video_id)
                self.found_item.emit(t, u, th, heights, formats_data)
            self.finished.emit("Quét xong!")
        except Exception as e:
            self.error.emit(str(e))
