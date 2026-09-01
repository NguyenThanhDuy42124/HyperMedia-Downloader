"""Module tự động Refresh & Duy trì Cookies Bilibili sống 24/7.

Bilibili thường bóp hoặc ngắt kết nối sau 500MB do token `bili_ticket` hết hạn.
Module này tự động:
1. Gọi API Bilibili cấp mới `bili_ticket` từ `SESSDATA`.
2. Đồng bộ Cookies từ trình duyệt (Chrome/Edge/Firefox) khi cần.
"""
import os
import sys
import time
import json
import urllib.request
import urllib.parse

COOKIE_FILE = os.path.join(os.path.dirname(__file__), "cookies", "cookies.txt")

def parse_cookies_txt(filepath):
    cookies = {}
    if not os.path.exists(filepath):
        return cookies
    with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
        for line in f:
            if line.startswith('#') or not line.strip():
                continue
            parts = line.strip().split('\t')
            if len(parts) >= 7:
                name = parts[5]
                value = parts[6]
                cookies[name] = value
    return cookies

def refresh_bilibili_ticket():
    """Tự động gọi API cấp mới bili_ticket từ SESSDATA để duy trì cookies sống liên tục."""
    cookies = parse_cookies_txt(COOKIE_FILE)
    sessdata = cookies.get("SESSDATA")
    bili_jct = cookies.get("bili_jct")

    if not sessdata:
        print("[COOKIE AUTO-REFRESH] Không tìm thấy SESSDATA trong cookies.txt")
        return False

    url = "https://api.bilibili.com/x/passport/web/add/v2"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
        "Referer": "https://www.bilibili.com/",
        "Cookie": f"SESSDATA={sessdata}; bili_jct={bili_jct};"
    }

    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            if data.get("code") == 0:
                print("[COOKIE AUTO-REFRESH] Cấp mới bili_ticket Bilibili thành công!")
                return True
    except Exception as e:
        print(f"[COOKIE AUTO-REFRESH] Lỗi kết nối làm mới bili_ticket: {e}")
    return False

def get_live_browser_cookies(browser_name="chrome"):
    """Lấy cookies trực tiếp từ trình duyệt đang mở trên máy (Chrome/Edge)."""
    try:
        import yt_dlp.cookies
        cookie_jar = yt_dlp.cookies.extract_cookies_from_browser(browser_name.lower())
        if cookie_jar:
            # Ghi trực tiếp ra file cookies.txt
            with open(COOKIE_FILE, 'w', encoding='utf-8') as f:
                f.write("# Netscape HTTP Cookie File\n")
                for cookie in cookie_jar:
                    if "bilibili.com" in cookie.domain:
                        domain = cookie.domain
                        flag = "TRUE" if domain.startswith(".") else "FALSE"
                        path = cookie.path
                        secure = "TRUE" if cookie.secure else "FALSE"
                        expiry = str(cookie.expires or 0)
                        name = cookie.name
                        value = cookie.value
                        f.write(f"{domain}\t{flag}\t{path}\t{secure}\t{expiry}\t{name}\t{value}\n")
            print(f"[COOKIE AUTO-REFRESH] Đã trích xuất Cookies Bilibili sống từ trình duyệt {browser_name} thành công!")
            return True
    except Exception as e:
        print(f"[COOKIE AUTO-REFRESH] Không đọc được cookies từ {browser_name}: {e}")
    return False
