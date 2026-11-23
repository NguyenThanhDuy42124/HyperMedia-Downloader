"""
drama_path_utils.py
~~~~~~~~~~~~~~~~~~~
Bộ công cụ quản lý cấu trúc thư mục, chuẩn hóa tên file/folder an toàn theo chuẩn Windows,
chống Path Traversal, định danh Việt hóa cho MiniApp Douyin và xử lý file trùng lặp (Dup1_, Dup2_).

Cấu trúc lưu trữ chuẩn:
- MiniApp Douyin:
  downloads/
  └── MiniApp Douyin/
      └── {Tên MiniApp Việt hóa}/
          └── {Tên bộ phim}/
              ├── 01 - {Tên tập}.mp4
              └── ...
- Các nền tảng Short Drama khác (DramaBox, KissKH, v.v.):
  downloads/
  └── {Tên nền tảng}/
      └── {Tên bộ phim}/
          ├── 01 - {Tên tập}.mp4
          └── ...
"""

import os
import re
from typing import Optional, Tuple

# Bảng mã ánh xạ tên hiển thị tiếng Việt cố định cho các nguồn MiniApp Douyin (họ duolai)
MINIAPP_DISPLAY_NAMES = {
    "tt5b4d2df0c47bdd2201": "Đa Lai",
    "tt839df5201ca3d79a01": "Hắc Nham Mạn",
    "tt3eca4877a1fed32a01": "Kim Miêu Mạn Phẩm",
    "ttbe17c8aa2121c82101": "Vạn Hoa Câu Chuyện",
    "tt48293e94d71caebe01": "Tiểu Thất Mạn Sảng Các",
    "tte1e6975b7eecc91e01": "Tinh Nguyệt Mạn",
    "tte06596d87f5402a101": "Man Mạn Thời Không",
}

# Tên thiết bị dành riêng bị cấm trong Windows (Reserved Device Names)
WINDOWS_RESERVED_NAMES = {
    "CON", "PRN", "AUX", "NUL",
    "COM1", "COM2", "COM3", "COM4", "COM5", "COM6", "COM7", "COM8", "COM9",
    "LPT1", "LPT2", "LPT3", "LPT4", "LPT5", "LPT6", "LPT7", "LPT8", "LPT9",
}

# Ký tự bất hợp pháp trên Windows file system: \ / : * ? " < > | và control chars (0x00-0x1F)
ILLEGAL_WINDOWS_CHARS = re.compile(r'[\x00-\x1f\\/:*?"<>|]')


def get_miniapp_display_name(app_id: str, fallback: str = "") -> str:
    """
    Trả về tên hiển thị tiếng Việt chuẩn hóa cho MiniApp Douyin.
    Nếu app_id nằm trong bảng ánh xạ cố định: trả về tên tiếng Việt.
    Nếu không: trả về fallback, hoặc tên builtin tiếng Trung nếu có, hoặc f'MiniApp_{app_id}'.
    """
    if not app_id:
        return fallback or "MiniApp Douyin"

    app_id_clean = str(app_id).strip()
    if app_id_clean in MINIAPP_DISPLAY_NAMES:
        return MINIAPP_DISPLAY_NAMES[app_id_clean]

    if fallback and fallback.strip():
        return fallback.strip()

    # Thử tìm trong BUILTIN_MINIAPP_SOURCES nếu có
    try:
        from providers.miniapp_douyin_client import BUILTIN_MINIAPP_SOURCES
        for src in BUILTIN_MINIAPP_SOURCES:
            if src.get("app_id") == app_id_clean:
                return src.get("name") or f"MiniApp_{app_id_clean}"
    except Exception:
        pass

    return f"MiniApp_{app_id_clean}"


def sanitize_windows_name(
    name: str,
    max_len: int = 120,
    fallback: str = "untitled",
    is_filename: bool = False,
) -> str:
    """
    Làm sạch chuỗi ký tự để an toàn 100% trên hệ điều hành Windows:
    1. Loại bỏ các ký tự cấm: \\ / : * ? " < > | và ký tự điều khiển (0x00-0x1F).
    2. Rút gọn khoảng trắng liên tiếp.
    3. Cắt bỏ dấu chấm và khoảng trắng ở đầu và cuối chuỗi (Windows cấm file/folder kết thúc bằng dấu chấm hoặc khoảng trắng).
    4. Kiểm tra các tên thiết bị cấm (CON, PRN, AUX, NUL, COM1-9, LPT1-9).
    5. Cắt ngắn an toàn để không vượt quá giới hạn độ dài ký tự Windows (tránh lỗi MAX_PATH).
    """
    if not name or not str(name).strip():
        return fallback

    raw = str(name).strip()

    # 1. Thay thế các ký tự cấm bằng khoảng trắng hoặc gạch dưới
    cleaned = ILLEGAL_WINDOWS_CHARS.sub(" ", raw)

    # 2. Chuẩn hóa khoảng trắng liên tiếp
    cleaned = re.sub(r"\s+", " ", cleaned).strip()

    # 3. Cắt bỏ dấu chấm và khoảng trắng ở đầu và cuối chuỗi
    cleaned = cleaned.strip(". ")

    if not cleaned:
        return fallback

    # 4. Kiểm tra tên thiết bị cấm trên Windows
    stem_check = cleaned.split(".")[0].upper() if is_filename else cleaned.upper()
    if stem_check in WINDOWS_RESERVED_NAMES:
        cleaned = f"_{cleaned}"

    # 5. Cắt ngắn độ dài tối đa an toàn
    if len(cleaned) > max_len:
        cleaned = cleaned[:max_len].strip(". ")

    return cleaned or fallback


def sanitize_windows_foldername(name: str, max_len: int = 100, fallback: str = "untitled_folder") -> str:
    """Làm sạch tên thư mục Windows."""
    return sanitize_windows_name(name, max_len=max_len, fallback=fallback, is_filename=False)


def sanitize_windows_filename(name: str, max_len: int = 120, fallback: str = "untitled") -> str:
    """Làm sạch tên tập tin Windows (không bao gồm phần mở rộng)."""
    return sanitize_windows_name(name, max_len=max_len, fallback=fallback, is_filename=True)


def build_drama_destination_dir(
    base_folder: str,
    platform_id: str,
    series_name: str,
    source_app_id: str = "",
    source_name: str = "",
) -> str:
    """
    Xây dựng đường dẫn thư mục lưu trữ phân cấp chuẩn cho bộ phim ngắn:
    - MiniApp Douyin:
      base_folder / 'MiniApp Douyin' / {Tên MiniApp Việt hóa} / {Tên bộ phim}
    - Các nền tảng Short Drama khác:
      base_folder / {Tên nền tảng} / {Tên bộ phim}

    Chống Path Traversal nghiêm ngặt: Tuyệt đối không cho phép '..' hoặc ký tự lạ thoát khỏi base_folder.
    Tự động tạo thư mục trên đĩa (os.makedirs).
    """
    # Phòng chống Path Traversal chủ động: Từ chối các tham số chứa '..' hoặc ký tự ổ đĩa tuyệt đối
    for param_val in (platform_id, series_name, source_app_id, source_name):
        if param_val and (".." in str(param_val) or (len(str(param_val)) > 1 and str(param_val)[1] == ":")):
            raise ValueError(f"Phát hiện nguy cơ Path Traversal trong tham số: {param_val}")

    base_abs = os.path.abspath(base_folder or os.path.join(os.getcwd(), "downloads"))

    platform_clean = str(platform_id or "").strip().lower()

    if platform_clean in ("miniapp_douyin", "douyin_miniapp"):
        source_display = get_miniapp_display_name(source_app_id, fallback=source_name or "Đa Lai")
        source_folder = sanitize_windows_foldername(source_display, max_len=80, fallback="Đa Lai")
        series_folder = sanitize_windows_foldername(
            series_name,
            max_len=100,
            fallback=f"Untitled_MiniApp_{source_app_id[:8] if source_app_id else 'series'}",
        )
        dest_dir = os.path.join(base_abs, "MiniApp Douyin", source_folder, series_folder)
    else:
        # Nền tảng DramaBox, KissKH, HongGuo, v.v.
        platform_display = {
            "dramabox": "DramaBox",
            "kisskh": "KissKH",
            "hongguo": "HongGuo",
            "goodshort": "GoodShort",
            "shortmax": "ShortMax",
            "netshort": "NetShort",
            "freereels": "FreeReels",
            "dramawave": "DramaWave",
            "raptdrama": "RaptDrama",
            "flextv": "FlexTV",
            "stardusttv": "StardustTV",
        }.get(platform_clean, sanitize_windows_foldername(platform_clean.capitalize() or "Drama"))

        series_folder = sanitize_windows_foldername(
            series_name,
            max_len=100,
            fallback="Untitled_Drama",
        )
        dest_dir = os.path.join(base_abs, platform_display, series_folder)

    # Chống Path Traversal: Kiểm tra đường dẫn đích có nằm trong base_abs không
    dest_abs = os.path.abspath(dest_dir)
    try:
        common = os.path.commonpath([base_abs, dest_abs])
        if common != base_abs:
            raise ValueError(f"Phát hiện nguy cơ Path Traversal: {dest_abs} nằm ngoài {base_abs}")
    except ValueError:
        # Trên Windows nếu khác drive letter (ví dụ C: vs D:) commonpath sẽ quăng ValueError
        raise ValueError(f"Đường dẫn thư mục không hợp lệ: {dest_abs}")

    # Tạo thư mục nếu chưa tồn tại
    os.makedirs(dest_abs, exist_ok=True)
    return dest_abs


def build_drama_filename(episode_number: int, episode_title: str = "", ext: str = "mp4") -> str:
    """
    Tạo tên file tập phim theo quy tắc chuẩn:
    - Nếu có tiêu đề tập riêng biệt: '{episode_number:02d} - {episode_title}.{ext}'
    - Nếu không có tiêu đề hoặc tiêu đề trùng số tập: '{episode_number:02d} - Tập {episode_number}.{ext}'
    """
    clean_ext = ext.lstrip(".").lower() or "mp4"
    clean_title = sanitize_windows_filename(episode_title, max_len=100, fallback="")

    # Kiểm tra xem clean_title có phải chỉ là số tập hoặc rỗng không
    if not clean_title or clean_title.lower() in (f"tap {episode_number}", f"tập {episode_number}", f"{episode_number}", f"ep {episode_number}", f"episode {episode_number}"):
        stem = f"{episode_number:02d} - Tập {episode_number}"
    else:
        # Nếu clean_title đã bắt đầu bằng số thứ tự (ví dụ: '01 - ...' hoặc '1 - ...')
        if re.match(rf"^{episode_number:02d}\s*[-_.]\s*", clean_title):
            stem = clean_title
        elif re.match(rf"^{episode_number}\s*[-_.]\s*", clean_title):
            # Thay '1 - ' thành '01 - '
            sub_title = re.sub(rf"^{episode_number}\s*[-_.]\s*", "", clean_title)
            stem = f"{episode_number:02d} - {sub_title}" if sub_title else f"{episode_number:02d} - Tập {episode_number}"
        else:
            stem = f"{episode_number:02d} - {clean_title}"

    return f"{stem}.{clean_ext}"


def resolve_unique_drama_filepath(
    output_dir: str,
    base_stem: str,
    ext: str = "mp4",
    allow_duplicates: bool = True,
) -> Tuple[str, str]:
    """
    Xác định stem và đường dẫn file tuyệt đối duy nhất trong thư mục lưu.
    Kiểm tra cả file hoàn chỉnh và các file tạm dở dang:
    - {stem}.{ext}
    - {stem}.{ext}.part
    - {stem}.{ext}.ytdl
    - {stem}.part-Frag*
    - {stem}.segs
    - {stem}.ts.part

    Nếu trùng và allow_duplicates=True:
    Tự động đánh dấu tiền tố: Dup1_{base_stem}, Dup2_{base_stem}, ...
    Trả về: (final_stem, final_filepath)
    """
    clean_ext = ext.lstrip(".").lower() or "mp4"
    clean_stem = sanitize_windows_filename(base_stem, max_len=120, fallback="episode")

    def _has_conflict(stem: str) -> bool:
        if not os.path.exists(output_dir):
            return False

        # Kiểm tra file hoàn chỉnh
        exact_file = os.path.join(output_dir, f"{stem}.{clean_ext}")
        if os.path.exists(exact_file):
            return True

        # Kiểm tra các định dạng container phổ biến khác nếu đã tồn tại cùng tên
        for other_ext in ("mp4", "mkv", "webm", "ts"):
            if os.path.exists(os.path.join(output_dir, f"{stem}.{other_ext}")):
                return True

        # Kiểm tra file tạm dở dang của yt-dlp và HLS
        temp_candidates = [
            os.path.join(output_dir, f"{stem}.{clean_ext}.part"),
            os.path.join(output_dir, f"{stem}.{clean_ext}.ytdl"),
            os.path.join(output_dir, f"{stem}.ts.part"),
            os.path.join(output_dir, f"{stem}.segs"),
        ]
        for p in temp_candidates:
            if os.path.exists(p):
                return True

        # Kiểm tra fragment patterns (ví dụ: stem.mp4.part-Frag0)
        try:
            for fname in os.listdir(output_dir):
                if fname.startswith(f"{stem}.") and any(part_suffix in fname for part_suffix in (".part", ".ytdl", "Frag")):
                    return True
        except Exception:
            pass

        return False

    if not _has_conflict(clean_stem) or not allow_duplicates:
        final_stem = clean_stem
        return final_stem, os.path.join(output_dir, f"{final_stem}.{clean_ext}")

    # Nếu có file trùng và cho phép tạo bản sao (allow_duplicates)
    dup_index = 1
    while True:
        dup_stem = f"Dup{dup_index}_{clean_stem}"
        if not _has_conflict(dup_stem):
            return dup_stem, os.path.join(output_dir, f"{dup_stem}.{clean_ext}")
        dup_index += 1
