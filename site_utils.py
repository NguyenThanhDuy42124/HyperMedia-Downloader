"""Phân loại URL theo site để thiết lập http_headers phù hợp."""
import re

_BILI_LISTS_QS = re.compile(
    r"(https?://space\.bilibili\.com/\d+)/lists\?sid=(\d+)"
)
_BILI_COLLDETAIL = re.compile(
    r"(https?://space\.bilibili\.com/\d+)/channel/collectiondetail/?\?sid=(\d+)"
)


def detect_site(url):
    """Trả về dict http_headers phù hợp cho site đích."""
    u = (url or "").lower()
    if "bilibili.com" in u or "b23.tv" in u:
        return {
            "Referer": "https://www.bilibili.com/",
            "Origin": "https://www.bilibili.com",
            "Accept": "*/*",
            "Accept-Language": "zh-CN,zh;q=0.9,en-US;q=0.8,en;q=0.7",
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "cross-site",
        }
    if "douyin.com" in u:
        return {
            "Referer": "https://www.douyin.com/",
            "Origin": "https://www.douyin.com",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "cross-site",
        }
    if "youtube.com" in u or "youtu.be" in u:
        return {
            "Referer": "https://www.youtube.com/",
            "Origin": "https://www.youtube.com",
        }
    return {}


def is_bilibili_url(url):
    u = (url or "").lower()
    return "bilibili.com" in u or "b23.tv" in u


def normalize_url(url):
    """Chuẩn hóa URL bilibili và douyin về dạng yt-dlp hỗ trợ chuẩn nhất."""
    if not url:
        return url
    u = url.strip()
    # Douyin short link / iesdouyin -> www.douyin.com/video/<id>
    if "v.douyin.com" in u:
        try:
            import requests
            r = requests.head(u, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}, allow_redirects=True, timeout=4)
            u = r.url
        except Exception:
            pass
    # Nếu là link user có chứa vid= (ví dụ mở video ngay trong profile)
    m_vid = re.search(r'[?&]vid=(\d+)', u)
    if m_vid and "douyin.com" in u:
        return f"https://www.douyin.com/video/{m_vid.group(1)}"

    m_dy = re.search(r'/(?:video|share/video)/(\d+)', u)
    if m_dy and ("douyin.com" in u or "iesdouyin.com" in u):
        return f"https://www.douyin.com/video/{m_dy.group(1)}"

    m = _BILI_LISTS_QS.search(u) or _BILI_COLLDETAIL.search(u)
    if m:
        return f"{m.group(1)}/lists/{m.group(2)}"
    return u
