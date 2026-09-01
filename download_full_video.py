import os
import sys
import time

sys.stdout.reconfigure(encoding='utf-8')

import yt_dlp
import bilibili_patch

bilibili_patch.patch_bilibili_extractor()

from download_worker import DownloadWorker

url = "https://www.bilibili.com/video/BV1uwknYHEsw"
out_dir = os.path.join(os.getcwd(), "downloads")

print("=== STARTING FULL 100% DOWNLOAD INTO downloads/ ===")
print("URL:", url)
print("Output Directory:", out_dir)

worker = DownloadWorker(
    url,
    {
        "output_path": out_dir,
        "resolution": "1080",
        "file_type": "mp4",
        "codec": "H.264",
        "browser": "None",
    }
)

def progress_cb(pct):
    pass

def status_cb(msg):
    print(f"[PROGRESS] {msg}")

def finished_cb():
    print("\n========================================================")
    print("SUCCESS: FULL 100% DOWNLOAD COMPLETED SUCCESSFULLY!")
    print("========================================================")

def error_cb(err):
    print(f"\n[DOWNLOAD ERROR] {err}")

worker.task_progress.connect(progress_cb)
worker.status_update.connect(status_cb)
worker.task_finished.connect(finished_cb)
worker.task_error.connect(error_cb)

worker.run()
