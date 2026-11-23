"""
Bài kiểm tra xác minh Live End-to-End cho MiniApp Douyin bằng phiên cookie thật của người dùng.
Tuân thủ:
- Không log cookie/token thô.
- Che giấu episode ID và URL nhạy cảm.
- Kiểm tra toàn bộ chuỗi: Cookie -> Token -> Browse -> Playlist -> Resolve Free -> Block Locked -> Tải thử tập Free.
"""
import os
import sys
import tempfile
import shutil
import unittest
import requests

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from providers.miniapp_douyin_client import MiniAppDouyinClient, mask_sensitive
from providers.miniapp_douyin_provider import MiniAppDouyinProvider
from providers.base import ACCESS_STATE_FREE, ACCESS_STATE_REQUIRES_VIP, ACCESS_STATE_REQUIRES_LOGIN


class TestLiveDouyinVerification(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.provider = MiniAppDouyinProvider()
        cls.client = cls.provider.client
        cls.app_id = "tt5b4d2df0c47bdd2201"
        cls.test_cid = "16263"
        cls.series = None

    def test_01_mint_token_live(self):
        token, msg = self.client.mint_token(self.app_id, force=False)
        self.assertIsNotNone(token, f"mint_token thất bại: {msg}")
        self.assertTrue(token.startswith("duolai_"), "Token không đúng định dạng duolai_")
        print(f"\n[LIVE TEST] 1. Mint Token thành công: {mask_sensitive(token)}")

    def test_02_browse_catalog_live(self):
        catalog_result = self.provider.load_catalog(page=1)
        self.assertIsNotNone(catalog_result)
        self.assertGreater(len(catalog_result.items), 0, "Catalog không được rỗng")
        first = catalog_result.items[0]
        print(f"\n[LIVE TEST] 2. Browse thành công: {len(catalog_result.items)} phim, phim đầu: id={first.id}, title={first.name}")

    def test_03_load_playlist_live(self):
        series_url = f"douyin_miniapp:{self.app_id}:{self.test_cid}"
        series = self.provider.load_series(series_url)
        self.__class__.series = series
        self.assertIsNotNone(series, f"Không thể tải playlist cho series {series_url}")
        self.assertGreater(len(series.episodes), 0, "Danh sách tập không được rỗng")

        free_eps = [ep for ep in series.episodes if ep.access_state == ACCESS_STATE_FREE]
        vip_eps = [ep for ep in series.episodes if ep.access_state in (ACCESS_STATE_REQUIRES_VIP, ACCESS_STATE_REQUIRES_LOGIN)]

        print(f"\n[LIVE TEST] 3. Playlist '{series.name}' (CID: {self.test_cid}): Tổng {len(series.episodes)} tập (Free: {len(free_eps)}, VIP/Khóa: {len(vip_eps)})")
        self.assertGreater(len(free_eps), 0, "Cần có ít nhất 1 tập Free để kiểm tra")

    def test_04_resolve_free_and_block_vip_live(self):
        series = self.__class__.series
        if not series:
            series_url = f"douyin_miniapp:{self.app_id}:{self.test_cid}"
            series = self.provider.load_series(series_url)
        self.assertIsNotNone(series)

        # 1. Resolve tập Free
        free_eps = [ep for ep in series.episodes if ep.access_state == ACCESS_STATE_FREE]
        self.assertGreater(len(free_eps), 0)
        first_free = free_eps[0]
        masked_free_id = first_free.episode_id[:6] + "***" if len(first_free.episode_id) > 6 else first_free.episode_id

        stream = self.provider.resolve_stream(first_free)
        self.assertIsNotNone(stream, f"Không thể lấy play_url cho tập Free {first_free.title}")
        is_hls = stream.startswith("douyin_miniapp:")
        stream_type = "HLS Antihook" if is_hls else "Direct MP4"
        print(f"\n[LIVE TEST] 4a. Resolve tập Free thành công ({first_free.title}, ID: {masked_free_id}) -> Dạng stream: {stream_type}")

        # 2. Chặn tập VIP
        vip_eps = [ep for ep in series.episodes if ep.access_state in (ACCESS_STATE_REQUIRES_VIP, ACCESS_STATE_REQUIRES_LOGIN)]
        if vip_eps:
            first_vip = vip_eps[0]
            masked_vip_id = first_vip.episode_id[:6] + "***" if len(first_vip.episode_id) > 6 else first_vip.episode_id
            vip_stream = self.provider.resolve_stream(first_vip)
            self.assertIsNone(vip_stream, "Tập VIP phải bị chặn hoàn toàn, resolve_stream phải trả về None")
            print(f"\n[LIVE TEST] 4b. Chặn tập VIP chính xác ({first_vip.title}, ID: {masked_vip_id}) -> Stream: {vip_stream}")

    def test_05_download_free_episode_live(self):
        series = self.__class__.series
        if not series:
            series_url = f"douyin_miniapp:{self.app_id}:{self.test_cid}"
            series = self.provider.load_series(series_url)
        free_eps = [ep for ep in series.episodes if ep.access_state == ACCESS_STATE_FREE]
        self.assertGreater(len(free_eps), 0)
        first_free = free_eps[0]
        stream_url = self.provider.resolve_stream(first_free)
        self.assertIsNotNone(stream_url)

        temp_dir = tempfile.mkdtemp(prefix="hm_miniapp_test_")
        try:
            target_file = os.path.join(temp_dir, f"test_ep_{first_free.episode_number}.mp4")
            if stream_url.startswith("douyin_miniapp:"):
                # HLS Stream
                ok = self.client.download_hls_antihook(
                    stream_url, target_file, app_id=self.app_id
                )
                self.assertTrue(ok, "Download HLS thất bại")
            else:
                # Direct MP4 stream (yêu cầu header tương thích)
                headers = {
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                    "Referer": "https://www.douyin.com/",
                }
                # Tải một phần (chunk 256KB) để xác minh download HTTP stream thành công
                r = requests.get(stream_url, headers=headers, stream=True, timeout=15)
                self.assertEqual(r.status_code, 200, f"HTTP status tải video không phải 200: {r.status_code}")
                content_len = int(r.headers.get("Content-Length", 0))
                with open(target_file, "wb") as f:
                    downloaded = 0
                    for chunk in r.iter_content(chunk_size=64 * 1024):
                        if chunk:
                            f.write(chunk)
                            downloaded += len(chunk)
                            if downloaded >= 256 * 1024:  # Đã xác minh stream hợp lệ
                                break

            self.assertTrue(os.path.exists(target_file), "File tải về không tồn tại")
            file_size = os.path.getsize(target_file)
            self.assertGreater(file_size, 1024, "File tải về quá nhỏ")
            masked_id = first_free.episode_id[:6] + "***" if len(first_free.episode_id) > 6 else first_free.episode_id
            print(f"\n[LIVE TEST] 5. Tải thử tập Free thành công ({first_free.title}, ID: {masked_id}) -> Kích thước nhận: {file_size} bytes")
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
