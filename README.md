# 🚀 HyperMedia-Downloader (HyperMedia Downloader Pro)

<div align="center">

[![Python Version](https://img.shields.io/badge/Python-3.10%2B-blue.svg?style=for-the-badge&logo=python&logoColor=white)](https://python.org)
[![Framework](https://img.shields.io/badge/GUI-PySide6%20%2F%20Qt6-41CD52.svg?style=for-the-badge&logo=qt&logoColor=white)](https://pyside.org)
[![Engine](https://img.shields.io/badge/Engine-yt--dlp%20%2B%20FFmpeg-FF0000.svg?style=for-the-badge&logo=youtube&logoColor=white)](https://github.com/yt-dlp/yt-dlp)
[![Platform](https://img.shields.io/badge/Platform-Windows-0078D6.svg?style=for-the-badge&logo=windows&logoColor=white)](https://microsoft.com)

**Ứng dụng tải Video & Audio đa nền tảng tốc độ cao (YouTube 4K, Bilibili 1080p, Douyin Full HD không logo) với giao diện Cyberpunk Dark Neon hiện đại.**

[Tính năng nổi bật](#-tính-năng-nổi-bật) • [Cài đặt & Chạy](#-cài-đặt--chạy-nguồn) • [Đóng gói Exe](#-đóng-gói-thành-file-exe) • [Phím tắt](#-phím-tắt-tiện-lợi)

</div>

---

## ✨ Tính Năng Nổi Bật

### 🌐 1. Hỗ Trợ Đa Nền Tảng Toàn Diện (All-In-One)
* **YouTube:** Tải mọi chất lượng từ **360p, 1080p, 2K (1440p) đến 4K (2160p) / 8K**, hỗ trợ video đơn, Playlist và quét toàn bộ Video Kênh.
* **Bilibili (哔哩哔哩):** Vượt cơ chế Anti-Bot & WBI Signature, mở khóa **1080p / 60fps**, tải Danh sách phát (`/lists`), Hợp tập (`/channel/collectiondetail`) và Trang cá nhân (`space.bilibili.com`).
* **Douyin (抖音 - TikTok Trung Quốc):** Mở khóa trực tiếp luồng **1080p Full HD gốc không Watermark / không Logo**, hỗ trợ link rút gọn `v.douyin.com` và link chia sẻ văn bản.

### ⚡ 2. Động Cơ Tải Siêu Tốc (Turbo Multi-threading)
* **Chia nhỏ tập tin (Chunk Segments):** Kích hoạt 4 đến 16 luồng tải song song trên từng video, tối đa hóa băng thông đường truyền internet.
* **Hàng đợi động (Dynamic Queue):** Vừa quét link mới vừa bấm tải ngay, các video tiếp theo sẽ tự động nối đuôi vào hàng đợi đang tải ngầm mà không làm gián đoạn tiến trình.
* **Tải hàng loạt (Batch Paste):** Copy và dán cùng lúc **20 - 50 link** (hoặc cả đoạn văn bản chia sẻ), ứng dụng tự động lọc link sạch sẽ và nạp toàn bộ vào danh sách.

### 🎨 3. Giao Diện Cyber Dark Neon Hiện Đại
* Thiết kế trực quan bằng **PySide6 (Qt6)** với phong cách Dark Mode neon sắc nét.
* Thanh điều khiển ngữ cảnh nổi thông minh (**Floating Action Bar**) xuất hiện mượt mà khi chọn video.
* Bảng điều khiển giám sát thời gian thực: Tốc độ tải (MB/s), Dung lượng (Size), Thời gian còn lại (ETA), Số luồng hoạt động (Threads).
* Hỗ trợ tự động thử lại thông minh **6 lần** khi mạng chập chờn với độ trễ lũy tiến.

### 🎵 4. Quản Lý Định Dạng & Tách Âm Thanh Linh Hoạt
* Xuất file **MP4** với codec tùy chọn (H.264, H.265/HEVC, AV1).
* Tách nhạc chất lượng cao **MP3 320kbps / Lossless** chỉ với 1 click.

---

## 🖥️ Yêu Cầu Hệ Thống

* **Hệ điều hành:** Windows 10 / 11 (64-bit).
* **Python:** 3.10 trở lên.
* **FFmpeg:** Đi kèm sẵn trong thư mục ứng dụng để ghép luồng Audio/Video chất lượng cao.

---

## 🚀 Cài Đặt & Chạy Nguồn

1. **Clone repository về máy:**
   ```bash
   git clone https://github.com/NguyenThanhDuy42124/HyperMedia-Downloader.git
   cd HyperMedia-Downloader
   ```

2. **Tạo môi trường ảo & cài đặt thư viện:**
   ```bash
   python -m venv env
   env\Scripts\activate
   pip install -r requirements.txt
   ```
   *(Nếu chưa có file requirements: `pip install PySide6 yt-dlp requests Cryptodome brotli certifi curl_cffi`)*

3. **Khởi chạy ứng dụng:**
   ```bash
   python Main.py
   ```

---

## 📦 Đóng Gói Thành File EXE

Để build ra 1 file `.exe` duy nhất hoàn chỉnh có sẵn Icon và FFmpeg:

```bash
pyinstaller --noconfirm --onefile --windowed --icon=icon/icon.ico --add-data="icon/icon.ico;icon" --add-binary="ffmpeg.exe;." --name "HyperMedia_Downloader_Pro" Main.py
```

File sau khi build sẽ nằm gọn gàng tại thư mục: `dist/HyperMedia_Downloader_Pro.exe`.

---

## ⌨️ Phím Tắt Tiện Lợi

| Phím tắt | Tác vụ |
| :--- | :--- |
| **`Ctrl + A`** | Chọn tất cả video trong danh sách |
| **`Ctrl + D`** | Bỏ chọn tất cả video |
| **`Ctrl + F`** | Di chuyển nhanh vào ô nhập link tìm kiếm |
| **`Delete`** | Xóa các thẻ video đang chọn khỏi bảng |
| **`Esc`** | Dừng toàn bộ tiến trình tải ngay lập tức |

---

## 📜 Giấy Phép (License)

Dự án được phân phối dưới giấy phép mã nguồn mở MIT License.
Mọi đóng góp (Pull Request, Issue, Feature Request) đều được hoan nghênh!
