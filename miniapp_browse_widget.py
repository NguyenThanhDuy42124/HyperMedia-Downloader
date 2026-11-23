"""
miniapp_browse_widget.py
~~~~~~~~~~~~~~~~~~~~~~~~
Widget tab độc lập 'MiniApp Douyin' cho HyperMedia Downloader Pro:
- Thanh công cụ:
  - Đồng bộ cookie Douyin từ Chrome Extension / cookies.txt
  - Xóa phiên Douyin bảo mật
  - Hiển thị trạng thái phiên (Chưa đăng nhập / Đã nhận cookie / Hết hạn)
  - Chọn MiniApp nguồn với tên Việt hóa (Đa Lai, Hắc Nham Mạn, Kim Miêu Mạn Phẩm, v.v.)
  - Ô tìm kiếm phim và phân trang danh mục
- Grid danh sách phim kèm poster, tên phim, số tập, nhãn nguồn Việt hóa:
  - Click chuột đơn: Chọn card (viền phát sáng, cập nhật trạng thái).
  - Nhấp đúp chuột hoặc bấm 'Xem tập': Mở trực tiếp dialog chọn tập mà không bị đúp request.
  - Các QLabel con được thiết lập Qt.WA_TransparentForMouseEvents để không nuốt sự kiện click.
- Bảng thông tin trạng thái trực quan, thanh tiến trình loading, xử lý lỗi inline kèm nút 'Thử lại' / 'Đồng bộ lại Cookie'.
- Vô hiệu hóa điều khiển trong khi worker đang tải để chống race condition và stale state.
- Hỗ trợ lưu trữ phân cấp:
  downloads/MiniApp Douyin/{Tên MiniApp Việt hóa}/{Tên bộ phim}/01 - {Tên tập}.mp4
"""

import os
import time
import uuid
from PySide6.QtCore import Qt, Signal, QThread, QTimer, QEvent
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QLineEdit,
    QComboBox,
    QScrollArea,
    QGridLayout,
    QFrame,
    QProgressBar,
    QMessageBox,
)
from PySide6.QtGui import QFont, QPixmap, QCursor
from lucide_icons import get_lucide_icon
from log_drawer_widget import LogDrawerWidget
from empty_state_widget import EmptyStateWidget
from ca_bundle_utils import sanitize_error_message, sanitize_log_text
from providers.base import CatalogItem, CatalogResult, Series
from providers.miniapp_douyin_client import (
    BUILTIN_MINIAPP_SOURCES,
    clear_douyin_session,
    get_douyin_session_status,
    save_douyin_session,
    MiniAppDouyinClient,
    SESSION_STATE_NO_SESSION,
    SESSION_STATE_COOKIE_STORED,
    SESSION_STATE_SYNC_REQUESTED,
    SESSION_STATE_SYNC_RECEIVED,
    SESSION_STATE_AUTHENTICATING,
    SESSION_STATE_AUTHENTICATED,
    SESSION_STATE_SESSION_EXPIRED,
    SESSION_STATE_AUTH_FAILED,
    SESSION_STATE_SYNC_TIMEOUT,
)
from providers.miniapp_douyin_provider import MiniAppDouyinProvider
from miniapp_episode_dialog import MiniAppEpisodeDialog
from thumbnail_loader import ThumbnailLoader
from drama_path_utils import (
    get_miniapp_display_name,
    build_drama_destination_dir,
    sanitize_windows_filename,
    resolve_unique_drama_filepath,
)


class MiniAppCatalogWorker(QThread):
    results_ready = Signal(int, object)  # generation, CatalogResult
    error = Signal(int, str)  # generation, error_msg

    def __init__(self, generation: int, app_id: str, page: int = 1, query: str = "", parent=None):
        super().__init__(parent)
        self.generation = generation
        self.app_id = app_id
        self.page = page
        self.query = query

    def run(self):
        try:
            p = MiniAppDouyinProvider()
            res = p.get_catalog(page=self.page, query=self.query, app_id=self.app_id)
            self.results_ready.emit(self.generation, res)
        except Exception as e:
            self.error.emit(self.generation, str(e))


class MiniAppDetailWorker(QThread):
    series_ready = Signal(int, object)  # generation, Series
    error = Signal(int, str)  # generation, error_msg

    def __init__(self, generation: int, link_or_id: str, app_id: str = "", parent=None):
        super().__init__(parent)
        self.generation = generation
        self.link_or_id = link_or_id
        self.app_id = app_id

    def run(self):
        try:
            p = MiniAppDouyinProvider()
            if self.app_id:
                p.default_app_id = self.app_id
            series = p.load_series(self.link_or_id)
            self.series_ready.emit(self.generation, series)
        except Exception as e:
            self.error.emit(self.generation, str(e))


class SessionValidationWorker(QThread):
    validation_done = Signal(str, bool, str)  # request_id, success, message

    def __init__(self, request_id: str, app_id: str = "", parent=None):
        super().__init__(parent)
        self.request_id = request_id
        self.app_id = app_id

    def run(self):
        try:
            client = MiniAppDouyinClient()
            ok, msg = client.validate_session(self.app_id)
            self.validation_done.emit(self.request_id, ok, msg)
        except Exception as e:
            self.validation_done.emit(self.request_id, False, str(e))


class MiniAppCardWidget(QFrame):
    clicked = Signal(object)  # CatalogItem
    double_clicked = Signal(object)  # CatalogItem

    def __init__(self, item: CatalogItem, thumb_loader: ThumbnailLoader, app_id: str = "", parent=None):
        super().__init__(parent)
        self.item = item
        self.thumb_loader = thumb_loader
        self.app_id = app_id or getattr(item, "extra", {}).get("app_id", "")
        self.is_selected = False

        self.setFixedSize(176, 296)
        self.setCursor(QCursor(Qt.PointingHandCursor))
        self._update_style()

        # Timer debounce cho single-click vs double-click (250ms)
        self._click_timer = QTimer(self)
        self._click_timer.setSingleShot(True)
        self._click_timer.timeout.connect(self._on_click_timeout)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        # Poster thumbnail - Bắt buộc set WA_TransparentForMouseEvents để không nuốt sự kiện chuột
        self.lbl_thumb = QLabel()
        self.lbl_thumb.setFixedSize(160, 195)
        self.lbl_thumb.setStyleSheet("background-color: #0f1017; border-radius: 6px; border: 1px solid #1e2230; color: #64748b; font-size: 11px;")
        self.lbl_thumb.setAlignment(Qt.AlignCenter)
        self.lbl_thumb.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        if item.cover:
            self.lbl_thumb.setText("Đang tải ảnh...")
        else:
            self.lbl_thumb.setText("Không có ảnh")
        layout.addWidget(self.lbl_thumb)

        # Tiêu đề phim - WA_TransparentForMouseEvents
        self.lbl_title = QLabel(item.name)
        self.lbl_title.setToolTip(item.name)
        self.lbl_title.setStyleSheet("color: #f3f4f6; font-size: 11px; font-weight: bold;")
        self.lbl_title.setFixedHeight(28)
        self.lbl_title.setWordWrap(True)
        self.lbl_title.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        layout.addWidget(self.lbl_title)

        # Dòng meta: Số tập & Badge Free-first
        meta_layout = QHBoxLayout()
        meta_layout.setSpacing(4)

        self.lbl_episodes = QLabel(f"{item.episodes} tập" if item.episodes else "Phim ngắn")
        self.lbl_episodes.setStyleSheet("color: #ec4899; font-size: 10px; font-weight: 500;")
        self.lbl_episodes.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        meta_layout.addWidget(self.lbl_episodes)

        meta_layout.addStretch()

        badge_free = QLabel("Free-first")
        badge_free.setStyleSheet(
            "color: #10b981; font-size: 9px; font-weight: bold; background: #064e3b; "
            "padding: 1px 4px; border-radius: 3px;"
        )
        badge_free.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        meta_layout.addWidget(badge_free)

        layout.addLayout(meta_layout)

        # Nút thao tác trực tiếp 'Xem tập'
        self.btn_view = QPushButton("Xem tập")
        self.btn_view.setIcon(get_lucide_icon("play", "#ffffff", 11))
        self.btn_view.setStyleSheet("""
            QPushButton {
                background-color: #2563eb;
                color: white;
                font-size: 10px;
                font-weight: bold;
                border: none;
                border-radius: 4px;
                padding: 3px 8px;
            }
            QPushButton:hover {
                background-color: #1d4ed8;
            }
        """)
        self.btn_view.clicked.connect(lambda: self.double_clicked.emit(self.item))
        layout.addWidget(self.btn_view)

        if item.cover:
            self.lbl_thumb.setText("Đang tải ảnh...")
            self.thumb_loader.load(item.cover, self._on_thumb_loaded)
        else:
            self.lbl_thumb.setText("Không có ảnh")

    def _update_style(self):
        if self.is_selected:
            self.setStyleSheet("""
                MiniAppCardWidget {
                    background-color: #1e1b4b;
                    border: 2px solid #ec4899;
                    border-radius: 8px;
                }
            """)
        else:
            self.setStyleSheet("""
                MiniAppCardWidget {
                    background-color: #161824;
                    border: 1px solid #232738;
                    border-radius: 8px;
                }
                MiniAppCardWidget:hover {
                    border: 1.5px solid #ec4899;
                    background-color: #1d2136;
                }
            """)

    def set_selected(self, selected: bool):
        """Cập nhật trạng thái được chọn của card."""
        self.is_selected = selected
        self._update_style()

    def _on_thumb_loaded(self, url_or_pixmap, maybe_pixmap=None):
        pixmap = maybe_pixmap if maybe_pixmap is not None else url_or_pixmap
        if pixmap and isinstance(pixmap, QPixmap) and not pixmap.isNull():
            scaled = pixmap.scaled(self.lbl_thumb.size(), Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
            crop_x = max(0, (scaled.width() - self.lbl_thumb.width()) // 2)
            crop_y = max(0, (scaled.height() - self.lbl_thumb.height()) // 2)
            cropped = scaled.copy(crop_x, crop_y, self.lbl_thumb.width(), self.lbl_thumb.height())
            self.lbl_thumb.setPixmap(cropped)
        else:
            self.lbl_thumb.setPixmap(QPixmap())
            self.lbl_thumb.setText("Không có ảnh")

    def _on_click_timeout(self):
        """Xử lý sau 250ms nếu không có double-click."""
        self.clicked.emit(self.item)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            # Bắt đầu timer debounce cho single click
            self._click_timer.start(250)
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.LeftButton:
            # Hủy single-click timer để không tạo 2 request trùng nhau
            if self._click_timer.isActive():
                self._click_timer.stop()
            self.double_clicked.emit(self.item)
            event.accept()
            return
        super().mouseDoubleClickEvent(event)


class MiniAppBrowseWidget(QWidget):
    queue_episodes_requested = Signal(list, str)  # list of dicts for queue, series_name

    def __init__(self, parent=None):
        super().__init__(parent)
        self.current_page = 1
        self.current_query = ""
        self._has_more = False
        self._catalog_gen = 0
        self._detail_gen = 0
        self._selected_card: MiniAppCardWidget = None
        self._cards = []
        self._current_cols = -1
        self._is_busy = False
        self._loaded_series_ids = set()
        self._pending_catalog_request = None

        self.thumb_loader = ThumbnailLoader()
        self.catalog_worker = None
        self.detail_worker = None
        self.val_worker = None

        self._sync_timeout_timer = QTimer(self)
        self._sync_timeout_timer.setSingleShot(True)
        self._sync_timeout_timer.timeout.connect(self._on_sync_timer_timeout)
        self._active_sync_request_id = ""
        self._is_syncing = False
        self._session_state = SESSION_STATE_NO_SESSION
        self._connected_server = None

        self._init_ui()
        self.update_session_status_display()
        self.load_catalog()

    def shutdown(self):
        """Dừng an toàn các worker bất đồng bộ khi đóng ứng dụng."""
        if hasattr(self, "_sync_timeout_timer") and self._sync_timeout_timer.isActive():
            self._sync_timeout_timer.stop()
        if hasattr(self, "val_worker") and self.val_worker and self.val_worker.isRunning():
            try:
                self.val_worker.validation_done.disconnect()
            except Exception:
                pass
            self.val_worker.wait(500)
        if self.catalog_worker and self.catalog_worker.isRunning():
            try:
                self.catalog_worker.results_ready.disconnect()
                self.catalog_worker.error.disconnect()
                self.catalog_worker.finished.disconnect()
            except Exception:
                pass
            self.catalog_worker.wait(500)
        if self.detail_worker and self.detail_worker.isRunning():
            try:
                self.detail_worker.series_ready.disconnect()
                self.detail_worker.error.disconnect()
                self.detail_worker.finished.disconnect()
            except Exception:
                pass
            self.detail_worker.wait(500)

    def _init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(14, 14, 14, 14)
        main_layout.setSpacing(10)

        # 1. Top Bar: Session controls & Extension sync
        top_bar = QHBoxLayout()
        top_bar.setSpacing(10)

        self.btn_sync = QPushButton(" Đồng bộ phiên")
        self.btn_sync.setIcon(get_lucide_icon("refresh-cw", "#e5e7eb", 13))
        self.btn_sync.setFixedHeight(32)
        self.btn_sync.setStyleSheet("""
            QPushButton {
                background-color: #1f2937;
                color: #e5e7eb;
                font-weight: 500;
                font-size: 11px;
                border: 1px solid #374151;
                border-radius: 6px;
                padding: 5px 14px;
            }
            QPushButton:hover {
                background-color: #374151;
            }
            QPushButton:disabled {
                background-color: #111827;
                color: #4b5563;
            }
        """)
        self.btn_sync.clicked.connect(self._on_sync_clicked)
        top_bar.addWidget(self.btn_sync)

        self.btn_clear_sess = QPushButton(" Xóa phiên")
        self.btn_clear_sess.setIcon(get_lucide_icon("trash-2", "#f87171", 13))
        self.btn_clear_sess.setFixedHeight(32)
        self.btn_clear_sess.setStyleSheet("""
            QPushButton {
                background-color: #1f2937;
                color: #f87171;
                border: 1px solid #7f1d1d;
                border-radius: 6px;
                padding: 5px 12px;
                font-size: 11px;
                font-weight: 500;
            }
            QPushButton:hover {
                background-color: #7f1d1d;
                color: white;
            }
            QPushButton:disabled {
                background-color: #111827;
                color: #4b5563;
                border-color: #374151;
            }
        """)
        self.btn_clear_sess.clicked.connect(self._on_clear_session_clicked)
        top_bar.addWidget(self.btn_clear_sess)

        self.lbl_session = QLabel("Chưa đăng nhập")
        self.lbl_session.setStyleSheet("color: #9ca3af; font-size: 11px; padding: 4px 10px; border-radius: 4px; background: #161824; border: 1px solid #232738;")
        top_bar.addWidget(self.lbl_session)

        top_bar.addStretch()

        # MiniApp Source dropdown - Hiển thị tên Việt hóa chuẩn hóa
        lbl_source = QLabel("Nguồn MiniApp:")
        lbl_source.setStyleSheet("color: #9ca3af; font-weight: bold; font-size: 11px;")
        top_bar.addWidget(lbl_source)

        self.cbo_source = QComboBox()
        self.cbo_source.setFixedWidth(210)
        self.cbo_source.setFixedHeight(32)
        self.cbo_source.setStyleSheet("""
            QComboBox {
                background-color: #161824;
                border: 1px solid #232738;
                border-radius: 6px;
                padding: 5px 10px;
                color: #f3f4f6;
                font-weight: 500;
                font-size: 11px;
            }
            QComboBox QAbstractItemView {
                background-color: #161824;
                color: #f3f4f6;
                selection-background-color: #2563eb;
            }
        """)
        for src in BUILTIN_MINIAPP_SOURCES:
            v_name = get_miniapp_display_name(src["app_id"], fallback=src["name"])
            self.cbo_source.addItem(f"{v_name} ({src['name']})", src["app_id"])
        self.cbo_source.currentIndexChanged.connect(self._on_source_changed)
        top_bar.addWidget(self.cbo_source)

        main_layout.addLayout(top_bar)

        # 2. Search & Filter Bar
        search_bar = QHBoxLayout()
        search_bar.setSpacing(10)

        self.txt_search = QLineEdit()
        self.txt_search.setPlaceholderText("Tìm kiếm phim hoặc dán link video / MiniApp Douyin...")
        self.txt_search.setFixedHeight(34)
        self.txt_search.setStyleSheet("""
            QLineEdit {
                background-color: #161824;
                border: 1px solid #232738;
                border-radius: 6px;
                padding: 6px 12px;
                color: #f3f4f6;
                font-size: 12px;
            }
            QLineEdit:focus {
                border: 1px solid #3b82f6;
            }
        """)
        self.txt_search.returnPressed.connect(self._on_search_clicked)
        search_bar.addWidget(self.txt_search, stretch=1)

        self.btn_search = QPushButton(" Tìm kiếm")
        self.btn_search.setIcon(get_lucide_icon("search", "#ffffff", 14))
        self.btn_search.setFixedHeight(34)
        self.btn_search.setStyleSheet("""
            QPushButton {
                background-color: #2563eb;
                color: white;
                font-weight: 600;
                font-size: 12px;
                border-radius: 6px;
                padding: 6px 16px;
                border: none;
            }
            QPushButton:hover {
                background-color: #1d4ed8;
            }
            QPushButton:disabled {
                background-color: #1e3a8a;
                color: #93c5fd;
            }
        """)
        self.btn_search.clicked.connect(self._on_search_clicked)
        search_bar.addWidget(self.btn_search)

        self.btn_refresh = QPushButton(" Làm mới")
        self.btn_refresh.setIcon(get_lucide_icon("rotate-cw", "#e5e7eb", 14))
        self.btn_refresh.setFixedHeight(34)
        self.btn_refresh.setStyleSheet("""
            QPushButton {
                background-color: #1f2937;
                color: #e5e7eb;
                border: 1px solid #374151;
                border-radius: 6px;
                padding: 6px 14px;
                font-weight: 500;
                font-size: 12px;
            }
            QPushButton:hover {
                background-color: #374151;
            }
            QPushButton:disabled {
                background-color: #111827;
                color: #4b5563;
            }
        """)
        self.btn_refresh.clicked.connect(self._on_refresh_clicked)
        search_bar.addWidget(self.btn_refresh)

        main_layout.addLayout(search_bar)

        # 3. Status & Notification Panel trực quan
        self.status_panel = QFrame()
        self.status_panel.setStyleSheet("""
            QFrame {
                background-color: #11131f;
                border: 1px solid #1f2333;
                border-radius: 6px;
                padding: 4px 8px;
            }
        """)
        status_panel_layout = QHBoxLayout(self.status_panel)
        status_panel_layout.setContentsMargins(8, 4, 8, 4)
        status_panel_layout.setSpacing(10)

        self.lbl_status = QLabel("Sẵn sàng")
        self.lbl_status.setStyleSheet("color: #9ca3af; font-size: 11px;")
        status_panel_layout.addWidget(self.lbl_status, stretch=1)

        self.btn_reauth = QPushButton(" Đồng bộ lại phiên")
        self.btn_reauth.setIcon(get_lucide_icon("refresh-cw", "#fde68a", 12))
        self.btn_reauth.setFixedHeight(26)
        self.btn_reauth.setStyleSheet("""
            QPushButton {
                background-color: #78350f; color: #fde68a; font-weight: bold; font-size: 11px;
                border: 1px solid #d97706; border-radius: 4px; padding: 2px 10px;
            }
            QPushButton:hover { background-color: #92400e; }
        """)
        self.btn_reauth.setVisible(False)
        self.btn_reauth.clicked.connect(self._on_sync_clicked)
        status_panel_layout.addWidget(self.btn_reauth)

        self.btn_retry = QPushButton(" Thử lại")
        self.btn_retry.setIcon(get_lucide_icon("rotate-cw", "#ffffff", 12))
        self.btn_retry.setFixedHeight(26)
        self.btn_retry.setStyleSheet("""
            QPushButton {
                background-color: #2563eb; color: white; font-weight: bold; font-size: 11px;
                border: none; border-radius: 4px; padding: 2px 10px;
            }
            QPushButton:hover { background-color: #1d4ed8; }
        """)
        self.btn_retry.setVisible(False)
        self.btn_retry.clicked.connect(self._on_retry_clicked)
        status_panel_layout.addWidget(self.btn_retry)

        self.progress_bar = QProgressBar()
        self.progress_bar.setFixedHeight(4)
        self.progress_bar.setFixedWidth(140)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setStyleSheet("""
            QProgressBar {
                background-color: #1f2438;
                border: none;
                border-radius: 2px;
            }
            QProgressBar::chunk {
                background-color: #2563eb;
                border-radius: 2px;
            }
        """)
        self.progress_bar.setVisible(False)
        status_panel_layout.addWidget(self.progress_bar)

        main_layout.addWidget(self.status_panel)

        # 4. Main Content: Scrollable Grid for Cards with Infinite Scroll
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.viewport().installEventFilter(self)
        self.scroll_area.setStyleSheet("QScrollArea { border: 1px solid #1f2937; border-radius: 8px; background-color: #0b0c13; }")
        self.scroll_area.verticalScrollBar().valueChanged.connect(self._on_scroll_changed)

        self.grid_container = QWidget()
        self.grid_layout = QGridLayout(self.grid_container)
        self.grid_layout.setSpacing(14)
        self.grid_layout.setContentsMargins(16, 16, 16, 16)
        self.grid_layout.setAlignment(Qt.AlignTop | Qt.AlignHCenter)

        self.empty_state = EmptyStateWidget(self.grid_container)
        self.empty_state.setVisible(False)

        self.scroll_area.setWidget(self.grid_container)
        main_layout.addWidget(self.scroll_area, stretch=1)

        # 5. Log Drawer (Thu gọn mặc định - Progressive Disclosure)
        self.log_drawer = LogDrawerWidget("Nhật ký MiniApp Douyin", parent=self)
        self.log_drawer.setVisible(False)
        self.log_drawer.closed.connect(self._on_log_drawer_closed)
        main_layout.addWidget(self.log_drawer)

        # 6. Status Footer (Bỏ phân trang nút bấm, giữ Infinite Scroll & Nút phụ trợ)
        footer = QHBoxLayout()
        footer.setContentsMargins(2, 4, 2, 2)
        footer.setSpacing(10)

        self.lbl_footer_info = QLabel("")
        self.lbl_footer_info.setStyleSheet("color: #94a3b8; font-size: 11px;")
        footer.addWidget(self.lbl_footer_info)

        footer.addStretch()

        self.btn_load_more_footer = QPushButton(" Tải thêm phim")
        self.btn_load_more_footer.setIcon(get_lucide_icon("plus-circle", "#e5e7eb", 13))
        self.btn_load_more_footer.setFixedHeight(30)
        self.btn_load_more_footer.setStyleSheet("""
            QPushButton {
                background-color: #1f2937; color: #e5e7eb; border: 1px solid #374151;
                border-radius: 6px; padding: 4px 12px; font-size: 11px; font-weight: 500;
            }
            QPushButton:hover { background-color: #374151; border-color: #4b5563; }
            QPushButton:disabled { background-color: #111827; color: #4b5563; }
        """)
        self.btn_load_more_footer.setVisible(False)
        self.btn_load_more_footer.clicked.connect(self._on_load_more_clicked)
        footer.addWidget(self.btn_load_more_footer)

        self.btn_log = QPushButton(" Nhật ký")
        self.btn_log.setIcon(get_lucide_icon("terminal", "#94a3b8", 13))
        self.btn_log.setFixedHeight(30)
        self.btn_log.setStyleSheet("""
            QPushButton {
                background-color: #1f2937; color: #cbd5e1; border: 1px solid #374151;
                border-radius: 6px; padding: 4px 12px; font-size: 11px; font-weight: 500;
            }
            QPushButton:hover { background-color: #374151; color: white; }
        """)
        self.btn_log.clicked.connect(self._toggle_log_drawer)
        footer.addWidget(self.btn_log)

        main_layout.addLayout(footer)

        # Backward compatibility aliases & stubs for test harness
        self.btn_load_more = self.btn_load_more_footer
        self.btn_prev = QPushButton()
        self.btn_prev.hide()
        self.btn_next = QPushButton()
        self.btn_next.hide()
        self.lbl_page = QLabel("Trang 1")
        self.lbl_page.hide()

    def _set_loading(self, busy: bool, message: str = ""):
        """Kiểm soát trạng thái loading và khóa các nút điều khiển."""
        self._is_busy = busy
        self.progress_bar.setVisible(busy)
        if busy:
            self.progress_bar.setRange(0, 0)
        else:
            self.progress_bar.setRange(0, 100)
            self.progress_bar.setValue(0)

        self.cbo_source.setEnabled(not busy)
        self.txt_search.setEnabled(not busy)
        self.btn_search.setEnabled(not busy)
        self.btn_refresh.setEnabled(not busy)
        self.btn_sync.setEnabled(not busy)
        self.btn_clear_sess.setEnabled(not busy)
        if hasattr(self, "btn_load_more_footer"):
            self.btn_load_more_footer.setEnabled(not busy)

        if message:
            self.lbl_status.setText(message)

    def set_session_state(self, state: str, custom_text: str = ""):
        """Cập nhật trạng thái phiên và giao diện badge chuẩn hóa."""
        self._session_state = state
        if state in (SESSION_STATE_AUTHENTICATED, "valid"):
            txt = custom_text or "Đã kết nối"
            self.lbl_session.setText(txt)
            self.lbl_session.setStyleSheet("color: #10b981; font-weight: bold; font-size: 11px; padding: 4px 10px; border-radius: 4px; background: rgba(16, 185, 129, 0.12); border: 1px solid #059669;")
        elif state == SESSION_STATE_COOKIE_STORED:
            txt = custom_text or "Đã lưu cookie"
            self.lbl_session.setText(txt)
            self.lbl_session.setStyleSheet("color: #38bdf8; font-weight: bold; font-size: 11px; padding: 4px 10px; border-radius: 4px; background: rgba(56, 189, 248, 0.12); border: 1px solid #0284c7;")
        elif state == SESSION_STATE_SYNC_REQUESTED:
            txt = custom_text or "Đang đồng bộ..."
            self.lbl_session.setText(txt)
            self.lbl_session.setStyleSheet("color: #f59e0b; font-weight: bold; font-size: 11px; padding: 4px 10px; border-radius: 4px; background: rgba(245, 158, 11, 0.12); border: 1px solid #d97706;")
        elif state in (SESSION_STATE_SYNC_RECEIVED, SESSION_STATE_AUTHENTICATING):
            txt = custom_text or "Đang xác thực..."
            self.lbl_session.setText(txt)
            self.lbl_session.setStyleSheet("color: #06b6d4; font-weight: bold; font-size: 11px; padding: 4px 10px; border-radius: 4px; background: rgba(6, 182, 212, 0.12); border: 1px solid #0891b2;")
        elif state in (SESSION_STATE_SESSION_EXPIRED, "expired"):
            txt = custom_text or "Phiên hết hạn"
            self.lbl_session.setText(txt)
            self.lbl_session.setStyleSheet("color: #f59e0b; font-weight: bold; font-size: 11px; padding: 4px 10px; border-radius: 4px; background: rgba(245, 158, 11, 0.12); border: 1px solid #d97706;")
        elif state == SESSION_STATE_AUTH_FAILED:
            txt = custom_text or "Xác thực thất bại"
            self.lbl_session.setText(txt)
            self.lbl_session.setStyleSheet("color: #ef4444; font-weight: bold; font-size: 11px; padding: 4px 10px; border-radius: 4px; background: rgba(239, 68, 68, 0.12); border: 1px solid #dc2626;")
        elif state == SESSION_STATE_SYNC_TIMEOUT:
            txt = custom_text or "Không nhận được phản hồi Extension"
            self.lbl_session.setText(txt)
            self.lbl_session.setStyleSheet("color: #f97316; font-weight: bold; font-size: 11px; padding: 4px 10px; border-radius: 4px; background: rgba(249, 115, 22, 0.12); border: 1px solid #ea580c;")
        else:
            txt = custom_text or "Chưa có phiên"
            self.lbl_session.setText(txt)
            self.lbl_session.setStyleSheet("color: #9ca3af; font-size: 11px; padding: 4px 10px; border-radius: 4px; background: #161824; border: 1px solid #232738;")

    def update_session_status_display(self):
        """Cập nhật nhãn trạng thái phiên Douyin theo chuẩn badge phân tách cookie vs auth."""
        code, msg = get_douyin_session_status(app_id=self.get_selected_app_id())
        self.set_session_state(code)

    def _on_scroll_changed(self, value: int):
        bar = self.scroll_area.verticalScrollBar()
        if bar.maximum() > 0 and value >= bar.maximum() - 150:
            if self._has_more and not self._is_busy:
                self.current_page += 1
                self.load_catalog(is_append=True)

    def _on_load_more_clicked(self):
        if self._is_busy or not self._has_more:
            return
        self.current_page += 1
        self.request_catalog_reload(page=self.current_page, append=True, reason="Tải thêm trang")

    def _toggle_log_drawer(self):
        vis = not self.log_drawer.isVisible()
        self.log_drawer.setVisible(vis)
        self.btn_log.setText(" Đóng nhật ký" if vis else " Nhật ký")

    def _on_log_drawer_closed(self):
        self.btn_log.setText(" Nhật ký")

    def log_info(self, msg: str):
        self.log_drawer.log_info(sanitize_log_text(msg))

    def log_warn(self, msg: str):
        self.log_drawer.log_warn(sanitize_log_text(msg))

    def log_error(self, msg: str):
        self.log_drawer.log_error(sanitize_log_text(msg))

    def _connect_server_signals(self, server):
        """Kết nối an toàn tới các signal của LocalServer."""
        if not server or getattr(self, "_connected_server", None) == server:
            return
        self._connected_server = server
        for sig_name, slot in (
            ("miniapp_sync_started", self.on_miniapp_sync_started),
            ("miniapp_sync_received", self.on_miniapp_sync_received),
            ("miniapp_sync_saved", self.on_miniapp_sync_saved),
            ("miniapp_sync_failed", self.on_miniapp_sync_failed),
            ("miniapp_sync_timeout", self.on_miniapp_sync_timeout),
            ("miniapp_cookie_synced", self.on_cookie_synced),
        ):
            sig = getattr(server, sig_name, None)
            if sig:
                try:
                    sig.connect(slot, Qt.UniqueConnection)
                except Exception:
                    pass

    def _on_sync_clicked(self):
        """Kích hoạt yêu cầu Extension gửi cookie Douyin với lifecycle rõ ràng."""
        if self._is_syncing:
            return

        self._is_syncing = True
        self.btn_sync.setEnabled(False)
        self.progress_bar.setRange(0, 0)
        self.progress_bar.setVisible(True)

        req_id = f"sync_{int(time.time() * 1000)}_{uuid.uuid4().hex[:6]}"
        self._active_sync_request_id = req_id

        self.log_info("[INFO] Bắt đầu đồng bộ phiên Douyin")
        self.log_info(f"[INFO] Đã gửi yêu cầu Extension, request_id={req_id}")

        main_win = self.window()
        server = getattr(main_win, "local_server", None) or getattr(self, "local_server", None)
        if not server:
            self.log_warn("[WARN] Extension chưa kết nối với ứng dụng")
            self.lbl_status.setText("Extension chưa kết nối với ứng dụng. Hãy mở Extension hoặc khởi động lại ứng dụng.")
            self.set_session_state(SESSION_STATE_NO_SESSION)
            self.btn_sync.setEnabled(True)
            self.progress_bar.setVisible(False)
            self._is_syncing = False
            return

        self._connect_server_signals(server)
        server.request_miniapp_douyin_cookie_refresh(force=True, request_id=req_id)

        if not server.is_extension_connected():
            self.log_warn("[WARN] Extension chưa phản hồi heartbeat (trình duyệt có thể chưa mở)")
            self.lbl_status.setText("Đang kết nối Extension... Hãy mở douyin.com và đăng nhập trước khi đồng bộ.")
        else:
            self.lbl_status.setText("Đã gửi yêu cầu tới Extension. Vui lòng mở hoặc chuyển sang tab douyin.com...")

        self.set_session_state(SESSION_STATE_SYNC_REQUESTED)
        self._sync_timeout_timer.start(8000)

    def _on_sync_timer_timeout(self):
        """Xử lý timeout 8 giây khi Extension không phản hồi."""
        if not self._is_syncing:
            return
        self._is_syncing = False
        self._active_sync_request_id = ""
        self.btn_sync.setEnabled(True)
        self.progress_bar.setVisible(False)
        self.log_warn("[WARN] Extension chưa phản hồi")
        self.lbl_status.setText("Không nhận được phản hồi từ Extension. Hãy mở douyin.com và kiểm tra Extension.")
        self.set_session_state(SESSION_STATE_SYNC_TIMEOUT)

    def on_miniapp_sync_started(self, request_id: str, browser: str):
        pass

    def on_miniapp_sync_saved(self, request_id: str, count: int):
        self.log_info("[INFO] Session DPAPI đã lưu thành công")

    def on_miniapp_sync_received(self, request_id: str, count: int, browser: str):
        """Xử lý khi Extension phản hồi cookie Douyin."""
        self._sync_timeout_timer.stop()
        if count <= 0:
            self._is_syncing = False
            self.btn_sync.setEnabled(True)
            self.progress_bar.setVisible(False)
            self.log_warn("[WARN] Extension phản hồi nhưng không tìm thấy cookie Douyin hợp lệ")
            self.lbl_status.setText("Không tìm thấy cookie Douyin hợp lệ. Hãy mở douyin.com và đăng nhập trước khi đồng bộ.")
            self.set_session_state(SESSION_STATE_AUTH_FAILED)
            return

        self.log_info(f"[INFO] Extension đã phản hồi, nhận {count} cookie từ {browser}")
        self.set_session_state(SESSION_STATE_AUTHENTICATING)
        self.lbl_status.setText(f"Extension đã phản hồi: {count} cookies. Đang xác thực phiên...")

        # Kích hoạt xác thực session thật bằng mint token bất đồng bộ
        self.log_info("[INFO] Bắt đầu mint MiniApp token")
        if hasattr(self, "val_worker") and self.val_worker and self.val_worker.isRunning():
            try:
                self.val_worker.validation_done.disconnect()
            except Exception:
                pass
        self.val_worker = SessionValidationWorker(request_id, app_id=self.get_selected_app_id(), parent=self)
        self.val_worker.validation_done.connect(self._on_validation_done)
        self.val_worker.start()

    def _on_validation_done(self, request_id: str, success: bool, message: str):
        """Kết quả xác thực token MiniApp."""
        self._is_syncing = False
        self._active_sync_request_id = ""
        self.btn_sync.setEnabled(True)
        self.progress_bar.setVisible(False)

        if success:
            self.log_info("[INFO] Mint token thành công")
            self.log_info("[INFO] Session MiniApp đã xác thực")
            self.set_session_state(SESSION_STATE_AUTHENTICATED)
            self.lbl_status.setText("Đã kết nối MiniApp Douyin")
            if hasattr(self, "btn_reauth") and self.btn_reauth:
                self.btn_reauth.setVisible(False)
            # Giữ nguyên catalog public, không reload catalog thừa
        else:
            self.log_error(f"[ERROR] Không thể mint token: {sanitize_log_text(message)}")
            self.set_session_state(SESSION_STATE_AUTH_FAILED)
            self.lbl_status.setText(f"Cookie đã nhận nhưng phiên MiniApp không được xác thực ({sanitize_error_message(message)})")

    def on_miniapp_sync_failed(self, request_id: str, reason: str):
        self._sync_timeout_timer.stop()
        self._is_syncing = False
        self._active_sync_request_id = ""
        self.btn_sync.setEnabled(True)
        self.progress_bar.setVisible(False)
        self.log_warn(f"[WARN] Đồng bộ thất bại: {sanitize_log_text(reason)}")
        self.lbl_status.setText(f"Đồng bộ thất bại: {sanitize_error_message(reason)}")
        self.set_session_state(SESSION_STATE_AUTH_FAILED)

    def on_miniapp_sync_timeout(self, request_id: str):
        self._on_sync_timer_timeout()

    def on_cookie_synced(self, domain: str = "", count: int = 0, browser: str = ""):
        """Tự động làm mới danh mục và cập nhật trạng thái khi nhận signal đồng bộ cookie."""
        self.log_drawer.log_info(f"Nhận thông báo đồng bộ cookie ({count} cookies) từ {browser}.")
        self.update_session_status_display()
        self.request_catalog_reload(reason="Phiên đã thay đổi, đang làm mới dữ liệu")

    def _on_clear_session_clicked(self):
        """Xóa bỏ phiên cookie đã mã hóa."""
        if clear_douyin_session():
            self.set_session_state(SESSION_STATE_NO_SESSION)
            self.lbl_status.setText("Đã xóa phiên Douyin bảo mật")
            self.log_info("[INFO] Đã xóa phiên Douyin bảo mật")
            if hasattr(self, "btn_reauth") and self.btn_reauth:
                self.btn_reauth.setVisible(False)
        else:
            self.lbl_status.setText("Không thể xóa file phiên đăng nhập.")

    def _on_source_changed(self):
        self.current_page = 1
        self.current_query = ""
        self.txt_search.clear()
        self.request_catalog_reload(source_id=self.get_selected_app_id(), query="", page=1, append=False, reason="Đổi nguồn MiniApp")

    def _on_search_clicked(self):
        text = self.txt_search.text().strip()
        if text and (
            text.startswith("http://")
            or text.startswith("https://")
            or text.startswith("douyin_miniapp:")
            or text.startswith("miniapp_douyin:")
        ):
            dummy_item = CatalogItem(
                id=text,
                name="Liên kết Douyin / MiniApp",
                cover="",
                episodes=0,
                desc="",
                link=text,
                platform="miniapp_douyin",
            )
            self._fetch_series_detail(dummy_item)
            return

        self.current_query = text
        self.current_page = 1
        self.request_catalog_reload(query=text, page=1, append=False, reason="Tìm kiếm phim")

    def _on_refresh_clicked(self):
        self.txt_search.clear()
        self.current_query = ""
        self.current_page = 1
        self.update_session_status_display()
        self.request_catalog_reload(page=1, append=False, reason="Làm mới danh mục")

    def _on_retry_clicked(self):
        """Thử lại tác vụ vừa lỗi."""
        self.request_catalog_reload(query=self.current_query, page=self.current_page, append=False, reason="Thử lại")

    def _clear_grid(self):
        while self.grid_layout.count():
            item = self.grid_layout.takeAt(0)
            widget = item.widget()
            if widget and widget is not self.empty_state:
                widget.deleteLater()
        if hasattr(self, "empty_state") and self.empty_state:
            self.empty_state.setVisible(False)
        self._selected_card = None
        self._cards.clear()

    def eventFilter(self, obj, event):
        if obj is self.scroll_area.viewport() and event.type() == QEvent.Type.Resize:
            self._relayout_cards()
        return super().eventFilter(obj, event)

    def _calculate_columns(self) -> int:
        viewport_w = self.scroll_area.viewport().width()
        win = self.window()
        win_w = win.width() if (win and win.width() > 300) else 0
        self_w = self.width() if self.width() > 300 else 0
        scroll_w = self.scroll_area.width() if self.scroll_area.width() > 300 else 0

        best_w = max(viewport_w, scroll_w, self_w)
        if win_w > 0 and (best_w < win_w - 200 or best_w < 500):
            best_w = max(best_w, win_w - 60)

        target_w = max(best_w, 400)
        card_w = 176
        spacing = 14
        margins = 32
        avail_w = max(100, target_w - margins)
        cols = max(1, (avail_w + spacing) // (card_w + spacing))
        return max(4, min(10, int(cols)))

    def _relayout_cards(self, force: bool = False):
        if not self._cards:
            return
        cols = self._calculate_columns()
        if not force and getattr(self, "_current_cols", None) == cols and self.grid_layout.count() == len(self._cards):
            return
        self._current_cols = cols
        while self.grid_layout.count():
            item = self.grid_layout.takeAt(0)
            w = item.widget()
            if w and w not in self._cards and w is not self.empty_state:
                w.deleteLater()
        for idx, card in enumerate(self._cards):
            row = idx // cols
            col = idx % cols
            self.grid_layout.addWidget(card, row, col)

    def showEvent(self, event):
        super().showEvent(event)
        QTimer.singleShot(0, lambda: self._relayout_cards(force=True))
        QTimer.singleShot(100, lambda: self._relayout_cards(force=True))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._relayout_cards()

    def get_selected_app_id(self) -> str:
        idx = self.cbo_source.currentIndex()
        if idx >= 0:
            return self.cbo_source.itemData(idx)
        return BUILTIN_MINIAPP_SOURCES[0]["app_id"]

    def request_catalog_reload(
        self,
        source_id: Optional[str] = None,
        query: Optional[str] = None,
        page: int = 1,
        append: bool = False,
        reason: str = "",
    ):
        """Yêu cầu nạp catalog MiniApp với cơ chế race-guard: tăng gen ngay lập tức và xếp hàng nếu bận."""
        self._catalog_gen += 1
        current_gen = self._catalog_gen

        prev_source = self._pending_catalog_request.get("source_id") if self._pending_catalog_request else None
        app_id = source_id or prev_source or self.get_selected_app_id()
        q = self.current_query if query is None else query

        if self._is_busy or (self.catalog_worker and self.catalog_worker.isRunning()):
            self._pending_catalog_request = {
                "source_id": app_id,
                "query": q,
                "page": page,
                "append": append,
                "reason": reason,
            }
            if reason:
                self.lbl_status.setText(reason)
            self.log_drawer.log_info(
                f"Yêu cầu tải MiniApp (gen={current_gen}) được đưa vào hàng đợi chờ worker hoàn tất ({reason})."
            )
            return

        self._execute_catalog_request(app_id, q, page, append, current_gen)

    def _execute_catalog_request(self, app_id: str, query: str, page: int, is_append: bool, gen: int):
        self.current_page = page
        self.current_query = query

        source_name = self.cbo_source.currentText()
        for src in BUILTIN_MINIAPP_SOURCES:
            if src["app_id"] == app_id:
                source_name = src["name"]
                break

        if not is_append:
            self._loaded_series_ids.clear()
            self._clear_grid()
            self.empty_state.show_loading("Đang tải danh sách phim...", f"Đang kết nối đến nguồn {source_name}...")
            self.grid_layout.addWidget(self.empty_state, 0, 0)
            self._set_loading(True, f"Đang tải danh mục {source_name}...")
            self.log_drawer.log_info(f"Nạp danh mục MiniApp: nguồn={source_name}, query='{query}', gen={gen}")
        else:
            self._set_loading(True, f"Đang tải thêm phim (Trang {page})...")
            self.log_drawer.log_info(f"Tải thêm trang {page} cho {source_name}, gen={gen}")

        self.btn_load_more_footer.setEnabled(False)

        if self.catalog_worker:
            try:
                self.catalog_worker.results_ready.disconnect()
            except Exception:
                pass
            try:
                self.catalog_worker.error.disconnect()
            except Exception:
                pass
            try:
                self.catalog_worker.finished.disconnect()
            except Exception:
                pass
            self.catalog_worker.deleteLater()
            self.catalog_worker = None

        self.catalog_worker = MiniAppCatalogWorker(
            gen,
            app_id=app_id,
            page=page,
            query=query,
            parent=self,
        )
        self.catalog_worker.results_ready.connect(lambda g, r: self._on_catalog_ready(g, r, is_append))
        self.catalog_worker.error.connect(lambda g, e: self._on_catalog_error(g, e, is_append))
        self.catalog_worker.finished.connect(lambda g=gen: self._on_catalog_worker_finished(g))
        self.catalog_worker.start()

    def _on_catalog_worker_finished(self, worker_gen: int):
        """Chỉ chạy pending request sau khi QThread.finished được phát và isRunning() == False."""
        self.log_drawer.log_info(f"MiniAppCatalogWorker (gen={worker_gen}) đã kết thúc (finished).")

        if worker_gen != self._catalog_gen:
            self.log_drawer.log_info(f"Worker MiniApp cũ gen {worker_gen} đã finished. Đang kích hoạt pending request cho gen mới nhất {self._catalog_gen}...")
            if self._pending_catalog_request:
                self._run_pending_catalog_request()
            else:
                self._set_loading(False)
            return

        self._set_loading(False)

        if self._pending_catalog_request:
            self._run_pending_catalog_request()

    def _run_pending_catalog_request(self) -> bool:
        """Kích hoạt ngay yêu cầu catalog đang xếp hàng khi worker đã thực sự finished."""
        if self._pending_catalog_request:
            req = self._pending_catalog_request
            self._pending_catalog_request = None
            self._execute_catalog_request(
                app_id=req["source_id"],
                query=req["query"],
                page=req["page"],
                is_append=req["append"],
                gen=self._catalog_gen,
            )
            return True
        return False

    def load_catalog(self, is_append: bool = False):
        """Bí danh tương thích ngược gọi qua request_catalog_reload."""
        if self._is_busy and is_append:
            return
        self.request_catalog_reload(
            source_id=self.get_selected_app_id(),
            query=self.current_query,
            page=self.current_page if is_append else 1,
            append=is_append,
            reason="Tải danh mục",
        )

    def _check_and_run_pending_request(self) -> bool:
        """Alias tương thích ngược."""
        return self._run_pending_catalog_request()

    def _on_catalog_ready(self, gen: int, res: CatalogResult, is_append: bool = False):
        if gen != self._catalog_gen:
            self.log_drawer.log_info(f"Bỏ qua kết quả MiniApp cũ (gen {gen} != hiện tại {self._catalog_gen})")
            return

        if getattr(res, "error", None):
            raw_err = str(res.error)
            err_lower = raw_err.lower()

            if any(k in err_lower for k in ("401", "token", "session", "đăng nhập", "hết hạn")):
                friendly = sanitize_error_message(raw_err)
                is_401 = True
            elif any(k in err_lower for k in ("dữ liệu danh mục từ nguồn đã thay đổi", "không đúng định dạng", "keyerror", "json", "schema")):
                friendly = "Dữ liệu từ nguồn không đúng định dạng"
                is_401 = False
            elif any(k in err_lower for k in ("kết nối", "connection", "timeout", "network", "tls", "ca-bundle", "ssl")):
                friendly = "Không thể kết nối nguồn phim"
                is_401 = False
            else:
                friendly = sanitize_error_message(raw_err)
                is_401 = False

            self.log_drawer.log_error(f"Lỗi nạp danh mục: {raw_err}")
            if not is_append:
                self._clear_grid()
                if is_401:
                    self.empty_state.show_session_expired("Phiên đăng nhập đã hết hạn", "Vui lòng đồng bộ lại cookie từ Extension", callback=self._on_sync_clicked)
                else:
                    self.empty_state.show_error(friendly, callback=lambda: self.request_catalog_reload(source_id=self.get_selected_app_id(), query=self.current_query, page=self.current_page, append=False, reason="Thử lại"))
                self.grid_layout.addWidget(self.empty_state, 0, 0)
                self.lbl_status.setText(friendly)
            else:
                self.lbl_status.setText(f"Không thể tải thêm: {friendly}")
            self.btn_load_more_footer.setVisible(False)
            return

        if not is_append:
            self._clear_grid()
            self._loaded_series_ids.clear()

        new_items = []
        for item in (res.items or []):
            if item.id not in self._loaded_series_ids:
                self._loaded_series_ids.add(item.id)
                new_items.append(item)

        if not self._loaded_series_ids:
            self._clear_grid()
            if self.current_query and self.current_query.strip():
                empty_title = "Không có phim phù hợp với từ khóa"
                empty_desc = f"Không tìm thấy phim nào khớp với '{self.current_query}'."
            else:
                empty_title = "Chưa có phim phù hợp"
                empty_desc = "Thử tìm kiếm với từ khóa khác hoặc chọn nguồn MiniApp khác."
            self.empty_state.show_empty(empty_title, empty_desc)
            self.grid_layout.addWidget(self.empty_state, 0, 0)
            self.lbl_status.setText(empty_title)
            self.btn_load_more_footer.setVisible(False)
            self.log_drawer.log_info(f"Danh mục MiniApp rỗng: {empty_title}")
            return

        app_id = self.get_selected_app_id()
        for item in new_items:
            card = MiniAppCardWidget(item, self.thumb_loader, app_id=app_id, parent=self.grid_container)
            card.clicked.connect(self._on_card_single_clicked)
            card.double_clicked.connect(self._on_card_double_clicked)
            self._cards.append(card)

        self._has_more = getattr(res, "has_more", False)
        self.btn_next.setEnabled(self._has_more)
        self.lbl_page.setText(f"Trang {self.current_page}")
        self._relayout_cards(force=True)
        QTimer.singleShot(0, lambda: self._relayout_cards(force=True))
        QTimer.singleShot(100, lambda: self._relayout_cards(force=True))

        source_name = self.cbo_source.currentText()
        if self._has_more:
            self.lbl_status.setText(f"Đã tải {len(self._cards)} phim (Cuộn xuống để xem thêm)")
            self.btn_load_more_footer.setVisible(True)
            self.btn_load_more_footer.setEnabled(True)
        else:
            self.lbl_status.setText(f"Đã hiển thị toàn bộ {len(self._cards)} phim ({source_name})")
            self.btn_load_more_footer.setVisible(False)

        self.log_drawer.log_info(f"Nạp thành công {len(new_items)} phim mới từ {source_name} (Tổng hiển thị: {len(self._cards)})")

    def _on_catalog_error(self, gen: int, err_msg: str, is_append: bool = False):
        if gen != self._catalog_gen:
            self.log_drawer.log_info(f"Bỏ qua lỗi từ worker MiniApp cũ (gen {gen} != {self._catalog_gen}): {err_msg}")
            return

        raw_err = str(err_msg)
        err_lower = raw_err.lower()

        if any(k in err_lower for k in ("401", "token", "session", "đăng nhập", "hết hạn")):
            friendly = sanitize_error_message(raw_err)
            is_401 = True
        elif any(k in err_lower for k in ("dữ liệu danh mục từ nguồn đã thay đổi", "không đúng định dạng", "keyerror", "json", "schema")):
            friendly = "Dữ liệu từ nguồn không đúng định dạng"
            is_401 = False
        elif any(k in err_lower for k in ("kết nối", "connection", "timeout", "network", "tls", "ca-bundle", "ssl")):
            friendly = "Không thể kết nối nguồn phim"
            is_401 = False
        else:
            friendly = sanitize_error_message(raw_err)
            is_401 = False

        self.log_drawer.log_error(f"Lỗi MiniAppCatalogWorker: {raw_err}")
        if not is_append:
            self._clear_grid()
            if is_401:
                self.empty_state.show_session_expired("Phiên đăng nhập đã hết hạn", "Vui lòng đồng bộ lại cookie từ Extension", callback=self._on_sync_clicked)
            else:
                self.empty_state.show_error(friendly, callback=lambda: self.request_catalog_reload(source_id=self.get_selected_app_id(), query=self.current_query, page=self.current_page, append=False, reason="Thử lại"))
            self.grid_layout.addWidget(self.empty_state, 0, 0)
            self.lbl_status.setText(friendly)
        else:
            self.lbl_status.setText(f"Không thể tải thêm: {friendly}")
        self.btn_load_more_footer.setVisible(False)

    def _on_card_single_clicked(self, item: CatalogItem):
        """Single-click: Đánh dấu chọn card và cập nhật thông báo hướng dẫn."""
        sender_card = self.sender()
        if self._selected_card and self._selected_card != sender_card:
            self._selected_card.set_selected(False)

        if isinstance(sender_card, MiniAppCardWidget):
            sender_card.set_selected(True)
            self._selected_card = sender_card

        self.lbl_status.setText(f"Đã chọn: '{item.name}'. Nhấp đúp hoặc bấm 'Xem tập' để tải.")
        self.lbl_status.setStyleSheet("color: #38bdf8;")

    def _on_card_double_clicked(self, item: CatalogItem):
        """Double-click hoặc bấm 'Xem tập': Nạp chi tiết tập và mở dialog."""
        sender_card = self.sender()
        if self._selected_card and self._selected_card != sender_card:
            self._selected_card.set_selected(False)

        if isinstance(sender_card, MiniAppCardWidget):
            sender_card.set_selected(True)
            self._selected_card = sender_card

        self._fetch_series_detail(item)

    def _fetch_series_detail(self, item: CatalogItem):
        """Khởi động detail worker với guard generation chống stale overwrite."""
        self._detail_gen += 1
        current_gen = self._detail_gen

        self._set_loading(True, f"Đang tải danh sách tập cho '{item.name}'...")

        if self.detail_worker:
            try:
                self.detail_worker.series_ready.disconnect()
                self.detail_worker.error.disconnect()
            except Exception:
                pass

        app_id = self.get_selected_app_id()
        self.detail_worker = MiniAppDetailWorker(current_gen, item.link or item.id, app_id=app_id, parent=self)
        self.detail_worker.series_ready.connect(self._on_series_ready)
        self.detail_worker.error.connect(self._on_series_error)
        self.detail_worker.start()

    def _on_series_ready(self, gen: int, series: Series):
        if gen != self._detail_gen:
            return

        self._set_loading(False)
        free_count = sum(1 for e in series.episodes if e.access_state in ("free", "authorized") and not e.locked)
        vip_count = len(series.episodes) - free_count

        self.lbl_status.setText(f"Đã tải {len(series.episodes)} tập: {free_count} Free, {vip_count} VIP")
        self.lbl_status.setStyleSheet("color: #10b981;")

        app_id = self.get_selected_app_id()
        main_win = self.window()
        base_folder = getattr(main_win, "save_folder", "") or os.path.join(os.getcwd(), "downloads")

        dialog = MiniAppEpisodeDialog(series, app_id=app_id, base_folder=base_folder, parent=self)
        dialog.episodes_selected.connect(
            lambda eps: self._on_episodes_selected(eps, series, dest_dir=dialog.get_destination_dir())
        )
        dialog.exec()

    def _on_series_error(self, gen: int, err_msg: str):
        if gen != self._detail_gen:
            return

        self._set_loading(False)
        raw_err = str(err_msg)
        err_lower = raw_err.lower()

        is_auth_error = any(k in err_lower for k in ("401", "token", "session", "phiên", "auth", "xác thực"))
        if is_auth_error:
            self.log_error(f"[ERROR] Playlist bị từ chối: HTTP 401 - {sanitize_log_text(raw_err)}")
            self.set_session_state(SESSION_STATE_SESSION_EXPIRED)
            self.lbl_status.setText("Phiên cần xác thực lại. Vui lòng bấm Đồng bộ phiên.")
            self.lbl_status.setStyleSheet("color: #ef4444;")
            self.btn_reauth.setVisible(True)
            self.btn_retry.setVisible(False)
        else:
            self.log_error(f"[ERROR] Lỗi nạp tập phim: {sanitize_log_text(raw_err)}")
            self.lbl_status.setText(f"Lỗi nạp tập phim: {sanitize_error_message(raw_err)}")
            self.lbl_status.setStyleSheet("color: #ef4444;")
            self.btn_retry.setVisible(True)
            self.btn_reauth.setVisible(False)

    def _on_episodes_selected(self, episodes: list, series: Series, dest_dir: str = ""):
        """
        Chuyển danh sách tập Free đã chọn sang hàng đợi tải chuẩn của HyperMedia.
        Tổ chức cấu trúc thư mục lưu theo MiniApp và tên bộ phim:
        downloads/MiniApp Douyin/{Tên MiniApp Việt hóa}/{Tên bộ phim}/
        """
        app_id = self.get_selected_app_id()
        source_disp = get_miniapp_display_name(app_id)

        if not dest_dir:
            main_win = self.window()
            base_folder = getattr(main_win, "save_folder", "") or os.path.join(os.getcwd(), "downloads")
            dest_dir = build_drama_destination_dir(
                base_folder,
                "miniapp_douyin",
                series.name,
                source_app_id=app_id,
            )

        from site_utils import detect_site
        queue_items = []
        for ep in episodes:
            # Tuyệt đối bảo vệ: Cấm nạp tập VIP hoặc locked chưa được ủy quyền
            if ep.locked or ep.access_state not in ("free", "authorized"):
                continue

            # Xác định tên file gốc và giải quyết trùng lặp (Dup1_, Dup2_)
            ep_title = ep.title or f"Tập {ep.num}"
            clean_title = sanitize_windows_filename(ep_title, max_len=80, fallback=f"Tập {ep.num}")
            base_stem = f"{ep.num:02d} - {clean_title}" if not clean_title.startswith(f"{ep.num:02d} -") else clean_title
            exact_stem, _ = resolve_unique_drama_filepath(dest_dir, base_stem, ext="mp4", allow_duplicates=True)

            ep_id = str(getattr(ep, "episode_id", "") or (ep.extra or {}).get("episode_id") or "")
            ep_num = getattr(ep, "episode_number", 0) or ep.num
            masked_ep = f"{ep_id[:6]}***" if len(ep_id) > 6 else (ep_id or f"ep{ep_num}")
            self.log_info(f"[QUEUE] provider=miniapp_douyin episode={masked_ep} access={ep.access_state}")

            title = f"{series.name} - {ep.title}"
            subs_serialized = [s.to_dict() if hasattr(s, "to_dict") else dict(s) for s in (getattr(ep, "subtitles", None) or [])]
            queue_items.append({
                "title": title,
                "url": ep.url,
                "source_url": ep.url,
                "direct_url": getattr(ep, "direct_url", None),
                "expires_at": getattr(ep, "expires_at", None),
                "thumb": ep.thumb or series.cover,
                "heights": [],
                "item_index": ep.num,
                "episode_number": ep_num,
                "episode_id": ep_id,
                "access_state": ep.access_state,
                "locked": bool(ep.locked),
                "provider": "miniapp_douyin",
                "provider_id": "miniapp_douyin",
                "platform": "miniapp_douyin",
                "source_app_id": app_id,
                "source_name": self.cbo_source.currentText(),
                "source_display_name": source_disp,
                "series_id": series.series_id,
                "series_name": series.name,
                "output_dir": dest_dir,
                "exact_file_stem": exact_stem,
                "subtitle_url": getattr(ep, "subtitle", None) or (subs_serialized[0]["url"] if subs_serialized else ""),
                "subtitles": subs_serialized,
                "headers": detect_site(ep.url),
                "extra": dict(ep.extra or {}),
                "formats": [{
                    "format_id": "best",
                    "ext": "mp4",
                    "resolution": "best",
                }],
            })

        if not queue_items:
            return

        self.queue_episodes_requested.emit(queue_items, series.name)
        self.lbl_status.setText(f"Đã thêm {len(queue_items)} tập vào hàng đợi tải")
        self.lbl_status.setStyleSheet("color: #10b981;")
        QMessageBox.information(
            self,
            "Đã thêm vào hàng đợi",
            f"Đã thêm thành công {len(queue_items)} tập phim của '{series.name}' vào hàng đợi tải!\n"
            f"Thư mục đích: {dest_dir}",
        )
