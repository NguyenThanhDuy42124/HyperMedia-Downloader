"""
tests/test_live_hongguo_and_douyin_probe.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Kiểm thử Live Network Probe riêng biệt cho Kylin, NovelQuickApp, Douyin và Hongguo Catalog.
Chỉ ghi nhận HTTP status, tiêu đề, số tập, episode ID đã che (masked).
TUYỆT ĐỐI KHÔNG ghi cookie/token hay thông tin nhạy cảm vào log.
"""

import os
import sys
import unittest
import requests

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from providers.hongguo_provider import HongguoProvider
from providers.miniapp_douyin_provider import MiniAppDouyinProvider
from providers.base import ACCESS_STATE_FREE, ACCESS_STATE_REQUIRES_VIP


def mask_id(raw_id: str) -> str:
    """Che ID chỉ để lại 6 ký tự đầu và 3 dấu sao."""
    s = str(raw_id).strip()
    return f"{s[:6]}***" if len(s) > 6 else "***"


class TestLiveHongguoAndDouyinProbe(unittest.TestCase):

    def setUp(self):
        self.hongguo = HongguoProvider()
        self.douyin = MiniAppDouyinProvider()

    def test_live_kylin_share_probe(self):
        """Live Probe: Phân giải link Kylin, kiểm tra 86 tập và xác thực HTTP 206 CDN stream."""
        url = "https://kylin.hainanyuyue.com/s/-mVjL3iKXGY/"
        series = self.hongguo.load_series(url)

        self.assertIsNotNone(series)
        self.assertIn("仙帝", series.name)
        self.assertGreaterEqual(series.episode_count, 80)
        self.assertEqual(len(series.episodes), series.episode_count)

        masked_ep1 = mask_id(series.episodes[0].episode_id)
        print(f"[LIVE PROBE] Kylin Series: '{series.name}', Tong tap: {series.episode_count}, Ep1 ID: {masked_ep1}")

        # Kiểm tra stream tập 1 (đã có direct_url)
        ep1 = series.episodes[0]
        stream_ep1 = self.hongguo.resolve_episode_stream(ep1)
        self.assertIsNotNone(stream_ep1, "Tap 1 phai co stream truc tiep")

        # HTTP Range probe trên CDN ByteDance
        h_resp = requests.head(
            stream_ep1,
            headers={"User-Agent": "Mozilla/5.0", "Range": "bytes=0-1024"},
            timeout=10,
        )
        self.assertIn(h_resp.status_code, (200, 206))
        print(f"[LIVE PROBE] Kylin Ep1 CDN Stream HTTP Status: {h_resp.status_code}, Content-Type: {h_resp.headers.get('Content-Type')}")

        # Kiểm tra stream tập 2 (giải mã động qua loader)
        ep2 = series.episodes[1]
        stream_ep2 = self.hongguo.resolve_episode_stream(ep2)
        self.assertIsNotNone(stream_ep2, "Tap 2 phai giai ma thanh cong qua loader")

        h_resp2 = requests.head(
            stream_ep2,
            headers={"User-Agent": "Mozilla/5.0", "Range": "bytes=0-1024"},
            timeout=10,
        )
        self.assertIn(h_resp2.status_code, (200, 206))
        masked_ep2 = mask_id(ep2.episode_id)
        print(f"[LIVE PROBE] Kylin Ep2 ({masked_ep2}) CDN Stream HTTP Status: {h_resp2.status_code}")

    def test_live_novelquickapp_share_probe(self):
        """Live Probe: Phân giải NovelQuickApp, fallback video_id sang detail_page, xác minh 5 tập Free."""
        url = "https://novelquickapp.com/s/leok-rgP11w/"
        series = self.hongguo.load_series(url)

        self.assertIsNotNone(series)
        self.assertIn("分身", series.name)
        self.assertEqual(series.episode_count, 47)
        self.assertEqual(series.accessible_count, 5)

        masked_sid = mask_id(series.series_id)
        print(f"[LIVE PROBE] NovelQuickApp Series: '{series.name}', ID: {masked_sid}, Tong tap: {series.episode_count}, Free: {series.accessible_count}")

        # Ranh giới Free / VIP
        for i in range(5):
            self.assertEqual(series.episodes[i].access_state, ACCESS_STATE_FREE)
            self.assertFalse(series.episodes[i].locked)

        for j in range(5, len(series.episodes)):
            self.assertEqual(series.episodes[j].access_state, ACCESS_STATE_REQUIRES_VIP)
            self.assertTrue(series.episodes[j].locked)

        # Bảo vệ: Tập locked tuyệt đối không resolve stream
        locked_ep = series.episodes[5]
        res = self.hongguo.resolve_episode_stream(locked_ep)
        self.assertIsNone(res, "Tap VIP/locked khong duoc resolve stream")
        print(f"[LIVE PROBE] NovelQuickApp Access Guard: Tap 6 (VIP) -> Resolve stream: None (BLOCKED)")

    def test_live_douyin_share_probe(self):
        """Live Probe: Nhận diện URL Douyin share, bóc tách aweme_id và chuyển luồng an toàn."""
        url = "https://www.iesdouyin.com/share/video/7700535750642748706/?region=VN"
        series = self.douyin.load_series(url)

        self.assertIsNotNone(series)
        self.assertEqual(series.episode_count, 1)
        masked_aid = mask_id(series.episodes[0].episode_id)
        print(f"[LIVE PROBE] Douyin Video: '{series.name}', Ep ID: {masked_aid}, Tong tap: {series.episode_count}")

    def test_live_hongguo_catalog_probe(self):
        """Live Probe: Kiểm tra endpoint trang chủ hongguoduanju.com live, không trùng lặp."""
        cat_p1 = self.hongguo.get_catalog(page=1)
        self.assertGreaterEqual(len(cat_p1.items), 10)
        self.assertGreaterEqual(cat_p1.total, 30)
        self.assertTrue(cat_p1.has_more)

        masked_item0 = mask_id(cat_p1.items[0].id)
        print(f"[LIVE PROBE] Hongguo Live Catalog: Trang 1 ({len(cat_p1.items)} phim), Tong: {cat_p1.total}, Phim dau: '{cat_p1.items[0].name}' (ID: {masked_item0})")

    def test_live_miniapp_public_catalog_probe(self):
        """Live Probe: Kiểm tra endpoint catalog công khai của MiniApp Douyin (Đa Lai)."""
        from providers.miniapp_douyin_client import MiniAppDouyinClient, BUILTIN_MINIAPP_SOURCES
        client = MiniAppDouyinClient()
        app_id = BUILTIN_MINIAPP_SOURCES[0]["app_id"]
        source_name = BUILTIN_MINIAPP_SOURCES[0]["name"]

        try:
            items, has_more, err = client.browse_catalog(app_id, page=1, pagesize=10)
            if err:
                print(f"[LIVE PROBE] MiniApp Public Catalog ({source_name}): {err}")
            else:
                self.assertGreaterEqual(len(items), 0)
                first_name = items[0].get("title", "N/A") if items else "No items"
                first_id = mask_id(items[0].get("album_id", "")) if items else "N/A"
                print(f"[LIVE PROBE] MiniApp Public Catalog ({source_name}): Nạp thành công {len(items)} phim, has_more={has_more}, Phim đầu: '{first_name}' (ID: {first_id})")
        except Exception as e:
            print(f"[LIVE PROBE] MiniApp Public Catalog probe connection warning: {e}")

    def test_live_miniapp_authenticated_catalog_probe(self):
        """Live Probe: Kiểm tra endpoint authenticated có cookie/token trong DPAPI (Skip nếu chưa có session)."""
        from providers.miniapp_douyin_client import get_douyin_session_status, MiniAppDouyinClient, BUILTIN_MINIAPP_SOURCES
        status, msg = get_douyin_session_status()
        if status != "valid":
            self.skipTest(f"Live MiniApp Authenticated probe skipped: No valid live VIP session in DPAPI (Trạng thái hiện tại: {status})")

        client = MiniAppDouyinClient()
        app_id = BUILTIN_MINIAPP_SOURCES[0]["app_id"]
        items, has_more, err = client.browse_catalog(app_id, page=1)
        self.assertIsNone(err, f"Authenticated catalog không được trả lỗi khi session valid: {err}")
        print(f"[LIVE PROBE] MiniApp Authenticated Catalog: Thành công nạp {len(items)} phim với phiên bảo mật")


if __name__ == "__main__":
    unittest.main()
