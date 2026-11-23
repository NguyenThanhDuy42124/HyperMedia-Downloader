"""
miniapp_episode_dialog.py
~~~~~~~~~~~~~~~~~~~~~~~~~
Dialog chọn tập phim ngắn MiniApp Douyin theo kiến trúc Free-first:
- Hiển thị thông tin series, nguồn MiniApp Việt hóa và danh sách các tập.
- Đánh dấu tập [Free] (màu xanh lục, cho phép chọn) và tập [VIP / Khóa] (màu xám/vàng, bị vô hiệu hóa).
- Tuyệt đối cấm chọn các tập bị khóa hoặc yêu cầu VIP.
- Hỗ trợ chọn theo khoảng (ví dụ: 1-5, 8, 10-12), nút 'Chọn tất cả tập Free', và 'Bỏ chọn'.
- Xem trước cấu trúc thư mục lưu trữ phân cấp:
  downloads/MiniApp Douyin/{Tên MiniApp Việt hóa}/{Tên bộ phim}/
- Nút thao tác: 'Mở thư mục bộ phim', 'Đổi thư mục gốc', 'Sao chép đường dẫn'.
"""

import os
from PySide6.QtCore import Qt, Signal, QTimer, QUrl
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
    QFileDialog,
    QApplication,
)
from PySide6.QtGui import QFont, QPixmap, QDesktopServices
from lucide_icons import get_lucide_icon
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
from providers.miniapp_douyin_client import get_douyin_session_status
from drama_path_utils import (
    get_miniapp_display_name,
    build_drama_destination_dir,
)
from thumbnail_loader import ThumbnailLoader


class MiniAppEpisodeDialog(QDialog):
    episodes_selected = Signal(list)  # list of Episode

    def __init__(self, series: Series, app_id: str = "", base_folder: str = "", parent=None):
        super().__init__(parent)
        self.series = series
        self.app_id = app_id or getattr(series, "extra", {}).get("app_id", "") or "tt5b4d2df0c47bdd2201"
        self.source_display_name = get_miniapp_display_name(self.app_id)
        self.base_folder = base_folder or os.path.join(os.getcwd(), "downloads")

        # Khởi tạo thư mục đích chuẩn hóa
        self.dest_dir = build_drama_destination_dir(
            self.base_folder,
            "miniapp_douyin",
            self.series.name,
            source_app_id=self.app_id,
        )

        self.episode_checkboxes: dict[int, QCheckBox] = {}
        self.episode_map: dict[int, Episode] = {ep.num: ep for ep in self.series.episodes}
        self.thumb_loader = ThumbnailLoader()

        self.setWindowTitle(f"Chọn tập tải - {series.name} ({self.source_display_name} - MiniApp Douyin)")
        self.resize(840, 680)
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
                background-color: #ec4899;
                color: white;
                border: none;
                border-radius: 6px;
                padding: 6px 14px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #db2777;
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
            QPushButton#btnOutline {
                background-color: transparent;
                border: 1px solid #4b5563;
                color: #9ca3af;
                font-size: 11px;
                padding: 4px 10px;
            }
            QPushButton#btnOutline:hover {
                background-color: #1f2937;
                color: #f3f4f6;
                border-color: #6b7280;
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
                border: 1px solid #ec4899;
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

    def get_destination_dir(self) -> str:
        """Trả về thư mục lưu trữ đích của bộ phim."""
        return self.dest_dir

    def _init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(20, 20, 20, 20)
        main_layout.setSpacing(12)

        # 1. Header info: Poster & Metadata
        header_layout = QHBoxLayout()
        header_layout.setSpacing(16)

        self.lbl_cover = QLabel()
        self.lbl_cover.setFixedSize(96, 128)
        self.lbl_cover.setStyleSheet("background-color: #1e202e; border-radius: 6px; border: 1px solid #2d3748;")
        self.lbl_cover.setAlignment(Qt.AlignCenter)
        header_layout.addWidget(self.lbl_cover)

        if self.series.cover:
            self.thumb_loader.load(self.series.cover, self._on_cover_loaded)
        else:
            self.lbl_cover.setText("Không có ảnh")

        info_layout = QVBoxLayout()
        info_layout.setSpacing(6)

        # Tiêu đề phim và Badge Nguồn MiniApp
        title_box = QHBoxLayout()
        lbl_title = QLabel(self.series.name)
        font_title = QFont()
        font_title.setPointSize(13)
        font_title.setBold(True)
        lbl_title.setFont(font_title)
        lbl_title.setStyleSheet("color: #f43f5e;")
        lbl_title.setWordWrap(True)
        title_box.addWidget(lbl_title, stretch=1)

        badge_source = QLabel(f"Nguồn: {self.source_display_name}")
        badge_source.setStyleSheet(
            "background-color: #3b0764; color: #d8b4fe; border: 1px solid #7e22ce; "
            "padding: 3px 8px; border-radius: 4px; font-weight: bold; font-size: 11px;"
        )
        title_box.addWidget(badge_source)
        info_layout.addLayout(title_box)

        free_count = sum(1 for e in self.series.episodes if e.access_state in (ACCESS_STATE_FREE, ACCESS_STATE_AUTHORIZED) and not e.locked)
        total_count = len(self.series.episodes)
        vip_locked_count = total_count - free_count

        lbl_counts = QLabel(
            f"Tổng số: {total_count} tập  |  Tập miễn phí [Free]: {free_count} tập  |  VIP/Khóa: {vip_locked_count} tập"
        )
        lbl_counts.setStyleSheet("color: #9ca3af; font-size: 12px; font-weight: 500;")
        info_layout.addWidget(lbl_counts)

        # Trạng thái phiên Douyin
        sess_code, _ = get_douyin_session_status()
        sess_text = "Đã có phiên Douyin" if sess_code == "valid" else "Chưa có phiên Douyin (chỉ tải tập Free)"
        sess_color = "#10b981" if sess_code == "valid" else "#f59e0b"
        lbl_sess = QLabel(f"Phiên làm việc: {sess_text}")
        lbl_sess.setStyleSheet(f"color: {sess_color}; font-size: 11px;")
        info_layout.addWidget(lbl_sess)

        if self.series.description:
            lbl_desc = QLabel(self.series.description[:200] + ("..." if len(self.series.description) > 200 else ""))
            lbl_desc.setStyleSheet("color: #6b7280; font-size: 11px;")
            lbl_desc.setWordWrap(True)
            info_layout.addWidget(lbl_desc)

        info_layout.addStretch()
        header_layout.addLayout(info_layout, stretch=1)
        main_layout.addLayout(header_layout)

        # 2. Thanh thông tin Thư mục lưu trữ & Thao tác đường dẫn
        path_frame = QFrame()
        path_frame.setStyleSheet("""
            QFrame {
                background-color: #161824;
                border: 1px solid #232738;
                border-radius: 6px;
                padding: 6px;
            }
        """)
        path_layout = QVBoxLayout(path_frame)
        path_layout.setContentsMargins(8, 6, 8, 6)
        path_layout.setSpacing(6)

        path_row = QHBoxLayout()
        lbl_dir_icon = QLabel()
        lbl_dir_icon.setPixmap(get_lucide_icon("folder", "#ec4899", 14).pixmap(14, 14))
        path_row.addWidget(lbl_dir_icon)

        lbl_dest_label = QLabel("Thư mục lưu:")
        lbl_dest_label.setStyleSheet("color: #9ca3af; font-size: 11px; font-weight: bold;")
        path_row.addWidget(lbl_dest_label)

        self.lbl_dest_path = QLabel(self.dest_dir)
        self.lbl_dest_path.setStyleSheet("color: #38bdf8; font-size: 11px; font-family: Consolas, monospace;")
        self.lbl_dest_path.setToolTip(self.dest_dir)
        path_row.addWidget(self.lbl_dest_path, stretch=1)

        btn_open_folder = QPushButton("Mở thư mục bộ phim")
        btn_open_folder.setObjectName("btnOutline")
        btn_open_folder.setIcon(get_lucide_icon("external-link", "#9ca3af", 12))
        btn_open_folder.clicked.connect(self._open_destination_folder)
        path_row.addWidget(btn_open_folder)

        btn_change_base = QPushButton("Đổi thư mục gốc")
        btn_change_base.setObjectName("btnOutline")
        btn_change_base.setIcon(get_lucide_icon("edit-3", "#9ca3af", 12))
        btn_change_base.clicked.connect(self._change_base_folder)
        path_row.addWidget(btn_change_base)

        btn_copy_path = QPushButton("Sao chép")
        btn_copy_path.setObjectName("btnOutline")
        btn_copy_path.setIcon(get_lucide_icon("copy", "#9ca3af", 12))
        btn_copy_path.clicked.connect(self._copy_destination_path)
        path_row.addWidget(btn_copy_path)

        path_layout.addLayout(path_row)

        self.lbl_dest_notice = QLabel("")
        self.lbl_dest_notice.setStyleSheet("color: #10b981; font-size: 10px; font-style: italic;")
        path_layout.addWidget(self.lbl_dest_notice)

        main_layout.addWidget(path_frame)

        # 3. Thanh công cụ chọn tập nhanh
        tools_layout = QHBoxLayout()
        tools_layout.setSpacing(10)

        tools_layout.addWidget(QLabel("Khoảng tập:"))
        self.txt_range = QLineEdit()
        self.txt_range.setPlaceholderText("VD: 1-5, 8")
        self.txt_range.setFixedWidth(130)
        tools_layout.addWidget(self.txt_range)

        btn_apply_range = QPushButton("Áp dụng")
        btn_apply_range.setObjectName("btnSecondary")
        btn_apply_range.clicked.connect(self._apply_range_filter)
        tools_layout.addWidget(btn_apply_range)

        btn_select_free = QPushButton("Chọn tất cả tập Free")
        btn_select_free.setObjectName("btnSecondary")
        btn_select_free.clicked.connect(self._select_free_only)
        tools_layout.addWidget(btn_select_free)

        btn_deselect = QPushButton("Bỏ chọn")
        btn_deselect.setObjectName("btnSecondary")
        btn_deselect.clicked.connect(self._deselect_all)
        tools_layout.addWidget(btn_deselect)

        tools_layout.addStretch()
        main_layout.addLayout(tools_layout)

        # 4. Khu vực danh sách tập (Scroll Grid)
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
                cb.setToolTip(ep.access_reason or "Tập này yêu cầu mua VIP trên ứng dụng MiniApp Douyin.")
                cb.setEnabled(False)
                cb.setChecked(False)
            elif ep.access_state == ACCESS_STATE_REQUIRES_LOGIN:
                cb.setText(f"Tập {ep.num} [Login]")
                cb.setStyleSheet("color: #3b82f6; font-size: 11px;")
                cb.setToolTip("Tập này yêu cầu đăng nhập tài khoản.")
                cb.setEnabled(False)
                cb.setChecked(False)
            else:
                cb.setText(f"Tập {ep.num} [Khóa]")
                cb.setStyleSheet("color: #6b7280; font-size: 11px;")
                cb.setToolTip("Tập này bị khóa, không thể tải.")
                cb.setEnabled(False)
                cb.setChecked(False)

            cb.stateChanged.connect(self._update_counter)
            self.episode_checkboxes[ep.num] = cb

        self._relayout_episodes()

        scroll.setWidget(container)
        main_layout.addWidget(scroll, stretch=1)

        # 5. Footer & Action buttons
        footer_layout = QHBoxLayout()
        self.lbl_count = QLabel("Đã chọn: 0 tập")
        self.lbl_count.setStyleSheet("font-weight: bold; color: #ec4899;")
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

    def _open_destination_folder(self):
        """Mở thư mục lưu trữ bộ phim trên máy tính."""
        try:
            os.makedirs(self.dest_dir, exist_ok=True)
            if hasattr(os, "startfile"):
                os.startfile(self.dest_dir)
            else:
                QDesktopServices.openUrl(QUrl.fromLocalFile(self.dest_dir))
            self.lbl_dest_notice.setText("Đã mở thư mục lưu trữ.")
            QTimer.singleShot(2500, lambda: self.lbl_dest_notice.setText(""))
        except Exception as e:
            QMessageBox.warning(self, "Không thể mở thư mục", f"Lỗi khi mở thư mục: {e}")

    def _change_base_folder(self):
        """Cho phép người dùng chọn lại thư mục gốc lưu trữ."""
        new_base = QFileDialog.getExistingDirectory(self, "Chọn thư mục gốc tải về", self.base_folder)
        if new_base:
            self.base_folder = new_base
            self.dest_dir = build_drama_destination_dir(
                self.base_folder,
                "miniapp_douyin",
                self.series.name,
                source_app_id=self.app_id,
            )
            self.lbl_dest_path.setText(self.dest_dir)
            self.lbl_dest_path.setToolTip(self.dest_dir)
            self.lbl_dest_notice.setText("Đã cập nhật thư mục lưu trữ.")
            QTimer.singleShot(2500, lambda: self.lbl_dest_notice.setText(""))

    def _copy_destination_path(self):
        """Sao chép đường dẫn tuyệt đối của thư mục lưu trữ vào clipboard."""
        QApplication.clipboard().setText(self.dest_dir)
        self.lbl_dest_notice.setText("Đã sao chép đường dẫn thư mục vào Clipboard!")
        QTimer.singleShot(2500, lambda: self.lbl_dest_notice.setText(""))

    def _on_cover_loaded(self, url_or_pixmap, maybe_pixmap=None):
        pixmap = maybe_pixmap if maybe_pixmap is not None else url_or_pixmap
        if pixmap and isinstance(pixmap, QPixmap) and not pixmap.isNull():
            scaled = pixmap.scaled(self.lbl_cover.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
            self.lbl_cover.setPixmap(scaled)

    def _select_free_only(self):
        """Chỉ chọn những tập có access_state là free hoặc authorized và không bị khóa."""
        for num, cb in self.episode_checkboxes.items():
            ep = self.episode_map.get(num)
            if ep and ep.access_state in (ACCESS_STATE_FREE, ACCESS_STATE_AUTHORIZED) and not ep.locked:
                cb.setChecked(True)
            else:
                cb.setChecked(False)
        self._update_counter()

    def _deselect_all(self):
        """Bỏ chọn tất cả tập."""
        for cb in self.episode_checkboxes.values():
            cb.setChecked(False)
        self._update_counter()

    def _apply_range_filter(self):
        """Áp dụng bộ lọc khoảng tập (ví dụ: '1-5, 8'). Tuyệt đối không chọn tập bị khóa."""
        txt = self.txt_range.text().strip()
        if not txt:
            return
        selected_nums = set(parse_episode_selection(txt, len(self.series.episodes)))
        for num, cb in self.episode_checkboxes.items():
            ep = self.episode_map.get(num)
            if num in selected_nums:
                if ep and ep.access_state in (ACCESS_STATE_FREE, ACCESS_STATE_AUTHORIZED) and not ep.locked:
                    cb.setChecked(True)
                else:
                    cb.setChecked(False)
            else:
                cb.setChecked(False)
        self._update_counter()

    def _update_counter(self):
        count = sum(1 for cb in self.episode_checkboxes.values() if cb.isChecked() and cb.isEnabled())
        self.lbl_count.setText(f"Đã chọn: {count} tập")
        self.btn_confirm.setEnabled(count > 0)

    def _on_confirm(self):
        selected_episodes = []
        for num, cb in self.episode_checkboxes.items():
            if cb.isChecked() and cb.isEnabled():
                ep = self.episode_map.get(num)
                if ep:
                    # Kiểm tra bảo vệ: Tuyệt đối không cho phép chọn tập VIP/locked chưa được ủy quyền
                    if ep.locked or ep.access_state not in (ACCESS_STATE_FREE, ACCESS_STATE_AUTHORIZED):
                        continue
                    selected_episodes.append(ep)

        if not selected_episodes:
            QMessageBox.warning(self, "Chưa chọn tập", "Vui lòng chọn ít nhất một tập phim miễn phí để tiếp tục.")
            return

        self.episodes_selected.emit(selected_episodes)
        self.accept()
