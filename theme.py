"""Theme tối hiện đại cho toàn app (QSS)."""

THEME_QSS = """
* {
    font-family: "Segoe UI", system-ui, -apple-system, sans-serif;
    font-size: 13px;
    color: #f4f4f5;
}
QMainWindow, QDialog {
    background-color: #121215;
}
QLabel {
    background: transparent;
    color: #a1a1aa;
}
QLineEdit {
    background-color: #1c1c22;
    border: 1.5px solid #272730;
    border-radius: 8px;
    padding: 7px 12px;
    color: #ffffff;
    selection-background-color: #00B0FF;
}
QLineEdit:focus {
    border: 1.5px solid #00B0FF;
    background-color: #22222b;
}
QPushButton {
    background-color: #272730;
    border: 1px solid #383845;
    border-radius: 8px;
    padding: 7px 14px;
    color: #ffffff;
    font-weight: 600;
}
QPushButton:hover {
    background-color: #343442;
    border-color: #00B0FF;
}
QPushButton:pressed {
    background-color: #1c1c22;
}
QPushButton:disabled {
    background-color: #1a1a20;
    color: #52525b;
    border-color: #272730;
}
QComboBox {
    background-color: #1c1c22;
    border: 1.5px solid #272730;
    border-radius: 8px;
    padding: 6px 10px;
    color: #ffffff;
}
QComboBox:hover {
    border-color: #00B0FF;
}
QComboBox QAbstractItemView {
    background-color: #1c1c22;
    border: 1px solid #383845;
    selection-background-color: #00B0FF;
    selection-color: #ffffff;
    padding: 4px;
}
QSpinBox {
    background-color: #1c1c22;
    border: 1.5px solid #272730;
    border-radius: 8px;
    padding: 5px 8px;
    color: #ffffff;
}
QCheckBox {
    background: transparent;
    color: #e4e4e7;
    spacing: 6px;
}
QListView {
    background-color: #16161a;
    border: 1px solid #23232b;
    border-radius: 10px;
    outline: none;
    padding: 4px;
}
QListView::item {
    background: transparent;
}
QListView::item:selected {
    background: transparent;
}
QScrollBar:vertical {
    background: #121215;
    width: 8px;
    margin: 0px;
}
QScrollBar::handle:vertical {
    background: #2b2b36;
    border-radius: 4px;
    min-height: 30px;
}
QScrollBar::handle:vertical:hover {
    background: #00B0FF;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0px;
}
QScrollBar:horizontal {
    background: #121215;
    height: 8px;
    margin: 0px;
}
QScrollBar::handle:horizontal {
    background: #2b2b36;
    border-radius: 4px;
    min-width: 30px;
}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
    width: 0px;
}
QProgressBar {
    background-color: #1c1c22;
    border: none;
    border-radius: 3px;
    height: 6px;
    text-align: center;
}
QProgressBar::chunk {
    background-color: #00B0FF;
    border-radius: 3px;
}
QMessageBox, QDialog {
    background-color: #16161a;
}
QToolTip {
    background-color: #1c1c22;
    color: #ffffff;
    border: 1px solid #383845;
    border-radius: 6px;
    padding: 6px 10px;
}
QTextEdit {
    background-color: #1c1c22;
    border: 1px solid #272730;
    border-radius: 8px;
    padding: 8px;
    color: #ffffff;
}
QFrame#controlPanel {
    background-color: #18181c;
    border-left: 1px solid #23232b;
    border-radius: 10px;
}
QStatusBar {
    background-color: #121215;
    border-top: 1px solid #23232b;
}
QStatusBar QLabel {
    color: #a1a1aa;
}
"""