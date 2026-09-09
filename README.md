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

## 🔑 Hệ Thống Bản Quyền & Tạo Key (`generate_key.py`)

Hệ thống hỗ trợ 2 cơ chế sinh Key linh hoạt & bảo mật cao dành cho Admin:

### 1. Kiểu 1: Khóa Theo HWID Khách Gửi (HWID Key - Cố định trước)
* **Cú pháp:**
  ```bash
  python generate_key.py <HWID_KHACH> [PERM / 30 / 365 / YYYYMMDD]
  ```
* **Ví dụ:**
  ```bash
  python generate_key.py 4A21-8F9E-3B12-90CD PERM
  python generate_key.py 4A21-8F9E-3B12-90CD 30
  ```
* **Cơ chế:** Khách gửi mã HWID trên máy ➔ Admin nhập HWID để tạo Key. Key này chỉ có thể kích hoạt trên đúng máy có HWID đó.
* **Định dạng:** `KEY-PERM-A1B2-C3D4-E5F6-7890`

### 2. Kiểu 2: Key Đổi Tự Active / Không HWID (Redeem Key - No-HWID)
* **Cú pháp:**
  ```bash
  python generate_key.py nohwid [PERM / 30 / 365 / YYYYMMDD]
  ```
* **Ví dụ:**
  ```bash
  python generate_key.py nohwid PERM
  python generate_key.py nohwid 30
  ```
* **Cơ chế:** Admin sinh sẵn hàng loạt Key mà không cần hỏi HWID của khách trước. Mỗi Key chứa chuỗi ngẫu nhiên độc bản (Random Nonce).
* **Tự động khóa máy:** Khi khách hàng nhập Key và bấm **Kích Hoạt** lần đầu tiên trên máy A, phần mềm sẽ tự động ký số mã phần cứng Windows (`MachineGuid`) của máy A và khóa chặt Key đó vĩnh viễn với máy A. Từ đó về sau, máy B nhập lại Key này sẽ bị báo lỗi không hợp lệ!
* **Định dạng:** `KEY-REDEEM-PERM-A4B7C9-X1Y2-Z3W4-V5U6`

### 3. Cơ Chế Chống Hack & Bảo Mật An Toàn
* **Chống Hack Lùi Ngày Hệ Thống (Internet Time Check):** Tự động kiểm tra ngày giờ chuẩn từ Internet (Google / Cloudflare / WorldTimeAPI) để tính số ngày còn lại của Key. Người dùng lùi đồng hồ Windows cũng không hack được hạn dùng.
* **Nhận Diện Phần Cứng Bất Biến (MachineGuid Binding):** HWID sử dụng mã `MachineGuid` duy nhất trong Registry Windows. Người dùng đổi Wi-Fi, cắm dây mạng, bật VPN hay đổi MAC card mạng thì phần mềm vẫn nhận diện đúng máy cũ và giữ nguyên bản quyền.
* **Lưu Trữ Vĩnh Viễn Trong AppData:** File mã hóa `license.lic` và `activated.token` được lưu an toàn tại `%LOCALAPPDATA%\HyperMedia_Downloader_Pro`. Dù người dùng di chuyển file `.exe` sang bất kỳ ổ đĩa nào thì bản quyền vẫn tự động nhận diện.

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

## 👨‍💻 Tác Giả (Author)

* **GitHub:** [@NguyenThanhDuy42124 (Nguyễn Thanh Duy)](https://github.com/NguyenThanhDuy42124)
* **Repository:** [https://github.com/NguyenThanhDuy42124/HyperMedia-Downloader](https://github.com/NguyenThanhDuy42124/HyperMedia-Downloader)
* **Zalo hỗ trợ:** `0334674017`

---

## 📜 Giấy Phép (License)

Dự án được phân phối dưới giấy phép mã nguồn mở MIT License.
Mọi đóng góp (Pull Request, Issue, Feature Request) đều được hoan nghênh!

