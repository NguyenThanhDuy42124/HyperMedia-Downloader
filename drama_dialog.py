"""
drama_dialog.py
~~~~~~~~~~~~~~~
Dialog cho phép người dùng xem chi tiết series phim ngắn, chọn từng tập hoặc
chọn theo khoảng (1-5, 8, 10-12), lọc tập miễn phí, và đưa vào hàng đợi tải.
"""

from PySide6.QtCore import Qt, Signal, QTimer
from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QLineEdit,
    QScrollArea,
    QWidget,
    QGridLayout,
    QCheckBox,
    QFrame,
    QMessageBox,
)
from PySide6.QtGui import QFont, QPixmap
from providers.base import (
    Series,
    Episode,
    parse_episode_selection,
    ACCESS_STATE_FREE,
    ACCESS_STATE_AUTHORIZED,
    ACCESS_STATE_REQUIRES_LOGIN,
    ACCESS_STATE_REQUIRES_VIP,
    ACCESS_STATE_UNAVAILABLE,
)
from thumbnail_loader import ThumbnailLoader


class DramaEpisodeDialog(QDialog):
    episodes_selected = Signal(list)  # list of Episode

    def __init__(self, series: Series, parent=None):
        super().__init__(parent)
        self.series = series
        self.episode_checkboxes: dict[int, QCheckBox] = {}
        self.episode_map: dict[int, Episode] = {ep.num: ep for ep in self.series.episodes}
        self.thumb_loader = ThumbnailLoader()

        self.setWindowTitle(f"Chọn tập tải - {series.name} ({series.platform.upper()})")
        self.resize(840, 620)
        self._current_cols = -1
        self.setStyleSheet("""
            QDialog {
                background-color: #12131a;
                color: #e5e7eb;
            }
            QLabel {
                color: #e5e7eb;
            }
            QLineEdit {
                background-color: #1a1c26;
                border: 1px solid #374151;
                border-radius: 6px;
                padding: 6px 10px;
                color: #f9fafb;
            }
            QPushButton {
                background-color: #2563eb;
                color: white;
                border: none;
                border-radius: 6px;
                padding: 6px 14px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #1d4ed8;
            }
            QPushButton#btnCancel {
                background-color: #374151;
            }
            QPushButton#btnCancel:hover {
                background-color: #4b5563;
            }
            QPushButton#btnSecondary {
                background-color: #1f2937;
                border: 1px solid #374151;
            }
            QPushButton#btnSecondary:hover {
                background-color: #374151;
            }
            QCheckBox {
                spacing: 8px;
                padding: 5px 8px;
                border-radius: 6px;
                background-color: #161824;
                border: 1px solid #232738;
            }
            QCheckBox:hover {
                background-color: #1e2236;
                border: 1px solid #3b82f6;
            }
            QCheckBox:disabled {
                background-color: #10121a;
                border: 1px solid #1c1e2b;
            }
            QScrollArea {
                border: 1px solid #2d3748;
                border-radius: 8px;
                background-color: #161822;
            }
        """)

        self._init_ui()

    def _calculate_columns(self) -> int:
        w = self.width()
        cols = max(5, min(8, (w - 60) // 135))
        return cols

    def _relayout_episodes(self, force: bool = False):
        if not self.episode_checkboxes:
            return
        cols = self._calculate_columns()
        if not force and getattr(self, "_current_cols", None) == cols and self.grid_layout.count() == len(self.series.episodes):
            return
        self._current_cols = cols
        for i in reversed(range(self.grid_layout.count())):
            self.grid_layout.takeAt(i)
        for idx, ep in enumerate(self.series.episodes):
            cb = self.episode_checkboxes.get(ep.num)
            if cb:
                row = idx // cols
                col = idx % cols
                self.grid_layout.addWidget(cb, row, col)

    def showEvent(self, event):
        super().showEvent(event)
        QTimer.singleShot(0, lambda: self._relayout_episodes(force=True))
        QTimer.singleShot(50, lambda: self._relayout_episodes(force=True))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._relayout_episodes()

    def _init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(20, 20, 20, 20)
        main_layout.setSpacing(14)

        # 1. Header: Thumbnail + Metadata
        header_layout = QHBoxLayout()
        header_layout.setSpacing(16)

        self.lbl_cover = QLabel()
        self.lbl_cover.setFixedSize(90, 120)
        self.lbl_cover.setStyleSheet("border-radius: 6px; background-color: #1e2230; border: 1px solid #374151;")
        self.lbl_cover.setAlignment(Qt.AlignCenter)
        self.lbl_cover.setText("Poster")
        header_layout.addWidget(self.lbl_cover)

        if self.series.cover:
            self.thumb_loader.load_thumbnail(self.series.cover, self._on_cover_loaded)

        info_layout = QVBoxLayout()
        info_layout.setSpacing(6)

        title_lbl = QLabel(self.series.name)
        title_font = QFont()
        title_font.setPointSize(14)
        title_font.setBold(True)
        title_lbl.setFont(title_font)
        title_lbl.setWordWrap(True)
        info_layout.addWidget(title_lbl)

        meta_text = (
            f"Nguồn: <b>{self.series.platform.upper()}</b> | "
            f"Tổng số tập: <b>{self.series.episode_count}</b> | "
            f"Có thể tải: <b style='color:#10b981;'>{self.series.accessible_count}</b>"
        )
        meta_lbl = QLabel(meta_text)
        meta_lbl.setTextFormat(Qt.RichText)
        info_layout.addWidget(meta_lbl)

        if self.series.description:
            desc_text = self.series.description[:200] + ("..." if len(self.series.description) > 200 else "")
            desc_lbl = QLabel(desc_text)
            desc_lbl.setStyleSheet("color: #9ca3af; font-size: 11px;")
            desc_lbl.setWordWrap(True)
            info_layout.addWidget(desc_lbl)

        info_layout.addStretch()
        header_layout.addLayout(info_layout, stretch=1)
        main_layout.addLayout(header_layout)

        # Đường phân cách
        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet("color: #2d3748;")
        main_layout.addWidget(sep)

        # 2. Thanh công cụ chọn tập nhanh
        tools_layout = QHBoxLayout()
        tools_layout.setSpacing(10)

        tools_layout.addWidget(QLabel("Khoảng tập:"))
        self.txt_range = QLineEdit()
        self.txt_range.setPlaceholderText("VD: 1-5, 8, 10-12")
        self.txt_range.setFixedWidth(150)
        tools_layout.addWidget(self.txt_range)

        btn_apply_range = QPushButton("Áp dụng")
        btn_apply_range.setObjectName("btnSecondary")
        btn_apply_range.clicked.connect(self._apply_range_filter)
        tools_layout.addWidget(btn_apply_range)

        btn_select_all = QPushButton("Chọn tất cả")
        btn_select_all.setObjectName("btnSecondary")
        btn_select_all.clicked.connect(self._select_all)
        tools_layout.addWidget(btn_select_all)

        btn_select_free = QPushButton("Chỉ tập miễn phí")
        btn_select_free.setObjectName("btnSecondary")
        btn_select_free.clicked.connect(self._select_free_only)
        tools_layout.addWidget(btn_select_free)

        btn_deselect = QPushButton("Bỏ chọn")
        btn_deselect.setObjectName("btnSecondary")
        btn_deselect.clicked.connect(self._deselect_all)
        tools_layout.addWidget(btn_deselect)

        tools_layout.addStretch()
        main_layout.addLayout(tools_layout)

        # 3. Khu vực danh sách tập (Scroll Grid)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        container = QWidget()
        self.grid_layout = QGridLayout(container)
        self.grid_layout.setSpacing(10)
        self.grid_layout.setContentsMargins(12, 12, 12, 12)

        for idx, ep in enumerate(self.series.episodes):
            cb = QCheckBox(f"Tập {ep.num}")
            if ep.access_state == ACCESS_STATE_FREE and not ep.locked:
                cb.setText(f"Tập {ep.num} [Free]")
                cb.setStyleSheet("color: #10b981; font-weight: 500; font-size: 11px;")
                cb.setToolTip("Tập miễn phí - có thể tải ngay")
                cb.setChecked(True)
            elif ep.access_state == ACCESS_STATE_AUTHORIZED and not ep.locked:
                cb.setText(f"Tập {ep.num} [VIP Mua]")
                cb.setStyleSheet("color: #38bdf8; font-weight: 500; font-size: 11px;")
                cb.setToolTip("Tập VIP đã được xác thực qua tài khoản - có thể tải")
                cb.setChecked(True)
            elif ep.access_state == ACCESS_STATE_REQUIRES_VIP:
                cb.setText(f"Tập {ep.num} [VIP]")
                cb.setStyleSheet("color: #f59e0b; font-size: 11px;")
                cb.setToolTip(ep.access_reason or "Tập này yêu cầu quyền VIP trên ứng dụng chính thức. HyperMedia không thể xác minh quyền truy cập từ trình duyệt PC.")
                cb.setEnabled(False)
                cb.setChecked(False)
            elif ep.access_state == ACCESS_STATE_REQUIRES_LOGIN:
                cb.setText(f"Tập {ep.num} [Login]")
                cb.setStyleSheet("color: #3b82f6; font-size: 11px;")
                cb.setToolTip("Tập này yêu cầu đăng nhập tài khoản trên nền tảng chính thức.")
                cb.setEnabled(False)
                cb.setChecked(False)
            else:
                cb.setText(f"Tập {ep.num} [Khóa]")
                cb.setStyleSheet("color: #6b7280; font-size: 11px;")
                cb.setToolTip("Tập này hiện không khả dụng để tải về.")
                cb.setEnabled(False)
                cb.setChecked(False)

            cb.stateChanged.connect(self._update_counter)
            self.episode_checkboxes[ep.num] = cb

        self._relayout_episodes()

        scroll.setWidget(container)
        main_layout.addWidget(scroll, stretch=1)

        # 4. Footer & Action buttons
        footer_layout = QHBoxLayout()
        self.lbl_count = QLabel("Đã chọn: 0 tập")
        self.lbl_count.setStyleSheet("font-weight: bold; color: #60a5fa;")
        footer_layout.addWidget(self.lbl_count)

        footer_layout.addStretch()

        btn_cancel = QPushButton("Hủy bỏ")
        btn_cancel.setObjectName("btnCancel")
        btn_cancel.clicked.connect(self.reject)
        footer_layout.addWidget(btn_cancel)

        self.btn_confirm = QPushButton("Thêm vào hàng đợi tải")
        self.btn_confirm.clicked.connect(self._on_confirm)
        footer_layout.addWidget(self.btn_confirm)

        main_layout.addLayout(footer_layout)

        self._update_counter()

    def _on_cover_loaded(self, pixmap: QPixmap):
        if not pixmap.isNull():
            self.lbl_cover.setPixmap(
                pixmap.scaled(self.lbl_cover.size(), Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
            )

    def _update_counter(self):
        selected_cnt = sum(1 for cb in self.episode_checkboxes.values() if cb.isChecked() and cb.isEnabled())
        self.lbl_count.setText(f"Đã chọn: <b>{selected_cnt}</b>/{self.series.accessible_count} tập có thể tải")
        self.btn_confirm.setText(f"Thêm vào hàng đợi tải ({selected_cnt})")
        self.btn_confirm.setEnabled(selected_cnt > 0)

    def _select_all(self):
        for cb in self.episode_checkboxes.values():
            if cb.isEnabled():
                cb.setChecked(True)
        self._update_counter()

    def _select_free_only(self):
        for num, cb in self.episode_checkboxes.items():
            ep = self.episode_map.get(num)
            if ep and not ep.locked and ep.access_state in (ACCESS_STATE_FREE, ACCESS_STATE_AUTHORIZED):
                cb.setChecked(True)
            else:
                cb.setChecked(False)
        self._update_counter()

    def _deselect_all(self):
        for cb in self.episode_checkboxes.values():
            cb.setChecked(False)
        self._update_counter()

    def _apply_range_filter(self):
        range_str = self.txt_range.text().strip()
        if not range_str:
            return
        selected_nums = parse_episode_selection(range_str, self.series.episode_count)
        if not selected_nums:
            QMessageBox.warning(self, "Khoảng tập không hợp lệ", "Vui lòng nhập định dạng hợp lệ như: 1-5, 8, 10-12")
            return

        for num, cb in self.episode_checkboxes.items():
            if cb.isEnabled():
                cb.setChecked(num in selected_nums)
        self._update_counter()

    def _on_confirm(self):
        selected_eps = []
        for num, cb in self.episode_checkboxes.items():
            if cb.isChecked() and cb.isEnabled():
                ep = self.episode_map.get(num)
                if ep:
                    selected_eps.append(ep)

        if not selected_eps:
            QMessageBox.information(self, "Chưa chọn tập", "Vui lòng chọn ít nhất 1 tập phim để tải.")
            return

        self.episodes_selected.emit(selected_eps)
        self.accept()
