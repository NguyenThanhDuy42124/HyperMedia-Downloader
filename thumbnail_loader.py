"""Tải thumbnail có giới hạn song song, emit về model theo uid."""
import threading
from collections import deque

import requests
from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QPixmap

from app_constants import MAX_THUMB_WORKERS


class ThumbnailPool(QObject):
    """Pool tải thumbnail: tối đa N worker, hàng đợi FIFO, bỏ item đã huỷ."""

    thumb_ready = Signal(str, object)  # uid, QPixmap (hoặc None)

    def __init__(self, max_workers=MAX_THUMB_WORKERS, parent=None):
        super().__init__(parent)
        self.max_workers = max_workers
        self._queue = deque()
        self._in_flight = set()
        self._requested = set()
        self._lock = threading.Lock()
        self._closed = False
        self._executor = None

    def _ensure_executor(self):
        if self._executor is None:
            from concurrent.futures import ThreadPoolExecutor

            self._executor = ThreadPoolExecutor(max_workers=self.max_workers)
            self._worker_executor = self._executor

    def request(self, uid, url):
        if not url:
            return
        with self._lock:
            if self._closed or uid in self._requested or uid in self._in_flight:
                return
            self._requested.add(uid)
            self._queue.append((uid, url))
        self._ensure_executor()
        self._worker_executor.submit(self._process)

    def cancel(self, uid):
        """Bỏ uid khỏi hàng đợi nếu chưa tải (không huỷ thread đang chạy)."""
        with self._lock:
            if uid in self._in_flight:
                return
            self._queue = deque((u, u_) for u, u_ in self._queue if u != uid)
            self._requested.discard(uid)

    def reset(self):
        """Xoá hàng đợi + danh sách đã yêu cầu (khi xoá sạch list)."""
        with self._lock:
            self._queue.clear()
            self._requested.clear()

    def _process(self):
        while True:
            with self._lock:
                if not self._queue:
                    return
                uid, url = self._queue.popleft()
                self._in_flight.add(uid)
            pixmap = self._fetch(url)
            with self._lock:
                self._in_flight.discard(uid)
            self.thumb_ready.emit(uid, pixmap)

    @staticmethod
    def _fetch(url):
        try:
            resp = requests.get(url, timeout=10)
            if resp.status_code == 200:
                pm = QPixmap()
                if pm.loadFromData(resp.content):
                    return pm
        except Exception as e:
            print(f"[THUMBNAIL ERROR] {e}")
        return None

    def shutdown(self):
        with self._lock:
            self._closed = True
            self._queue.clear()
        if self._executor is not None:
            self._executor.shutdown(wait=False, cancel_futures=True)
