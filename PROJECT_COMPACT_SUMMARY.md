# ⚡ HYPERMEDIA DOWNLOADER PRO — DỰ ÁN TỔNG HỢP & BÁO CÁO KỸ THUẬT TOÀN DIỆN (COMPACT SUMMARY)

> **Dự án:** HyperMedia Downloader Pro (Desktop App & Companion Extension)  
> **Phiên bản:** Core 3.9+ / Bilibili Engine 2.5 / YouTube EJS Engine / Extension Manifest V3  
> **Ngôn ngữ & Công nghệ chính:** Python 3.10+, PySide6 (Qt6), yt-dlp, FFmpeg, QuickJS-ng, JavaScript (ES6+), Chrome MV3 Extension, PyInstaller.  
> **Trạng thái kiểm thử:** 21/21 Unit Tests PASS (100% QA Test Suite)  

---

## 1. TỔNG QUAN HỆ THỐNG & KIẾN TRÚC (SYSTEM ARCHITECTURE)

Dự án gồm **2 phân hệ hoạt động song song**:
1. **Desktop Client:** Ứng dụng giao diện đồ họa PySide6 cao cấp (Cyber Dark Neon), tích hợp công cụ tải đa luồng, cơ chế giải mã chống bot (Anti-Bot / Cipher Solver), và hệ thống quản lý bản quyền phần cứng (HWID Lock).
2. **Companion Browser Extension:** Tiện ích mở rộng Chrome / Edge / Cốc Cốc / Brave / Opera (Manifest V3) đóng vai trò cầu nối: bắt link hàng loạt, bắt stream CDN 1080p gốc của Douyin/TikTok, và trích xuất Live Cookies trực tiếp từ trình duyệt nạp tự động vào Desktop App qua cổng HTTP nội bộ (Local Port Hopping 42124–42135).

```
                      +------------------------------------------+
                      |       TRÌNH DUYỆT (CHROME / EDGE)        |
                      |  - Đăng nhập tài khoản VIP/Thường        |
                      |  - Extension HyperMedia Helper (MV3)     |
                      +--------------------+---------------------+
                                           |
                   Bắn Link & Live Cookies | HTTP REST / Long-Polling
                      (http://127.0.0.1:42124 -> 42135)
                                           v
+-----------------------------------------------------------------------------------+
|                        HYPERMEDIA DOWNLOADER PRO (DESKTOP)                        |
|                                                                                   |
|  [Main.py]                                                                        |
|    ├── LicenseManager (HWID Lock + NTP Time chống lùi lịch + Mã kích hoạt)       |
|    └── Bilibili / YouTube Patches                                                 |
|                                                                                   |
|  [main_window.py]                                                                 |
|    ├── UI Grid Card ảo hóa (VideoListView + VideoItemDelegate)                   |
|    ├── LocalServer (Cầu nối nhận Link & Cookies tự động)                         |
|    ├── Bộ điều phối Adaptive Platform Dispatcher + Staggered Launch              |
|    ├── Quản lý Tiền tố Tên file (Prefix) & Tải trùng (Dup1, Dup2...)             |
|    └── Chu kỳ tự động đồng bộ Cookies: Tải -> Lấy Cookie mới -> Tải tiếp       |
|                                                                                   |
|  [scan_worker.py] & [download_worker.py]                                          |
|    ├── Nhúng QuickJS-ng (qjs.exe 1.87MB) -> Giải mã n-sig / Cipher YouTube        |
|    ├── Bilibili Engine: DASH 1080p fnval=4048 + Tencent Cloud MirrorCOS          |
|    ├── Fallback giao diện mới Bilibili (Bypass "Unable to extract initial state") |
|    ├── Douyin Direct Mobile API 1080p (Không watermark)                          |
|    └── Dọn dẹp cách ly file .part (Không xóa nhầm luồng tải song song khác)       |
+-----------------------------------------------------------------------------------+
```

---

## 2. DANH MỤC CÁC MODULE CỐT LÕI (CORE MODULES)

| Tên File | Vai trò & Trách nhiệm kỹ thuật |
| :--- | :--- |
| [`Main.py`](file:///d:/BaiThucHanh/PythonFile/AppDowloadYoutube/Main.py) | Entrypoint của ứng dụng. Dọn dẹp tiến trình cũ (`kill_previous_instances`), khởi động logging, kích hoạt bản vá Bilibili, kiểm tra bản quyền máy trạm (HWID) trước khi mở giao diện chính. |
| [`main_window.py`](file:///d:/BaiThucHanh/PythonFile/AppDowloadYoutube/main_window.py) | Cửa sổ trung tâm (~2.200 dòng). Điều phối hàng đợi tải đa luồng, xử lý giao diện thẻ Card (Grid 4 cột), bảng điều khiển nâng cao, tiền tố (Prefix), bắt stdout hiển thị Live Log Console, đồng bộ cookie theo chu kỳ. |
| [`download_worker.py`](file:///d:/BaiThucHanh/PythonFile/AppDowloadYoutube/download_worker.py) | Worker QThread chuyên sâu phụ trách tải video. Tích hợp cấu hình yt-dlp tối ưu theo từng nền tảng, cơ chế chunking, cascade fallback hạ độ phân giải khi gặp lỗi định dạng, và xử lý dọn file tạm cô lập. |
| [`scan_worker.py`](file:///d:/BaiThucHanh/PythonFile/AppDowloadYoutube/scan_worker.py) | Worker QThread quét nhanh metadata video, playlist, tuyển tập phim, kênh space mà không làm đơ giao diện người dùng. |
| [`bilibili_patch.py`](file:///d:/BaiThucHanh/PythonFile/AppDowloadYoutube/bilibili_patch.py) | Monkey-patch các phương thức của yt-dlp: Bypass lỗi HTTP 412, giữ tiêu đề space/list khi quét flat, sửa lỗi Bilibili giao diện mới không có `INITIAL_STATE`, và rewrite CDN P2P sang Tencent Cloud. |
| [`app_constants.py`](file:///d:/BaiThucHanh/PythonFile/AppDowloadYoutube/app_constants.py) | Hằng số cấu hình, danh sách User-Agent, bảng map độ phân giải và hàm `get_js_runtime()` tự động phát hiện `qjs.exe` (QuickJS) nhúng sẵn hoặc Node.js/Deno hệ thống. |
| [`local_server.py`](file:///d:/BaiThucHanh/PythonFile/AppDowloadYoutube/local_server.py) | Máy chủ HTTP đa luồng cục bộ (port 42124–42135). Hỗ trợ Port Hopping, Long-polling nhận link và live cookies từ Extension, trang Sync Hub hướng dẫn người dùng. |
| [`license_manager.py`](file:///d:/BaiThucHanh/PythonFile/AppDowloadYoutube/license_manager.py) | Hệ thống bảo mật: Thuật toán tạo Hardware ID duy nhất dựa trên bo mạch chủ & CPU, ký và xác minh Key kích hoạt (Vĩnh viễn hoặc Có thời hạn), kiểm tra thời gian chuẩn qua NTP Server (chống gian lận lùi giờ hệ thống). |
| [`activation_dialog.py`](file:///d:/BaiThucHanh/PythonFile/AppDowloadYoutube/activation_dialog.py) | Hộp thoại kích hoạt bản quyền giao diện Cyber Dark Neon sang trọng, hiển thị HWID, trạng thái giấy phép và ô nhập License Key. |
| [`generate_key.py`](file:///d:/BaiThucHanh/PythonFile/AppDowloadYoutube/generate_key.py) | Tool CLI nội bộ dùng để tạo Key kích hoạt cho khách hàng từ xa theo HWID (chọn gói: Ngày, Tháng, Năm, Vĩnh viễn). |
| [`delegates.py`](file:///d:/BaiThucHanh/PythonFile/AppDowloadYoutube/delegates.py) | QStyledItemDelegate vẽ giao diện thẻ Card (320x300px) ảo hóa mượt mà: Thumbnail, thanh tiến trình màu động, thông số tốc độ tải, nút thao tác nhanh. |
| [`models.py`](file:///d:/BaiThucHanh/PythonFile/AppDowloadYoutube/models.py) | `VideoListModel` kế thừa QAbstractListModel với 15+ Custom Roles, quản lý trạng thái realtime từng video trong danh sách. |
| [`site_utils.py`](file:///d:/BaiThucHanh/PythonFile/AppDowloadYoutube/site_utils.py) | Nhận diện nền tảng (YouTube, Bilibili, Douyin), chuẩn hóa URL (URL Regex parser, link chia sẻ di động v.douyin.com, link modal, link rút gọn). |
| [`qa_test_suite.py`](file:///d:/BaiThucHanh/PythonFile/AppDowloadYoutube/qa_test_suite.py) | Bộ kiểm thử hợp đồng tự động (21 Unit Test Cases) kiểm tra toàn bộ tính năng và bảo vệ chống hồi quy (Regression Testing). |
| [`qjs.exe`](file:///d:/BaiThucHanh/PythonFile/AppDowloadYoutube/qjs.exe) | File thực thi QuickJS-ng v0.18.0 (1.87 MB) đóng gói cùng ứng dụng, đóng vai trò JavaScript Runtime độc lập cho yt-dlp. |
| [`ffmpeg.exe`](file:///d:/BaiThucHanh/PythonFile/AppDowloadYoutube/ffmpeg.exe) | Bộ xử lý đa phương tiện FFmpeg đóng gói kèm, ghép luồng video DASH và audio riêng biệt thành file MP4 hoàn chỉnh. |

---

## 3. CÁC TÍNH NĂNG & ĐỘT PHÁ KỸ THUẬT QUAN TRỌNG

### 3.1. Giải pháp YouTube HD/4K & Nhúng JS Runtime (QuickJS)
- **Vấn đề trước đây:** YouTube áp dụng cơ chế xác thực GVS PO Token trên các client di động/nhúng (`ios`, `android`, `mweb`) khiến yt-dlp bị bóp về duy nhất 360p. Đồng thời, trên máy khách không có Node.js/Deno, yt-dlp không giải mã được chữ ký Cipher $\rightarrow$ văng lỗi `HTTP Error 403: Forbidden`.
- **Giải pháp:**
  - Chuẩn hóa client Web chuẩn, áp dụng `player_skip: ["configs"]`.
  - Nhúng trực tiếp binary **QuickJS-ng v0.18.0** (`qjs.exe` - 1.87 MB) vào file `.spec` của PyInstaller.
  - Máy khách 100% không cần cài đặt Node.js hay Deno vẫn tải được video YouTube Full HD (1080p), 2K (1440p) và 4K (2160p) mượt mà.

### 3.2. Cứu luồng Bilibili giao diện mới (`Unable to extract initial state`)
- **Vấn đề trước đây:** Bilibili triển khai giao diện mới thử nghiệm (`pageVersion = "new_video"`), gỡ bỏ biến `window.__INITIAL_STATE__` trong HTML tĩnh. `yt-dlp` tìm không thấy biến này liền báo lỗi `Unable to extract initial state` và dừng tải.
- **Giải pháp:**
  - Viết bản vá Monkey-Patch trong `bilibili_patch.py`.
  - Khi gặp ngoại lệ trên, App tự động kích hoạt Fallback gọi trực tiếp API `x/web-interface/wbi/view/detail`.
  - Tự động bóc tách tiêu đề, danh sách tập (`pages`), mã phân mảnh (`cid`), phân tách đa tập (`p01`, `p02`...) và tải bình thường.

### 3.3. Tối ưu tốc độ tải Bilibili (Config E & CDN Rewrite)
- Phân phối luồng DASH: Video chất lượng cao (H.264/HEVC) và âm thanh (AAC 192kbps) tải riêng biệt qua tham số `fnval=4048`.
- Cơ chế **Config E**: Thiết lập 6 luồng tải song song + chunk size 8MB chống rớt socket.
- Tự động phát hiện và chuyển đổi (rewrite) các server CDN P2P (`mcdn.bilivideo.com`) hoặc Akamai bị bóp băng thông sang cụm máy chủ **Tencent Cloud MirrorCOS** (`upos-sz-mirrorcos.bilivideo.com`) tốc độ cao.

### 3.4. Hệ thống đặt Tiền tố Tên file (Prefix) thông minh
Tích hợp giao diện chọn tiền tố kèm live preview:
1. **Prefix Số Đầu:** `1 ( Tên video )`, `2 ( Tên video )`...
2. **Prefix Số Đầu (01):** Tự bù số 0 nếu dưới 10: `01 ( Tên video )`, `02 ( Tên video )`...
3. **Prefix Tập + số:** `Tập 1 - Tên video`, `Tập 2 - Tên video`...
4. **Prefix Tên Film:** Hiển thị ô nhập tên phim riêng: `Tên Film Bạn Nhập - (Tên Film Bạn Tải)`.
5. Tự động làm sạch toàn bộ ký tự cấm trên Windows (`\ / : * ? " < > |`) chống crash khi ghi file.

### 3.5. Chế độ Tải trùng an toàn (Duplicate Handling)
- Checkbox `Cho phép tải trùng (Dup1, Dup2...)`: Khi bật, nếu phát hiện file cùng tên (hoặc file `.part` đang tải dở) trong thư mục lưu, app không bỏ qua mà tự động đánh số tăng dần: `Dup1_TenVideo.mp4`, `Dup2_TenVideo.mp4`...

### 3.6. Chu kỳ lấy Cookies tự động từ Extension
- Quy trình khép kín:
  $$\text{Bắt đầu tải} \longrightarrow \text{Extension trích xuất Live Cookies} \longrightarrow \text{Tải video} \longrightarrow \text{Lấy cookies mới} \longrightarrow \text{Tải tiếp}$$
- Tránh tình trạng cookie session bị hết hạn giữa chừng khi tải danh sách hàng chục video dài.

### 3.7. Bảo vệ tiến trình tải file dở dang (.part)
- Hàm `_cleanup_my_part_files()` sử dụng thuật toán cô lập dựa trên `_resolved_title`, chỉ xóa file `.part` của chính video đang hoàn thành hoặc lỗi, **tuyệt đối không xóa nhầm** file `.part` của các video khác đang tải song song bên cạnh.

---

## 4. CHI TIẾT BỘ KIỂM THỬ QA HỢP ĐỒNG (21 TEST CASES)

Bộ test `qa_test_suite.py` là lá chắn chất lượng bảo đảm không có lỗi phát sinh sau mỗi lần cập nhật mã:

```
============================================================
KHỞI CHẠY BỘ KIỂM THỬ QA TOÀN DIỆN (OFFLINE CONTRACT SUITE)
============================================================
test_custom_pattern_substitution ......................... ok
test_empty_or_unknown_title_fallback ..................... ok
test_forbidden_windows_characters ........................ ok
test_prefix_modes_with_film_name_box ..................... ok
test_preset_01_ten_phim .................................. ok
test_preset_1_ten_phim ................................... ok
test_preset_tap_va_phim .................................. ok
test_duplicate_checks_part_files ......................... ok
test_duplicate_naming_sequence ........................... ok
test_file_exists_bypass_when_allow_duplicates ............ ok
test_youtube_base_opts_contract .......................... ok
test_youtube_high_res_extraction ......................... ok
test_youtube_url_detection ............................... ok
test_bilibili_base_opts_contract ......................... ok
test_bilibili_headers .................................... ok
test_bilibili_url_detection .............................. ok
test_douyin_headers ...................................... ok
test_douyin_prefix_and_duplicate_support ................. ok
test_douyin_url_normalization ............................ ok
test_isolation_no_accidental_delete ...................... ok
test_local_server_cookie_request_dispatch ................ ok
------------------------------------------------------------
Ran 21 tests in 2.3s — STATUS: PASS (100%)
```

---

## 5. HƯỚNG DẪN VẬN HÀNH & ĐÓNG GÓI (OPERATIONAL GUIDE)

### 5.1. Chạy mã nguồn trực tiếp
```bash
# Kích hoạt virtualenv
env\Scripts\activate

# Khởi chạy giao diện chính
python Main.py
```

### 5.2. Chạy bộ kiểm thử tự động
```bash
python qa_test_suite.py
```

### 5.3. Tạo Key bản quyền cho khách hàng từ xa
```bash
# Cách 1: Chạy file batch giao diện trực quan
Tao_Key_Ban_Quyen.bat

# Cách 2: Dùng lệnh CLI
python generate_key.py --hwid "HWID_CUA_KHACH" --type lifetime
# Hoặc tạo key có thời hạn 30 ngày:
python generate_key.py --hwid "HWID_CUA_KHACH" --type days --val 30
```

### 5.4. Đóng gói ứng dụng sang file thực thi (.exe) độc lập
File cấu hình `HyperMedia_Downloader_Pro.spec` đã được thiết lập nhúng sẵn `ffmpeg.exe` và `qjs.exe`:
```bash
# Đảm bảo tắt app cũ trước khi build
Stop-Process -Name "HyperMedia_Downloader_Pro" -Force -ErrorAction SilentlyContinue

# Đóng gói với PyInstaller
env\Scripts\pyinstaller.exe --noconfirm HyperMedia_Downloader_Pro.spec

# Dọn dẹp thư mục tạm build
Remove-Item -Recurse -Force "build" -ErrorAction SilentlyContinue
```
- **Thành phẩm:** `dist\HyperMedia_Downloader_Pro.exe` (Dung lượng: ~142 MB). File hoàn toàn độc lập, chạy ngay trên bất kỳ máy Windows nào mà không cần cài đặt thêm bất kỳ phần mềm phụ trợ nào.
