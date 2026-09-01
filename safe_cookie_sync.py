"""Safe Cookie Extractor cho Chrome / Edge trên Windows.
Tự động copy file SQLite bị khóa ra %TEMP% và giải mã DPAPI để xuất cookies.txt sạch 100%.
"""
import os
import sys
import shutil
import sqlite3
import tempfile
import json
import base64
import ctypes
from ctypes import wintypes

class DATA_BLOB(ctypes.Structure):
    _fields_ = [
        ("cbData", wintypes.DWORD),
        ("pbData", ctypes.POINTER(ctypes.c_byte))
    ]

def dpapi_decrypt(encrypted_bytes):
    """Giải mã DPAPI trên Windows bằng ctypes (Không cần pywin32)."""
    try:
        data_in = DATA_BLOB(len(encrypted_bytes), (ctypes.c_byte * len(encrypted_bytes))(*encrypted_bytes))
        data_out = DATA_BLOB()
        if ctypes.windll.crypt32.CryptUnprotectData(ctypes.byref(data_in), None, None, None, None, 0, ctypes.byref(data_out)):
            length = data_out.cbData
            buffer = (ctypes.c_byte * length)()
            ctypes.memmove(buffer, data_out.pbData, length)
            ctypes.windll.kernel32.LocalFree(data_out.pbData)
            return bytes(buffer)
    except Exception as e:
        print(f"[SafeCookie] Lỗi giải mã DPAPI: {e}")
    return None

def extract_browser_cookies(browser_name="chrome"):
    """Trích xuất cookies sạch từ Chrome/Edge sang cookies/cookies.txt."""
    user_data = os.path.expanduser("~")
    paths = {
        "chrome": os.path.join(user_data, "AppData", "Local", "Google", "Chrome", "User Data"),
        "edge": os.path.join(user_data, "AppData", "Local", "Microsoft", "Edge", "User Data"),
    }

    base_path = paths.get(browser_name.lower())
    if not base_path or not os.path.exists(base_path):
        return False, f"Không tìm thấy thư mục của trình duyệt {browser_name}"

    cookie_db = os.path.join(base_path, "Default", "Network", "Cookies")
    local_state_path = os.path.join(base_path, "Local State")

    if not os.path.exists(cookie_db):
        # Thử profile 1 hoặc Default
        cookie_db = os.path.join(base_path, "Profile 1", "Network", "Cookies")

    if not os.path.exists(cookie_db):
        return False, "Không tìm thấy file Cookies trong trình duyệt"

    # 1. Copy file sang TEMP để tránh lỗi WinError 32 (file being used by Chrome)
    temp_dir = tempfile.gettempdir()
    temp_db = os.path.join(temp_dir, f"temp_{browser_name}_cookies.db")
    try:
        shutil.copyfile(cookie_db, temp_db)
    except Exception as e:
        return False, f"Không thể copy file Cookies: {e}"

    # 2. Lấy Master Key giải mã AES-GCM (nếu có Local State)
    aes_key = None
    if os.path.exists(local_state_path):
        try:
            with open(local_state_path, "r", encoding="utf-8") as f:
                local_state = json.load(f)
            encrypted_key = base64.b64decode(local_state["os_crypt"]["encrypted_key"])
            encrypted_key = encrypted_key[5:] # Remove 'DPAPI' prefix
            aes_key = dpapi_decrypt(encrypted_key)
        except Exception as e:
            print(f"[SafeCookie] Không đọc được AES key: {e}")

    # 3. Đọc dữ liệu từ SQLite
    out_cookie_file = os.path.join(os.path.dirname(__file__), "cookies", "cookies.txt")
    bilibili_cookies = []

    try:
        conn = sqlite3.connect(temp_db)
        cursor = conn.cursor()
        cursor.execute("SELECT host_key, name, path, is_secure, expires_utc, encrypted_value, value FROM cookies WHERE host_key LIKE '%bilibili.com%'")
        rows = cursor.fetchall()
        
        for host, name, path, is_secure, expires, enc_val, val in rows:
            real_val = val
            if not real_val and enc_val:
                # Thử giải mã bằng DPAPI trực tiếp
                dec = dpapi_decrypt(enc_val)
                if dec:
                    real_val = dec.decode('utf-8', errors='ignore')
            
            if real_val:
                bilibili_cookies.append((host, is_secure, path, expires, name, real_val))

        conn.close()
        try:
            os.remove(temp_db)
        except Exception:
            pass

        if not bilibili_cookies:
            return False, "Không tìm thấy Cookies Bilibili nào trong trình duyệt"

        # Ghi ra file cookies/cookies.txt dạng Netscape
        os.makedirs(os.path.dirname(out_cookie_file), exist_ok=True)
        with open(out_cookie_file, "w", encoding="utf-8") as f:
            f.write("# Netscape HTTP Cookie File\n")
            for host, is_sec, path, exp, name, val in bilibili_cookies:
                flag = "TRUE" if host.startswith(".") else "FALSE"
                sec_str = "TRUE" if is_sec else "FALSE"
                f.write(f"{host}\t{flag}\t{path}\t{sec_str}\t{exp}\t{name}\t{val}\n")

        print(f"[SafeCookie] Đã tự động giải mã & trích xuất {len(bilibili_cookies)} cookies Bilibili sang cookies.txt!")
        return True, f"Đã trích xuất {len(bilibili_cookies)} cookies Bilibili thành công!"
    except Exception as e:
        return False, f"Lỗi đọc SQLite: {e}"
