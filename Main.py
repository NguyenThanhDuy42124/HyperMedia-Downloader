import sys

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

import bilibili_patch
from app_constants import get_icon_path
from logger import setup_app_logging
from main_window import YoutubeDownloaderApp
from theme import THEME_QSS


def main():
    setup_app_logging()
    bilibili_patch.patch_bilibili_extractor()
    bilibili_patch.patch_bilibili_space_titles()
    bilibili_patch.patch_bilibili_list_titles()

    app = QApplication(sys.argv)
    app.setApplicationName("YouTube Downloader Pro")
    app.setStyleSheet(THEME_QSS)
    icon_path = get_icon_path()
    if icon_path:
        app.setWindowIcon(QIcon(icon_path))

    window = YoutubeDownloaderApp()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()