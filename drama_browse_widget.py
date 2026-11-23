"""
drama_browse_widget.py
~~~~~~~~~~~~~~~~~~~~~~
Widget tab 'Khám Phá Phim' hỗ trợ duyệt poster, phân trang, lọc/tìm kiếm,
xem chi tiết tập phim và đẩy vào hàng đợi tải.
"""

import os
from typing import Optional, List
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
    QMessageBox,
)
from PySide6.QtGui import QFont, QPixmap, QCursor
from lucide_icons import get_lucide_icon
from log_drawer_widget import LogDrawerWidget
from empty_state_widget import EmptyStateWidget
from ca_bundle_utils import sanitize_error_message, sanitize_log_text
import providers
from providers.base import CatalogItem, CatalogResult, Series
from drama_dialog import DramaEpisodeDialog
from thumbnail_loader import ThumbnailLoader
from drama_path_utils import (
    build_drama_destination_dir,
    build_drama_filename,
    resolve_unique_drama_filepath,
)


class CatalogWorker(QThread):
    results_ready = Signal(int, object)  # generation, CatalogResult
    error = Signal(int, str)  # generation, error_msg

    def __init__(self, generation: int, platform_id: str, page: int = 1, query: str = "", parent=None):
        super().__init__(parent)
        self.generation = generation
        self.platform_id = platform_id
        self.page = page
        self.query = query

    def run(self):
        try:
            p = providers.get_provider(self.platform_id)
            if not p:
                self.error.emit(self.generation, f"Không tìm thấy provider: {self.platform_id}")
                return
            res = p.get_catalog(page=self.page, query=self.query)
            self.results_ready.emit(self.generation, res)
        except Exception as e:
            self.error.emit(self.generation, str(e))


class SeriesDetailWorker(QThread):
    series_ready = Signal(int, object)  # generation, Series
    error = Signal(int, str)  # generation, error_msg

    def __init__(self, generation: int, link_or_id: str, platform_id: str = "", parent=None):
        super().__init__(parent)
        self.generation = generation
        self.link_or_id = link_or_id
        self.platform_id = platform_id

    def run(self):
        try:
            series = providers.load_series(self.link_or_id, platform_hint=self.platform_id)
            self.series_ready.emit(self.generation, series)
        except Exception as e:
            self.error.emit(self.generation, str(e))


class DramaCardWidget(QFrame):
    clicked = Signal(object)  # CatalogItem

    def __init__(self, item: CatalogItem, thumb_loader: ThumbnailLoader, parent=None):
        super().__init__(parent)
        self.item = item
        self.thumb_loader = thumb_loader

        self.setFixedSize(168, 275)
        self.setCursor(QCursor(Qt.PointingHandCursor))
        self.setStyleSheet("""
            DramaCardWidget {
                background-color: #161824;
                border: 1px solid #232738;
                border-radius: 8px;
            }
            DramaCardWidget:hover {
                border: 1.5px solid #3b82f6;
                background-color: #1d2136;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        self.lbl_thumb = QLabel()
        self.lbl_thumb.setFixedSize(152, 195)
        self.lbl_thumb.setStyleSheet("background-color: #0f1017; border-radius: 6px; border: 1px solid #1e2230; color: #64748b; font-size: 11px;")
        self.lbl_thumb.setAlignment(Qt.AlignCenter)
        if self.item.cover:
            self.lbl_thumb.setText("Đang tải ảnh...")
            self.thumb_loader.load_thumbnail(self.item.cover, self._on_thumb_loaded)
        else:
            self.lbl_thumb.setText("Không có ảnh")
        layout.addWidget(self.lbl_thumb)

        self.lbl_title = QLabel(self.item.name)
        self.lbl_title.setStyleSheet("color: #f1f5f9; font-weight: 600; font-size: 11px;")
        self.lbl_title.setWordWrap(True)
        self.lbl_title.setMaximumHeight(32)
        layout.addWidget(self.lbl_title)

        sub_layout = QHBoxLayout()
        lbl_ep = QLabel(f" {self.item.episodes} tập " if self.item.episodes else " Series ")
        lbl_ep.setStyleSheet("background-color: #064e3b; color: #34d399; font-size: 10px; font-weight: 600; border-radius: 3px; padding: 1px 4px;")
        sub_layout.addWidget(lbl_ep)

        lbl_plat = QLabel(f" {self.item.platform.upper()} ")
        lbl_plat.setStyleSheet("background-color: #1e293b; color: #94a3b8; font-size: 9px; font-weight: 600; border-radius: 3px; padding: 1px 4px;")
        lbl_plat.setAlignment(Qt.AlignRight)
        sub_layout.addWidget(lbl_plat)

        layout.addLayout(sub_layout)

    def _on_thumb_loaded(self, pixmap: Optional[QPixmap]):
        if pixmap and isinstance(pixmap, QPixmap) and not pixmap.isNull():
            self.lbl_thumb.setPixmap(
                pixmap.scaled(self.lbl_thumb.size(), Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
            )
        else:
            self.lbl_thumb.setPixmap(QPixmap())
            self.lbl_thumb.setText("Không có ảnh")

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit(self.item)
        super().mousePressEvent(event)


class DramaBrowseWidget(QWidget):
    queue_episodes_requested = Signal(list, str)  # list of dicts for queue, series_name

    def __init__(self, parent=None):
        super().__init__(parent)
        self.current_page = 1
        self.current_query = ""
        self._catalog_gen = 0
        self._detail_gen = 0
        self._loaded_series_ids = set()
        self._cards = []
        self._current_cols = -1
        self._is_append = False
        self._is_loading = False
        self._has_more = False
        self._total_count = 0
        self._pending_catalog_request = None
        self._last_valid_platform_idx = 0
        self.thumb_loader = ThumbnailLoader(self)
        self.catalog_worker = None
        self.detail_worker = None

        self._init_ui()
        self.populate_platforms(include_planned=False)
        self._load_catalog()

    def shutdown(self):
        """Dừng an toàn các worker bất đồng bộ khi đóng ứng dụng."""
        if self.catalog_worker and self.catalog_worker.isRunning():
            try:
                self.catalog_worker.results_ready.disconnect()
                self.catalog_worker.error.disconnect()
            except Exception:
                pass
            self.catalog_worker.wait(500)
        if self.detail_worker and self.detail_worker.isRunning():
            try:
                self.detail_worker.series_ready.disconnect()
                self.detail_worker.error.disconnect()
            except Exception:
                pass
            self.detail_worker.wait(500)

    def _init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(14, 14, 14, 14)
        main_layout.setSpacing(12)

        # 1. Header Toolbar
        top_bar = QHBoxLayout()
        top_bar.setSpacing(10)

        lbl_platform = QLabel("Nguồn phim:")
        lbl_platform.setStyleSheet("font-weight: bold; color: #9ca3af;")
        top_bar.addWidget(lbl_platform)

        self.cb_platform = QComboBox()
        self.cb_platform.setMinimumWidth(180)
        self.cb_platform.currentIndexChanged.connect(self._on_platform_changed)
        top_bar.addWidget(self.cb_platform)

        self.txt_search = QLineEdit()
        self.txt_search.setPlaceholderText("Tìm kiếm phim theo tên / từ khóa...")
        self.txt_search.setStyleSheet("""
            QLineEdit {
                background-color: #0f172a;
                border: 1px solid #1e293b;
                border-radius: 6px;
                padding: 6px 10px;
                color: #f8fafc;
                font-size: 12px;
            }
            QLineEdit:focus {
                border: 1px solid #3b82f6;
            }
        """)
        self.txt_search.returnPressed.connect(self._on_search)
        top_bar.addWidget(self.txt_search, stretch=1)

        self.btn_search = QPushButton(" Tìm kiếm")
        self.btn_search.setIcon(get_lucide_icon("search", "#ffffff", 14))
        self.btn_search.setFixedHeight(34)
        self.btn_search.setStyleSheet("""
            QPushButton {
                background-color: #2563eb; color: white; font-weight: 600; font-size: 12px;
                border-radius: 6px; padding: 6px 16px; border: none;
            }
            QPushButton:hover { background-color: #1d4ed8; }
            QPushButton:disabled { background-color: #1e3a8a; color: #93c5fd; }
        """)
        self.btn_search.clicked.connect(self._on_search)
        top_bar.addWidget(self.btn_search)

        self.btn_refresh = QPushButton(" Làm mới")
        self.btn_refresh.setIcon(get_lucide_icon("rotate-cw", "#e5e7eb", 14))
        self.btn_refresh.setFixedHeight(34)
        self.btn_refresh.setStyleSheet("""
            QPushButton {
                background-color: #1f2937; color: #e5e7eb; font-weight: 500; font-size: 12px;
                border: 1px solid #374151; border-radius: 6px; padding: 6px 14px;
            }
            QPushButton:hover { background-color: #374151; }
            QPushButton:disabled { background-color: #111827; color: #4b5563; }
        """)
        self.btn_refresh.clicked.connect(self._on_refresh)
        top_bar.addWidget(self.btn_refresh)

        main_layout.addLayout(top_bar)

        # 2. Main Scroll Area: Grid of Poster Cards with Infinite Scroll
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.viewport().installEventFilter(self)
        self.scroll_area.setStyleSheet("""
            QScrollArea {
                border: 1px solid #2d3748;
                border-radius: 8px;
                background-color: #12131a;
            }
        """)
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

        # 3. Log Drawer (Thu gọn mặc định - Progressive Disclosure)
        self.log_drawer = LogDrawerWidget("Nhật ký Khám Phá Phim", parent=self)
        self.log_drawer.setVisible(False)
        self.log_drawer.closed.connect(self._on_log_drawer_closed)
        main_layout.addWidget(self.log_drawer)

        # 4. Status Footer (Bỏ phân trang nút bấm, giữ Infinite Scroll & Nút phụ trợ)
        footer_layout = QHBoxLayout()
        footer_layout.setContentsMargins(2, 4, 2, 2)
        footer_layout.setSpacing(10)

        self.lbl_status = QLabel("Sẵn sàng")
        self.lbl_status.setStyleSheet("color: #94a3b8; font-size: 11px;")
        footer_layout.addWidget(self.lbl_status)

        footer_layout.addStretch()

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
        self.btn_load_more_footer.clicked.connect(self._on_load_more)
        footer_layout.addWidget(self.btn_load_more_footer)

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
        footer_layout.addWidget(self.btn_log)

        main_layout.addLayout(footer_layout)

        # Backward compatibility aliases & stubs for test harness
        self.btn_load_more = self.btn_load_more_footer
        self.btn_prev = QPushButton()
        self.btn_prev.setEnabled(False)
        self.btn_prev.hide()
        self.btn_next = QPushButton()
        self.btn_next.hide()
        self.lbl_page = QLabel("Trang 1")
        self.lbl_page.hide()

    def eventFilter(self, obj, event):
        if obj is self.scroll_area.viewport() and event.type() == QEvent.Type.Resize:
            self._relayout_cards()
        return super().eventFilter(obj, event)

    def populate_platforms(self, include_planned: bool = False):
        """Đổ danh sách các provider vào dropdown theo kiến trúc phân loại Group A/B."""
        self.cb_platform.blockSignals(True)
        self.cb_platform.clear()

        # Nhóm A: Browse Catalog Enabled (supports_catalog=True)
        catalog_providers = providers.get_catalog_providers()
        for p in catalog_providers:
            self.cb_platform.addItem(p.display_name, p.platform_id)
            idx = self.cb_platform.count() - 1
            item = self.cb_platform.model().item(idx)
            if item:
                item.setEnabled(True)

        # Nhóm B: URL-only / Planned (chỉ hiện khi include_planned=True và disabled)
        if include_planned:
            other_providers = providers.get_url_only_providers() + providers.get_planned_providers()
            for p in other_providers:
                label = f"{p.display_name} — Sắp hỗ trợ duyệt danh mục"
                self.cb_platform.addItem(label, p.platform_id)
                idx = self.cb_platform.count() - 1
                item = self.cb_platform.model().item(idx)
                if item:
                    item.setEnabled(False)

        if self.cb_platform.count() > 0:
            self.cb_platform.setCurrentIndex(0)
            self._last_valid_platform_idx = 0
        self.cb_platform.blockSignals(False)

    def _on_platform_changed(self):
        idx = self.cb_platform.currentIndex()
        if idx < 0:
            return
        model = self.cb_platform.model()
        item = model.item(idx) if model else None
        if item and not item.isEnabled():
            # Chặn chọn provider bị disable, hoàn trả về provider hợp lệ trước đó
            self.cb_platform.blockSignals(True)
            self.cb_platform.setCurrentIndex(self._last_valid_platform_idx)
            self.cb_platform.blockSignals(False)
            return

        self._last_valid_platform_idx = idx
        self.current_page = 1
        self.lbl_page.setText("Trang 1")
        self.current_query = ""
        self.txt_search.clear()
        platform_id = self.cb_platform.currentData() or "hongguo"
        self.request_catalog_reload(source_id=platform_id, query="", page=1, append=False, reason="Đổi nguồn phim")

    def _on_search(self):
        text = self.txt_search.text().strip()
        if text and (text.startswith("http://") or text.startswith("https://") or providers.detect_provider(text)):
            self._load_series_from_url(text)
            return

        self.current_query = text
        self.current_page = 1
        self.lbl_page.setText("Trang 1")
        self.request_catalog_reload(query=text, page=1, append=False, reason="Tìm kiếm phim")

    def _on_refresh(self):
        self.request_catalog_reload(page=1, append=False, reason="Làm mới danh mục")

    def _on_load_more(self):
        if self._is_loading or not self._has_more:
            return
        self.current_page += 1
        self.lbl_page.setText(f"Trang {self.current_page}")
        self.request_catalog_reload(page=self.current_page, append=True, reason="Tải thêm trang")

    def on_cookie_synced(self, *args, **kwargs):
        """Tự động làm mới danh mục khi nhận tín hiệu đồng bộ cookie mới từ extension."""
        self.log_drawer.log_info("Nhận thông báo đồng bộ cookie từ extension.")
        self.request_catalog_reload(reason="Phiên đã thay đổi, đang làm mới dữ liệu")

    def request_catalog_reload(
        self,
        source_id: Optional[str] = None,
        query: Optional[str] = None,
        page: int = 1,
        append: bool = False,
        reason: str = "",
    ):
        """Yêu cầu nạp catalog với cơ chế race-guard: tăng generation ngay lập tức và xếp hàng nếu bận."""
        self._catalog_gen += 1
        current_gen = self._catalog_gen

        # Bảo vệ source_id và query mới nhất: nếu không truyền rõ ràng, ưu tiên kế thừa từ pending request trước đó
        prev_source = self._pending_catalog_request.get("source_id") if self._pending_catalog_request else None
        platform_id = source_id or prev_source or self.cb_platform.currentData() or "hongguo"
        q = self.current_query if query is None else query

        if self._is_loading or (self.catalog_worker and self.catalog_worker.isRunning()):
            self._pending_catalog_request = {
                "source_id": platform_id,
                "query": q,
                "page": page,
                "append": append,
                "reason": reason,
            }
            if reason:
                self.lbl_status.setText(reason)
            self.log_drawer.log_info(
                f"Yêu cầu tải {platform_id} (gen={current_gen}) được đưa vào hàng đợi chờ worker hoàn tất ({reason})."
            )
            return

        self._execute_catalog_request(platform_id, q, page, append, current_gen)

    def _execute_catalog_request(self, platform_id: str, query: str, page: int, is_append: bool, gen: int):
        self._is_loading = True
        self._is_append = is_append
        self.current_page = page
        self.current_query = query

        p_obj = providers.get_provider(platform_id)
        disp_name = p_obj.display_name if p_obj else platform_id.upper()

        if not is_append:
            self._loaded_series_ids.clear()
            self._clear_grid()
            self.empty_state.show_loading(f"Đang tải danh mục từ {disp_name}...", f"Đang kết nối đến nguồn {disp_name}...")
            self.grid_layout.addWidget(self.empty_state, 0, 0)
            self.lbl_status.setText(f"Đang tải danh mục từ {disp_name}...")
            self.log_drawer.log_info(f"Nạp danh mục: {platform_id}, query='{query}', gen={gen}")
        else:
            self.lbl_status.setText(f"Đang tải thêm phim (Trang {page})...")
            self.log_drawer.log_info(f"Tải thêm trang {page} cho {platform_id}, gen={gen}")

        self.btn_load_more_footer.setEnabled(False)

        # Dọn dẹp an toàn worker cũ nếu đã hoàn tất
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

        self.catalog_worker = CatalogWorker(gen, platform_id, page, query, parent=self)
        self.catalog_worker.results_ready.connect(self._on_catalog_ready)
        self.catalog_worker.error.connect(self._on_catalog_error)
        self.catalog_worker.finished.connect(lambda g=gen: self._on_catalog_worker_finished(g))
        self.catalog_worker.start()

    def _on_catalog_worker_finished(self, worker_gen: int):
        """Chỉ chạy pending request sau khi QThread.finished được phát và isRunning() == False."""
        self.log_drawer.log_info(f"CatalogWorker (gen={worker_gen}) đã kết thúc (finished).")

        if worker_gen != self._catalog_gen:
            self.log_drawer.log_info(f"Worker cũ gen {worker_gen} đã finished. Đang kích hoạt pending request cho gen mới nhất {self._catalog_gen}...")
            if self._pending_catalog_request:
                self._run_pending_catalog_request()
            else:
                self._is_loading = False
            return

        self._is_loading = False

        if self._pending_catalog_request:
            self._run_pending_catalog_request()

    def _run_pending_catalog_request(self) -> bool:
        """Kích hoạt ngay yêu cầu danh mục đang xếp hàng khi worker đã thực sự finished."""
        if self._pending_catalog_request:
            req = self._pending_catalog_request
            self._pending_catalog_request = None
            self._execute_catalog_request(
                platform_id=req["source_id"],
                query=req["query"],
                page=req["page"],
                is_append=req["append"],
                gen=self._catalog_gen,
            )
            return True
        return False

    def _check_and_run_pending_request(self) -> bool:
        """Alias tương thích ngược."""
        return self._run_pending_catalog_request()

    def _load_catalog(self, is_append: bool = False):
        """Bí danh tương thích ngược gọi qua request_catalog_reload."""
        self.request_catalog_reload(
            source_id=self.cb_platform.currentData(),
            query=self.current_query,
            page=self.current_page if is_append else 1,
            append=is_append,
            reason="Tải danh mục",
        )

    def _on_scroll_changed(self, value: int):
        bar = self.scroll_area.verticalScrollBar()
        if bar.maximum() > 0 and value >= bar.maximum() - 150:
            if self._has_more and not self._is_loading:
                self._on_load_more()

    def _toggle_log_drawer(self):
        vis = not self.log_drawer.isVisible()
        self.log_drawer.setVisible(vis)
        self.btn_log.setText(" Đóng nhật ký" if vis else " Nhật ký")

    def _on_log_drawer_closed(self):
        self.btn_log.setText(" Nhật ký")

    def log_info(self, msg: str):
        self.log_drawer.log_info(msg)

    def log_warn(self, msg: str):
        self.log_drawer.log_warn(msg)

    def log_error(self, msg: str):
        self.log_drawer.log_error(msg)

    def _clear_grid(self):
        while self.grid_layout.count():
            item = self.grid_layout.takeAt(0)
            widget = item.widget()
            if widget and widget is not self.empty_state:
                widget.deleteLater()
        if hasattr(self, "empty_state") and self.empty_state:
            self.empty_state.setVisible(False)
        self._cards.clear()

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
        card_w = 168
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

    def _on_catalog_ready(self, gen: int, res: CatalogResult):
        if gen != self._catalog_gen:
            self.log_drawer.log_info(f"Bỏ qua kết quả danh mục cũ (gen {gen} != hiện tại {self._catalog_gen})")
            return

        if getattr(res, "error", None):
            raw_err = str(res.error)
            err_lower = raw_err.lower()
            p_obj = providers.get_provider(res.platform)

            if p_obj and not getattr(p_obj, "supports_catalog", False):
                friendly_title = "Danh mục chưa hỗ trợ cho nguồn này"
            elif any(k in err_lower for k in ("dữ liệu danh mục từ nguồn đã thay đổi", "không đúng định dạng", "keyerror", "json", "schema")):
                friendly_title = "Dữ liệu từ nguồn không đúng định dạng"
            elif any(k in err_lower for k in ("kết nối", "connection", "timeout", "network", "tls", "ca-bundle", "ssl")):
                friendly_title = "Không thể kết nối nguồn phim"
            else:
                friendly_title = sanitize_error_message(raw_err)

            self.log_drawer.log_error(f"Lỗi nạp danh sách: {raw_err}")
            if not self._is_append:
                self._clear_grid()
                self.empty_state.show_error(
                    friendly_title,
                    callback=lambda: self.request_catalog_reload(source_id=res.platform, query=self.current_query, page=self.current_page, append=False, reason="Thử lại"),
                )
                self.grid_layout.addWidget(self.empty_state, 0, 0)
                self.lbl_status.setText(friendly_title)
            else:
                self.lbl_status.setText(f"Không thể tải thêm: {friendly_title}")
            self.btn_load_more_footer.setVisible(False)
            return

        if not self._is_append:
            self._clear_grid()
            self._loaded_series_ids.clear()

        # Lọc các phim chưa từng hiển thị để chống trùng lặp
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
                empty_desc = "Thử tìm kiếm với từ khóa khác hoặc chuyển sang nguồn phim khác."
            self.empty_state.show_empty(empty_title, empty_desc)
            self.grid_layout.addWidget(self.empty_state, 0, 0)
            self.lbl_status.setText(empty_title)
            self.btn_load_more_footer.setVisible(False)
            self.log_drawer.log_info(f"Danh mục rỗng: {empty_title}")
            return

        for item in new_items:
            card = DramaCardWidget(item, self.thumb_loader, parent=self.grid_container)
            card.clicked.connect(self._on_card_clicked)
            self._cards.append(card)

        self._has_more = getattr(res, "has_more", False)
        self._total_count = getattr(res, "total", 0)
        self.btn_prev.setEnabled(self.current_page > 1)
        self.btn_next.setEnabled(self._has_more)
        self.lbl_page.setText(f"Trang {self.current_page}")

        self._relayout_cards(force=True)
        QTimer.singleShot(0, lambda: self._relayout_cards(force=True))
        QTimer.singleShot(100, lambda: self._relayout_cards(force=True))

        if self._has_more:
            if self._total_count:
                self.lbl_status.setText(f"Đang hiển thị {len(self._cards)} / {self._total_count} phim ({res.platform.upper()})")
            else:
                self.lbl_status.setText(f"Đã tải {len(self._cards)} phim (Cuộn xuống để xem thêm)")
            self.btn_load_more_footer.setVisible(True)
            self.btn_load_more_footer.setEnabled(True)
        else:
            total_txt = f" / {self._total_count}" if self._total_count else ""
            self.lbl_status.setText(f"Đã hiển thị {len(self._cards)}{total_txt} phim")
            self.btn_load_more_footer.setVisible(False)

        self.log_drawer.log_info(f"Nạp thành công {len(new_items)} phim từ {res.platform.upper()} (Tổng hiển thị: {len(self._cards)})")

    def _on_catalog_error(self, gen: int, err_msg: str):
        if gen != self._catalog_gen:
            self.log_drawer.log_info(f"Bỏ qua lỗi từ worker cũ (gen {gen} != {self._catalog_gen}): {err_msg}")
            return

        raw_err = str(err_msg)
        err_lower = raw_err.lower()

        if any(k in err_lower for k in ("dữ liệu danh mục từ nguồn đã thay đổi", "không đúng định dạng", "keyerror", "json", "schema")):
            friendly = "Dữ liệu từ nguồn không đúng định dạng"
        elif any(k in err_lower for k in ("kết nối", "connection", "timeout", "network", "tls", "ca-bundle", "ssl")):
            friendly = "Không thể kết nối nguồn phim"
        else:
            friendly = sanitize_error_message(raw_err)

        self.log_drawer.log_error(f"CatalogWorker error: {raw_err}")
        if not self._is_append:
            self._clear_grid()
            self.empty_state.show_error(
                friendly,
                callback=lambda: self.request_catalog_reload(query=self.current_query, page=self.current_page, append=False, reason="Thử lại"),
            )
            self.grid_layout.addWidget(self.empty_state, 0, 0)
            self.lbl_status.setText(friendly)
        else:
            self.lbl_status.setText(f"Không thể tải thêm: {friendly}")
        self.btn_load_more_footer.setVisible(False)

    def _load_series_from_url(self, url: str):
        self.lbl_status.setText(f"Đang nạp thông tin phim: {url[:50]}...")
        self._detail_gen += 1
        current_gen = self._detail_gen

        if self.detail_worker:
            try:
                self.detail_worker.series_ready.disconnect()
                self.detail_worker.error.disconnect()
            except Exception:
                pass

        self.detail_worker = SeriesDetailWorker(current_gen, url, parent=self)
        self.detail_worker.series_ready.connect(self._on_series_ready)
        self.detail_worker.error.connect(self._on_series_error)
        self.detail_worker.start()

    def _on_card_clicked(self, item: CatalogItem):
        self.lbl_status.setText(f"Đang đọc danh sách tập cho '{item.name}'...")

        self._detail_gen += 1
        current_gen = self._detail_gen

        if self.detail_worker:
            try:
                self.detail_worker.series_ready.disconnect()
                self.detail_worker.error.disconnect()
            except Exception:
                pass

        self.detail_worker = SeriesDetailWorker(current_gen, item.link or item.id, platform_id=item.platform, parent=self)
        self.detail_worker.series_ready.connect(self._on_series_ready)
        self.detail_worker.error.connect(self._on_series_error)
        self.detail_worker.start()

    def _on_series_ready(self, gen: int, series: Series):
        if gen != self._detail_gen:
            return
        self.lbl_status.setText(f"Đã mở chi tiết '{series.name}' ({len(series.episodes)} tập)")
        dialog = DramaEpisodeDialog(series, parent=self)
        dialog.episodes_selected.connect(lambda eps: self._on_episodes_selected(eps, series))
        dialog.exec()

    def _on_series_error(self, gen: int, err_msg: str):
        if gen != self._detail_gen:
            return
        self.lbl_status.setText("Lỗi nạp tập phim")
        QMessageBox.warning(self, "Lỗi tải tập phim", f"Không thể lấy thông tin tập phim: {err_msg}")

    def _on_episodes_selected(self, episodes: list, series: Series):
        """Chuyển danh sách tập đã chọn sang format hàng đợi tải của app với cấu trúc thư mục chuẩn."""
        from site_utils import detect_site
        import providers

        main_win = self.window()
        base_folder = getattr(main_win, "save_folder", "") or os.path.join(os.getcwd(), "downloads")
        dest_dir = build_drama_destination_dir(
            base_folder,
            series.platform,
            series.name,
        )

        prov_obj = providers.get_provider(series.platform)
        source_name = getattr(prov_obj, "display_name", "") or self.cb_platform.currentText() or series.platform

        queue_items = []
        for ep in episodes:
            # Tuyệt đối bảo vệ: Chặn tập VIP hoặc locked chưa được ủy quyền
            if ep.locked or ep.access_state not in ("free", "authorized"):
                continue

            filename_with_ext = build_drama_filename(ep.num, ep.title, ext="mp4")
            base_stem = os.path.splitext(filename_with_ext)[0]
            exact_stem, _ = resolve_unique_drama_filepath(dest_dir, base_stem, ext="mp4", allow_duplicates=True)

            ep_id = str(getattr(ep, "episode_id", "") or (ep.extra or {}).get("episode_id") or (ep.extra or {}).get("vid") or (ep.extra or {}).get("cid") or "")
            ep_num = getattr(ep, "episode_number", 0) or ep.num
            masked_ep = f"{ep_id[:6]}***" if len(ep_id) > 6 else (ep_id or f"ep{ep_num}")
            self.log_drawer.log_info(f"[QUEUE] provider={series.platform} episode={masked_ep} access={ep.access_state}")

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
                "output_dir": dest_dir,
                "exact_file_stem": exact_stem,
                "series_id": series.series_id,
                "series_name": series.name,
                "provider": series.platform,
                "provider_id": series.platform,
                "platform": series.platform,
                "source_name": source_name,
                "episode_number": ep_num,
                "episode_id": ep_id,
                "access_state": ep.access_state,
                "locked": bool(ep.locked),
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
            QMessageBox.warning(self, "Không có tập hợp lệ", "Không có tập phim miễn phí nào được chọn.")
            return

        self.queue_episodes_requested.emit(queue_items, series.name)
        QMessageBox.information(
            self,
            "Đã thêm vào hàng đợi",
            f"Đã thêm thành công {len(queue_items)} tập phim của '{series.name}' vào danh sách tải!\nThư mục lưu: {dest_dir}",
        )
