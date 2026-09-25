"""Cửa sổ chính: list ảo hóa, marquee select, xóa item, tìm kiếm,
tải song song, stop/retry/skip, session & settings."""
import os
import shutil
import time
import webbrowser
from collections import deque

from PySide6.QtCore import (
    QItemSelection,
    QObject,
    QParallelAnimationGroup,
    QPropertyAnimation,
    QSettings,
    QSize,
    QSortFilterProxyModel,
    Qt,
    Signal,
    QTimer,
)
from PySide6.QtGui import QAction, QIcon, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListView,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QSplitter,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from activation_dialog import ActivationDialog
from license_manager import check_current_machine_license, get_license_info
from local_server import LocalServer
from site_utils import is_bilibili_url

try:
    from bilibili_patch import patch_bilibili_anti_throttling, patch_bilibili_extractor
    patch_bilibili_extractor()
    patch_bilibili_anti_throttling()
except Exception as e:
    pass


class PrintInterceptor(QObject):
    log_signal = Signal(str)

    def __init__(self, original_stdout):
        super().__init__()
        self.original_stdout = original_stdout

    def write(self, text):
        if text:
            try:
                self.original_stdout.write(text)
            except Exception:
                pass
            self.log_signal.emit(text)

    def flush(self):
        try:
            self.original_stdout.flush()
        except Exception:
            pass

from app_constants import (
    APP_NAME,
    BROWSER_MAP,
    DEFAULT_PARALLEL,
    DEFAULT_THREADS,
    MAX_PARALLEL,
    base_dir,
    ensure_dir,
    get_icon_path,
)
import html
import time
from delegates import GRID_H, GRID_W, VideoItemDelegate
from download_worker import DownloadWorker
from logger import app_logger, clean_ansi
from models import VideoListModel, VideoRoles
from scan_worker import ScanWorker
from session_store import load_session, save_session
from thumbnail_loader import ThumbnailPool
from lucide_icons import get_lucide_icon, get_lucide_pixmap


class FilterProxy(QSortFilterProxyModel):
    """Lọc theo tiêu đề (không đổi động để giữ thứ tự)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._text = ""
        self.setDynamicSortFilter(False)

    def set_filter(self, text):
        self._text = (text or "").lower()
        self.invalidateFilter()

    def filterAcceptsRow(self, src_row, src_parent):
        if not self._text:
            return True
        title = self.sourceModel().data(
            self.sourceModel().index(src_row, 0), VideoRoles.Title
        )
        return self._text in str(title or "").lower()


class VideoListView(QListView):
    hoveredChanged = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._last = None
        self.setMouseTracking(True)
        self.viewport().setMouseTracking(True)

    def mouseMoveEvent(self, event):
        super().mouseMoveEvent(event)
        idx = self.indexAt(event.position().toPoint())
        uid = idx.data(VideoRoles.Uid) if idx.isValid() else None
        if uid != self._last:
            self._last = uid
            self.hoveredChanged.emit(uid or "")

    def leaveEvent(self, event):
        super().leaveEvent(event)
        self._last = None
        self.hoveredChanged.emit("")


class HelpDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Hướng dẫn sử dụng")
        self.resize(660, 530)
        layout = QVBoxLayout(self)
        txt = QTextEdit()
        txt.setReadOnly(True)
        txt.setOpenExternalLinks(True)
        txt.setText("""
        <h2>Hướng Dẫn Sử Dụng HyperMedia Downloader Pro</h2>
        <p><b>1. Quét & Chọn Video:</b><br>
        Dán link (YouTube, Bilibili, Douyin, TikTok - video đơn, playlist, kênh hoặc nhiều link dán cùng lúc) rồi bấm <b>Quét</b>.<br>
        Kéo chuột trên danh sách để khoanh vùng chọn nhiều video cùng lúc hoặc tích chọn trên từng thẻ video.<br>
        Ô <i>Giới hạn</i> = 0 (Toàn bộ) để quét hết danh sách của trang.</p>

        <p><b>2. Tải Xuống Đa Luồng Siêu Tốc:</b><br>
        Chọn video cần tải rồi bấm <b>TẢI ĐÃ CHỌN</b> hoặc <b>Tải Tất Cả</b>. Mặc định tải song song 3 video.<br>
        Bấm <b>Dừng tải</b> để dừng; <b>Thử lại file lỗi</b> để tải lại các video bị ngắt kết nối.<br>
        Tích <i>Bỏ qua file đã có</i> để tránh tải trùng lặp.</p>

        <p><b>3. Bilibili & Douyin 1080p:</b><br>
        - <b>Bilibili:</b> Tự động bypass chống chặn WBI. Hỗ trợ import cookies hoặc trích xuất cookie trình duyệt tự động.<br>
        - <b>Douyin:</b> Tự động mở khóa luồng 1080p Full HD gốc không watermark / không logo.</p>

        <p><b>4. Phím Tắt Tiện Lợi:</b><br>
        Delete: Xóa thẻ chọn · Ctrl+A: Chọn hết · Ctrl+D: Bỏ chọn · Ctrl+F: Tìm kiếm · Esc: Dừng tải.</p>

        <hr style="border:0; border-top:1px solid #333344; margin:15px 0;">
        <p style="color:#00E5FF; font-size:12px;"><b>Tác giả:</b> <a href="https://github.com/NguyenThanhDuy42124" style="color:#00E5FF; text-decoration:underline;"><b>NguyenThanhDuy42124 (Nguyễn Thanh Duy)</b></a> &nbsp;|&nbsp; <b>Zalo:</b> 0334674017</p>
        """)
        layout.addWidget(txt)


def open_browser_for_url(url, browser_choice="Auto"):
    """Mở URL bằng chính xác trình duyệt đã chọn (Edge / Chrome / Cốc Cốc / Firefox / Brave / Opera) hoặc mặc định."""
    choice = (browser_choice or "Auto").lower()
    import subprocess
    import shutil

    if "edge" in choice:
        try:
            os.startfile(f"microsoft-edge:{url}")
            return True
        except Exception:
            pass

        edge_paths = [
            r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
            r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
            shutil.which("msedge") or "",
        ]
        for ep in edge_paths:
            if ep and os.path.exists(ep):
                try:
                    subprocess.Popen([ep, url])
                    return True
                except Exception:
                    pass

    elif "coccoc" in choice or "cốc" in choice:
        coccoc_paths = [
            r"C:\Program Files\CocCoc\Browser\Application\browser.exe",
            r"C:\Program Files (x86)\CocCoc\Browser\Application\browser.exe",
            os.path.expandvars(r"%LOCALAPPDATA%\CocCoc\Browser\Application\browser.exe"),
            shutil.which("browser") or "",
        ]
        for cp in coccoc_paths:
            if cp and os.path.exists(cp):
                try:
                    subprocess.Popen([cp, url])
                    return True
                except Exception:
                    pass

    elif "firefox" in choice:
        ff_paths = [
            r"C:\Program Files\Mozilla Firefox\firefox.exe",
            r"C:\Program Files (x86)\Mozilla Firefox\firefox.exe",
            shutil.which("firefox") or "",
        ]
        for fp in ff_paths:
            if fp and os.path.exists(fp):
                try:
                    subprocess.Popen([fp, url])
                    return True
                except Exception:
                    pass

    elif "brave" in choice:
        brave_paths = [
            r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe",
            r"C:\Program Files (x86)\BraveSoftware\Brave-Browser\Application\brave.exe",
            os.path.expandvars(r"%LOCALAPPDATA%\BraveSoftware\Brave-Browser\Application\brave.exe"),
            shutil.which("brave") or "",
        ]
        for bp in brave_paths:
            if bp and os.path.exists(bp):
                try:
                    subprocess.Popen([bp, url])
                    return True
                except Exception:
                    pass

    elif "opera" in choice:
        opera_paths = [
            os.path.expandvars(r"%LOCALAPPDATA%\Programs\Opera\opera.exe"),
            os.path.expandvars(r"%LOCALAPPDATA%\Programs\Opera GX\opera.exe"),
            r"C:\Program Files\Opera\opera.exe",
            shutil.which("opera") or "",
        ]
        for op in opera_paths:
            if op and os.path.exists(op):
                try:
                    subprocess.Popen([op, url])
                    return True
                except Exception:
                    pass

    elif "chrome" in choice:
        chrome_paths = [
            os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
            shutil.which("chrome") or "",
        ]
        for cp in chrome_paths:
            if cp and os.path.exists(cp):
                try:
                    subprocess.Popen([cp, url])
                    return True
                except Exception:
                    pass

    # Fallback mặc định
    try:
        webbrowser.open(url)
        return True
    except Exception:
        return False


class YoutubeDownloaderApp(QMainWindow):
    def __init__(self, license_info: dict | None = None):
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.license_info = license_info or {}
        icon_path = get_icon_path()
        if icon_path and os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))
        self.resize(960, 720)

        self.settings = QSettings("DTSV", "YTDownloader")
        self.save_folder = self.settings.value(
            "folder", os.path.join(base_dir(), "downloads")
        )

        self.model = VideoListModel(self)
        self.proxy = FilterProxy(self)
        self.proxy.setSourceModel(self.model)
        self.thumb_pool = ThumbnailPool(parent=self)

        self._scanning = False
        self._is_downloading = False
        self._stop_requested = False
        self._pending_uids = deque()
        self._active = {}
        self._completed_ok = 0
        self._retry_counts = {}

        self.delegate = VideoItemDelegate(self.model, self)

        self.init_ui()
        self.connect_signals()
        self.load_settings()
        self.restore_session()
        self.setup_shortcuts()

        import sys
        self.print_interceptor = PrintInterceptor(sys.stdout)
        self.print_interceptor.log_signal.connect(self.append_log)
        sys.stdout = self.print_interceptor

        # Khởi động Local Server giao tiếp với Chrome Extension
        self._custom_metadata = {}
        self.local_server = LocalServer(self)
        self.local_server.links_received.connect(self._on_extension_links)
        self.local_server.items_received.connect(self._on_extension_items)
        self.local_server.cookies_synced.connect(self._on_extension_cookies)
        self.local_server.start()

    def _on_extension_items(self, items):
        if not items:
            return
        clean_urls = []
        for it in items:
            if isinstance(it, dict):
                u = (it.get("url") or "").strip()
                t = (it.get("title") or "").strip()
                th = (it.get("thumb") or "").strip()
                if u:
                    clean_urls.append(u)
                    if t or th:
                        self._custom_metadata[u] = {"title": t, "thumb": th}
            elif isinstance(it, str) and it.strip():
                clean_urls.append(it.strip())
        if clean_urls:
            self._on_extension_links(clean_urls)

    def _on_extension_links(self, urls):
        if not urls:
            return
        clean_urls = [u.strip() for u in urls if u and u.strip()]
        if not clean_urls:
            return
        if len(clean_urls) == 1:
            self.url_inp.setText(clean_urls[0])
        else:
            self.url_inp.setText(f"{clean_urls[0]} (+{len(clean_urls)-1} links khác)")
        print(f"[EXTENSION CONNECT] Đã nhận {len(clean_urls)} link từ Extension! Bắt đầu quét...")
        self.status_label.setText(f"Đã nhận {len(clean_urls)} link từ Extension. Đang quét...")
        try:
            self.showNormal()
            self.activateWindow()
            self.raise_()
        except Exception:
            pass
        self.start_scan(custom_urls=clean_urls)

    def _on_browser_changed(self, text):
        br = (text or "").lower()
        if "edge" in br:
            tip = "Yêu cầu Extension trên Microsoft Edge tự động trích xuất và đồng bộ Cookies mới nhất vào App"
        elif "chrome" in br:
            tip = "Yêu cầu Extension trên Google Chrome tự động trích xuất và đồng bộ Cookies mới nhất vào App"
        elif "cốc" in br or "coccoc" in br:
            tip = "Yêu cầu Extension trên Cốc Cốc tự động trích xuất và đồng bộ Cookies mới nhất vào App"
        elif "firefox" in br:
            tip = "Yêu cầu Extension trên Mozilla Firefox tự động trích xuất và đồng bộ Cookies mới nhất vào App"
        elif "brave" in br:
            tip = "Yêu cầu Extension trên Brave tự động trích xuất và đồng bộ Cookies mới nhất vào App"
        elif "opera" in br:
            tip = "Yêu cầu Extension trên Opera / Opera GX tự động trích xuất và đồng bộ Cookies mới nhất vào App"
        elif "none" in br:
            tip = "Không sử dụng Cookies trình duyệt (Tải ẩn danh Anonymous)"
        else:
            tip = "Yêu cầu Extension trên trình duyệt (Edge / Chrome / Cốc Cốc / Firefox / Brave / Opera) tự động trích xuất và đồng bộ Cookies mới nhất vào App"
        if hasattr(self, "btn_ext_cookie"):
            self.btn_ext_cookie.setToolTip(tip)

    def _on_extension_cookies(self, site_name, count, source_browser="Extension"):
        source_name = source_browser if source_browser and source_browser != "Extension" else "Trình duyệt"
        print(f"[EXTENSION CONNECT] Đã tự động đồng bộ {count} live cookies ({site_name}) từ {source_name} Extension!")
        self.status_label.setText(f"Đã nhận {count} live cookies mới từ {source_name} Extension!")
        if hasattr(self, "btn_ext_cookie"):
            self.btn_ext_cookie.setEnabled(True)
            self.btn_ext_cookie.setText(f" Đã Nhận {count} Cookie")
            self.btn_ext_cookie.setIcon(get_lucide_icon("check-circle", "#00E676", 16))
            def _reset_btn():
                if hasattr(self, "btn_ext_cookie") and self.btn_ext_cookie.text() != " Lấy từ Extension":
                    self.btn_ext_cookie.setText(" Lấy từ Extension")
                    self.btn_ext_cookie.setIcon(get_lucide_icon("rotate-cw", "#00E676", 16))
            QTimer.singleShot(4000, _reset_btn)

        cur_br = self.browser_cb.currentText() if hasattr(self, "browser_cb") else "Auto"
        br_name = source_name if source_name != "Trình duyệt" else (
            "Microsoft Edge" if "Edge" in cur_br else (
                "Google Chrome" if "Chrome" in cur_br else (
                    "Cốc Cốc" if ("Cốc" in cur_br or "CocCoc" in cur_br) else (
                        "Mozilla Firefox" if "Firefox" in cur_br else (
                            "Brave" if "Brave" in cur_br else (
                                "Opera" if "Opera" in cur_br else "Trình duyệt"
                            )
                        )
                    )
                )
            )
        )

        self.status_label.setText(
            f"Đã nhận {count} Live Cookies ({site_name}) từ {br_name} Extension! Sẵn sàng tải VIP."
        )

    def _on_worker_request_cookies(self, domain, reason):
        if hasattr(self, "local_server") and self.local_server:
            if not self.local_server.is_extension_connected():
                print(f"[COOKIE SYNC] Chrome Extension chưa kết nối (trình duyệt chưa mở hoặc chưa cài Extension). Bỏ qua re-fetch tự động.")
                return
            sent = self.local_server.request_cookie_refresh(domain, reason)
            if sent:
                print(f"[AUTO COOKIE RE-FETCH] Phát hiện CDN chặn/hết hạn cookies ({reason}). Đã gửi yêu cầu lấy Live Cookies mới tới Chrome Extension...")
                self.status_label.setText(f"Đang tự động lấy Live Cookies mới từ Extension...")

    # ---------------------------------------------------------------
    def init_ui(self):
        self.resize(1440, 860)
        self.setMinimumSize(1120, 700)
        central = QWidget()
        self.setCentralWidget(central)
        vbox = QVBoxLayout(central)
        vbox.setSpacing(8)
        vbox.setContentsMargins(10, 8, 10, 8)

        # ---------- Top bar: URL + Quét + Giới hạn + Cookie + Status ----------
        top = QHBoxLayout()
        self.url_inp = QLineEdit()
        self.url_inp.setPlaceholderText("Link YouTube / Bilibili (video, playlist, space)...")
        top.addWidget(self.url_inp, 1)

        self.scan_btn = QPushButton(" Quét")
        self.scan_btn.setIcon(get_lucide_icon("search", "#ffffff", 16))
        self.scan_btn.clicked.connect(self.start_scan)
        top.addWidget(self.scan_btn)

        top.addWidget(QLabel("Giới hạn:"))
        self.limit_sb = QSpinBox()
        self.limit_sb.setRange(0, 1000)
        self.limit_sb.setValue(10)
        self.limit_sb.setSpecialValueText("Toàn bộ")
        self.limit_sb.setToolTip(
            "Số video tối đa sẽ quét. Chọn 0 (Toàn bộ) để đọc hết danh sách của trang."
        )
        self.limit_sb.setFixedWidth(90)
        top.addWidget(self.limit_sb)

        top.addWidget(QLabel("Cookie:"))
        self.browser_cb = QComboBox()
        self.browser_cb.addItems(["Auto (Tự tìm)", "Chrome", "Edge", "Cốc Cốc", "Firefox", "Brave", "Opera", "None"])
        self.browser_cb.currentTextChanged.connect(self._on_browser_changed)
        top.addWidget(self.browser_cb)

        btn_imp = QPushButton(" Import Cookies")
        btn_imp.setIcon(get_lucide_icon("cookie", "#00E5FF", 16))
        btn_imp.clicked.connect(self.import_cookies)
        top.addWidget(btn_imp)

        self.btn_ext_cookie = QPushButton(" Lấy từ Extension")
        self.btn_ext_cookie.setIcon(get_lucide_icon("rotate-cw", "#00E676", 16))
        self.btn_ext_cookie.setToolTip("Yêu cầu Extension trên trình duyệt đã chọn (Edge / Chrome / Cốc Cốc / Firefox / Brave / Opera) tự động trích xuất và đồng bộ Cookies mới nhất vào App")
        self.btn_ext_cookie.clicked.connect(self.request_cookies_from_extension)
        top.addWidget(self.btn_ext_cookie)

        self.btn_stop = QPushButton(" Dừng tải")
        self.btn_stop.setIcon(get_lucide_icon("stop-circle", "#ffffff", 16))
        self.btn_stop.clicked.connect(self.stop_download)
        self.btn_stop.setEnabled(False)
        self.btn_stop.setStyleSheet("background:#B71C1C;color:white;font-weight:bold;")
        top.addWidget(self.btn_stop)

        top.addWidget(QLabel("Status:"))
        self.status_label = QLabel("Sẵn sàng")
        vbox.addLayout(top)

        # ---------- Splitter: grid card (trái) + panel điều khiển (phải) ----------
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)

        # View: grid card 4 cột
        self.view = VideoListView()
        self.view.setModel(self.proxy)
        self.view.setItemDelegate(self.delegate)
        self.delegate.set_view(self.view)
        self.view.setViewMode(QListView.ViewMode.IconMode)
        self.view.setMovement(QListView.Movement.Static)
        self.view.setResizeMode(QListView.ResizeMode.Adjust)
        self.view.setFlow(QListView.Flow.LeftToRight)
        self.view.setWrapping(True)
        self.view.setGridSize(QSize(GRID_W, GRID_H))
        self.view.setSpacing(0)
        self.view.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.view.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.view.setEditTriggers(
            QAbstractItemView.EditTrigger.SelectedClicked
            | QAbstractItemView.EditTrigger.DoubleClicked
        )
        self.view.setFrameShape(QFrame.Shape.NoFrame)
        self.view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.view.customContextMenuRequested.connect(self.show_context_menu)

        # Khu vực bên trái: List Video (Trên) + Live Terminal Log Console (Dưới)
        self.left_box = QWidget()
        left_vbox = QVBoxLayout(self.left_box)
        left_vbox.setContentsMargins(0, 0, 0, 0)
        left_vbox.setSpacing(0)
        left_vbox.addWidget(self.view, 1)

        # Floating Contextual Panel (Nổi lơ lửng trên list khi chọn video)
        self.floating_panel = QFrame(self.view)
        self.floating_panel.setObjectName("floatingPanel")
        self.floating_panel.setFixedHeight(54)
        self.floating_panel.setStyleSheet("""
            QFrame#floatingPanel {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #12121c, stop:1 #1e1e2d);
                border: 1px solid #383854;
                border-radius: 10px;
            }
            QLabel {
                color: #e2e8f0;
                font-weight: bold;
                font-size: 11px;
                border: none;
            }
            QComboBox {
                background: #1e1e2e;
                color: #ffffff;
                border: 1px solid #3b4261;
                border-radius: 4px;
                padding: 3px 6px;
                font-size: 11px;
            }
            QPushButton {
                font-size: 11px;
                font-weight: bold;
                border-radius: 6px;
                padding: 5px 10px;
            }
        """)
        float_layout = QHBoxLayout(self.floating_panel)
        float_layout.setContentsMargins(12, 6, 12, 6)
        float_layout.setSpacing(8)

        self.lbl_float_count = QLabel("Đã chọn: 0")
        self.lbl_float_count.setStyleSheet("color: #00E5FF; font-size: 12px; font-weight: bold;")
        float_layout.addWidget(self.lbl_float_count)

        self.bulk_type_cb = QComboBox()
        self.bulk_type_cb.addItems(["mp4", "mp3", "av1"])
        self.bulk_res_cb = QComboBox()
        self.bulk_res_cb.addItems(["best", "4K", "2K", "1080", "720", "480", "360"])
        self.bulk_bitrate_cb = QComboBox()
        self.bulk_bitrate_cb.addItems(["320", "256", "192", "128"])
        self.bulk_codec_cb = QComboBox()
        self.bulk_codec_cb.addItems(["H.264", "HEVC", "VA1"])

        float_layout.addWidget(QLabel("Loại:"))
        float_layout.addWidget(self.bulk_type_cb)
        float_layout.addWidget(QLabel("CL:"))
        float_layout.addWidget(self.bulk_res_cb)
        float_layout.addWidget(QLabel("Bitrate:"))
        float_layout.addWidget(self.bulk_bitrate_cb)
        float_layout.addWidget(QLabel("Codec:"))
        float_layout.addWidget(self.bulk_codec_cb)

        btn_apply = QPushButton(" Áp dụng")
        btn_apply.setIcon(get_lucide_icon("check", "#ffffff", 14))
        btn_apply.setStyleSheet("background:#FF9800; color:white; font-weight:bold;")
        btn_apply.clicked.connect(self.apply_bulk_changes)
        float_layout.addWidget(btn_apply)

        self.btn_dl_selected = QPushButton(" TẢI ĐÃ CHỌN")
        self.btn_dl_selected.setIcon(get_lucide_icon("download", "#ffffff", 14))
        self.btn_dl_selected.setStyleSheet("background:#0284c7; color:white; font-weight:bold; font-size:11px; padding:5px 12px;")
        self.btn_dl_selected.clicked.connect(self.download_selected)
        float_layout.addWidget(self.btn_dl_selected)

        self.btn_dl_thumb = QPushButton(" TẢI THUMBNAIL")
        self.btn_dl_thumb.setIcon(get_lucide_icon("image", "#ffffff", 14))
        self.btn_dl_thumb.setStyleSheet("background:#7c3aed; color:white; font-weight:bold; font-size:11px; padding:5px 12px;")
        self.btn_dl_thumb.clicked.connect(self.download_selected_thumbnails)
        float_layout.addWidget(self.btn_dl_thumb)

        self.floating_panel.setVisible(False)

        # Log Console Panel
        self.log_panel = QFrame()
        self.log_panel.setObjectName("logPanel")
        self.log_panel.setStyleSheet("QFrame#logPanel { background-color: #08080c; border-top: 1px solid #22222e; }")
        log_vbox = QVBoxLayout(self.log_panel)
        log_vbox.setContentsMargins(8, 4, 8, 4)
        log_vbox.setSpacing(4)

        log_head = QHBoxLayout()
        lbl_log_icon = QLabel()
        lbl_log_icon.setPixmap(get_lucide_pixmap("terminal", "#00E5FF", 14))
        log_head.addWidget(lbl_log_icon)
        lbl_log = QLabel("Nhật Ký Hoạt Động (Live Terminal Logs)")
        lbl_log.setStyleSheet("color:#00E5FF;font-weight:bold;font-size:11px;")
        log_head.addWidget(lbl_log)
        log_head.addStretch(1)

        btn_copy_log = QPushButton(" Copy")
        btn_copy_log.setIcon(get_lucide_icon("layers", "#cccccc", 12))
        btn_copy_log.setFixedSize(78, 24)
        btn_copy_log.setStyleSheet("font-size:10px;background:#1a1a24;color:#ccc;border-radius:3px;")
        btn_copy_log.clicked.connect(self.copy_logs)
        log_head.addWidget(btn_copy_log)

        btn_clear_log = QPushButton(" Xóa")
        btn_clear_log.setIcon(get_lucide_icon("trash-2", "#cccccc", 12))
        btn_clear_log.setFixedSize(72, 24)
        btn_clear_log.setStyleSheet("font-size:10px;background:#1a1a24;color:#ccc;border-radius:3px;")
        btn_clear_log.clicked.connect(lambda: self.log_edit.clear())
        log_head.addWidget(btn_clear_log)

        self.btn_toggle_log = QPushButton(" Ẩn Log")
        self.btn_toggle_log.setIcon(get_lucide_icon("chevron-down", "#ffffff", 12))
        self.btn_toggle_log.setFixedSize(85, 24)
        self.btn_toggle_log.setStyleSheet("font-size:10px;background:#0284c7;color:white;font-weight:bold;border-radius:3px;")
        self.btn_toggle_log.clicked.connect(self.toggle_log_panel)
        log_head.addWidget(self.btn_toggle_log)

        log_vbox.addLayout(log_head)

        self.log_edit = QTextEdit()
        self.log_edit.setReadOnly(True)
        self.log_edit.setFixedHeight(140)
        self.log_edit.setStyleSheet("""
            QTextEdit {
                background-color: #060609;
                color: #e2e8f0;
                font-family: 'Consolas', 'Segoe UI', monospace;
                font-size: 11px;
                border: 1px solid #1a1a26;
                border-radius: 4px;
                padding: 4px 6px;
            }
            QScrollBar:vertical {
                width: 6px;
                background: #060609;
                border-radius: 3px;
            }
            QScrollBar::handle:vertical {
                background: #252538;
                border-radius: 3px;
            }
            QScrollBar::handle:vertical:hover {
                background: #00E5FF;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0px;
            }
        """)
        log_vbox.addWidget(self.log_edit)

        left_vbox.addWidget(self.log_panel)
        splitter.addWidget(self.left_box)

        # Panel điều khiển bên phải (có QScrollArea & Custom 6px ScrollBar chống khuất chữ)
        scroll_panel = QScrollArea()
        scroll_panel.setWidgetResizable(True)
        scroll_panel.setFrameShape(QFrame.Shape.NoFrame)
        scroll_panel.setMinimumWidth(285)
        scroll_panel.setMaximumWidth(340)
        scroll_panel.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll_panel.setStyleSheet("""
            QScrollArea { border: none; background: transparent; }
            QScrollBar:vertical { width: 6px; background: #0c0c0e; border-radius: 3px; }
            QScrollBar::handle:vertical { background: #2a2a36; border-radius: 3px; }
            QScrollBar::handle:vertical:hover { background: #00E5FF; }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0px; }
        """)

        panel = QFrame()
        panel.setObjectName("controlPanel")
        pv = QVBoxLayout(panel)
        pv.setContentsMargins(10, 10, 10, 10)
        pv.setSpacing(8)

        # 1. KHU VỰC THAO TÁC CHÍNH (HERO ACTION ZONE)
        self.lbl_count = QLabel("Đã chọn: 0/0")
        self.lbl_count.setStyleSheet("color:#00E5FF;font-weight:bold;font-size:12px;")
        pv.addWidget(self.lbl_count)

        self.btn_dl_all = QPushButton(" Tải Tất Cả")
        self.btn_dl_all.setIcon(get_lucide_icon("download", "#ffffff", 16))
        self.btn_dl_all.setIconSize(QSize(16, 16))
        self.btn_dl_all.clicked.connect(self.download_all)
        self.btn_dl_all.setFixedHeight(38)
        self.btn_dl_all.setStyleSheet("""
            QPushButton { background:#00C853; color:white; font-weight:bold; font-size:12px; border-radius:5px; padding:2px 6px; }
            QPushButton:disabled { background:#1b432c; color:#66a57f; }
        """)
        pv.addWidget(self.btn_dl_all)

        self.btn_dl_all_thumb = QPushButton(" Tải Thumbnail Tất Cả")
        self.btn_dl_all_thumb.setIcon(get_lucide_icon("image", "#ffffff", 14))
        self.btn_dl_all_thumb.setStyleSheet("background:#6366f1;color:white;font-weight:bold;font-size:11px;border-radius:4px;padding:4px 6px;")
        self.btn_dl_all_thumb.clicked.connect(self.download_all_thumbnails)
        pv.addWidget(self.btn_dl_all_thumb)

        self.btn_retry = QPushButton(" Thử lại file lỗi")
        self.btn_retry.setIcon(get_lucide_icon("rotate-cw", "#ffffff", 16))
        self.btn_retry.setStyleSheet("background:#334155;color:white;font-weight:bold;")
        self.btn_retry.clicked.connect(self.retry_errors)
        pv.addWidget(self.btn_retry)

        line1 = QFrame()
        line1.setFrameShape(QFrame.Shape.HLine)
        line1.setStyleSheet("color:#333333;")
        pv.addWidget(line1)

        # 2. CẤU HÌNH BĂNG THÔNG & AV1 SMART TRICK
        self.advanced_group = QGroupBox("Cài đặt nâng cao")
        self.advanced_group.setCheckable(True)
        self.advanced_group.setChecked(False) # Collapsed by default
        self.advanced_group.setStyleSheet("""
            QGroupBox { font-weight: bold; color: #00E5FF; border: 1px solid #333333; border-radius: 5px; margin-top: 10px; padding-top: 15px; }
            QGroupBox::title { subcontrol-origin: margin; subcontrol-position: top left; padding: 0 3px; left: 10px; }
            QGroupBox::indicator { width: 13px; height: 13px; }
        """)
        
        adv_layout = QVBoxLayout()
        adv_layout.setContentsMargins(5, 5, 5, 5)
        
        # 1. Bilibili song song (Cố định 1 để chống quét bot)
        par_bili = QHBoxLayout()
        par_bili.setSpacing(6)
        ic_bili = QLabel()
        ic_bili.setPixmap(get_lucide_pixmap("shield-check", "#00E676", 14))
        par_bili.addWidget(ic_bili)
        
        lbl_bili_tag = QLabel("Bilibili (Cố định Anti-Bot):")
        lbl_bili_tag.setToolTip("Cố định 1 video tại một thời điểm để tránh bị Bilibili quét bot và ngắt kết nối CDN.")
        lbl_bili_tag.setStyleSheet("color: #00E676; font-size: 11px; font-weight: 600;")
        par_bili.addWidget(lbl_bili_tag)
        par_bili.addStretch()
        
        self.bilibili_parallel_sb = QSpinBox()
        self.bilibili_parallel_sb.setRange(1, 1)
        self.bilibili_parallel_sb.setValue(1)
        self.bilibili_parallel_sb.setEnabled(False)
        self.bilibili_parallel_sb.setFixedWidth(75)
        self.bilibili_parallel_sb.setToolTip("Cố định 1 video tại một thời điểm để tránh bị Bilibili quét bot và ngắt kết nối CDN.")
        self.bilibili_parallel_sb.setStyleSheet("""
            QSpinBox {
                background: #181824;
                color: #00E676;
                border: 1px solid #2d3748;
                border-radius: 4px;
                padding: 2px 4px;
                font-weight: bold;
                font-size: 11px;
            }
        """)
        par_bili.addWidget(self.bilibili_parallel_sb)
        adv_layout.addLayout(par_bili)

        # 2. Douyin / Khác song song (Tùy chỉnh đa nhiệm tự do)
        par_douyin = QHBoxLayout()
        par_douyin.setSpacing(6)
        ic_dy = QLabel()
        ic_dy.setPixmap(get_lucide_pixmap("zap", "#00E5FF", 14))
        par_douyin.addWidget(ic_dy)
        
        lbl_dy_tag = QLabel("Douyin / YT:")
        lbl_dy_tag.setToolTip("Số video Douyin/YouTube/TikTok tải song song cùng lúc (Khuyên dùng: 2-3 video).")
        lbl_dy_tag.setStyleSheet("color: #e2e8f0; font-size: 11px; font-weight: 500;")
        par_douyin.addWidget(lbl_dy_tag)
        par_douyin.addStretch()
        
        self.parallel_sb = QSpinBox()
        self.parallel_sb.setRange(1, MAX_PARALLEL)
        self.parallel_sb.setValue(DEFAULT_PARALLEL)
        self.parallel_sb.setFixedWidth(75)
        self.parallel_sb.setToolTip("Số video Douyin/YouTube/TikTok tải song song cùng lúc (Khuyên dùng: 2-3 video).")
        self.parallel_sb.setStyleSheet("""
            QSpinBox {
                background: #181824;
                color: #00E5FF;
                border: 1px solid #2d3748;
                border-radius: 4px;
                padding: 2px 4px;
                font-weight: bold;
                font-size: 11px;
            }
        """)
        par_douyin.addWidget(self.parallel_sb)
        adv_layout.addLayout(par_douyin)

        thr = QHBoxLayout()
        thr.addWidget(QLabel("Luồng/Video:"))
        self.threads_sb = QSpinBox()
        self.threads_sb.setRange(1, 32)
        self.threads_sb.setValue(DEFAULT_THREADS)
        self.threads_sb.setToolTip("Số luồng tải Range song song cho 1 video. Khuyên dùng 4 luồng để tránh bị CDN Bilibili ngắt kết nối.")
        thr.addWidget(self.threads_sb)
        adv_layout.addLayout(thr)

        chk_lay = QHBoxLayout()
        chk_lay.addWidget(QLabel("Chunking:"))
        self.chunk_cb = QComboBox()
        self.chunk_cb.addItems(["Tự động (10MB)", "Tắt Chunking (Đơn luồng)", "Nhỏ (2MB)", "Vừa (5MB)", "Lớn (20MB)"])
        chk_lay.addWidget(self.chunk_cb)
        adv_layout.addLayout(chk_lay)

        self.chk_av1_trick = QCheckBox("AV1 Smart (Tải nhẹ / Dự phòng)")
        self.chk_av1_trick.setChecked(False)
        self.chk_av1_trick.setToolTip("Mặc định tắt để ưu tiên video chất lượng gốc siêu nét (H.264 / HEVC VIP). AV1 sẽ tự động kích hoạt làm Fallback khi luồng VIP gặp sự cố.")
        adv_layout.addWidget(self.chk_av1_trick)

        self.chk_skip = QCheckBox(" Bỏ qua file đã có")
        self.chk_skip.setChecked(True)
        adv_layout.addWidget(self.chk_skip)

        # Wrap in a widget to allow hiding
        self.adv_container = QWidget()
        self.adv_container.setLayout(adv_layout)
        
        grp_layout = QVBoxLayout(self.advanced_group)
        grp_layout.addWidget(self.adv_container)
        
        self.advanced_group.toggled.connect(self.adv_container.setVisible)
        self.adv_container.setVisible(False)
        
        pv.addWidget(self.advanced_group)

        line2 = QFrame()
        line2.setFrameShape(QFrame.Shape.HLine)
        line2.setStyleSheet("color:#333333;")
        pv.addWidget(line2)

        # 3. QUẢN LÝ THƯ MỤC & SỬA HÀNG LOẠT
        pv.addWidget(QLabel("<b>Tìm Kiếm & Lưu Trữ</b>"))
        self.search_inp = QLineEdit()
        self.search_inp.setPlaceholderText("Tìm theo tiêu đề...")
        self.search_inp.textChanged.connect(lambda t: self.proxy.set_filter(t))
        pv.addWidget(self.search_inp)

        btn_folder = QPushButton(" Chọn thư mục lưu")
        btn_folder.setIcon(get_lucide_icon("folder", "#ffffff", 16))
        btn_folder.clicked.connect(self.select_folder)
        pv.addWidget(btn_folder)

        btn_open = QPushButton(" Mở thư mục")
        btn_open.setIcon(get_lucide_icon("folder-open", "#ffffff", 16))
        btn_open.clicked.connect(self.open_folder)
        pv.addWidget(btn_open)

        pv.addStretch(1)

        row = QHBoxLayout()
        btn_all = QPushButton(" Chọn hết")
        btn_all.setIcon(get_lucide_icon("check-circle-2", "#00E5FF", 14))
        btn_all.clicked.connect(lambda: self.toggle_all(True))
        row.addWidget(btn_all)
        btn_none = QPushButton(" Bỏ chọn")
        btn_none.setIcon(get_lucide_icon("x-circle", "#B0BEC5", 14))
        btn_none.clicked.connect(lambda: self.toggle_all(False))
        row.addWidget(btn_none)
        pv.addLayout(row)

        btn_clear = QPushButton(" Xóa sạch")
        btn_clear.setIcon(get_lucide_icon("trash-2", "#ffffff", 16))
        btn_clear.setStyleSheet("background:#b71c1c;color:white;font-weight:bold;")
        btn_clear.clicked.connect(self.clear_all)
        pv.addWidget(btn_clear)

        scroll_panel.setWidget(panel)
        splitter.addWidget(scroll_panel)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 0)
        splitter.setSizes([1120, 295])
        vbox.addWidget(splitter, 1)

        # ---------- Status bar: Đường dẫn thư mục + Live Log + Bản quyền + Hướng dẫn ----------
        self.lbl_path = QLabel(f"  Thư mục lưu: {self.save_folder}")
        self.lbl_path.setStyleSheet("color:#00E5FF;font-weight:bold;font-size:11px;")
        self.lbl_path.setToolTip("Click đúp để mở thư mục lưu.")
        self.lbl_path.mouseDoubleClickEvent = lambda e: self.open_folder()
        self.statusBar().addWidget(self.lbl_path)

        self.btn_license_bar = QPushButton(" Bản quyền")
        self.btn_license_bar.setIcon(get_lucide_icon("shield-check", "#00E676", 14))
        self.btn_license_bar.setStyleSheet("background:#1a1a24;color:#00E676;font-weight:bold;")
        self.btn_license_bar.setToolTip("Xem thông tin bản quyền hoặc kích hoạt License Key mới.")
        self.btn_license_bar.clicked.connect(self.show_license_dialog)
        self.statusBar().addPermanentWidget(self.btn_license_bar)
        self.update_license_display()

        self.btn_log_bar = QPushButton(" Live Logs")
        self.btn_log_bar.setIcon(get_lucide_icon("terminal", "#00E5FF", 14))
        self.btn_log_bar.setStyleSheet("background:#1a1a24;color:#00E5FF;font-weight:bold;")
        self.btn_log_bar.clicked.connect(self.toggle_log_panel)
        self.statusBar().addPermanentWidget(self.btn_log_bar)

        self.btn_help = QPushButton(" Hướng dẫn")
        self.btn_help.setIcon(get_lucide_icon("help-circle", "#ffffff", 14))
        self.btn_help.setFixedWidth(115)
        self.btn_help.clicked.connect(lambda: HelpDialog(self).exec())
        self.statusBar().addPermanentWidget(self.btn_help)

    def update_license_display(self):
        info = self.license_info or get_license_info()
        if info.get("is_lifetime"):
            self.btn_license_bar.setText(" Bản quyền: Vĩnh viễn")
            self.btn_license_bar.setStyleSheet("background:#1a1a24;color:#00E676;font-weight:bold;")
            self.btn_license_bar.setIcon(get_lucide_icon("shield-check", "#00E676", 14))
        elif info.get("days_left") is not None and info.get("days_left") >= 0:
            days = info["days_left"]
            self.btn_license_bar.setText(f" Bản quyền: {days} ngày")
            self.btn_license_bar.setStyleSheet("background:#1a1a24;color:#00E5FF;font-weight:bold;")
            self.btn_license_bar.setIcon(get_lucide_icon("shield-check", "#00E5FF", 14))
        else:
            self.btn_license_bar.setText(" Bản quyền: Hết hạn")
            self.btn_license_bar.setStyleSheet("background:#5c1010;color:#ff8080;font-weight:bold;")
            self.btn_license_bar.setIcon(get_lucide_icon("shield-check", "#ff8080", 14))

    def show_license_dialog(self):
        dlg = ActivationDialog(self)
        dlg.exec()
        is_valid, msg, info = check_current_machine_license()
        self.license_info = info
        self.update_license_display()

    def append_log(self, text):
        if not hasattr(self, "log_edit") or not text:
            return
        clean = clean_ansi(text).strip()
        if not clean:
            return

        ts = time.strftime("%H:%M:%S")
        escaped = html.escape(clean)

        # Tự động phát hiện phân loại log để gắn Badge & Màu sắc chuyên nghiệp
        u = clean.upper()
        if "[ERROR]" in u or "[DOWNLOAD ERROR]" in u or "EXCEPTION" in u or ("ERR" in u and "ERROR" in u):
            badge = '<span style="background:#5c1010; color:#ff8080; padding:1px 6px; border-radius:3px; font-weight:bold; font-size:10px;">ERROR</span>'
            msg_color = "#ff9999"
        elif "[WARNING]" in u or "[WARN]" in u or "[FALLBACK]" in u or "[RETRY" in u:
            badge = '<span style="background:#4d2c00; color:#ffc107; padding:1px 6px; border-radius:3px; font-weight:bold; font-size:10px;">WARN</span>'
            msg_color = "#ffe082"
        elif "SUCCESS" in u or "COMPLETED" in u or "[DONE]" in u or "THÀNH CÔNG" in u:
            badge = '<span style="background:#003d19; color:#00E676; padding:1px 6px; border-radius:3px; font-weight:bold; font-size:10px;">SUCCESS</span>'
            msg_color = "#b9f6ca"
        elif "[DOUYIN" in u:
            badge = '<span style="background:#3b1259; color:#e040fb; padding:1px 6px; border-radius:3px; font-weight:bold; font-size:10px;">DOUYIN</span>'
            msg_color = "#ea80fc"
        elif "[PATCH]" in u or "[BILIBILI" in u:
            badge = '<span style="background:#0d3356; color:#40c4ff; padding:1px 6px; border-radius:3px; font-weight:bold; font-size:10px;">BILIBILI</span>'
            msg_color = "#80d8ff"
        elif "[SCAN" in u:
            badge = '<span style="background:#003847; color:#00E5FF; padding:1px 6px; border-radius:3px; font-weight:bold; font-size:10px;">SCAN</span>'
            msg_color = "#84ffff"
        elif "[LUỒNG TẢI]" in u or "[TURBO]" in u or "[AV1" in u:
            badge = '<span style="background:#281047; color:#b388ff; padding:1px 6px; border-radius:3px; font-weight:bold; font-size:10px;">TURBO</span>'
            msg_color = "#d1c4e9"
        elif "[COOKIE" in u:
            badge = '<span style="background:#262359; color:#8c9eff; padding:1px 6px; border-radius:3px; font-weight:bold; font-size:10px;">COOKIE</span>'
            msg_color = "#c5cae9"
        elif "[DOWNLOAD]" in u or "[PROGRESS]" in u:
            badge = '<span style="background:#004033; color:#1de9b6; padding:1px 6px; border-radius:3px; font-weight:bold; font-size:10px;">DOWNLOAD</span>'
            msg_color = "#a7ffeb"
        else:
            badge = '<span style="background:#1c1c24; color:#90a4ae; padding:1px 6px; border-radius:3px; font-size:10px;">INFO</span>'
            msg_color = "#cfd8dc"

        line_html = f'<div style="margin:2px 0; line-height:16px;"><span style="color:#546e7a; font-size:10px; margin-right:4px;">[{ts}]</span> {badge} <span style="color:{msg_color}; font-family:\'Consolas\', \'Segoe UI\', monospace; font-size:11px;">{escaped}</span></div>'

        self.log_edit.append(line_html)
        sb = self.log_edit.verticalScrollBar()
        if sb:
            sb.setValue(sb.maximum())

    def copy_logs(self):
        if hasattr(self, "log_edit"):
            from PySide6.QtWidgets import QApplication
            QApplication.clipboard().setText(self.log_edit.toPlainText())

    def toggle_log_panel(self):
        if hasattr(self, "log_panel"):
            is_vis = self.log_panel.isVisible()
            self.log_panel.setVisible(not is_vis)
            if hasattr(self, "btn_toggle_log"):
                if is_vis:
                    self.btn_toggle_log.setText(" Hiện Log")
                    self.btn_toggle_log.setIcon(get_lucide_icon("chevron-up", "#ffffff", 12))
                else:
                    self.btn_toggle_log.setText(" Ẩn Log")
                    self.btn_toggle_log.setIcon(get_lucide_icon("chevron-down", "#ffffff", 12))

    def connect_signals(self):
        self.delegate.deleteRequested.connect(self.delete_item)
        self.delegate.retryRequested.connect(self.retry_single_item)
        self.delegate.formatSelectorRequested.connect(self.open_format_dialog)
        self.thumb_pool.thumb_ready.connect(self.on_thumb_ready)
        self.view.hoveredChanged.connect(self.on_hovered)
        sel = self.view.selectionModel()
        sel.selectionChanged.connect(lambda *_: self.update_count_label())
        self.model.rowsInserted.connect(lambda *_: self.update_count_label())
        self.model.rowsRemoved.connect(lambda *_: self.update_count_label())
        self.model.modelReset.connect(self.update_count_label)

    def open_format_dialog(self, uid):
        item = self.model.get(uid)
        if not item:
            return
        dialog = FormatSelectorDialog(item, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            selected_fmt = dialog.get_selected_format()
            print(f"[FORMAT SELECTOR] Đã chọn Format ID: {selected_fmt} cho video {uid}")
            self.model.set_field(uid, VideoRoles.FormatId, selected_fmt)
            self.model.set_field(uid, VideoRoles.Resolution, f"Custom ({selected_fmt})")
            self.view.viewport().update()

    def load_settings(self):
        saved_name = self.settings.value("browser_name", "")
        if saved_name:
            idx = self.browser_cb.findText(saved_name)
            if idx >= 0:
                self.browser_cb.setCurrentIndex(idx)
        else:
            # Migration từ bản cũ: index 3 trước đây là "Edge", index 2 là "Chrome"
            legacy_idx = self.settings.value("browser_idx", 0, type=int)
            legacy_map = {0: "Auto (Tự tìm)", 1: "None", 2: "Chrome", 3: "Edge", 4: "Firefox"}
            target_text = legacy_map.get(legacy_idx, "Auto (Tự tìm)")
            idx = self.browser_cb.findText(target_text)
            if idx >= 0:
                self.browser_cb.setCurrentIndex(idx)
            else:
                self.browser_cb.setCurrentIndex(0)

        self.limit_sb.setValue(self.settings.value("limit", 10, type=int))
        self.parallel_sb.setValue(self.settings.value("parallel", DEFAULT_PARALLEL, type=int))
        self.chk_skip.setChecked(self.settings.value("skip", True, type=bool))
        self.last_cookies_dir = self.settings.value(
            "last_cookies_dir", os.path.join(os.path.expanduser("~"), "Downloads")
        )
        geo = self.settings.value("geometry")
        if geo:
            self.restoreGeometry(geo)

    def save_settings(self):
        self.settings.setValue("folder", self.save_folder)
        self.settings.setValue("browser_name", self.browser_cb.currentText())
        self.settings.setValue("browser_idx", self.browser_cb.currentIndex())
        self.settings.setValue("limit", self.limit_sb.value())
        self.settings.setValue("parallel", self.parallel_sb.value())
        self.settings.setValue("skip", self.chk_skip.isChecked())
        if hasattr(self, "last_cookies_dir") and self.last_cookies_dir:
            self.settings.setValue("last_cookies_dir", self.last_cookies_dir)
        self.settings.setValue("geometry", self.saveGeometry())

    def setup_shortcuts(self):
        QShortcut(QKeySequence.StandardKey.Delete, self, self.remove_selected)
        QShortcut(QKeySequence("Ctrl+A"), self, lambda: self.toggle_all(True))
        QShortcut(QKeySequence("Ctrl+D"), self, lambda: self.toggle_all(False))
        QShortcut(QKeySequence("Ctrl+F"), self, self.search_inp.setFocus)
        QShortcut(QKeySequence("Esc"), self, self.stop_download)

    # ---------------------------------------------------------------
    # Scan
    def start_scan(self, custom_urls=None):
        if custom_urls and isinstance(custom_urls, (list, tuple, set)):
            urls = list(custom_urls)
        else:
            raw_text = self.url_inp.text().strip()
            if not raw_text:
                return
            import re
            urls = re.findall(r'(https?://[^\s]+)', raw_text)
            if not urls:
                urls = [raw_text]
            else:
                # Trích xuất tiêu đề nếu người dùng dán cả đoạn chia sẻ Douyin/TikTok
                cand_title = re.sub(r'https?://[^\s]+', '', raw_text)
                cand_title = re.sub(r'^[0-9.]+\s+[A-Za-z0-9@.:/+\-_]+\s*', '', cand_title)
                cand_title = re.sub(r'复制此链接.*$', '', cand_title).strip()
                if len(cand_title) >= 3 and urls[0] not in self._custom_metadata:
                    self._custom_metadata[urls[0]] = {"title": cand_title, "thumb": ""}

        if self._scanning:
            print(f"[SCAN QUEUE] Đang quét, đã thêm {len(urls)} link mới vào hàng đợi quét...")
            for u in urls:
                self._scan_queue.append(u)
            self.status_label.setText(f"Đã thêm {len(urls)} link vào hàng đợi quét...")
            return

        self.url_inp.setText(urls[0] if len(urls) == 1 else f"Đang quét {len(urls)} link...")
        self._scanning = True
        self.scan_btn.setEnabled(False)
        self.scan_btn.setText("Đang quét...")

        br = self.browser_cb.currentText()
        br = "Auto" if "Auto" in br else br

        from collections import deque
        self._scan_queue = deque(urls)
        self._scan_next(br)

    def _scan_next(self, br):
        if not self._scan_queue:
            self.on_scan_done("Quét xong!")
            return
        url = self._scan_queue.popleft()
        self.status_label.setText(f"Đang quét: {url[:30]}...")
        self.scan_worker = ScanWorker(url, 0, self.limit_sb.value(), br, parent=self)
        self.scan_worker.found_item.connect(self.add_item)
        self.scan_worker.finished.connect(lambda msg: self._scan_next(br))
        self.scan_worker.error.connect(lambda err: self._on_scan_item_error(err, br))
        self.scan_worker.start()

    def _on_scan_item_error(self, err, br):
        print(f"[SCAN ERROR] Lỗi quét: {err}")
        self._scan_next(br)

    def add_item(self, t, u, th, heights, formats_list=None):
        # Tự động thay thế bằng tiêu đề và thumbnail thật nếu có từ Extension hoặc Clipboard
        if hasattr(self, "_custom_metadata"):
            meta = self._custom_metadata.get(u)
            if not meta:
                for k, v in self._custom_metadata.items():
                    if (k and k in u) or (u and u in k):
                        meta = v
                        break
            if meta:
                if meta.get("title"):
                    t = meta["title"]
                if meta.get("thumb"):
                    th = meta["thumb"]

        uid = self.model.add_video(
            {
                "title": t,
                "url": u,
                "thumb_url": th,
                "heights": heights,
                "formats_list": formats_list or [],
            }
        )
        if th:
            self.thumb_pool.request(uid, th)

    def on_thumb_ready(self, uid, pixmap):
        self.model.set_thumb(uid, pixmap)

    def on_scan_done(self, msg):
        self._scanning = False
        self.scan_btn.setEnabled(True)
        self.scan_btn.setText(" Quét")
        self.status_label.setText(msg)
        self.save_session_now()

    def on_scan_error(self, e):
        self._scanning = False
        self.scan_btn.setEnabled(True)
        self.scan_btn.setText(" Quét")
        self.status_label.setText("Lỗi quét")
        QMessageBox.warning(self, "Lỗi", e)

    def on_hovered(self, uid):
        old = self.delegate.hover_uid
        self.delegate.hover_uid = uid or None
        for u in (old, self.delegate.hover_uid):
            if not u:
                continue
            idx = self.model.index_for_uid(u)
            if idx.isValid():
                self.model.dataChanged.emit(idx, idx, [])

    # ---------------------------------------------------------------
    # Selection helpers
    def _selected_uids(self):
        sm = self.view.selectionModel()
        return [
            self.proxy.data(self.proxy.index(i, 0), VideoRoles.Uid)
            for i in range(self.proxy.rowCount())
            if sm.isSelected(self.proxy.index(i, 0))
        ]

    def reposition_floating_panel(self):
        if not hasattr(self, "floating_panel") or not hasattr(self, "view"):
            return
        if not self.floating_panel.isVisible():
            return
        self.floating_panel.adjustSize()
        pw = self.floating_panel.width()
        ph = self.floating_panel.height()
        vw = self.view.width()
        vh = self.view.height()
        x = max(10, (vw - pw) // 2)
        y = max(10, vh - ph - 20)
        self.floating_panel.move(x, y)
        self.floating_panel.raise_()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.reposition_floating_panel()

    def update_count_label(self):
        total = self.proxy.rowCount()
        sel = len(self.view.selectionModel().selectedIndexes())
        self.lbl_count.setText(f"Đã chọn: {sel}/{total}")
        if hasattr(self, "lbl_float_count"):
            self.lbl_float_count.setText(f"Đã chọn: <b>{sel}</b>")
        if hasattr(self, "btn_dl_selected"):
            self.btn_dl_selected.setText(f" TẢI ĐÃ CHỌN ({sel})" if sel > 0 else " TẢI ĐÃ CHỌN")
        if hasattr(self, "btn_dl_all"):
            self.btn_dl_all.setText(f" Tải Tất Cả ({total})" if total > 0 else " Tải Tất Cả")
        if hasattr(self, "floating_panel"):
            if sel > 0:
                self.floating_panel.show()
                self.reposition_floating_panel()
            else:
                self.floating_panel.hide()

    def toggle_all(self, state):
        sm = self.view.selectionModel()
        if not state:
            sm.clearSelection()
            return
        if self.proxy.rowCount() == 0:
            return
        sel = QItemSelection(
            self.proxy.index(0, 0),
            self.proxy.index(self.proxy.rowCount() - 1, 0),
        )
        sm.select(sel, sm.SelectionFlag.ClearAndSelect)

    # ---------------------------------------------------------------
    # Item ops
    def delete_item(self, uid):
        if self._is_downloading and uid in self._active:
            return
        self.model.remove_uid(uid)
        self.thumb_pool.cancel(uid)
        self.save_session_now()

    def remove_selected(self):
        if self._is_downloading:
            QMessageBox.warning(self, "Cảnh báo", "Vui lòng đợi tải xong.")
            return
        uids = self._selected_uids()
        if not uids:
            return
        self.model.remove_uids(uids)
        for u in uids:
            self.thumb_pool.cancel(u)
        self.view.selectionModel().clearSelection()
        self.save_session_now()

    def clear_all(self):
        if self._is_downloading:
            QMessageBox.warning(self, "Cảnh báo", "Vui lòng đợi tải xong.")
            return
        self.model.clear()
        self.thumb_pool.reset()
        self.save_session_now()

    def apply_bulk_changes(self):
        sel_type = self.bulk_type_cb.currentText()
        sel_res = self.bulk_res_cb.currentText()
        sel_bitrate = self.bulk_bitrate_cb.currentText()
        sel_codec = self.bulk_codec_cb.currentText()
        for uid in self._selected_uids():
            self.model.set_field(uid, VideoRoles.Type, sel_type)
            if sel_type == "mp4":
                self.model.set_field(uid, VideoRoles.Resolution, sel_res)
                self.model.set_field(uid, VideoRoles.Codec, sel_codec)
            elif sel_type == "mp3":
                self.model.set_field(uid, VideoRoles.Bitrate, sel_bitrate)
        self.save_session_now()

    # ---------------------------------------------------------------
    # Download queue
    def _build_options(self, item):
        use_av1 = self.chk_av1_trick.isChecked() or item.get("av1_auto_fallback", False)
        base = {
            "output_path": self.save_folder,
            "browser": self.browser_cb.currentText(),
            "available_heights": list(item.get("heights") or []),
            "skip_existing": self.chk_skip.isChecked(),
            "num_threads": self.threads_sb.value(),
            "chunk_mode": self.chunk_cb.currentText(),
            "av1_smart_trick": use_av1,
            "format_id": item.get("format_id"),
            "title": item.get("title", ""),
        }
        if use_av1 and item.get("type", "mp4") != "mp3":
            base.update({"file_type": "av1"})
        else:
            file_type = item.get("type", "mp4")
            if file_type == "mp3":
                base.update({"file_type": "mp3", "bitrate": item.get("bitrate", "320")})
            elif file_type == "mp4":
                base.update(
                    {
                        "file_type": "mp4",
                        "resolution": item.get("resolution", "best"),
                        "codec": item.get("codec", "H.264"),
                    }
                )
            else:
                base.update({"file_type": "av1"})
        return base

    def download_all(self):
        uids = list(self.model.uids())
        if not uids:
            QMessageBox.warning(self, "Cảnh báo", "Danh sách đang trống, hãy quét video trước!")
            return
        print(f"[DOWNLOAD ALL] Bắt đầu tải TẤT CẢ {len(uids)} video trong danh sách...")
        self._start_queue(uids)

    def download_selected(self):
        uids = self._selected_uids()
        if not uids:
            QMessageBox.warning(self, "Cảnh báo", "Hãy chọn ít nhất 1 video để tải (bấm chọn thẻ card hoặc bấm 'Chọn hết').")
            return
        print(f"[DOWNLOAD SELECTED] Bắt đầu tải {len(uids)} video ĐÃ CHỌN...")
        self._start_queue(uids)

    def download_selected_thumbnails(self):
        uids = self._selected_uids()
        if not uids:
            QMessageBox.warning(self, "Cảnh báo", "Hãy chọn ít nhất 1 video để tải thumbnail!")
            return
        self.download_thumbnails(uids)

    def download_all_thumbnails(self):
        uids = list(self.model.uids())
        if not uids:
            QMessageBox.warning(self, "Cảnh báo", "Danh sách đang trống, hãy quét video trước!")
            return
        self.download_thumbnails(uids)

    def download_single_thumbnail(self, uid):
        if uid:
            self.download_thumbnails([uid])

    def download_thumbnails(self, uids):
        if not uids:
            return
        import threading
        import requests
        from site_utils import detect_site

        out_dir = self.save_folder or os.path.join(os.getcwd(), "downloads")
        os.makedirs(out_dir, exist_ok=True)
        self.status_label.setText(f"Đang tải {len(uids)} thumbnail...")

        def _run_bg():
            saved_count = 0
            for uid in uids:
                item = self.model.get(uid)
                if not item:
                    continue
                title = item.get("title", f"thumb_{uid}")
                safe_title = "".join(c for c in title if c not in r'\/:*?"<>|').strip()[:80]
                target_path = os.path.join(out_dir, f"{safe_title}_thumb.jpg")

                thumb_url = item.get("thumb_url")
                success = False
                if thumb_url:
                    try:
                        headers = detect_site(item.get("url", ""))
                        r = requests.get(thumb_url, headers=headers, timeout=10)
                        if r.status_code == 200 and len(r.content) > 1000:
                            with open(target_path, "wb") as f:
                                f.write(r.content)
                            success = True
                    except Exception as e:
                        print(f"[THUMBNAIL ERROR] Không tải được URL {thumb_url}: {e}")

                if not success:
                    pixmap = item.get("thumb")
                    if pixmap and not pixmap.isNull():
                        try:
                            pixmap.save(target_path, "JPG", 95)
                            success = True
                        except Exception:
                            pass

                if success:
                    saved_count += 1
                    print(f"[THUMBNAIL] Đã lưu thành công: {target_path}")

            msg = f"Đã lưu {saved_count}/{len(uids)} ảnh thumbnail vào thư mục tải về!"
            print(f"[THUMBNAIL HOÀN TẤT] {msg}")
            QTimer.singleShot(0, lambda: self.status_label.setText(msg))

        threading.Thread(target=_run_bg, daemon=True).start()

    def show_context_menu(self, pos):
        index = self.view.indexAt(pos)
        if not index.isValid():
            return
        source_index = self.proxy.mapToSource(index)
        row = source_index.row()
        item = self.model._items[row] if 0 <= row < len(self.model._items) else None
        if not item:
            return
        uid = item.get("uid")

        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu {
                background-color: #1a1a26;
                color: #e2e8f0;
                border: 1px solid #383854;
                border-radius: 6px;
                padding: 4px;
            }
            QMenu::item {
                padding: 6px 20px 6px 24px;
                border-radius: 4px;
            }
            QMenu::item:selected {
                background-color: #0284c7;
                color: #ffffff;
            }
        """)

        act_thumb = QAction(get_lucide_icon("image", "#a78bfa", 14), " Tải ảnh Thumbnail video này", self)
        act_thumb.triggered.connect(lambda: self.download_single_thumbnail(uid))
        menu.addAction(act_thumb)

        act_dl = QAction(get_lucide_icon("download", "#38bdf8", 14), " Tải video này", self)
        act_dl.triggered.connect(lambda: self._start_queue([uid]))
        menu.addAction(act_dl)

        act_retry = QAction(get_lucide_icon("rotate-cw", "#facc15", 14), " Thử lại video này", self)
        act_retry.triggered.connect(lambda: self.retry_single_item(uid))
        menu.addAction(act_retry)

        menu.addSeparator()

        act_del = QAction(get_lucide_icon("trash-2", "#f87171", 14), " Xóa khỏi danh sách", self)
        act_del.triggered.connect(lambda: self.delete_item(uid))
        menu.addAction(act_del)

        menu.exec(self.view.viewport().mapToGlobal(pos))

    def retry_errors(self):
        uids = [
            uid
            for uid in self.model.uids()
            if self.model.get(uid)["status"] in ("error", "stopped")
        ]
        if not uids:
            return
        self._start_queue(uids)

    def _start_queue(self, uids):
        if self._is_downloading:
            # Vừa add vừa tải: Thêm các video mới vào hàng đợi đang chạy
            added = 0
            for uid in uids:
                if uid not in self._pending_uids and uid not in self._active:
                    item = self.model.get(uid)
                    if item and item.get("status") not in ("completed", "downloading"):
                        self.model.set_status(uid, "queued")
                        self.model.set_progress(uid, 0)
                        self._pending_uids.append(uid)
                        added += 1
            if added > 0:
                print(f"[QUEUE UPDATE] Đã thêm {added} video mới vào hàng đợi đang tải...")
                self.status_label.setText(f"Đã thêm {added} video vào hàng đợi")
                self._pump_queue()
            return

        self._is_downloading = True
        self._stop_requested = False
        self._completed_ok = 0
        self.btn_stop.setEnabled(True)
        self.status_label.setText("Bắt đầu tải...")
        self._pending_uids = deque()
        for uid in uids:
            item = self.model.get(uid)
            if item is None:
                continue
            self.model.set_status(uid, "queued")
            self.model.set_progress(uid, 0)
            self._pending_uids.append(uid)
        self._pump_queue()

    def _pump_queue(self):
        if self._stop_requested:
            return

        # Bộ điều phối thông minh theo nền tảng (Adaptive Platform Dispatcher) kết hợp Staggered Launch
        if len(self._active) < self.parallel_sb.value() and self._pending_uids:
            active_bili_count = sum(
                1 for u in self._active
                if is_bilibili_url((self.model.get(u) or {}).get("url", ""))
            )
            selected_uid = None
            for u in self._pending_uids:
                u_item = self.model.get(u)
                u_url = (u_item or {}).get("url", "")
                if is_bilibili_url(u_url) and active_bili_count >= 1:
                    continue
                selected_uid = u
                break

            if selected_uid is not None:
                self._pending_uids.remove(selected_uid)
                uid = selected_uid
                item = self.model.get(uid)
                if item is not None:
                    is_bili = is_bilibili_url(item.get("url", ""))
                    print(f"[DISPATCHER] Kích hoạt video ({'Bilibili 1 luồng ưu tiên' if is_bili else 'Đa luồng song song'}): {item.get('title', '')[:40]}")
                    self.model.set_status(uid, "downloading")
                    self.model.set_progress(uid, 0)
                    worker = DownloadWorker(item["url"], self._build_options(item), parent=self)
                    worker.task_progress.connect(lambda p, u=uid: self.model.set_progress(u, p))
                    worker.status_update.connect(lambda s, u=uid: self._on_status_update(u, s))
                    worker.task_finished.connect(lambda u=uid: self._on_worker_done(u))
                    worker.task_error.connect(lambda e, u=uid: self._on_worker_error(u, e))
                    worker.task_stopped.connect(lambda u=uid: self._on_worker_stopped(u))
                    worker.cookie_refresh_requested.connect(self._on_worker_request_cookies)
                    worker.finished.connect(worker.deleteLater)
                    self._active[uid] = worker
                    worker.start()

                    # Nếu vẫn còn slot trống và còn video chờ: kích hoạt lượt tiếp theo so le sau 1.5s
                    if len(self._active) < self.parallel_sb.value() and self._pending_uids:
                        print("[STAGGERED LAUNCH] Giãn cách 1.5s khởi động video tiếp theo để chống CDN ngắt kết nối...")
                        QTimer.singleShot(1500, self._pump_queue)
                        return

        if not self._active and not self._pending_uids:
            self._finish_queue()

    RETRY_DELAYS = [1, 3, 5, 10, 30, 60]

    def retry_single_item(self, uid):
        item = self.model.get(uid)
        if not item:
            return
        print(f"[RETRY] Bấm nút thử lại thủ công cho video {uid}...")
        self._retry_counts[uid] = 0
        self.model.set_status(uid, "queued", "TH:16|TIME:00:00:00|DL:Đang khởi động...|SPD:Thử lại...|ETA:Bắt đầu")
        self.model.set_progress(uid, 0)
        self.view.viewport().update()
        if uid not in self._pending_uids and uid not in self._active:
            self._pending_uids.append(uid)
        if not self._is_downloading:
            self._start_queue([uid])
        else:
            self._pump_queue()

    def _requeue_failed_item(self, uid):
        if uid not in self._pending_uids and uid not in self._active:
            self._pending_uids.append(uid)  # ĐẨY XUỐNG CUỐI HÀNG ĐỢI (Round-robin)
        self._pump_queue()

    def _on_status_update(self, uid, msg):
        self.status_label.setText(msg)
        self.model.set_status(uid, "downloading", msg)
        self.view.viewport().update()

    def _cleanup_part_files(self, uid=None):
        try:
            import glob
            out_dir = self.save_folder or os.path.join(os.getcwd(), "downloads")
            if not os.path.exists(out_dir):
                return

            title = ""
            if uid:
                item = self.model.get(uid)
                if item:
                    title = item.get("title", "")
            
            safe_title = "".join(c for c in title if c not in r'\/:*?"<>|').strip()[:40]
            cleaned = 0

            for pattern in ("*.part", "*.ytdl", "*.part-Frag*", "*.temp"):
                for pf in glob.glob(os.path.join(out_dir, pattern)):
                    try:
                        fname = os.path.basename(pf)
                        # Bỏ đuôi .part / .ytdl để tìm file video hoàn thành tương ứng
                        base_target = pf[:-5] if pf.endswith((".part", ".ytdl")) else pf
                        is_target_ready = os.path.exists(base_target) and os.path.getsize(base_target) > 1024
                        
                        # Điều kiện xóa:
                        # 1. Đã có file video hoàn chỉnh tương ứng
                        # 2. Hoặc video cụ thể này đã xong (uid match title)
                        if is_target_ready or (safe_title and safe_title.lower() in fname.lower()):
                            os.remove(pf)
                            cleaned += 1
                            print(f"[DỌN DẸP] Đã dọn file tạm rác: {fname}")
                    except OSError:
                        pass
            if cleaned > 0:
                print(f"[DỌN DẸP HOÀN TẤT] Đã dọn {cleaned} file .part dở dang sau khi hoàn thành!")
        except Exception as e:
            print(f"[DỌN DẸP LỖI] {e}")

    def _on_worker_done(self, uid):
        self._active.pop(uid, None)
        self._completed_ok += 1
        self.model.set_status(uid, "done")
        self.model.set_progress(uid, 100)
        self.view.viewport().update()

        # Dọn dẹp file .part nếu video đó đã hoàn thành
        self._cleanup_part_files(uid)

        self._pump_queue()

    def _on_worker_error(self, uid, err):
        self._active.pop(uid, None)
        count = self._retry_counts.get(uid, 0) + 1
        self._retry_counts[uid] = count
        max_retries = 50  # Hỗ trợ tối đa 50 vòng retry cho video dài

        print(f"[ERROR] Lỗi tải video {uid}: {err}")

        # GIẢI PHÓNG VÀ KÍCH HOẠT NGAY TẬP TIẾP THEO trong hàng đợi!
        self._pump_queue()

        if count <= max_retries:
            delay_sec = min(15, 2 * min(count, 5))
            delay_text = f"{delay_sec}s"
            
            item = self.model.get(uid)
            if item:
                from site_utils import is_bilibili_url
                url = item.get("url", "")
                if is_bilibili_url(url) and any(k in str(err).lower() for k in ["702450", "412", "503", "cookie", "token", "remote end", "service unavailable", "bytes read"]):
                    self._on_worker_request_cookies("bilibili.com", f"retry_{count}")

            # Nếu sau 2 lần thử cookies gốc mà vẫn bị lỗi rớt CDN: Tự động đổi sang AV1 1080P
            if count >= 2 and item:
                from site_utils import is_bilibili_url
                if is_bilibili_url(item.get("url", "")) and not item.get("av1_auto_fallback"):
                    item["av1_auto_fallback"] = True
                    print(f"[AUTO-FALLBACK] Video {uid} đã thử cookies gốc {count-1} lần nhưng gặp lỗi CDN. Từ lần {count} sẽ tự động kích hoạt luồng 1080P AV1...")

            msg = f"TH:16|TIME:Tạm hoãn|DL:Thử lại {count}/{max_retries}|SPD:Cuối hàng đợi|ETA:Chờ lượt"
            print(f"[ROUND-ROBIN REQUEUE] Video {uid} gặp lỗi. Đã chuyển xuống CUỐI HÀNG ĐỢI (lần {count}/{max_retries}). Đang chạy tiếp các video khác...")
            self.model.set_status(uid, "queued", msg)
            self.model.set_progress(uid, 0)
            self.view.viewport().update()
            
            QTimer.singleShot(delay_sec * 1000, lambda u=uid: self._requeue_failed_item(u))
        else:
            item = self.model.get(uid)
            title = item.get("title", "Unknown") if item else "Unknown"
            err_msg = f"TH:16|TIME:Thất bại|DL:Lỗi {count} lần|SPD:Đã dừng|ETA:Bấm thử lại"
            self.model.set_status(uid, "error", err_msg)
            self.view.viewport().update()
            app_logger().error("Download error (%d retries failed) uid=%s: %s", max_retries, uid, err)
            print(f"[RETRY FAILED] Video {uid} đã thử lại {max_retries} lần nhưng vẫn thất bại: {err}")

    def _on_worker_stopped(self, uid):
        self._active.pop(uid, None)
        self.model.set_status(uid, "stopped")
        self._pump_queue()

    def stop_download(self):
        if not self._is_downloading:
            return
        self._stop_requested = True
        print("[STOP] Đã bấm Dừng tải! Đang chấm dứt tất cả luồng tải ngay lập tức...")
        for uid in list(self._pending_uids):
            self.model.set_status(uid, "stopped")
        self._pending_uids.clear()

        for uid, w in list(self._active.items()):
            try:
                w.stop()
                w.requestInterruption()
                w.quit()
            except Exception:
                pass
            self.model.set_status(uid, "stopped")

        self._active.clear()
        self._finish_queue()

    def _finish_queue(self):
        self._is_downloading = False
        was_stopped = self._stop_requested
        self._stop_requested = False
        if hasattr(self, "btn_dl_all"):
            self.btn_dl_all.setEnabled(True)
        if hasattr(self, "btn_dl_selected"):
            self.btn_dl_selected.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self.status_label.setText("Sẵn sàng")
        self.save_session_now()
        
        # Dọn dẹp quét lại lần cuối các file part rác
        self._cleanup_part_files()

        # Quét danh sách các video bị lỗi hoặc bị dừng
        failed_items = []
        stopped_items = []
        for uid in self.model.uids():
            it = self.model.get(uid)
            if it:
                if it.get("status") == "error":
                    failed_items.append(it)
                elif it.get("status") == "stopped":
                    stopped_items.append(it)

        if was_stopped:
            # Thông báo khi người dùng bấm DỪNG
            total_unfinish = len(failed_items) + len(stopped_items)
            unfinish_list = failed_items + stopped_items
            titles_str = "\n".join(f"• {it.get('title', 'Unknown')[:55]}" for it in unfinish_list[:5])
            if total_unfinish > 5:
                titles_str += f"\n... và {total_unfinish - 5} video khác."

            msg = (
                f"Đã dừng tiến trình tải theo yêu cầu!\n\n"
                f"- Đã tải xong: {self._completed_ok} video\n"
                f"- Chưa hoàn tất: {total_unfinish} video\n"
                f"{titles_str}\n\n"
                f"Lưu ý: Bạn có thể chọn video và bấm 'TẢI ĐÃ CHỌN' hoặc 'Thử lại file lỗi' bất cứ lúc nào để tiếp tục tải!"
            )
            QMessageBox.information(self, "Đã Dừng Quá Trình Tải", msg)
        elif failed_items:
            # Thông báo khi tải xong nhưng có tập bị lỗi
            failed_titles = "\n".join(f"• {it.get('title', 'Unknown')[:55]}" for it in failed_items[:5])
            if len(failed_items) > 5:
                failed_titles += f"\n... và {len(failed_items) - 5} video khác."

            msg = (
                f"Quá trình tải danh sách đã kết thúc!\n\n"
                f"- Đã tải thành công: {self._completed_ok} video\n"
                f"- Có {len(failed_items)} video KHÔNG TẢI ĐƯỢC:\n"
                f"{failed_titles}\n\n"
                f"NGUYÊN NHÂN & CÁCH XỬ LÝ:\n"
                f"• Link stream / Token CDN của tập này đã hết hạn hoặc bị Bilibili từ chối (HTTP 503 / 702450).\n"
                f"• Vui lòng mở lại video trên trình duyệt hoặc dùng Extension quét lại link/cookies mới rồi bấm 'Thử lại'!"
            )
            QMessageBox.warning(self, "Thông Báo Kết Quả Tải Video", msg)
        else:
            QMessageBox.information(
                self,
                "Tải Hoàn Tất",
                f"Chúc mừng! Đã tải thành công toàn bộ {self._completed_ok} video về máy!"
            )

    # ---------------------------------------------------------------
    # Folder / cookies
    def select_folder(self):
        d = QFileDialog.getExistingDirectory(self, "Chọn thư mục", self.save_folder)
        if d:
            self.save_folder = d
            self.lbl_path.setText(d)
            self.save_settings()

    def open_folder(self):
        if not os.path.exists(self.save_folder):
            os.makedirs(self.save_folder)
        os.startfile(self.save_folder)

    def import_cookies(self):
        initial_dir = getattr(self, "last_cookies_dir", "")
        if not initial_dir or not os.path.exists(initial_dir):
            initial_dir = os.path.join(os.path.expanduser("~"), "Downloads")

        f, _ = QFileDialog.getOpenFileName(
            self, "Chọn file cookies", initial_dir, "Text (*.txt);;All (*)"
        )
        if not f:
            return
        chosen_dir = os.path.dirname(f)
        self.last_cookies_dir = chosen_dir
        self.settings.setValue("last_cookies_dir", chosen_dir)
        try:
            with open(f, "r", encoding="utf-8", errors="ignore") as cf:
                content = cf.read()
            if len(content.strip()) < 50:
                QMessageBox.warning(self, "Lỗi", "File cookies trống hoặc quá ngắn!")
                return
            if not any(domain in content for domain in [".youtube.com", ".bilibili.com", ".douyin.com"]):
                QMessageBox.warning(
                    self, "Lỗi",
                    "File không chứa cookies YouTube, BiliBili hoặc Douyin!\n"
                    "Hãy xuất cookies từ trình duyệt của bạn.",
                )
                return
            has_auth = any(
                x in content
                for x in ["SID", "LOGIN_INFO", "SSID", "SESSDATA", "bili_jct", "DedeUserID", "sessionid", "ttwid"]
            )
            cookies_dir = os.path.join(base_dir(), "cookies")
            ensure_dir(cookies_dir)
            shutil.copy(f, os.path.join(cookies_dir, "cookies.txt"))
            msg = (
                "Đã import cookies thành công!\nCookies có chứa thông tin đăng nhập."
                if has_auth
                else "Đã import cookies nhưng KHÔNG tìm thấy cookie đăng nhập.\n"
                "Hãy đăng nhập YouTube/BiliBili/Douyin trong trình duyệt rồi xuất lại."
            )
            QMessageBox.information(self, "OK", msg)
        except Exception as e:
            QMessageBox.warning(self, "Lỗi", str(e))

    def request_cookies_from_extension(self):
        if not hasattr(self, "local_server") or not self.local_server:
            QMessageBox.warning(self, "Chưa Khởi Động Server", "Local Server chưa được khởi tạo trong App.")
            return

        port = self.local_server.active_port or 42124
        selected_browser = self.browser_cb.currentText() if hasattr(self, "browser_cb") else "Auto"
        is_edge = "Edge" in selected_browser
        is_chrome = "Chrome" in selected_browser
        is_coccoc = "Cốc" in selected_browser or "CocCoc" in selected_browser
        is_firefox = "Firefox" in selected_browser
        is_brave = "Brave" in selected_browser
        is_opera = "Opera" in selected_browser

        if is_edge:
            browser_name = "Microsoft Edge"
            br_param = "Edge"
        elif is_chrome:
            browser_name = "Google Chrome"
            br_param = "Chrome"
        elif is_coccoc:
            browser_name = "Cốc Cốc"
            br_param = "CocCoc"
        elif is_firefox:
            browser_name = "Mozilla Firefox"
            br_param = "Firefox"
        elif is_brave:
            browser_name = "Brave"
            br_param = "Brave"
        elif is_opera:
            browser_name = "Opera"
            br_param = "Opera"
        else:
            browser_name = "Trình duyệt"
            br_param = "Auto"

        # Đổi trạng thái nút bấm sang Loading & cập nhật status bar
        self.btn_ext_cookie.setEnabled(False)
        self.btn_ext_cookie.setText(" Đang đồng bộ...")
        self.btn_ext_cookie.setIcon(get_lucide_icon("loader", "#FFD600", 16))
        self.status_label.setText(f"Đang kết nối Extension trên {browser_name} để trích xuất Live Cookies...")

        # Xếp hàng yêu cầu trích xuất cookie trong LocalServer
        self.local_server.request_cookie_refresh("all", "manual_import", force=True)

        hub_url = f"http://127.0.0.1:{port}/sync_hub?browser={br_param}"

        # Ghi nhận trạng thái: Chờ Extension phản hồi qua Long-Polling
        if not self.local_server.is_extension_connected(timeout=20):
            print(f"[COOKIE IMPORT] Extension chưa gửi heartbeat gần đây, đang chờ Extension kết nối tại cổng {port}...")

        # Timer kiểm tra sau 7 giây nếu vẫn chưa nhận được cookie
        def _check_sync_timeout():
            if hasattr(self, "btn_ext_cookie") and not self.btn_ext_cookie.isEnabled():
                self.btn_ext_cookie.setEnabled(True)
                self.btn_ext_cookie.setText(" Lấy từ Extension")
                self.btn_ext_cookie.setIcon(get_lucide_icon("rotate-cw", "#00E676", 16))
                self.status_label.setText(f"Chưa nhận được Cookies từ {browser_name} Extension.")

                if is_edge:
                    guide_detail = (
                        "LƯU Ý CÀI ĐẶT TRÊN MICROSOFT EDGE (10 GIÂY):\n"
                        "1. Mở Microsoft Edge, vào thanh địa chỉ: edge://extensions\n"
                        "2. Bật 'Chế độ dành cho nhà phát triển' ở cột bên trái.\n"
                        "3. Bấm 'Tải phần mở rộng chưa được đóng gói' (Load unpacked)\n"
                        "   và chọn thư mục: HyperMedia_Extension\n"
                        "4. Đăng nhập tài khoản Bilibili / Douyin / YouTube trên Edge."
                    )
                elif is_chrome:
                    guide_detail = (
                        "LƯU Ý CÀI ĐẶT TRÊN GOOGLE CHROME (10 GIÂY):\n"
                        "1. Mở Google Chrome, vào thanh địa chỉ: chrome://extensions\n"
                        "2. Bật 'Chế độ nhà phát triển' ở góc trên bên phải.\n"
                        "3. Bấm 'Tải tiện ích đã giải nén' (Load unpacked)\n"
                        "   và chọn thư mục: HyperMedia_Extension\n"
                        "4. Đăng nhập tài khoản Bilibili / Douyin / YouTube trên Chrome."
                    )
                elif is_coccoc:
                    guide_detail = (
                        "LƯU Ý CÀI ĐẶT TRÊN CỐC CỐC (10 GIÂY):\n"
                        "1. Mở Cốc Cốc, vào thanh địa chỉ: coccoc://extensions\n"
                        "2. Bật 'Chế độ dành cho nhà phát triển' ở góc trên bên phải.\n"
                        "3. Bấm 'Tải tiện ích đã giải nén' (Load unpacked)\n"
                        "   và chọn thư mục: HyperMedia_Extension\n"
                        "4. Đăng nhập tài khoản Bilibili / Douyin / YouTube trên Cốc Cốc."
                    )
                elif is_firefox:
                    guide_detail = (
                        "LƯU Ý CÀI ĐẶT TRÊN MOZILLA FIREFOX (10 GIÂY):\n"
                        "1. Mở Firefox, vào thanh địa chỉ: about:debugging#/runtime/this-firefox\n"
                        "2. Bấm 'Tải phần bổ trợ tạm thời...' (Load Temporary Add-on...)\n"
                        "3. Chọn file manifest.json trong thư mục: HyperMedia_Extension\n"
                        "4. Đăng nhập tài khoản Bilibili / Douyin / YouTube trên Firefox."
                    )
                elif is_brave:
                    guide_detail = (
                        "LƯU Ý CÀI ĐẶT TRÊN BRAVE (10 GIÂY):\n"
                        "1. Mở Brave, vào thanh địa chỉ: brave://extensions\n"
                        "2. Bật 'Developer mode' ở góc trên bên phải.\n"
                        "3. Bấm 'Load unpacked' và chọn thư mục: HyperMedia_Extension\n"
                        "4. Đăng nhập tài khoản Bilibili / Douyin / YouTube trên Brave."
                    )
                elif is_opera:
                    guide_detail = (
                        "LƯU Ý CÀI ĐẶT TRÊN OPERA / OPERA GX (10 GIÂY):\n"
                        "1. Mở Opera, vào thanh địa chỉ: opera://extensions\n"
                        "2. Bật 'Developer mode' ở góc trên bên phải.\n"
                        "3. Bấm 'Load unpacked' và chọn thư mục: HyperMedia_Extension\n"
                        "4. Đăng nhập tài khoản Bilibili / Douyin / YouTube trên Opera."
                    )
                else:
                    guide_detail = (
                        "LƯU Ý CÀI ĐẶT EXTENSION (10 GIÂY):\n"
                        "• Edge: vào edge://extensions -> Bật Developer mode -> Load unpacked\n"
                        "• Chrome: vào chrome://extensions -> Bật Developer mode -> Load unpacked\n"
                        "• Cốc Cốc: vào coccoc://extensions -> Bật Developer mode -> Load unpacked\n"
                        "• Firefox: vào about:debugging#/runtime/this-firefox -> Load Temporary Add-on\n"
                        "• Brave: vào brave://extensions -> Bật Developer mode -> Load unpacked\n"
                        "• Opera: vào opera://extensions -> Bật Developer mode -> Load unpacked\n"
                        "Thư mục tiện ích: HyperMedia_Extension"
                    )

                msg = (
                    f"CHƯA NHẬN ĐƯỢC COOKIES TỪ {browser_name.upper()} EXTENSION!\n\n"
                    f"{guide_detail}\n\n"
                    f"Bạn có muốn mở trang Hỗ TrỢ Kết Nối trên {browser_name} ngay không?"
                )
                res = QMessageBox.question(
                    self,
                    f"Không Thấy Phản Hồi Từ {browser_name} Extension",
                    msg,
                    QMessageBox.Yes | QMessageBox.No,
                    QMessageBox.Yes
                )
                if res == QMessageBox.Yes:
                    open_browser_for_url(hub_url, selected_browser)

        QTimer.singleShot(7000, _check_sync_timeout)

    # ---------------------------------------------------------------
    def save_session_now(self):
        save_session(self.model.items())

    def restore_session(self):
        for it in load_session():
            uid = self.model.add_video(it)
            if it.get("thumb_url"):
                self.thumb_pool.request(uid, it["thumb_url"])
        self.update_count_label()

    def closeEvent(self, event):
        self._stop_requested = True
        for w in list(self._active.values()):
            try:
                w.stop()
                w.requestInterruption()
                w.quit()
                w.wait(800)
            except Exception:
                pass
        if hasattr(self, "local_server"):
            self.local_server.stop()
        self.thumb_pool.shutdown()
        self.save_session_now()
        self.save_settings()
        event.accept()