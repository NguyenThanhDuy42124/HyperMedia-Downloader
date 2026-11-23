r"""
ca_bundle_utils.py
~~~~~~~~~~~~~~~~~~
Quản lý an toàn chứng chỉ TLS CA bundle cho môi trường chạy thông thường
lẫn môi trường đóng gói PyInstaller (Frozen Standalone Executable).

Tránh hoàn toàn lỗi:
"Could not find a suitable TLS CA certificate bundle invalid path: ...\_MEIxxxxx\certifi\cacert.pem"

Quy tắc:
1. Không truyền đường dẫn không tồn tại vào requests.
2. Nếu không tìm thấy file CA trên đĩa, trả về True để requests/urllib3 dùng trust store hệ thống.
3. Tuyệt đối không dùng verify=False trong production.
4. Lọc bỏ toàn bộ đường dẫn nội bộ _MEIPASS khỏi log và thông báo giao diện.
"""

import os
import re
import sys
from typing import Union


def get_ca_bundle_path() -> Union[str, bool]:
    """
    Trả về đường dẫn tệp CA bundle hợp lệ nếu tồn tại,
    hoặc True nếu cần để requests/urllib3 dùng trust store mặc định.
    Tuyệt đối không bao giờ trả về chuỗi đường dẫn không tồn tại trên ổ đĩa.
    """
    candidates = []

    # 1. Kiểm tra bên trong thư mục giải nén tạm _MEIPASS của PyInstaller
    if hasattr(sys, "_MEIPASS"):
        candidates.append(os.path.join(sys._MEIPASS, "certifi", "cacert.pem"))
        candidates.append(os.path.join(sys._MEIPASS, "cacert.pem"))

    # 2. Kiểm tra bên cạnh tệp thực thi (executable dir)
    exe_dir = os.path.dirname(sys.executable) if sys.executable else ""
    if exe_dir:
        candidates.append(os.path.join(exe_dir, "certifi", "cacert.pem"))
        candidates.append(os.path.join(exe_dir, "cacert.pem"))

    # 3. Kiểm tra từ thư viện certifi tiêu chuẩn của Python
    try:
        import certifi
        cand = certifi.where()
        if cand:
            candidates.append(cand)
    except Exception:
        pass

    # 4. Kiểm tra các biến môi trường hiện có nếu chúng trỏ đến file thật
    for env_k in ("REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE", "SSL_CERT_FILE"):
        val = os.environ.get(env_k)
        if val and isinstance(val, str) and os.path.isfile(val):
            candidates.append(val)

    # Lọc và trả về ứng viên đầu tiên thực sự tồn tại trên ổ đĩa
    for path in candidates:
        if path and isinstance(path, str) and os.path.isfile(path):
            return path

    # Fallback an toàn: Cho phép thư viện mạng dùng certificate store mặc định của hệ thống
    return True


def setup_ca_bundle_env():
    """
    Khởi tạo và làm sạch môi trường TLS CA bundle khi ứng dụng khởi động.
    Nếu get_ca_bundle_path() trả về đường dẫn tệp hợp lệ, gán vào REQUESTS_CA_BUNDLE.
    Nếu trả về True (fallback), tuyệt đối không ghi chuỗi 'True' mà loại bỏ biến môi trường
    để requests và urllib3 tự động sử dụng system trust store của hệ điều hành.
    """
    ca_path = get_ca_bundle_path()
    if isinstance(ca_path, str) and os.path.isfile(ca_path):
        os.environ["REQUESTS_CA_BUNDLE"] = ca_path
        os.environ["CURL_CA_BUNDLE"] = ca_path
        os.environ["SSL_CERT_FILE"] = ca_path
    else:
        os.environ.pop("REQUESTS_CA_BUNDLE", None)
        os.environ.pop("CURL_CA_BUNDLE", None)
        os.environ.pop("SSL_CERT_FILE", None)


def sanitize_error_message(err: Union[str, Exception]) -> str:
    """
    Chuyển đổi lỗi kỹ thuật thành thông báo thân thiện với người dùng thương mại:
    - Lọc bỏ triệt để đường dẫn _MEIPASS và đường dẫn nhạy cảm.
    - Chuẩn hóa lỗi chứng chỉ TLS/SSL thành hướng dẫn thân thiện.
    - Mask cookie, token, sessionid.
    """
    raw = str(err) if err else "Đã xảy ra lỗi không xác định."

    # Kiểm tra lỗi liên quan đến chứng chỉ TLS/SSL
    lower_raw = raw.lower()
    if any(k in lower_raw for k in ("certificate verify failed", "tls ca certificate", "cacert.pem", "sslerror", "certificate_verify_failed")):
        return "Không thể xác minh chứng chỉ máy chủ. Hãy kiểm tra ngày giờ hệ thống hoặc cập nhật bản ứng dụng."

    if any(k in lower_raw for k in ("connection refused", "failed to establish a new connection", "nameresolutionerror", "getaddrinfo failed")):
        return "Không thể kết nối đến máy chủ. Hãy kiểm tra lại kết nối mạng Internet."

    if "timed out" in lower_raw or "timeout" in lower_raw:
        return "Yêu cầu kết nối quá thời gian chờ (Timeout). Vui lòng thử lại sau."

    return sanitize_log_text(raw)


def sanitize_log_text(text: str) -> str:
    """
    Làm sạch nhật ký:
    - Ẩn đường dẫn _MEIxxxxx nội bộ thành [APP_DIR].
    - Mask cookies, sessionid, tokens, passport_csrf_token, Bearer auth.
    """
    if not text:
        return ""

    s = str(text)

    # 1. Ẩn đường dẫn _MEIPASS
    s = re.sub(r"[A-Za-z]:\\[^\s\)\'\"]*\\_MEI\d+[^\s\)\'\"]*", "[APP_DIR]", s)
    s = re.sub(r"\/[^\s\)\'\"]*\/_MEI\d+[^\s\)\'\"]*", "[APP_DIR]", s)
    if hasattr(sys, "_MEIPASS") and sys._MEIPASS:
        s = s.replace(sys._MEIPASS, "[APP_DIR]")

    # 2. Mask sensitive tokens và cookies
    s = re.sub(r"(sessionid=)[^\s;&\'\"]+", r"\1***", s, flags=re.IGNORECASE)
    s = re.sub(r"(uid_tt=)[^\s;&\'\"]+", r"\1***", s, flags=re.IGNORECASE)
    s = re.sub(r"(passport_csrf_token=)[^\s;&\'\"]+", r"\1***", s, flags=re.IGNORECASE)
    s = re.sub(r"(token=)[^\s;&\'\"]+", r"\1***", s, flags=re.IGNORECASE)
    s = re.sub(r"(Bearer\s+)[A-Za-z0-9_\-\.]+", r"\1***", s, flags=re.IGNORECASE)
    s = re.sub(r"(cookie:\s*)[^\r\n]+", r"\1***", s, flags=re.IGNORECASE)
    s = re.sub(r"(authorization:\s*)[^\r\n]+", r"\1***", s, flags=re.IGNORECASE)

    return s
