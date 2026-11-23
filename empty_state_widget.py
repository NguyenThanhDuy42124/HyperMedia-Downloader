"""
empty_state_widget.py
~~~~~~~~~~~~~~~~~~~~~
Widget hiển thị trạng thái giao diện thương mại (State Container):
- Loading: Biểu tượng đang tải + Thông điệp
- Empty: Chưa có dữ liệu / Không tìm thấy phim
- Error: Lỗi kết nối / Máy chủ + Nút 'Thử lại'
- Offline: Mất kết nối mạng + Nút 'Thử lại'
- Session Expired: Phiên hết hạn + Nút 'Đồng bộ lại'
"""

from typing import Callable, Optional
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QVBoxLayout,
    QLabel,
    QPushButton,
    QWidget,
)
from PySide6.QtGui import QFont
from lucide_icons import get_lucide_icon


class EmptyStateWidget(QFrame):
    action_triggered = Signal()

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setStyleSheet("""
            EmptyStateWidget {
                background-color: transparent;
                border: none;
            }
            QLabel#lblTitle {
                color: #f1f5f9;
                font-size: 14px;
                font-weight: 700;
            }
            QLabel#lblDesc {
                color: #94a3b8;
                font-size: 11px;
                line-height: 1.4;
            }
            QPushButton#btnAction {
                background-color: #2563eb;
                color: white;
                font-size: 12px;
                font-weight: 600;
                border-radius: 6px;
                padding: 7px 18px;
                border: none;
                min-height: 32px;
            }
            QPushButton#btnAction:hover {
                background-color: #1d4ed8;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignCenter)
        layout.setSpacing(10)
        layout.setContentsMargins(24, 40, 24, 40)

        self.lbl_icon = QLabel()
        self.lbl_icon.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.lbl_icon)

        self.lbl_title = QLabel("Đang tải dữ liệu...")
        self.lbl_title.setObjectName("lblTitle")
        self.lbl_title.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.lbl_title)

        self.lbl_desc = QLabel("")
        self.lbl_desc.setObjectName("lblDesc")
        self.lbl_desc.setAlignment(Qt.AlignCenter)
        self.lbl_desc.setWordWrap(True)
        self.lbl_desc.setMaximumWidth(450)
        layout.addWidget(self.lbl_desc)

        self.btn_action = QPushButton("Thử lại")
        self.btn_action.setObjectName("btnAction")
        self.btn_action.setCursor(Qt.PointingHandCursor)
        self.btn_action.setVisible(False)
        self.btn_action.clicked.connect(self._on_action_clicked)
        layout.addWidget(self.btn_action, alignment=Qt.AlignCenter)

        self._action_callback: Optional[Callable] = None

    def _on_action_clicked(self):
        self.action_triggered.emit()
        if self._action_callback:
            self._action_callback()

    def show_loading(self, title: str = "Đang tải danh sách phim...", desc: str = "Đang kết nối đến nguồn dữ liệu, vui lòng chờ trong giây lát."):
        self.lbl_icon.setPixmap(get_lucide_icon("loader-2", "#38bdf8", 36).pixmap(36, 36))
        self.lbl_title.setText(title)
        self.lbl_desc.setText(desc)
        self.btn_action.setVisible(False)
        self.setVisible(True)

    def show_empty(self, title: str = "Chưa có phim phù hợp", desc: str = "Thử tìm kiếm với từ khóa khác hoặc chuyển sang nguồn phim khác."):
        self.lbl_icon.setPixmap(get_lucide_icon("film", "#64748b", 36).pixmap(36, 36))
        self.lbl_title.setText(title)
        self.lbl_desc.setText(desc)
        self.btn_action.setVisible(False)
        self.setVisible(True)

    def show_error(self, message: str, desc: str = "Vui lòng kiểm tra kết nối mạng hoặc thử lại sau.", callback: Optional[Callable] = None):
        self.lbl_icon.setPixmap(get_lucide_icon("alert-circle", "#ef4444", 36).pixmap(36, 36))
        self.lbl_title.setText(message)
        self.lbl_desc.setText(desc)
        self._action_callback = callback
        self.btn_action.setText("Thử lại")
        self.btn_action.setIcon(get_lucide_icon("rotate-cw", "#ffffff", 13))
        self.btn_action.setVisible(callback is not None)
        self.setVisible(True)

    def show_session_expired(self, message: str = "Phiên đăng nhập đã hết hạn", desc: str = "Vui lòng đồng bộ lại cookie từ Extension trình duyệt để tiếp tục.", callback: Optional[Callable] = None):
        self.lbl_icon.setPixmap(get_lucide_icon("key", "#f59e0b", 36).pixmap(36, 36))
        self.lbl_title.setText(message)
        self.lbl_desc.setText(desc)
        self._action_callback = callback
        self.btn_action.setText("Đồng bộ phiên")
        self.btn_action.setIcon(get_lucide_icon("refresh-cw", "#ffffff", 13))
        self.btn_action.setVisible(callback is not None)
        self.setVisible(True)

    def show_offline(self, message: str = "Không có kết nối mạng", desc: str = "Không thể kết nối đến máy chủ. Hãy kiểm tra kết nối Internet.", callback: Optional[Callable] = None):
        self.lbl_icon.setPixmap(get_lucide_icon("wifi-off", "#ef4444", 36).pixmap(36, 36))
        self.lbl_title.setText(message)
        self.lbl_desc.setText(desc)
        self._action_callback = callback
        self.btn_action.setText("Thử lại")
        self.btn_action.setIcon(get_lucide_icon("rotate-cw", "#ffffff", 13))
        self.btn_action.setVisible(callback is not None)
        self.setVisible(True)
