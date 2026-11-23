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
    host = ""
    try:
        from urllib.parse import urlparse
        host = (urlparse(url.strip()).netloc or "").lower().split(":")[0]
    except Exception:
        pass

    if host in {"dramaboxdb.com", "www.dramaboxdb.com"} or u.startswith("dramabox:"):
        return {
            "Referer": "https://www.dramaboxdb.com/",
            "Origin": "https://www.dramaboxdb.com",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        }
    if host in {"kisskh.co", "www.kisskh.co", "kisskh.do", "kisskh.id", "kisskh.is"} or u.startswith("kisskh:"):
        return {
            "Referer": "https://kisskh.co/",
            "Origin": "https://kisskh.co",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        }
    if host in {
        "kylin.hainanyuyue.com",
        "hainanyuyue.com",
        "www.hainanyuyue.com",
    } or ("hongman" in host and host.endswith("qznovelvod.com")):
        return {
            "Referer": "https://hainanyuyue.com/",
            "Origin": "https://hainanyuyue.com",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        }
    if host in {
        "hongguoduanju.com",
        "www.hongguoduanju.com",
        "fqnovel.com",
        "www.fqnovel.com",
        "fanqienovel.com",
        "www.fanqienovel.com",
        "novelquickapp.com",
        "www.novelquickapp.com",
    } or host.endswith("qznovelvod.com") or u.startswith("hongguo:"):
        return {
            "Referer": "https://hongguoduanju.com/",
            "Origin": "https://hongguoduanju.com",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        }
    if host in {"goodshort.com", "www.goodshort.com", "goodreels.com", "www.goodreels.com", "goodshort.goodbos.online"} or u.startswith(("goodshort:", "goodreels:")):
        return {
            "Referer": "https://www.goodshort.com/",
            "Origin": "https://www.goodshort.com",
            "User-Agent": "okhttp/4.10.0",
        }
    if host in {"shortmax.com", "www.shortmax.com", "shortmax.goodbos.online"} or u.startswith("shortmax:"):
        return {
            "Referer": "https://www.shortmax.com/",
            "Origin": "https://www.shortmax.com",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        }
    if host in {"netshort.com", "www.netshort.com", "flickreels.com", "www.flickreels.com", "netshort.goodbos.online"} or u.startswith(("netshort:", "flickreels:")):
        return {
            "Referer": "https://netshort.com/",
            "Origin": "https://netshort.com",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        }
    if host in {"freereels.app", "www.freereels.app", "freereels.cc", "www.freereels.cc", "drakula.goodbos.online"} or u.startswith("freereels:"):
        return {
            "Referer": "https://freereels.app/",
            "Origin": "https://freereels.app",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        }
    if host in {"dramawave.com", "www.dramawave.com", "dramawave.goodbos.online"} or u.startswith("dramawave:"):
        return {
            "Referer": "https://www.dramawave.com/",
            "Origin": "https://www.dramawave.com",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        }
    if host in {"raptdrama.com", "www.raptdrama.com", "raptdrama.goodbos.online"} or u.startswith("raptdrama:"):
        return {
            "Referer": "https://raptdrama.com/",
            "Origin": "https://raptdrama.com",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        }
    if host in {"flextv.com", "www.flextv.com", "flextv.cc", "www.flextv.cc", "flextv.goodbos.online"} or u.startswith("flextv:"):
        return {
            "Referer": "https://flextv.com/",
            "Origin": "https://flextv.com",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        }
    if host in {"stardusttv.com", "www.stardusttv.com", "stardusttv2.goodbos.online"} or u.startswith(("stardust:", "stardusttv:")):
        return {
            "Referer": "https://stardusttv.com/",
            "Origin": "https://stardusttv.com",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        }
    if host in {"xiaoguofanxing.lizhibj.cn", "ma.zijieapi.com"} or u.startswith(("douyin_miniapp:", "miniapp_douyin:")):
        return {
            "Referer": "https://xiaoguofanxing.lizhibj.cn/",
            "User-Agent": "Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 ToutiaoMicroApp",
        }
    if "youtube.com" in u or "youtu.be" in u:
        return {}
    return {}


def is_drama_url(url):
    """Kiểm tra URL có thuộc các nền tảng drama hay không bằng netloc và scheme."""
    if not url:
        return False
    try:
        from providers.registry import is_drama_url as reg_is_drama
        return reg_is_drama(url)
    except Exception:
        pass
    u = str(url).strip()
    if u.lower().startswith(("dramabox:", "kisskh:", "hongguo:", "douyin_miniapp:", "miniapp_douyin:", "goodshort:", "shortmax:", "netshort:", "freereels:", "dramawave:", "raptdrama:", "flextv:", "stardust:")):
        return True
    try:
        from urllib.parse import urlparse
        host = (urlparse(u).netloc or "").lower().split(":")[0]
        return host in {
            "dramaboxdb.com",
            "www.dramaboxdb.com",
            "kisskh.co",
            "www.kisskh.co",
            "kisskh.do",
            "kisskh.id",
            "kisskh.is",
            "hongguoduanju.com",
            "www.hongguoduanju.com",
            "fqnovel.com",
            "www.fqnovel.com",
            "fanqienovel.com",
            "www.fanqienovel.com",
            "kylin.hainanyuyue.com",
            "hainanyuyue.com",
            "www.hainanyuyue.com",
            "novelquickapp.com",
            "www.novelquickapp.com",
            "xiaoguofanxing.lizhibj.cn",
            "goodshort.com",
            "www.goodshort.com",
            "goodreels.com",
            "www.goodreels.com",
            "shortmax.com",
            "www.shortmax.com",
            "netshort.com",
            "www.netshort.com",
            "flickreels.com",
            "www.flickreels.com",
            "freereels.app",
            "www.freereels.app",
            "freereels.cc",
            "www.freereels.cc",
            "dramawave.com",
            "www.dramawave.com",
            "raptdrama.com",
            "www.raptdrama.com",
            "flextv.com",
            "www.flextv.com",
            "stardusttv.com",
            "www.stardusttv.com",
        }
    except Exception:
        return False


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

    # Giữ nguyên URI/URL của các nền tảng drama (tránh rule video_id= của Douyin ghi đè)
    if is_drama_url(raw):
        return raw

    # 1. Trích xuất URL nếu người dùng dán cả đoạn văn bản chia sẻ (ví dụ: '2.89 q@R.kC ... https://v.douyin.com/... ')
    m_url = re.search(r"https?://[^\s<>\"']+", raw)
    u = m_url.group(0) if m_url else raw
    if is_drama_url(u):
        return u

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


# Re-export các tiện ích đường dẫn drama từ drama_path_utils
from drama_path_utils import (
    MINIAPP_DISPLAY_NAMES,
    get_miniapp_display_name,
    sanitize_windows_name,
    sanitize_windows_foldername,
    sanitize_windows_filename,
    build_drama_destination_dir,
    build_drama_filename,
    resolve_unique_drama_filepath,
)

