"""Tải thumbnail có giới hạn song song, emit về model theo uid."""
import threading
from collections import deque, OrderedDict

import requests
from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QPixmap
from ca_bundle_utils import get_ca_bundle_path, sanitize_error_message

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
            if url.startswith("data:image/"):
                import base64
                header, base64_data = url.split(",", 1)
                img_data = base64.b64decode(base64_data)
                pm = QPixmap()
                if pm.loadFromData(img_data):
                    return pm
                return None

            from site_utils import detect_site
            from app_constants import get_random_user_agent
            headers = detect_site(url)
            headers["User-Agent"] = get_random_user_agent()
            resp = requests.get(url, headers=headers, timeout=10, verify=get_ca_bundle_path())
            if resp.status_code == 200:
                pm = QPixmap()
                if pm.loadFromData(resp.content):
                    return pm
        except Exception as e:
            pass  # Thumbnail load failure silently handled with fallback icon/text
        return None

    def shutdown(self):
        with self._lock:
            self._closed = True
            self._queue.clear()
        if self._executor is not None:
            self._executor.shutdown(wait=False, cancel_futures=True)


class ThumbnailLoader(QObject):
    """Tiện ích tải thumbnail có bộ nhớ đệm LRU giới hạn dung lượng và fan-out callback cho nhiều widget."""

    MAX_CACHE_SIZE = 120  # Giới hạn tối đa 120 ảnh trong RAM, tránh rò rỉ bộ nhớ dài hạn

    def __init__(self, parent=None):
        super().__init__(parent)
        self._pool = ThumbnailPool(max_workers=4, parent=self)
        self._cache = OrderedDict()  # url -> QPixmap với cơ chế LRU eviction
        self._callbacks = {}  # url -> list of callbacks
        self._pool.thumb_ready.connect(self._on_ready)

    def load_thumbnail(self, url: str, callback):
        if not url or not callback:
            return

        # 1. Trả về ngay nếu ảnh đã có sẵn trong bộ nhớ đệm (và refresh vị trí LRU)
        if url in self._cache:
            self._cache.move_to_end(url)
            try:
                callback(self._cache[url])
            except Exception:
                pass
            return

        # 2. Đăng ký callback cho subscriber
        first_time = url not in self._callbacks
        self._callbacks.setdefault(url, []).append(callback)

        # 3. Chỉ gửi request tải mạng nếu chưa có lượt tải nào đang chạy cho URL này
        if first_time:
            # Tạo unique UID kèm URL để ThumbnailPool không chặn khi refresh
            import uuid
            req_id = f"{uuid.uuid4().hex[:8]}|{url}"
            self._pool.request(req_id, url)

    def load(self, url: str, callback):
        """Bí danh tiện lợi cho load_thumbnail."""
        return self.load_thumbnail(url, callback)

    def _on_ready(self, req_id, pixmap):
        # Trích xuất URL gốc từ req_id
        url = req_id.split("|", 1)[1] if "|" in req_id else req_id

        if pixmap and not pixmap.isNull():
            self._cache[url] = pixmap
            self._cache.move_to_end(url)
            # Giới hạn dung lượng cache theo LRU
            if len(self._cache) > self.MAX_CACHE_SIZE:
                self._cache.popitem(last=False)

        cbs = self._callbacks.pop(url, [])
        for cb in cbs:
            try:
                cb(pixmap)
            except Exception:
                pass

    def shutdown(self):
        """Giải phóng toàn bộ cache và dừng pool khi ứng dụng/widget đóng."""
        self._cache.clear()
        self._callbacks.clear()
        self._pool.shutdown()
