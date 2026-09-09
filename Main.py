import sys

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

import bilibili_patch
from activation_dialog import ActivationDialog
from app_constants import get_icon_path
from license_manager import check_current_machine_license
from logger import setup_app_logging
from main_window import YoutubeDownloaderApp
from theme import THEME_QSS


def main():
    setup_app_logging()
    bilibili_patch.patch_bilibili_extractor()
    bilibili_patch.patch_bilibili_space_titles()
    bilibili_patch.patch_bilibili_list_titles()

    app = QApplication(sys.argv)
    app.setApplicationName("HyperMedia Downloader Pro")
    app.setStyleSheet(THEME_QSS)
    icon_path = get_icon_path()
    if icon_path:
        app.setWindowIcon(QIcon(icon_path))

    # 1. Kiểm tra bản quyền máy tính trước khi mở ứng dụng
    is_valid, msg, info = check_current_machine_license()
    if not is_valid:
        dialog = ActivationDialog()
        if dialog.exec() != ActivationDialog.DialogCode.Accepted or not dialog.is_activated:
            sys.exit(0)
        is_valid, msg, info = check_current_machine_license()

    window = YoutubeDownloaderApp(license_info=info)
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()