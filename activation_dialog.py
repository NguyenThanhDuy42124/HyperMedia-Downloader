"""
ActivationDialog & ContactDialog - Hộp thoại kích hoạt bản quyền HyperMedia Downloader Pro.
Phong cách Cyber Dark Neon kết hợp 100% Lucide Vector Icons sắc nét.
Tác giả: NguyenThanhDuy42124 (Nguyễn Thanh Duy) - Zalo: 0334674017
"""
import os
import sys
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QGuiApplication, QIcon
from PySide6.QtWidgets import (
    QDialog, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QMessageBox, QFrame
)

from license_manager import get_hwid, verify_license_key, save_license
from lucide_icons import get_lucide_icon, get_lucide_pixmap
from app_constants import get_icon_path


class ReadOnlyCopyLabel(QLineEdit):
    """QLineEdit thiết kế trong suốt như QLabel, hỗ trợ bôi đen quét chuột copy 100% mượt mà."""
    def __init__(self, text: str, width: int = 300, font_size: int = 10, parent=None):
        super().__init__(text, parent)
        self.setReadOnly(True)
        self.setFont(QFont("Consolas", font_size, QFont.Weight.Bold))
        self.setFixedWidth(width)
        self.setCursor(Qt.CursorShape.IBeamCursor)
        self.setToolTip("Rê chuột bôi đen hoặc nhấp đúp để sao chép")
        self.setStyleSheet("""
            QLineEdit {
                color: #00E5FF;
                background-color: transparent;
                border: none;
                padding: 0px;
                font-weight: bold;
                selection-background-color: #0284c7;
                selection-color: #FFFFFF;
            }
        """)


class ContactDialog(QDialog):
    """Hộp thoại thông tin liên hệ mua Key License tối giản với 100% Lucide SVG Icons."""
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("Thông Tin Liên Hệ Mua License Key")
        self.setFixedSize(520, 260)

        icon_path = get_icon_path()
        if icon_path and os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))

        self.setStyleSheet("""
            QDialog { background-color: #0c0c12; }
            QLabel { color: #E2E8F0; font-family: 'Segoe UI', Arial, sans-serif; font-size: 13px; }
            QPushButton {
                background-color: #1a1a24;
                color: #FFFFFF;
                border: 1px solid #2d2d3f;
                border-radius: 6px;
                padding: 6px 20px;
                font-weight: bold;
                font-size: 13px;
            }
            QPushButton:hover { background-color: #252538; border-color: #00E5FF; }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 18, 22, 18)
        layout.setSpacing(10)

        # Header Title với Lucide Phone Icon
        header_box = QHBoxLayout()
        header_box.setSpacing(8)

        ic_head = QLabel()
        ic_head.setPixmap(get_lucide_pixmap("phone", color="#00E5FF", size=20))
        header_box.addWidget(ic_head)

        lbl_head = QLabel("Vui lòng liên hệ để mua License Key bản quyền:")
        lbl_head.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))
        lbl_head.setStyleSheet("color: #00E5FF;")
        header_box.addWidget(lbl_head)
        header_box.addStretch()
        layout.addLayout(header_box)

        div = QFrame()
        div.setFrameShape(QFrame.Shape.HLine)
        div.setStyleSheet("background-color: #222233; max-height: 1px;")
        layout.addWidget(div)

        # Line 1: Tác giả
        row1 = QHBoxLayout()
        row1.setSpacing(8)
        ic_user = QLabel()
        ic_user.setPixmap(get_lucide_pixmap("user", color="#00E5FF", size=16))
        row1.addWidget(ic_user)

        lbl_u_title = QLabel("Tác giả:")
        lbl_u_title.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        lbl_u_title.setStyleSheet("color: #00E5FF;")
        row1.addWidget(lbl_u_title)

        lbl_user = ReadOnlyCopyLabel("NguyenThanhDuy42124 (Nguyễn Thanh Duy)", width=280, font_size=10)
        row1.addWidget(lbl_user)
        row1.addStretch()
        layout.addLayout(row1)

        # Line 2: Github
        row2 = QHBoxLayout()
        row2.setSpacing(8)
        ic_gh = QLabel()
        ic_gh.setPixmap(get_lucide_pixmap("github", color="#00E5FF", size=16))
        row2.addWidget(ic_gh)

        lbl_g_title = QLabel("Github:")
        lbl_g_title.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        lbl_g_title.setStyleSheet("color: #00E5FF;")
        row2.addWidget(lbl_g_title)

        lbl_gh = ReadOnlyCopyLabel("https://github.com/NguyenThanhDuy42124/HyperMedia-Downloader", width=330, font_size=10)
        row2.addWidget(lbl_gh)
        row2.addStretch()
        layout.addLayout(row2)

        # Line 3: Zalo
        row3 = QHBoxLayout()
        row3.setSpacing(8)
        ic_phone = QLabel()
        ic_phone.setPixmap(get_lucide_pixmap("phone", color="#00E676", size=16))
        row3.addWidget(ic_phone)

        lbl_p_title = QLabel("Zalo:")
        lbl_p_title.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        lbl_p_title.setStyleSheet("color: #00E676;")
        row3.addWidget(lbl_p_title)

        lbl_phone = ReadOnlyCopyLabel("0334674017", width=150, font_size=10)
        row3.addWidget(lbl_phone)
        row3.addStretch()
        layout.addLayout(row3)

        layout.addStretch()

        # Nút Đóng
        btn_close = QPushButton(" Đóng")
        btn_close.setIcon(get_lucide_icon("x", color="#FFFFFF", size=14))
        btn_close.setFixedWidth(100)
        btn_close.clicked.connect(self.accept)

        btn_box = QHBoxLayout()
        btn_box.addStretch()
        btn_box.addWidget(btn_close)
        layout.addLayout(btn_box)


class ActivationDialog(QDialog):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.is_activated = False
        self.setWindowTitle("Kích Hoạt Bản Quyền — HyperMedia Downloader Pro")
        self.setFixedSize(560, 350)

        icon_path = get_icon_path()
        if icon_path and os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))

        self._setup_stylesheet()
        self._init_ui()

    def _setup_stylesheet(self):
        self.setStyleSheet("""
            QDialog {
                background-color: #0c0c12;
            }
            QLabel {
                color: #E2E8F0;
                font-family: 'Segoe UI', Arial, sans-serif;
                font-size: 13px;
            }
            QLineEdit {
                background-color: #12121c;
                border: 2px solid #252538;
                border-radius: 6px;
                padding: 8px 12px;
                color: #00E5FF;
                font-family: 'Consolas', 'Courier New', monospace;
                font-size: 14px;
                font-weight: bold;
                min-height: 24px;
            }
            QLineEdit:focus {
                border: 2px solid #00B0FF;
                background-color: #161624;
                color: #FFFFFF;
            }
            QLineEdit[readOnly="true"] {
                background-color: #0e0e16;
                color: #00E5FF;
                border-color: #1f1f2e;
            }
            QPushButton#btnActivate {
                background-color: #0284c7;
                color: #FFFFFF;
                border: none;
                border-radius: 6px;
                padding: 10px;
                font-weight: bold;
                font-size: 13px;
                min-height: 28px;
            }
            QPushButton#btnActivate:hover {
                background-color: #00B0FF;
            }
            QPushButton#btnContact {
                background-color: #1a1a26;
                color: #FFFFFF;
                border: 1px solid #2d2d42;
                border-radius: 6px;
                padding: 10px;
                font-size: 13px;
                font-weight: bold;
                min-height: 28px;
            }
            QPushButton#btnContact:hover {
                background-color: #252538;
                border-color: #00E5FF;
            }
            QPushButton#btnCopy {
                background-color: #1a1a26;
                color: #FFFFFF;
                border: 1px solid #2d2d42;
                border-radius: 6px;
                font-size: 13px;
                padding: 8px 14px;
                font-weight: bold;
            }
            QPushButton#btnCopy:hover {
                background-color: #252538;
                border-color: #00E5FF;
            }
        """)

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)

        # Header Title với Lucide Icon
        title_box = QHBoxLayout()
        title_box.setSpacing(10)
        title_box.setAlignment(Qt.AlignmentFlag.AlignCenter)

        lbl_key_icon = QLabel()
        lbl_key_icon.setPixmap(get_lucide_pixmap("sparkles", color="#00E5FF", size=24))
        title_box.addWidget(lbl_key_icon)

        title_label = QLabel("KÍCH HOẠT BẢN QUYỀN PHẦN MỀM")
        title_font = QFont()
        title_font.setPointSize(14)
        title_font.setBold(True)
        title_label.setFont(title_font)
        title_label.setStyleSheet("color: #00E5FF;")
        title_box.addWidget(title_label)

        layout.addLayout(title_box)

        # HWID Section
        hwid_layout = QVBoxLayout()
        hwid_label = QLabel("Mã Máy Tính (HWID):")
        hwid_label.setStyleSheet("font-weight: bold; color: #E2E8F0;")
        hwid_layout.addWidget(hwid_label)

        hwid_box = QHBoxLayout()
        self.hwid = get_hwid()
        self.txt_hwid = QLineEdit(self.hwid)
        self.txt_hwid.setReadOnly(True)
        hwid_box.addWidget(self.txt_hwid)

        self.btn_copy = QPushButton(" Sao Chép HWID")
        self.btn_copy.setObjectName("btnCopy")
        self.btn_copy.setIcon(get_lucide_icon("copy", color="#FFFFFF", size=14))
        self.btn_copy.setToolTip("Sao chép mã HWID vào khay nhớ tạm để gửi cho Admin")
        self.txt_hwid.setToolTip("Mã định danh phần cứng duy nhất (HWID) của máy tính này")
        self.btn_copy.clicked.connect(self._copy_hwid)
        hwid_box.addWidget(self.btn_copy)

        hwid_layout.addLayout(hwid_box)
        layout.addLayout(hwid_layout)

        # License Key Section
        key_layout = QVBoxLayout()
        key_label = QLabel("Nhập License Key:")
        key_label.setStyleSheet("font-weight: bold; color: #E2E8F0;")
        key_layout.addWidget(key_label)

        self.txt_key = QLineEdit()
        self.txt_key.setPlaceholderText("KEY-XXXX-XXXX-XXXX-XXXX hoặc KEY-REDEEM-...")
        self.txt_key.setToolTip("Dán mã License Key bạn nhận được vào đây")
        key_layout.addWidget(self.txt_key)

        layout.addLayout(key_layout)

        # Action Buttons Row: [ Liên Hệ Mua Key ] | [ Kích Hoạt Bản Quyền ]
        action_btn_box = QHBoxLayout()
        action_btn_box.setSpacing(10)

        self.btn_contact = QPushButton(" Liên Hệ Mua Key")
        self.btn_contact.setObjectName("btnContact")
        self.btn_contact.setIcon(get_lucide_icon("phone", color="#00E5FF", size=15))
        self.btn_contact.setToolTip("Xem thông tin liên hệ SĐT 0334674017 (Zalo) mua Key License")
        self.btn_contact.clicked.connect(self._on_contact_clicked)
        action_btn_box.addWidget(self.btn_contact, 1)

        self.btn_activate = QPushButton(" Kích Hoạt Bản Quyền")
        self.btn_activate.setObjectName("btnActivate")
        self.btn_activate.setIcon(get_lucide_icon("shield-check", color="#FFFFFF", size=16))
        self.btn_activate.clicked.connect(self._on_activate_clicked)
        action_btn_box.addWidget(self.btn_activate, 1)

        layout.addLayout(action_btn_box)

    def _copy_hwid(self):
        QGuiApplication.clipboard().setText(self.hwid)
        QMessageBox.information(self, "Thông báo", f"Đã sao chép HWID thành công:\n{self.hwid}")

    def _on_contact_clicked(self):
        dlg = ContactDialog(self)
        dlg.exec()

    def _on_activate_clicked(self):
        input_key = self.txt_key.text().strip()
        is_valid, msg, info = verify_license_key(input_key)

        if is_valid:
            save_license(input_key)
            self.is_activated = True
            QMessageBox.information(self, "Thành công", f"{msg}\n\nCảm ơn bạn đã sử dụng HyperMedia Downloader Pro!")
            self.accept()
        else:
            QMessageBox.critical(self, "Lỗi Kích Hoạt", msg)
