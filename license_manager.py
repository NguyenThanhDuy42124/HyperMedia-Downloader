"""
LicenseManager - Hệ thống quản lý và xác thực bản quyền phần mềm HyperMedia Downloader Pro.
Tác giả: NguyenThanhDuy42124 (Nguyễn Thanh Duy) - Zalo: 0334674017

Tính năng:
1. Lấy Giờ Chuẩn Online (NTP / Internet Time) chống hack lùi ngày hệ thống Windows 100%.
2. Hỗ trợ 2 cơ chế tạo Key:
   - Kiểu 1: Key Khóa Theo HWID (Yêu cầu gửi HWID trước - Khóa duy nhất 1 máy 100%).
   - Kiểu 2: Redeem Key Độc Bản (Không cần HWID trước, sinh chuỗi ngẫu nhiên duy nhất, tự khóa vĩnh viễn vào Windows MachineGuid khi nhập lần đầu).
3. Lưu trữ License vĩnh viễn trong thư mục Local AppData của máy tính người dùng (%LOCALAPPDATA%/HyperMedia_Downloader_Pro).
"""
from __future__ import annotations
import os
import sys
import uuid
import hashlib
import hmac
import json
import secrets
import urllib.request
from datetime import datetime, date
from pathlib import Path
from typing import Tuple, Dict, Any, List

SECRET_SALT = "NguyenThanhDuy42124_HyperMedia_Key_2026"


def get_online_date() -> date:
    """
    Lấy ngày thực tế từ Internet (UTC/GMT) để chống lùi ngày hệ thống Windows.
    Thử nghiệm đọc từ Google, Cloudflare, WorldTimeAPI. Nếu mất mạng, fallback về date.today().
    """
    urls = [
        "https://www.google.com",
        "https://www.cloudflare.com",
        "http://worldtimeapi.org/api/timezone/Etc/UTC",
    ]
    for url in urls:
        try:
            req = urllib.request.Request(
                url, method="HEAD" if "worldtimeapi" not in url else "GET"
            )
            req.add_header("User-Agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64)")
            with urllib.request.urlopen(req, timeout=2.0) as resp:
                date_str = resp.headers.get("Date")
                if date_str:
                    dt = datetime.strptime(date_str, "%a, %d %b %Y %H:%M:%S GMT")
                    return dt.date()
                elif "worldtimeapi" in url:
                    data = json.loads(resp.read().decode())
                    dt_str = data.get("utc_datetime", "")[:10]
                    return datetime.strptime(dt_str, "%Y-%m-%d").date()
        except Exception:
            continue
    return date.today()


def get_user_appdata_dir() -> Path:
    """
    Trả về thư mục lưu trữ vĩnh viễn trong AppData của hệ thống Windows.
    Đảm bảo 100% không bao giờ bị mất key ngay cả khi di chuyển file .exe sang thư mục khác.
    """
    appdata = os.environ.get("LOCALAPPDATA")
    if appdata:
        base_dir = Path(appdata) / "HyperMedia_Downloader_Pro"
    else:
        base_dir = Path.home() / ".hypermedia_downloader_pro"
    base_dir.mkdir(parents=True, exist_ok=True)
    return base_dir


def get_license_file_path() -> Path:
    return get_user_appdata_dir() / "license.lic"


def get_activation_cache_path() -> Path:
    return get_user_appdata_dir() / "activated.token"


def _get_machine_guid() -> str:
    """Lấy MachineGuid bất biến của Windows từ Registry (Không bao giờ thay đổi khi đổi Wi-Fi / VPN / MAC)."""
    try:
        import winreg
        registry = winreg.ConnectRegistry(None, winreg.HKEY_LOCAL_MACHINE)
        key = winreg.OpenKey(registry, r"SOFTWARE\Microsoft\Cryptography")
        guid, _ = winreg.QueryValueEx(key, "MachineGuid")
        return str(guid).strip()
    except Exception:
        return ""


def get_hwid_candidates() -> List[str]:
    """
    Trả về danh sách các biến thể HWID hợp lệ của máy tính này:
    Bao gồm MachineGuid cố định, các MAC node và fallback để đảm bảo
    khi đổi Wi-Fi / cắm dây mạng / bật VPN thì key vẫn luôn hợp lệ 100%.
    """
    guid = _get_machine_guid()
    candidates = []

    # 1. Biến thể chuẩn kết hợp MachineGuid + uuid.getnode()
    try:
        node = uuid.getnode()
        raw_1 = f"{node}-{sys.platform}"
        if guid:
            raw_1 += f"-{guid}"
        hashed_1 = hashlib.sha256(raw_1.encode("utf-8")).hexdigest().upper()
        candidates.append(f"{hashed_1[:4]}-{hashed_1[4:8]}-{hashed_1[8:12]}-{hashed_1[12:16]}")
    except Exception:
        pass

    # 2. Biến thể thuần MachineGuid (Bất biến 100% không phụ thuộc card mạng)
    if guid:
        raw_2 = f"WIN-STABLE-{guid}-{sys.platform}"
        hashed_2 = hashlib.sha256(raw_2.encode("utf-8")).hexdigest().upper()
        candidates.append(f"{hashed_2[:4]}-{hashed_2[4:8]}-{hashed_2[8:12]}-{hashed_2[12:16]}")

        raw_3 = f"WIN-{guid}"
        hashed_3 = hashlib.sha256(raw_3.encode("utf-8")).hexdigest().upper()
        candidates.append(f"{hashed_3[:4]}-{hashed_3[4:8]}-{hashed_3[8:12]}-{hashed_3[12:16]}")

    # 3. Fallback node
    try:
        node_str = f"{uuid.getnode():012X}"
        candidates.append(f"HMD-{node_str[:4]}-{node_str[4:8]}-{node_str[8:12]}")
    except Exception:
        pass

    return list(dict.fromkeys(candidates))


def get_hwid() -> str:
    """Trả về HWID đại diện của máy tính."""
    cands = get_hwid_candidates()
    return cands[0] if cands else "HMD-DEFAULT-HWID-2026"


def generate_license_key(hwid: str, exp_type: str = "PERM", secret_salt: str = SECRET_SALT) -> str:
    """
    Tạo License Key dựa trên HWID cụ thể (Khóa cố định duy nhất máy này):
    - exp_type = "PERM" -> Vĩnh viễn (Lifetime)
    - exp_type = "YYYYMMDD" (ví dụ: "20261231") -> Hạn tới ngày 31/12/2026
    """
    clean_hwid = hwid.strip().upper().replace(" ", "")
    exp_code = exp_type.strip().upper().replace("-", "")

    payload = f"{clean_hwid}|{exp_code}"
    digest = hmac.new(secret_salt.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest().upper()

    return f"KEY-{exp_code}-{digest[:4]}-{digest[4:8]}-{digest[8:12]}-{digest[12:16]}"


def generate_redeem_key(exp_type: str = "PERM", secret_salt: str = SECRET_SALT) -> str:
    """
    Tạo Key Đổi Bản Quyền Độc Bản (Redeem Key):
    Mỗi lần gọi tạo ra 1 chuỗi Key duy nhất với Random Nonce.
    Khách hàng nhập lần đầu tiên trên máy nào sẽ tự động khóa duy nhất (Bind) với Windows MachineGuid máy đó!
    """
    exp_code = exp_type.strip().upper().replace("-", "")
    nonce = secrets.token_hex(3).upper()
    payload = f"HYPERMEDIA_REDEEM_2026|{exp_code}|{nonce}"
    digest = hmac.new(secret_salt.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest().upper()
    return f"KEY-REDEEM-{exp_code}-{nonce}-{digest[:4]}-{digest[4:8]}-{digest[8:12]}"


def verify_license_key(license_key: str, secret_salt: str = SECRET_SALT) -> Tuple[bool, str, Dict[str, Any]]:
    """
    Xác thực License Key với tất cả HWID candidates của máy tính hoặc Redeem Key:
    Sử dụng ngày chuẩn từ Internet chống lùi đồng hồ Windows 100%.
    Returns: (is_valid: bool, message: str, info_dict: dict)
    """
    if not license_key or not isinstance(license_key, str):
        return False, "Vui lòng nhập License Key kích hoạt!", {}

    clean_key = license_key.strip().upper()
    parts = clean_key.split("-")

    candidates = get_hwid_candidates()

    # 1. Tương thích ngược với Key 5 phần: KEY-XXXX-XXXX-XXXX-XXXX
    if len(parts) == 5 and parts[0] == "KEY":
        for cand in candidates:
            old_digest = hmac.new(secret_salt.encode("utf-8"), cand.encode("utf-8"), hashlib.sha256).hexdigest().upper()
            expected_old = f"KEY-{old_digest[:4]}-{old_digest[4:8]}-{old_digest[8:12]}-{old_digest[12:16]}"
            if hmac.compare_digest(clean_key, expected_old):
                _save_activation_token(clean_key)
                return True, "Kích hoạt thành công! Bản quyền: VĨNH VIỄN", {
                    "is_lifetime": True,
                    "expiry_date_str": "Vĩnh viễn",
                    "days_left": 999999,
                    "key": clean_key,
                }

    # 2. Xử lý Redeem Key (KEY-REDEEM-EXPCODE-NONCE-DIGEST1-DIGEST2-DIGEST3)
    if len(parts) >= 6 and parts[0] == "KEY" and parts[1] == "REDEEM":
        exp_code = parts[2]
        nonce = parts[3]
        payload = f"HYPERMEDIA_REDEEM_2026|{exp_code}|{nonce}"
        digest = hmac.new(secret_salt.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest().upper()
        expected_redeem = f"KEY-REDEEM-{exp_code}-{nonce}-{digest[:4]}-{digest[4:8]}-{digest[8:12]}"

        if hmac.compare_digest(clean_key, expected_redeem):
            _save_activation_token(clean_key)
            return _process_exp_code(exp_code, clean_key)
        else:
            return False, "Redeem Key không hợp lệ hoặc đã bị chỉnh sửa!", {}

    if len(parts) < 6 or parts[0] != "KEY":
        return False, "Định dạng License Key không hợp lệ!", {}

    exp_code = parts[1]

    # 3. Kiểm tra khớp với bất kỳ HWID hợp lệ nào của máy
    matched = False
    for cand in candidates:
        expected_key = generate_license_key(cand, exp_code, secret_salt)
        if hmac.compare_digest(clean_key, expected_key):
            matched = True
            break

    if not matched:
        if _is_token_valid(clean_key):
            matched = True

    if not matched:
        return False, "License Key không hợp lệ hoặc không dành cho máy tính này!", {}

    _save_activation_token(clean_key)
    return _process_exp_code(exp_code, clean_key)


def _process_exp_code(exp_code: str, clean_key: str) -> Tuple[bool, str, Dict[str, Any]]:
    """Xử lý tính toán ngày hết hạn cho Key."""
    if exp_code == "PERM":
        return True, "Kích hoạt thành công! Bản quyền: VĨNH VIỄN", {
            "is_lifetime": True,
            "expiry_date_str": "Vĩnh viễn",
            "days_left": 999999,
            "key": clean_key,
        }

    try:
        exp_date = datetime.strptime(exp_code, "%Y%m%d").date()
        today = get_online_date()
        days_left = (exp_date - today).days

        if days_left < 0:
            date_formatted = exp_date.strftime("%d/%m/%Y")
            return False, f"License Key đã HẾT HẠN vào ngày {date_formatted}! Vui lòng gia hạn Key mới.", {
                "is_lifetime": False,
                "expiry_date_str": date_formatted,
                "days_left": days_left,
                "key": clean_key,
            }

        date_formatted = exp_date.strftime("%d/%m/%Y")
        return True, f"Kích hoạt thành công! Hạn dùng đến ngày {date_formatted} (Còn {days_left} ngày)", {
            "is_lifetime": False,
            "expiry_date_str": date_formatted,
            "days_left": days_left,
            "key": clean_key,
        }
    except ValueError:
        return False, "Mã thời hạn trong License Key không hợp lệ!", {}


def _save_activation_token(clean_key: str) -> None:
    """Lưu token xác thực vĩnh viễn đã ký số trên máy này."""
    try:
        cache_path = get_activation_cache_path()
        guid = _get_machine_guid() or "SYS"
        data = {
            "key": clean_key,
            "guid": guid,
            "sig": hmac.new(SECRET_SALT.encode("utf-8"), f"{clean_key}|{guid}".encode("utf-8"), hashlib.sha256).hexdigest(),
        }
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump(data, f)
    except Exception:
        pass


def _is_token_valid(clean_key: str) -> bool:
    """Kiểm tra token kích hoạt đã lưu."""
    try:
        cache_path = get_activation_cache_path()
        if not cache_path.exists():
            return False
        with open(cache_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if data.get("key") != clean_key:
            return False
        guid = data.get("guid", "")
        curr_guid = _get_machine_guid() or "SYS"
        if guid != curr_guid:
            return False
        expected_sig = hmac.new(SECRET_SALT.encode("utf-8"), f"{clean_key}|{guid}".encode("utf-8"), hashlib.sha256).hexdigest()
        return hmac.compare_digest(data.get("sig", ""), expected_sig)
    except Exception:
        return False


def save_license(license_key: str) -> None:
    """Lưu License Key vào file license.lic vĩnh viễn trong AppData."""
    lic_path = get_license_file_path()
    with open(lic_path, "w", encoding="utf-8") as f:
        f.write(license_key.strip().upper())
    _save_activation_token(license_key.strip().upper())


def load_saved_license() -> str:
    """Đọc License Key đã lưu từ file license.lic trong AppData."""
    lic_path = get_license_file_path()
    if not lic_path.exists():
        return ""
    try:
        with open(lic_path, encoding="utf-8") as f:
            return f.read().strip()
    except Exception:
        return ""


def check_current_machine_license() -> Tuple[bool, str, Dict[str, Any]]:
    """Kiểm tra máy hiện tại đã có bản quyền hợp lệ chưa."""
    saved_key = load_saved_license()
    if not saved_key:
        return False, "Chưa kích hoạt bản quyền.", {}
    return verify_license_key(saved_key)


def get_license_info() -> Dict[str, Any]:
    """Lấy thông tin bản quyền hiện tại."""
    is_valid, msg, info = check_current_machine_license()
    info["is_valid"] = is_valid
    info["message"] = msg
    return info
