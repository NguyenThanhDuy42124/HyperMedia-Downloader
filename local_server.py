"""
Local HTTP Server cho HyperMedia Downloader Pro
Cầu nối nhận link và cookies trực tiếp từ Chrome Extension không cần thao tác file.
Hỗ trợ Auto Port Hopping (tự động né port từ 42124 đến 42135).
"""
import json
import os
import sys
import threading
import time
from collections import deque
from http.server import BaseHTTPRequestHandler, HTTPServer
from socketserver import ThreadingMixIn
from PySide6.QtCore import QObject, Signal

from app_constants import cookies_file, ensure_dir

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


DEFAULT_PORTS = list(range(42124, 42136))  # 42124 -> 42135


def detect_browser_from_ua(ua_string: str) -> str:
    """Tự động nhận diện tên trình duyệt từ User-Agent chuỗi HTTP request."""
    if not ua_string:
        return "Extension"
    ua = ua_string.lower()
    if "edg/" in ua or "edge/" in ua:
        return "Microsoft Edge"
    elif "coccoc" in ua:
        return "Cốc Cốc"
    elif "brave" in ua:
        return "Brave"
    elif "opr/" in ua or "opera" in ua:
        return "Opera"
    elif "firefox" in ua or "fxios" in ua:
        return "Mozilla Firefox"
    elif "chrome" in ua:
        return "Google Chrome"
    return "Trình duyệt"


class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def handle_error(self, request, client_address):
        # Bỏ qua các lỗi ngắt kết nối socket mạng thông thường (client/browser ngắt sớm)
        err = sys.exc_info()[1]
        if isinstance(err, (ConnectionResetError, ConnectionAbortedError, BrokenPipeError, OSError)):
            return
        try:
            super().handle_error(request, client_address)
        except Exception:
            pass


class LocalServer(QObject):
    links_received = Signal(list)            # emit list of URLs
    items_received = Signal(list)            # emit list of dicts with url, title, thumb
    cookies_synced = Signal(str, int, str)   # emit (site_name, count, browser_name)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.httpd = None
        self.active_port = None
        self._server_thread = None
        self._pending_events = deque()
        self._event_lock = threading.Lock()
        self._event_condition = threading.Condition(self._event_lock)
        self._cookie_lock = threading.Lock()
        self._last_cookie_req_time = 0
        self._last_extension_ping = 0
        self._last_cookie_sync_time = 0
        self._last_cookie_sync_count = 0
        self._last_cookie_sync_site = ""
        self.last_client_browser = "Trình duyệt"

    def is_extension_connected(self, timeout=30):
        """Kiểm tra xem Chrome Extension có đang kết nối và gửi heartbeat hay không."""
        return (time.time() - self._last_extension_ping) < timeout

    def request_cookie_refresh(self, domain="bilibili.com", reason="", force=False):
        """Yêu cầu Chrome Extension trích xuất live cookies mới và gửi vào App."""
        now = time.time()
        with self._event_condition:
            # Throttling: Không bắn dồn dập trong vòng 8 giây nếu không force
            if not force and (now - self._last_cookie_req_time < 8):
                return False
            self._last_cookie_req_time = now
            event = {
                "action": "REQUEST_COOKIES",
                "domain": domain,
                "reason": reason,
                "timestamp": now,
            }
            self._pending_events.append(event)
            self._event_condition.notify_all()
            safe_print(f"[LOCAL SERVER] Đã xếp hàng yêu cầu lấy Live Cookies ({domain}) cho Extension (Lý do: {reason})...")
            return True

    def get_and_clear_events(self, timeout=8.0):
        with self._event_condition:
            if not self._pending_events and timeout > 0:
                self._event_condition.wait(timeout=timeout)
            events = list(self._pending_events)
            self._pending_events.clear()
            return events

    def start(self):
        for port in DEFAULT_PORTS:
            try:
                server = ThreadedHTTPServer(("127.0.0.1", port), self._create_handler())
                self.httpd = server
                self.active_port = port
                safe_print(f"[LOCAL SERVER] Đã mở cổng kết nối Extension tại http://127.0.0.1:{port}")
                self._server_thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
                self._server_thread.start()
                return port
            except OSError:
                continue
        safe_print("[LOCAL SERVER] Cảnh báo: Không thể mở port trong dải 42124-42135 (Tất cả cổng đều bận)")
        return None

    def stop(self):
        if self.httpd:
            try:
                self.httpd.shutdown()
                self.httpd.server_close()
            except Exception:
                pass
            self.httpd = None

    def _create_handler(self):
        outer = self

        class ApiHandler(BaseHTTPRequestHandler):
            def log_message(self, format, *args):
                pass  # Tắt log stdout mặc định của http.server

            def _send_cors_headers(self):
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
                self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Requested-With, Access-Control-Request-Private-Network")
                self.send_header("Access-Control-Allow-Private-Network", "true")

            def do_OPTIONS(self):
                self.send_response(200)
                self._send_cors_headers()
                self.send_header("Access-Control-Max-Age", "86400")
                self.end_headers()

            def do_GET(self):
                try:
                    self._handle_get_internal()
                except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError, OSError):
                    pass

            def _handle_get_internal(self):
                outer._last_extension_ping = time.time()
                ua = self.headers.get("User-Agent", "")
                detected = detect_browser_from_ua(ua)
                if detected != "Trình duyệt":
                    outer.last_client_browser = detected

                clean_path = self.path.split("?")[0]
                if clean_path == "/api/ping":
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json; charset=utf-8")
                    self._send_cors_headers()
                    self.end_headers()
                    resp = {
                        "app": "HyperMedia Downloader Pro",
                        "status": "ready",
                        "port": outer.active_port,
                        "version": "3.9"
                    }
                    self.wfile.write(json.dumps(resp).encode("utf-8"))
                elif clean_path == "/api/poll_events":
                    # Long-polling: giữ kết nối tối đa 4.5 giây để đánh thức tức thì
                    events = outer.get_and_clear_events(timeout=4.5)
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json; charset=utf-8")
                    self._send_cors_headers()
                    self.end_headers()
                    resp = {
                        "status": "ok",
                        "events": events
                    }
                    self.wfile.write(json.dumps(resp).encode("utf-8"))
                elif clean_path == "/api/sync_status":
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json; charset=utf-8")
                    self._send_cors_headers()
                    self.end_headers()
                    resp = {
                        "status": "ok",
                        "last_sync_time": outer._last_cookie_sync_time,
                        "last_count": outer._last_cookie_sync_count,
                        "last_site": outer._last_cookie_sync_site,
                        "last_browser": outer.last_client_browser,
                        "extension_connected": outer.is_extension_connected(timeout=25),
                    }
                    self.wfile.write(json.dumps(resp).encode("utf-8"))
                elif clean_path == "/sync_hub":
                    hub_html = """<!DOCTYPE html>
<html lang="vi">
<head>
  <meta charset="UTF-8">
  <title>HyperMedia Cookie Sync Hub</title>
  <style>
    body {
      background: #0B0F19;
      color: #E2E8F0;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      display: flex;
      align-items: center;
      justify-content: center;
      min-height: 100vh;
      margin: 0;
    }
    .card {
      background: #111827;
      border: 1px solid #1F2937;
      border-radius: 12px;
      padding: 28px 32px;
      max-width: 520px;
      width: 90%;
      text-align: center;
      box-shadow: 0 10px 25px rgba(0,0,0,0.5);
    }
    h2 { color: #00E676; margin-top: 0; font-size: 20px; }
    p { color: #94A3B8; font-size: 14px; line-height: 1.6; }
    .status-badge {
      display: inline-block;
      padding: 8px 16px;
      border-radius: 20px;
      background: rgba(0, 230, 118, 0.1);
      color: #00E676;
      font-weight: 600;
      margin: 14px 0;
      font-size: 14px;
    }
    .spinner {
      border: 3px solid rgba(255,255,255,0.1);
      border-top: 3px solid #00E676;
      border-radius: 50%;
      width: 28px;
      height: 28px;
      animation: spin 0.8s linear infinite;
      margin: 12px auto;
    }
    .guide-box {
      margin-top: 16px;
      padding: 14px;
      border-radius: 8px;
      text-align: left;
      font-size: 13px;
      line-height: 1.6;
    }
    .edge-box { background: rgba(0, 229, 255, 0.08); border: 1px solid rgba(0, 229, 255, 0.25); color: #E0F7FA; }
    .chrome-box { background: rgba(0, 230, 118, 0.08); border: 1px solid rgba(0, 230, 118, 0.25); color: #E8F5E9; }
    .coccoc-box { background: rgba(46, 204, 113, 0.08); border: 1px solid rgba(46, 204, 113, 0.25); color: #E8F8F5; }
    .firefox-box { background: rgba(255, 113, 67, 0.08); border: 1px solid rgba(255, 113, 67, 0.25); color: #FBE9E7; }
    .brave-box { background: rgba(255, 87, 34, 0.08); border: 1px solid rgba(255, 87, 34, 0.25); color: #FBE9E7; }
    .opera-box { background: rgba(233, 30, 99, 0.08); border: 1px solid rgba(233, 30, 99, 0.25); color: #FCE4EC; }
    code {
      background: rgba(255,255,255,0.15);
      padding: 2px 5px;
      border-radius: 4px;
      font-family: monospace;
      color: #FFD600;
    }
    @keyframes spin { 0% { transform: rotate(0deg); } 100% { transform: rotate(360deg); } }
  </style>
</head>
<body>
  <div class="card">
    <h2>HyperMedia Sync Hub</h2>
    <div id="loader" class="spinner"></div>
    <div id="status" class="status-badge">Đang kết nối Extension & đồng bộ Cookies...</div>
    <p id="desc">Vui lòng đợi 1 giây, Extension đang trích xuất Cookies và tự động gửi vào Desktop App.</p>

    <!-- Microsoft Edge -->
    <div id="edge_tip" class="guide-box edge-box" style="display:none;">
      <b style="color: #00E5FF;">📌 Hướng Dẫn Kích Hoạt Trên Microsoft Edge:</b><br>
      1. Truy cập: <code>edge://extensions</code> trên thanh địa chỉ Edge.<br>
      2. Bật công tắc <b>"Chế độ dành cho nhà phát triển"</b> (cột bên trái).<br>
      3. Bấm <b>"Tải phần mở rộng chưa được đóng gói"</b> &rarr; chọn thư mục <code>HyperMedia_Extension</code>.<br>
      4. Mở tab Bilibili / Douyin / YouTube trên Edge & đăng nhập tài khoản.
    </div>

    <!-- Google Chrome -->
    <div id="chrome_tip" class="guide-box chrome-box" style="display:none;">
      <b style="color: #00E676;">📌 Hướng Dẫn Kích Hoạt Trên Google Chrome:</b><br>
      1. Truy cập: <code>chrome://extensions</code> trên thanh địa chỉ Chrome.<br>
      2. Bật công tắc <b>"Chế độ nhà phát triển"</b> (góc trên bên phải).<br>
      3. Bấm <b>"Tải tiện ích đã giải nén"</b> &rarr; chọn thư mục <code>HyperMedia_Extension</code>.<br>
      4. Mở tab Bilibili / Douyin / YouTube trên Chrome & đăng nhập tài khoản.
    </div>

    <!-- Cốc Cốc -->
    <div id="coccoc_tip" class="guide-box coccoc-box" style="display:none;">
      <b style="color: #2ECC71;">📌 Hướng Dẫn Kích Hoạt Trên Cốc Cốc:</b><br>
      1. Truy cập: <code>coccoc://extensions</code> trên thanh địa chỉ Cốc Cốc.<br>
      2. Bật công tắc <b>"Chế độ cho nhà phát triển"</b> (góc trên bên phải).<br>
      3. Bấm <b>"Tải tiện ích đã giải nén"</b> &rarr; chọn thư mục <code>HyperMedia_Extension</code>.<br>
      4. Mở tab Bilibili / Douyin / YouTube trên Cốc Cốc & đăng nhập tài khoản.
    </div>

    <!-- Mozilla Firefox -->
    <div id="firefox_tip" class="guide-box firefox-box" style="display:none;">
      <b style="color: #FF7043;">📌 Hướng Dẫn Kích Hoạt Trên Mozilla Firefox:</b><br>
      1. Truy cập: <code>about:debugging#/runtime/this-firefox</code> trên Firefox.<br>
      2. Bấm <b>"Tải phần bổ trợ tạm thời..."</b> (Load Temporary Add-on).<br>
      3. Chọn file <code>manifest.json</code> trong thư mục <code>HyperMedia_Extension</code>.<br>
      4. Mở tab Bilibili / Douyin / YouTube trên Firefox & đăng nhập tài khoản.
    </div>

    <!-- Brave -->
    <div id="brave_tip" class="guide-box brave-box" style="display:none;">
      <b style="color: #FF5722;">📌 Hướng Dẫn Kích Hoạt Trên Brave Browser:</b><br>
      1. Truy cập: <code>brave://extensions</code> trên thanh địa chỉ Brave.<br>
      2. Bật công tắc <b>"Developer mode"</b>.<br>
      3. Bấm <b>"Load unpacked"</b> &rarr; chọn thư mục <code>HyperMedia_Extension</code>.
    </div>

    <!-- Opera -->
    <div id="opera_tip" class="guide-box opera-box" style="display:none;">
      <b style="color: #E91E63;">📌 Hướng Dẫn Kích Hoạt Trên Opera:</b><br>
      1. Truy cập: <code>opera://extensions</code> trên thanh địa chỉ Opera.<br>
      2. Bật công tắc <b>"Developer mode"</b>.<br>
      3. Bấm <b>"Load unpacked"</b> &rarr; chọn thư mục <code>HyperMedia_Extension</code>.
    </div>
  </div>
  <script>
    const startTime = Date.now() / 1000;
    window.postMessage({ type: 'HM_TRIGGER_COOKIE_SYNC' }, '*');

    // Tự động nhận diện trình duyệt từ URL param hoặc User-Agent
    const urlParams = new URLSearchParams(window.location.search);
    const targetBrowser = (urlParams.get('browser') || '').toLowerCase();
    const ua = navigator.userAgent.toLowerCase();
    let currentId = 'chrome_tip';

    if (targetBrowser.includes('edge') || ua.includes('edg/')) {
      currentId = 'edge_tip';
    } else if (targetBrowser.includes('coccoc') || targetBrowser.includes('cốc') || ua.includes('coccoc')) {
      currentId = 'coccoc_tip';
    } else if (targetBrowser.includes('firefox') || ua.includes('firefox')) {
      currentId = 'firefox_tip';
    } else if (targetBrowser.includes('brave') || ua.includes('brave')) {
      currentId = 'brave_tip';
    } else if (targetBrowser.includes('opera') || ua.includes('opr/')) {
      currentId = 'opera_tip';
    } else {
      currentId = 'chrome_tip';
    }
    const tipEl = document.getElementById(currentId);
    if (tipEl) tipEl.style.display = 'block';

    let attempts = 0;
    const poller = setInterval(async () => {
      attempts++;
      if (attempts % 3 === 0) {
        window.postMessage({ type: 'HM_TRIGGER_COOKIE_SYNC' }, '*');
      }
      try {
        const res = await fetch('/api/sync_status');
        if (res.ok) {
          const data = await res.json();
          if (data.last_sync_time && data.last_sync_time >= startTime - 1) {
            clearInterval(poller);
            document.getElementById('loader').style.display = 'none';
            const br = data.last_browser || 'Extension';
            document.getElementById('status').innerText = 'Đồng bộ thành công ' + data.last_count + ' Cookies từ ' + br + '!';
            document.getElementById('status').style.background = 'rgba(0, 230, 118, 0.2)';
            document.getElementById('desc').innerText = 'Dữ liệu đã nạp vào Desktop App. Cửa sổ này sẽ tự đóng ngay...';
            setTimeout(() => { window.close(); }, 800);
            return;
          }
        }
      } catch (e) {}

      if (attempts > 25) {
        clearInterval(poller);
        document.getElementById('loader').style.display = 'none';
        document.getElementById('status').innerText = 'Chưa phát hiện phản hồi từ Extension';
        document.getElementById('status').style.color = '#F59E0B';
        document.getElementById('status').style.background = 'rgba(245, 158, 11, 0.15)';
        document.getElementById('desc').innerHTML = 'Hãy chắc chắn rằng tiện ích <b>HyperMedia Helper</b> đã được bật trong trình duyệt của bạn và bạn đã đăng nhập Bilibili / Douyin / YouTube.<br><br>Bạn cũng có thể bấm nút <b>Đồng Bộ Cookies Thẳng Vào App</b> trên icon Extension!<br><button onclick="location.reload()" style="background:#0284c7;color:white;border:none;padding:8px 18px;border-radius:6px;cursor:pointer;margin-top:14px;font-weight:bold;font-size:13px;">Thử Lại Ngay</button>';
      }
    }, 400);
  </script>
</body>
</html>"""
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self._send_cors_headers()
                    self.end_headers()
                    self.wfile.write(hub_html.encode("utf-8"))
                else:
                    self.send_response(404)
                    self._send_cors_headers()
                    self.end_headers()

            def do_POST(self):
                try:
                    self._handle_post_internal()
                except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError, OSError):
                    pass

            def _handle_post_internal(self):
                outer._last_extension_ping = time.time()
                ua = self.headers.get("User-Agent", "")
                detected = detect_browser_from_ua(ua)
                if detected != "Trình duyệt":
                    outer.last_client_browser = detected

                content_length = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(content_length)

                clean_path = self.path.split("?")[0]
                if clean_path == "/api/add_links":
                    try:
                        data = json.loads(body.decode("utf-8"))
                        items = data.get("items", [])
                        urls = data.get("urls", [])
                        if isinstance(urls, str):
                            urls = [urls]
                        if items:
                            first_u = items[0].get("url", "") if isinstance(items[0], dict) else str(items[0])
                            first_t = items[0].get("title", "") if isinstance(items[0], dict) else ""
                            first_th = items[0].get("thumb", "") if isinstance(items[0], dict) else ""
                            safe_print(f"[LOCAL SERVER] Nhận {len(items)} item từ {outer.last_client_browser}:")
                            safe_print(f"  -> Link: {first_u[:70]}...")
                            safe_print(f"  -> Title: {first_t[:60] if first_t else '(Trống)'}")
                            safe_print(f"  -> Thumb: {first_th[:70] if first_th else '(Trống)'}")
                            outer.items_received.emit(items)
                            self.send_response(200)
                            self.send_header("Content-Type", "application/json; charset=utf-8")
                            self._send_cors_headers()
                            self.end_headers()
                            self.wfile.write(json.dumps({"success": True, "added": len(items)}).encode("utf-8"))
                            return
                        elif urls:
                            safe_print(f"[LOCAL SERVER] Nhận {len(urls)} url từ {outer.last_client_browser} (link đầu: {urls[0][:70]}...)")
                            outer.links_received.emit(urls)
                            self.send_response(200)
                            self.send_header("Content-Type", "application/json; charset=utf-8")
                            self._send_cors_headers()
                            self.end_headers()
                            self.wfile.write(json.dumps({"success": True, "added": len(urls)}).encode("utf-8"))
                            return
                    except Exception as e:
                        safe_print(f"[LOCAL SERVER] Lỗi nhận links: {e}")

                    self.send_response(400)
                    self._send_cors_headers()
                    self.end_headers()

                elif clean_path == "/api/sync_cookies":
                    try:
                        data = json.loads(body.decode("utf-8"))
                        raw_text = data.get("cookies", "")
                        source_site = data.get("domain", "Unknown")

                        if raw_text and len(raw_text.strip()) > 30:
                            import urllib.parse as _urlp
                            c_path = cookies_file()
                            ensure_dir(os.path.dirname(c_path))

                            with outer._cookie_lock:
                                cookie_map = {}
                                header_lines = []

                                if os.path.exists(c_path):
                                    try:
                                        with open(c_path, "r", encoding="utf-8", errors="ignore") as f:
                                            for line in f.read().splitlines():
                                                line_s = line.strip()
                                                if not line_s or line.startswith("#"):
                                                    if not header_lines and line.startswith("#"):
                                                        header_lines.append(line)
                                                    continue
                                                parts = line.split("\t")
                                                if len(parts) == 7:
                                                    key = (parts[0].lower(), parts[2], parts[5])
                                                    cookie_map[key] = line
                                    except Exception:
                                        pass

                                for line in raw_text.splitlines():
                                    line_s = line.strip()
                                    if not line_s or line.startswith("#"):
                                        continue
                                    parts = line.split("\t")
                                    if len(parts) == 7:
                                        # Chỉ URL-decode cho SESSDATA của Bilibili
                                        if parts[5] == "SESSDATA" and "bilibili" in parts[0].lower():
                                            parts[6] = _urlp.unquote(parts[6])
                                            line = "\t".join(parts)
                                        key = (parts[0].lower(), parts[2], parts[5])
                                        cookie_map[key] = line

                                if not header_lines:
                                    header_lines = [
                                        "# Netscape HTTP Cookie File",
                                        "# https://curl.haxx.se/rfc/cookie_spec.html",
                                        "# Generated by HyperMedia Helper",
                                    ]

                                merged_text = "\n".join(header_lines) + "\n" + "\n".join(cookie_map.values()) + "\n"
                                with open(c_path, "w", encoding="utf-8") as f:
                                    f.write(merged_text)

                                cookie_count = len(cookie_map)
                                outer._last_cookie_sync_time = time.time()
                                outer._last_cookie_sync_count = cookie_count
                                outer._last_cookie_sync_site = source_site
                                outer.cookies_synced.emit(source_site, cookie_count, outer.last_client_browser)

                                self.send_response(200)
                                self.send_header("Content-Type", "application/json; charset=utf-8")
                                self._send_cors_headers()
                                self.end_headers()
                                self.wfile.write(json.dumps({"success": True, "count": cookie_count, "browser": outer.last_client_browser}).encode("utf-8"))
                                return
                    except Exception as e:
                        safe_print(f"[LOCAL SERVER] Lỗi sync cookies: {e}")

                    self.send_response(400)
                    self._send_cors_headers()
                    self.end_headers()
                else:
                    self.send_response(404)
                    self._send_cors_headers()
                    self.end_headers()

        return ApiHandler
