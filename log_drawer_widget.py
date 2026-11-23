"""
log_drawer_widget.py
~~~~~~~~~~~~~~~~~~~~
Khung hiển thị Nhật ký / Chi tiết kỹ thuật dạng trượt thu gọn (Collapsible Drawer).
Thiết kế theo Progressive Disclosure:
- Mặc định thu gọn, chỉ mở khi người dùng bấm 'Nhật ký' hoặc 'Chi tiết'.
- Lọc theo mức độ: Tất cả, Thông tin, Cảnh báo, Lỗi.
- Nút tác vụ: Sao chép, Lưu file, Xóa, Đóng.
- Tự động che giấu (mask) token, cookie, sessionid và đường dẫn _MEIPASS nội bộ.
"""

import os
import time
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QComboBox,
    QTextEdit,
    QApplication,
    QFileDialog,
)
from PySide6.QtGui import QFont
from lucide_icons import get_lucide_icon
from ca_bundle_utils import sanitize_log_text, sanitize_error_message


class LogDrawerWidget(QFrame):
    closed = Signal()

    def __init__(self, title: str = "Nhật ký hoạt động & Chi tiết", parent=None):
        super().__init__(parent)
        self.log_entries = []  # list of (timestamp_str, level, text)
        self.setMaximumHeight(220)
        self.setMinimumHeight(140)
        self.setStyleSheet("""
            LogDrawerWidget {
                background-color: #0b0d14;
                border-top: 1px solid #1f2937;
                border-bottom: 1px solid #1f2937;
            }
            QLabel {
                color: #94a3b8;
                font-size: 11px;
                font-weight: 600;
            }
            QComboBox {
                background-color: #161824;
                border: 1px solid #374151;
                border-radius: 4px;
                padding: 2px 8px;
                color: #e2e8f0;
                font-size: 11px;
            }
            QPushButton {
                background-color: #1f2937;
                color: #e5e7eb;
                border: 1px solid #374151;
                border-radius: 4px;
                padding: 3px 10px;
                font-size: 11px;
                font-weight: 500;
            }
            QPushButton:hover {
                background-color: #374151;
            }
            QTextEdit {
                background-color: #06070a;
                border: 1px solid #1e2230;
                border-radius: 4px;
                color: #cbd5e1;
                font-family: Consolas, 'Courier New', monospace;
                font-size: 11px;
                padding: 6px;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(6)

        # Header bar
        header = QHBoxLayout()
        header.setSpacing(8)

        lbl_icon = QLabel()
        lbl_icon.setPixmap(get_lucide_icon("terminal", "#60a5fa", 13).pixmap(13, 13))
        header.addWidget(lbl_icon)

        self.lbl_title = QLabel(title)
        header.addWidget(self.lbl_title)

        header.addSpacing(8)
        header.addWidget(QLabel("Lọc:"))
        self.cb_filter = QComboBox()
        self.cb_filter.addItems(["Tất cả", "Thông tin", "Cảnh báo", "Lỗi"])
        self.cb_filter.currentIndexChanged.connect(self._render_logs)
        header.addWidget(self.cb_filter)

        header.addStretch()

        self.btn_copy = QPushButton(" Sao chép")
        self.btn_copy.setIcon(get_lucide_icon("copy", "#94a3b8", 12))
        self.btn_copy.clicked.connect(self._copy_all)
        header.addWidget(self.btn_copy)

        self.btn_save = QPushButton(" Lưu file")
        self.btn_save.setIcon(get_lucide_icon("save", "#94a3b8", 12))
        self.btn_save.clicked.connect(self._save_file)
        header.addWidget(self.btn_save)

        self.btn_clear = QPushButton(" Xóa")
        self.btn_clear.setIcon(get_lucide_icon("trash-2", "#94a3b8", 12))
        self.btn_clear.clicked.connect(self.clear_logs)
        header.addWidget(self.btn_clear)

        self.btn_close = QPushButton(" Đóng")
        self.btn_close.setIcon(get_lucide_icon("x", "#94a3b8", 12))
        self.btn_close.clicked.connect(self._on_close)
        header.addWidget(self.btn_close)

        layout.addLayout(header)

        # Text display
        self.txt_log = QTextEdit()
        self.txt_log.setReadOnly(True)
        layout.addWidget(self.txt_log)

    def log_info(self, message: str):
        self._add_entry("INFO", message)

    def log_warn(self, message: str):
        self._add_entry("WARN", message)

    def log_error(self, message: str):
        self._add_entry("ERROR", message)

    def _add_entry(self, level: str, message: str):
        sanitized = sanitize_log_text(str(message))
        ts = time.strftime("%H:%M:%S")
        self.log_entries.append((ts, level, sanitized))
        if len(self.log_entries) > 500:
            self.log_entries = self.log_entries[-400:]
        self._render_logs()

    def _render_logs(self):
        filt = self.cb_filter.currentText()
        lines = []
        for ts, level, msg in self.log_entries:
            if filt == "Thông tin" and level != "INFO":
                continue
            if filt == "Cảnh báo" and level != "WARN":
                continue
            if filt == "Lỗi" and level != "ERROR":
                continue

            color = "#94a3b8"
            if level == "INFO":
                color = "#38bdf8"
            elif level == "WARN":
                color = "#f59e0b"
            elif level == "ERROR":
                color = "#ef4444"

            lines.append(f"<span style='color:#64748b;'>[{ts}]</span> <b style='color:{color};'>[{level}]</b> {msg}")

        self.txt_log.setHtml("<br>".join(lines))
        sb = self.txt_log.verticalScrollBar()
        sb.setValue(sb.maximum())

    def clear_logs(self):
        self.log_entries.clear()
        self.txt_log.clear()

    def _copy_all(self):
        text = "\n".join(f"[{ts}] [{level}] {msg}" for ts, level, msg in self.log_entries)
        QApplication.clipboard().setText(text)
        self.btn_copy.setText(" Đã chép!")
        from PySide6.QtCore import QTimer
        QTimer.singleShot(1500, lambda: self.btn_copy.setText(" Sao chép"))

    def _save_file(self):
        file_path, _ = QFileDialog.getSaveFileName(
            self, "Lưu nhật ký", "hypermedia_browse_log.txt", "Text Files (*.txt);;All Files (*)"
        )
        if file_path:
            try:
                with open(file_path, "w", encoding="utf-8") as f:
                    for ts, level, msg in self.log_entries:
                        f.write(f"[{ts}] [{level}] {msg}\n")
            except Exception:
                pass

    def _on_close(self):
        self.setVisible(False)
        self.closed.emit()
