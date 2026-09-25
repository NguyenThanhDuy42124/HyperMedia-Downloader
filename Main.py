import os
import subprocess
import sys

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

import bilibili_patch
from activation_dialog import ActivationDialog
from app_constants import get_icon_path, migrate_legacy_data
from license_manager import check_current_machine_license
from logger import setup_app_logging
from main_window import YoutubeDownloaderApp
from theme import THEME_QSS


def kill_previous_instances():
    """Đảm bảo chỉ có DUY NHẤT 1 phiên bản HyperMedia Downloader Pro chạy trên máy,

    tự động giải phóng cổng 42124 để Extension kết nối thông suốt.
    """
    try:
        current_pid = os.getpid()
        exe_name = "HyperMedia_Downloader_Pro.exe"
        cmd = f'tasklist /FI "IMAGENAME eq {exe_name}" /FO CSV /NH'
        out = subprocess.check_output(cmd, shell=True, text=True, stderr=subprocess.DEVNULL)
        for line in out.splitlines():
            line = line.strip()
            if not line or exe_name.lower() not in line.lower():
                continue
            parts = [p.strip(' "') for p in line.split('","')]
            if len(parts) >= 2 and parts[1].isdigit():
                pid = int(parts[1])
                if pid != current_pid:
                    print(f"[SINGLE INSTANCE] Đang dọn dẹp tiến trình cũ (PID: {pid})...")
                    subprocess.call(
                        f"taskkill /F /PID {pid}",
                        shell=True,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
    except Exception:
        pass


def main():
    kill_previous_instances()  # Luôn dọn dẹp tiến trình cũ trước khi chạy
    migrate_legacy_data()  # Chuyển file cũ sang %APPDATA%\HyperMedia nếu cần
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
        if (
            dialog.exec() != ActivationDialog.DialogCode.Accepted
            or not dialog.is_activated
        ):
            sys.exit(0)
        is_valid, msg, info = check_current_machine_license()

    window = YoutubeDownloaderApp(license_info=info)
    window.show()
    exit_code = app.exec()
    # Đảm bảo tắt triệt để mọi luồng ngầm khi người dùng bấm X tắt App
    os._exit(exit_code)


if __name__ == "__main__":
    main()