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
    if any(d in u for d in ("douyin.com", "douyinvod.com", "zjcdn.com", "douyinpic.com", "byteimg.com", "p3-dy", "p9-dy")):
        return {
            "Referer": "https://www.douyin.com/",
            "Origin": "https://www.douyin.com",
            "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Sec-Fetch-Dest": "image",
            "Sec-Fetch-Mode": "no-cors",
            "Sec-Fetch-Site": "cross-site",
        }
    if "youtube.com" in u or "youtu.be" in u:
        return {}
    return {}


def is_bilibili_url(url):
    u = (url or "").lower()
    return "bilibili.com" in u or "b23.tv" in u


def is_youtube_url(url):
    u = (url or "").lower()
    return "youtube.com" in u or "youtu.be" in u


def normalize_url(url):
    """Chuẩn hóa URL bilibili và douyin về dạng yt-dlp hỗ trợ chuẩn nhất."""
    if not url:
        return url
    raw = str(url).strip()
    
    # 1. Trích xuất URL nếu người dùng dán cả đoạn văn bản chia sẻ (ví dụ: '2.89 q@R.kC ... https://v.douyin.com/... ')
    m_url = re.search(r"https?://[^\s<>\"']+", raw)
    u = m_url.group(0) if m_url else raw

    # 2. Xử lý link rút gọn v.douyin.com / iesdouyin -> lấy URL chuyển hướng thực tế
    if "v.douyin.com" in u:
        try:
            import requests
            r = requests.head(
                u,
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"},
                allow_redirects=True,
                timeout=5,
            )
            u = r.url
        except Exception:
            pass

    # 3. Xử lý modal_id (Douyin Jingxuan / Đề xuất / Feed Modal: jingxuan?modal_id=7684524003720957203)
    m_modal = re.search(r"[?&]modal_id=(\d+)", u)
    if m_modal and ("douyin.com" in u or "iesdouyin.com" in u):
        return f"https://www.douyin.com/video/{m_modal.group(1)}"

    # 4. Nếu là link user có chứa vid= (ví dụ mở video ngay trong profile)
    m_vid = re.search(r"[?&]vid=(\d+)", u)
    if m_vid and "douyin.com" in u:
        return f"https://www.douyin.com/video/{m_vid.group(1)}"

    # 5. Link dạng standard /video/<id> hoặc /share/video/<id>
    m_dy = re.search(r"/(?:video|share/video)/(\d+)", u)
    if m_dy and ("douyin.com" in u or "iesdouyin.com" in u) and not ("douyinvod.com" in u or "snssdk.com" in u):
        return f"https://www.douyin.com/video/{m_dy.group(1)}"

    # 5.0. URL đã là CDN stream Douyin trực tiếp -> pass-through, không cần transform
    _DOUYIN_CDN = ('zjcdn.com', 'douyinvod.com', 'snssdk.com/aweme/v1/play')
    if any(d in u for d in _DOUYIN_CDN):
        return u

    # 5.1. Nếu là stream URL có chứa asset vid (v0... hoặc video_id=) -> chuyển thành link play 1080p full có tiếng
    m_v0 = re.search(r"(v0[0-9a-zA-Z]{15,})", u) or re.search(r"[?&]video_id=([a-zA-Z0-9_-]+)", u)
    if m_v0:
        return f"https://aweme.snssdk.com/aweme/v1/play/?video_id={m_v0.group(1)}&ratio=1080p&line=0"

    # 6. Chuẩn hóa Bilibili list / collection detail
    m = _BILI_LISTS_QS.search(u) or _BILI_COLLDETAIL.search(u)
    if m:
        return f"{m.group(1)}/lists/{m.group(2)}"
    return u
