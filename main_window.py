"""Cửa sổ chính: list ảo hóa, marquee select, xóa item, tìm kiếm,
tải song song, stop/retry/skip, session & settings."""
import os
import shutil
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
from PySide6.QtGui import QIcon, QKeySequence, QShortcut
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
        self.browser_cb.addItems(["Auto (Tự tìm)", "None", "Chrome", "Edge", "Firefox"])
        top.addWidget(self.browser_cb)

        btn_imp = QPushButton(" Import Cookies")
        btn_imp.setIcon(get_lucide_icon("cookie", "#00E5FF", 16))
        btn_imp.clicked.connect(self.import_cookies)
        top.addWidget(btn_imp)

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

        # Khu vực bên trái: List Video (Trên) + Live Terminal Log Console (Dưới)
        self.left_box = QWidget()
        left_vbox = QVBoxLayout(self.left_box)
        left_vbox.setContentsMargins(0, 0, 0, 0)
        left_vbox.setSpacing(0)
        left_vbox.addWidget(self.view, 1)

        # Floating Contextual Panel (Nổi lơ lửng trên list khi chọn video)
        self.floating_panel = QFrame(self.view)
        self.floating_panel.setObjectName("floatingPanel")
        self.floating_panel.setStyleSheet("""
            QFrame#floatingPanel {
                background-color: #12121a;
                border: 2px solid #00E5FF;
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
        scroll_panel.setFixedWidth(275)
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
        
        par = QHBoxLayout()
        par.addWidget(QLabel("Video song song:"))
        self.parallel_sb = QSpinBox()
        self.parallel_sb.setRange(1, MAX_PARALLEL)
        self.parallel_sb.setValue(DEFAULT_PARALLEL)
        par.addWidget(self.parallel_sb)
        adv_layout.addLayout(par)

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

        self.chk_av1_trick = QCheckBox("AV1 Smart (Khỏi cần VIP)")
        self.chk_av1_trick.setChecked(True)
        self.chk_av1_trick.setToolTip("Tự động kéo luồng AV1 1.66GB siêu nhẹ (Không cần VIP Cookies Bilibili) -> FFmpeg tự recode MP4.")
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
        splitter.setSizes([1180, 275])
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
        idx = self.settings.value("browser_idx", 0, type=int)
        self.browser_cb.setCurrentIndex(min(idx, self.browser_cb.count() - 1))
        self.limit_sb.setValue(self.settings.value("limit", 10, type=int))
        self.parallel_sb.setValue(self.settings.value("parallel", DEFAULT_PARALLEL, type=int))
        self.chk_skip.setChecked(self.settings.value("skip", True, type=bool))
        geo = self.settings.value("geometry")
        if geo:
            self.restoreGeometry(geo)

    def save_settings(self):
        self.settings.setValue("folder", self.save_folder)
        self.settings.setValue("browser_idx", self.browser_cb.currentIndex())
        self.settings.setValue("limit", self.limit_sb.value())
        self.settings.setValue("parallel", self.parallel_sb.value())
        self.settings.setValue("skip", self.chk_skip.isChecked())
        self.settings.setValue("geometry", self.saveGeometry())

    def setup_shortcuts(self):
        QShortcut(QKeySequence.StandardKey.Delete, self, self.remove_selected)
        QShortcut(QKeySequence("Ctrl+A"), self, lambda: self.toggle_all(True))
        QShortcut(QKeySequence("Ctrl+D"), self, lambda: self.toggle_all(False))
        QShortcut(QKeySequence("Ctrl+F"), self, self.search_inp.setFocus)
        QShortcut(QKeySequence("Esc"), self, self.stop_download)

    # ---------------------------------------------------------------
    # Scan
    def start_scan(self):
        raw_text = self.url_inp.text().strip()
        if not raw_text or self._scanning:
            return
            
        import re
        # Tự động lọc tất cả các link HTTP/HTTPS tìm thấy trong đoạn text dán vào
        urls = re.findall(r'(https?://[^\s]+)', raw_text)
        if not urls:
            urls = [raw_text]
        
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
        base = {
            "output_path": self.save_folder,
            "browser": self.browser_cb.currentText(),
            "available_heights": list(item.get("heights") or []),
            "skip_existing": self.chk_skip.isChecked(),
            "num_threads": self.threads_sb.value(),
            "chunk_mode": self.chunk_cb.currentText(),
            "av1_smart_trick": self.chk_av1_trick.isChecked(),
            "format_id": item.get("format_id"),
            "title": item.get("title", ""),
        }
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
        while len(self._active) < self.parallel_sb.value() and self._pending_uids:
            if self._stop_requested:
                break
            uid = self._pending_uids.popleft()
            item = self.model.get(uid)
            if item is None:
                continue
            self.model.set_status(uid, "downloading")
            self.model.set_progress(uid, 0)
            worker = DownloadWorker(item["url"], self._build_options(item), parent=self)
            worker.task_progress.connect(lambda p, u=uid: self.model.set_progress(u, p))
            worker.status_update.connect(lambda s, u=uid: self._on_status_update(u, s))
            worker.task_finished.connect(lambda u=uid: self._on_worker_done(u))
            worker.task_error.connect(lambda e, u=uid: self._on_worker_error(u, e))
            worker.task_stopped.connect(lambda u=uid: self._on_worker_stopped(u))
            worker.finished.connect(worker.deleteLater)
            self._active[uid] = worker
            worker.start()

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
            self._pending_uids.appendleft(uid)
        self._pump_queue()

    def _on_status_update(self, uid, msg):
        self.status_label.setText(msg)
        self.model.set_status(uid, "downloading", msg)
        self.view.viewport().update()

    def _on_worker_done(self, uid):
        self._active.pop(uid, None)
        self._completed_ok += 1
        self.model.set_status(uid, "done")
        self.model.set_progress(uid, 100)
        self.view.viewport().update()
        self._pump_queue()

    def _on_worker_error(self, uid, err):
        self._active.pop(uid, None)
        count = self._retry_counts.get(uid, 0) + 1
        self._retry_counts[uid] = count
        max_retries = len(self.RETRY_DELAYS)

        print(f"[ERROR] Lỗi tải video {uid}: {err}")

        if count <= max_retries:
            delay_sec = self.RETRY_DELAYS[count - 1]
            delay_text = f"{delay_sec}s" if delay_sec < 60 else "1p"
            msg = f"TH:16|TIME:00:00:00|DL:Tự thử lại {count}/{max_retries}|SPD:Đợi {delay_text}...|ETA:Tự động"
            print(f"[AUTO-RETRY] Video {uid} gặp lỗi [{err}]. Tự thử lại lần {count}/{max_retries} sau {delay_text}...")
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
            app_logger().error("Download error (6 retries failed) uid=%s: %s", uid, err)
            print(f"[RETRY FAILED] Video {uid} đã thử lại 6 lần nhưng vẫn thất bại: {err}")
            
            # Cảnh báo Popup Thông báo Hệ thống khi vượt quá 6 lần
            QMessageBox.warning(
                self,
                "Tải Thất Bại Ngưỡng 6 Lần",
                f"Video đã tự động thử lại 6 lần (1s, 3s, 5s, 10s, 30s, 1p) nhưng vẫn không tải được:\n\n"
                f"Tiêu đề: {title}\n"
                f"Lỗi: {err}\n\n"
                f"Bạn có thể kiểm tra đường truyền mạng hoặc bấm nút thử lại trên thẻ video để thử lại thủ công!"
            )
            self._pump_queue()

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
                w.terminate()
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
        if not was_stopped:
            QMessageBox.information(self, "Xong", "Hoàn tất!")

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
        f, _ = QFileDialog.getOpenFileName(
            self, "Chọn file cookies", "", "Text (*.txt);;All (*)"
        )
        if not f:
            return
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
            w.stop()
            if not w.wait(1500):
                w.terminate()
                w.wait(500)
        self.thumb_pool.shutdown()
        self.save_session_now()
        self.save_settings()
        event.accept()