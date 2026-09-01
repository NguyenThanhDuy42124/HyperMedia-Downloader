"""Module tải video đa phần (Multi-part Range Downloader 16 luồng kiểu IDM) tích hợp đồng bộ hóa an toàn tuyệt đối."""
import os
import sys
import time
import threading
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

def download_range_part(part_index, url, headers, start_byte, end_byte, out_filepath, lock, progress_callback=None, max_retries=10):
    """Mỗi thread tự mở một file handle riêng biệt để tránh xung đột pointer `.seek()` giữa các thread."""
    req_headers = dict(headers or {})
    req_headers['Range'] = f'bytes={start_byte}-{end_byte}'
    
    current_offset = start_byte
    retries = 0

    while current_offset <= end_byte and retries < max_retries:
        try:
            req = urllib.request.Request(url, headers=req_headers)
            req.add_header('Range', f'bytes={current_offset}-{end_byte}')
            
            # Mỗi thread mở file handle độc lập của riêng mình
            with urllib.request.urlopen(req, timeout=25) as resp:
                with open(out_filepath, 'r+b') as f:
                    f.seek(current_offset)
                    buffer_size = 512 * 1024  # 512KB buffer per read
                    while current_offset <= end_byte:
                        chunk = resp.read(min(buffer_size, end_byte - current_offset + 1))
                        if not chunk:
                            break
                        f.write(chunk)
                        chunk_len = len(chunk)
                        current_offset += chunk_len
                        
                        if progress_callback:
                            with lock:
                                progress_callback(chunk_len)
        except Exception as e:
            retries += 1
            time.sleep(1.0)
    
    if current_offset <= end_byte:
        raise IOError(f"Phân đoạn {part_index} ({start_byte}-{end_byte}) thất bại sau {max_retries} lần thử lại.")
    return part_index

class MultiPartDownloader:
    """Tải 1 stream URL bằng N luồng byte-range song song có rào chắn đồng bộ (Sync Barrier & Lock)."""
    def __init__(self, num_parts=16, max_retries=10):
        self.num_parts = num_parts
        self.max_retries = max_retries
        self.lock = threading.Lock()
        # Barrier đồng bộ hóa số luồng tải + 1 luồng chính
        self.barrier = threading.Barrier(self.num_parts + 1)

    def get_stream_info(self, url, headers=None):
        req = urllib.request.Request(url, headers=headers or {}, method='HEAD')
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                length = resp.headers.get('Content-Length')
                accept_ranges = resp.headers.get('Accept-Ranges') == 'bytes' or 'bytes' in resp.headers.get('Content-Range', '')
                return int(length) if length else None, accept_ranges
        except Exception:
            return None, False

    def download_stream(self, url, out_filepath, headers=None, status_callback=None):
        headers = headers or {}
        content_length, supports_range = self.get_stream_info(url, headers)

        if not content_length or not supports_range:
            # Fallback đơn luồng nếu server không hỗ trợ HTTP Range
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req) as resp, open(out_filepath, 'wb') as f:
                while True:
                    chunk = resp.read(512 * 1024)
                    if not chunk:
                        break
                    f.write(chunk)
            return

        # Tạo sẵn dung lượng file ảo chuẩn xác trên đĩa
        with open(out_filepath, 'wb') as f:
            f.truncate(content_length)

        # Tính toán chính xác 16 phân đoạn dải byte
        part_size = content_length // self.num_parts
        ranges = []
        for i in range(self.num_parts):
            start = i * part_size
            end = content_length - 1 if i == self.num_parts - 1 else (i + 1) * part_size - 1
            ranges.append((i, start, end))

        downloaded_bytes = 0
        last_time = time.time()
        last_bytes = 0
        completed_flags = [False] * self.num_parts

        def chunk_progress(size):
            nonlocal downloaded_bytes, last_time, last_bytes
            downloaded_bytes += size
            now = time.time()
            dt = now - last_time
            if dt >= 0.5:
                speed = (downloaded_bytes - last_bytes) / dt if dt > 0 else 0
                last_bytes = downloaded_bytes
                last_time = now
                if status_callback:
                    status_callback(downloaded_bytes, content_length, speed)

        def worker_task(idx, start, end):
            try:
                download_range_part(idx, url, headers, start, end, out_filepath, self.lock, chunk_progress, self.max_retries)
                completed_flags[idx] = True
            finally:
                # Mỗi luồng khi hoàn thành (dù thành công hay lỗi) đều điểm danh tại Rào chắn (Barrier)
                self.barrier.wait(timeout=120)

        with ThreadPoolExecutor(max_workers=self.num_parts) as executor:
            for idx, start, end in ranges:
                executor.submit(worker_task, idx, start, end)

            # Luồng chính đợi Rào chắn đồng bộ (Barrier) của 16 luồng hoàn tất
            try:
                self.barrier.wait(timeout=3600)
            except threading.BrokenBarrierError:
                raise TimeoutError("Lỗi đồng bộ hóa: Rào chắn Barrier bị đứt do có luồng quá thời gian.")

        # Đảm bảo rào cản 100%: Tất cả 16/16 phần đều phải đánh dấu True
        if not all(completed_flags):
            failed = [i for i, ok in enumerate(completed_flags) if not ok]
            raise RuntimeError(f"Tải không hoàn chỉnh! Các phân đoạn lỗi: {failed}")
