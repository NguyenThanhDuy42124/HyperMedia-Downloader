"""
tests/test_free_first_providers_contract.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Offline unit & mock contract test suite for the Free-first drama providers:
- HongguoProvider
- GoodShortProvider
- ShortMaxProvider
- NetShortProvider
- FreeReelsProvider
- DramaWaveProvider
- RaptDramaProvider
- FlexTVProvider
- StardustTVProvider

Verifies:
1. URL routing precision (hostname allowlist & schemes; rejection of YouTube/Bilibili).
2. Offline mock series parsing & episode ID stability.
3. Access state mapping (free vs requires_vip, locked synchronization).
4. Subtitle extraction where supported.
5. Rejection of locked/VIP episodes in DownloadWorker.
6. Authentication & entitlement stub interface contract.
"""

import os
import sys
import unittest
from unittest.mock import MagicMock, patch

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from providers.base import (
    ACCESS_STATE_FREE,
    ACCESS_STATE_REQUIRES_VIP,
    ACCESS_STATE_REQUIRES_LOGIN,
    Episode,
    Series,
)
from providers.hongguo_provider import HongguoProvider
from providers.goodshort_provider import GoodShortProvider
from providers.shortmax_provider import ShortMaxProvider
from providers.netshort_provider import NetShortProvider
from providers.freereels_provider import FreeReelsProvider
from providers.dramawave_provider import DramaWaveProvider
from providers.raptdrama_provider import RaptDramaProvider
from providers.flextv_provider import FlexTVProvider
from providers.stardusttv_provider import StardustTVProvider
from download_worker import DownloadWorker


class TestFreeFirstProvidersContract(unittest.TestCase):

    def test_routing_precision_across_all_providers(self):
        """Kiểm tra nhận diện URL chính xác của toàn bộ 9 provider Free-first và không nhận nhầm URL khác."""
        cases = [
            (HongguoProvider(), "https://hongguoduanju.com/detail?series_id=741000", True),
            (HongguoProvider(), "hongguo:741000", True),
            (HongguoProvider(), "https://www.fqnovel.com/player/741000?vid=v1", True),
            (HongguoProvider(), "https://youtube.com/watch?v=741000&series=hongguo", False),

            (GoodShortProvider(), "https://www.goodshort.com/video/12345678/1", True),
            (GoodShortProvider(), "goodshort:12345678", True),
            (GoodShortProvider(), "https://www.goodreels.com/detail/12345678", True),
            (GoodShortProvider(), "https://bilibili.com/video/BV123?ref=goodshort", False),

            (ShortMaxProvider(), "https://www.shortmax.com/drama/sm_key_123/1", True),
            (ShortMaxProvider(), "shortmax:sm_key_123", True),
            (ShortMaxProvider(), "https://google.com/search?q=shortmax", False),

            (NetShortProvider(), "https://netshort.com/drama/ns_key_123/1", True),
            (NetShortProvider(), "https://www.flickreels.com/drama/ns_key_123/1", True),
            (NetShortProvider(), "netshort:ns_key_123", True),

            (FreeReelsProvider(), "https://freereels.app/drama/fr_key_123/1", True),
            (FreeReelsProvider(), "freereels:fr_key_123", True),

            (DramaWaveProvider(), "https://www.dramawave.com/drama/dw_key/1", True),
            (DramaWaveProvider(), "dramawave:dw_key", True),

            (RaptDramaProvider(), "https://raptdrama.com/drama/99999", True),
            (RaptDramaProvider(), "raptdrama:99999", True),

            (FlexTVProvider(), "https://flextv.com/drama/fx12345", True),
            (FlexTVProvider(), "flextv:fx12345", True),

            (StardustTVProvider(), "https://stardusttv.com/video/88888", True),
            (StardustTVProvider(), "stardust:88888", True),
        ]

        for provider, url, expected in cases:
            self.assertEqual(
                provider.can_handle(url),
                expected,
                f"Lỗi routing với {provider.display_name} trên URL: {url}",
            )

    def test_hongguo_provider_load_series_and_stream_resolution(self):
        """Kiểm tra HongguoProvider: phân định Free-first theo accessible_episode_cnt và giải mã stream."""
        p = HongguoProvider()
        mock_payload = {
            "seriesDetail": {
                "series_name": "Hongguo Short Drama",
                "series_cover": "https://img.test/cover.jpg",
                "series_intro": "Intro text",
                "vid_list": ["v101", "v102", "v103"],
                "accessible_episode_cnt": 2,
            }
        }

        with patch.object(p.session, "get") as mock_get:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = mock_payload
            mock_get.return_value = mock_resp

            series = p.load_series("https://hongguoduanju.com/detail?series_id=741000")
            self.assertEqual(series.name, "Hongguo Short Drama")
            self.assertEqual(series.episode_count, 3)
            self.assertEqual(series.accessible_count, 2)
            self.assertEqual(series.episodes[0].access_state, ACCESS_STATE_FREE)
            self.assertFalse(series.episodes[0].locked)
            self.assertEqual(series.episodes[2].access_state, ACCESS_STATE_REQUIRES_VIP)
            self.assertTrue(series.episodes[2].locked)

        # Stream resolution for free episode
        mock_player_resp = {
            "videoPlayInfo": {
                "video_url": "https://cdn.test/v101.mp4",
            }
        }
        with patch.object(p.session, "get") as mock_get:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = mock_player_resp
            mock_get.return_value = mock_resp

            stream = p.resolve_episode_stream(series.episodes[0])
            self.assertEqual(stream, "https://cdn.test/v101.mp4")

        # Stream resolution for VIP episode must return None
        vip_stream = p.resolve_episode_stream(series.episodes[2])
        self.assertIsNone(vip_stream, "Tập VIP không được trả URL stream khi chưa có xác thực hợp lệ")

    def test_goodshort_provider_load_series(self):
        """Kiểm tra GoodShortProvider: phân tích book & chapters và phân định Free/VIP."""
        p = GoodShortProvider()
        mock_book = {
            "data": {
                "book": {
                    "bookName": "GoodShort Drama Title",
                    "cover": "https://img.test/gs.jpg",
                    "chapterCount": 2,
                }
            }
        }
        mock_chapters = {
            "data": {
                "list": [
                    {"index": 0, "chapterName": "Tập 1", "cdn": "https://cdn.test/ep1.mp4"},
                    {"index": 1, "chapterName": "Tập 2", "cdn": ""},
                ]
            }
        }

        def mock_get_side_effect(url, *args, **kwargs):
            resp = MagicMock()
            resp.status_code = 200
            if "chapters" in url:
                resp.json.return_value = mock_chapters
            else:
                resp.json.return_value = mock_book
            return resp

        with patch.object(p.session, "get", side_effect=mock_get_side_effect):
            series = p.load_series("https://www.goodshort.com/video/12345678/1")
            self.assertEqual(series.name, "GoodShort Drama Title")
            self.assertEqual(series.episode_count, 2)
            self.assertEqual(series.accessible_count, 1)
            self.assertEqual(series.episodes[0].access_state, ACCESS_STATE_FREE)
            self.assertEqual(series.episodes[0].direct_url, "https://cdn.test/ep1.mp4")
            self.assertEqual(series.episodes[1].access_state, ACCESS_STATE_REQUIRES_VIP)
            self.assertTrue(series.episodes[1].locked)

    def test_shortmax_provider_load_series(self):
        """Kiểm tra ShortMaxProvider: chọn best resolution và phân loại tập."""
        p = ShortMaxProvider()
        mock_data = {
            "data": {
                "name": "ShortMax Series Title",
                "cover": "https://img.test/sm.jpg",
                "episodes": [
                    {
                        "episode": 1,
                        "video": {"720p": "https://cdn.test/sm_720.mp4", "1080p": "https://cdn.test/sm_1080.mp4"},
                    },
                    {
                        "episode": 2,
                        "video": {},  # Khóa, không có stream
                    },
                ]
            }
        }

        with patch.object(p.session, "get") as mock_get:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = mock_data
            mock_get.return_value = mock_resp

            series = p.load_series("https://www.shortmax.com/drama/sm_key_123")
            self.assertEqual(series.name, "ShortMax Series Title")
            self.assertEqual(series.accessible_count, 1)
            # Ưu tiên 1080p
            self.assertEqual(series.episodes[0].direct_url, "https://cdn.test/sm_1080.mp4")
            self.assertEqual(series.episodes[0].access_state, ACCESS_STATE_FREE)
            self.assertEqual(series.episodes[1].access_state, ACCESS_STATE_REQUIRES_VIP)
            self.assertTrue(series.episodes[1].locked)

    def test_netshort_provider_load_series_and_subtitles(self):
        """Kiểm tra NetShortProvider: trích xuất playVoucher và subtitle list."""
        p = NetShortProvider()
        mock_data = {
            "data": {
                "shortPlayName": "NetShort Series",
                "shortPlayCover": "https://img.test/ns.jpg",
                "shortPlayEpisodeList": [
                    {
                        "episodeNo": 1,
                        "playVoucher": "https://cdn.test/ns1.mp4",
                        "subtitleList": [
                            {"lang": "en", "url": "https://sub.test/en.srt"},
                            {"lang": "vi", "url": "https://sub.test/vi.srt"},
                        ],
                    },
                    {
                        "episodeNo": 2,
                        "playVoucher": None,
                        "subtitleList": [],
                    },
                ]
            }
        }

        with patch.object(p.session, "get") as mock_get:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = mock_data
            mock_get.return_value = mock_resp

            series = p.load_series("https://netshort.com/drama/ns_key_123")
            self.assertEqual(series.name, "NetShort Series")
            self.assertEqual(series.accessible_count, 1)
            self.assertEqual(series.episodes[0].access_state, ACCESS_STATE_FREE)
            self.assertEqual(len(series.episodes[0].subtitles), 2)
            self.assertEqual(series.episodes[0].subtitles[0].lang, "en")
            self.assertEqual(series.episodes[1].access_state, ACCESS_STATE_REQUIRES_VIP)

    def test_freereels_provider_load_series_filter_bloopers(self):
        """Kiểm tra FreeReelsProvider: lọc blooper và trích xuất subtitle."""
        p = FreeReelsProvider()
        mock_data = {
            "data": {
                "name": "FreeReels Drama Title",
                "cover": "https://img.test/fr.jpg",
                "items": [
                    {
                        "serial_number": 1,
                        "is_blooper": False,
                        "video_path": "https://cdn.test/fr1.mp4",
                        "subtitle_list": [{"language_name": "vi", "subtitle_url": "https://sub.test/vi.vtt"}],
                    },
                    {
                        "serial_number": 2,
                        "is_blooper": True,  # Phải bị loại bỏ
                        "video_path": "https://cdn.test/blooper.mp4",
                    },
                    {
                        "serial_number": 3,
                        "is_blooper": False,
                        "video_path": None,  # Tập khóa
                    },
                ]
            }
        }

        with patch.object(p.session, "get") as mock_get:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = mock_data
            mock_get.return_value = mock_resp

            series = p.load_series("https://freereels.app/drama/fr_key_123")
            self.assertEqual(series.name, "FreeReels Drama Title")
            # Blooper bị lọc, còn 2 tập
            self.assertEqual(series.episode_count, 2)
            self.assertEqual(series.accessible_count, 1)
            self.assertEqual(series.episodes[0].direct_url, "https://cdn.test/fr1.mp4")
            self.assertEqual(len(series.episodes[0].subtitles), 1)
            self.assertEqual(series.episodes[1].access_state, ACCESS_STATE_REQUIRES_VIP)

    def test_dramawave_provider_load_series(self):
        """Kiểm tra DramaWaveProvider."""
        p = DramaWaveProvider()
        mock_data = {
            "data": {
                "name": "DramaWave Series",
                "episodes": [
                    {"video_url": "https://cdn.test/dw1.mp4"},
                    {"video_url": None},
                ]
            }
        }
        with patch.object(p.session, "get") as mock_get:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = mock_data
            mock_get.return_value = mock_resp

            series = p.load_series("https://www.dramawave.com/drama/dw_key")
            self.assertEqual(series.accessible_count, 1)
            self.assertEqual(series.episodes[0].access_state, ACCESS_STATE_FREE)
            self.assertEqual(series.episodes[1].access_state, ACCESS_STATE_REQUIRES_VIP)

    def test_raptdrama_provider_load_series(self):
        """Kiểm tra RaptDramaProvider."""
        p = RaptDramaProvider()
        mock_data = {
            "data": {
                "name": "RaptDrama Series",
                "episodes": [
                    {"src": "https://cdn.test/rd1.mp4"},
                    {"src": None},
                ]
            }
        }
        with patch.object(p.session, "get") as mock_get:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = mock_data
            mock_get.return_value = mock_resp

            series = p.load_series("https://raptdrama.com/drama/12345")
            self.assertEqual(series.accessible_count, 1)
            self.assertEqual(series.episodes[0].direct_url, "https://cdn.test/rd1.mp4")
            self.assertEqual(series.episodes[1].access_state, ACCESS_STATE_REQUIRES_VIP)

    def test_flextv_provider_load_series(self):
        """Kiểm tra FlexTVProvider."""
        p = FlexTVProvider()
        mock_data = {
            "data": {
                "name": "FlexTV Series",
                "episodes": [
                    {"video_url": "https://cdn.test/fx1.mp4"},
                    {"video_url": None},
                ]
            }
        }
        with patch.object(p.session, "get") as mock_get:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = mock_data
            mock_get.return_value = mock_resp

            series = p.load_series("https://flextv.com/drama/fx12345")
            self.assertEqual(series.accessible_count, 1)
            self.assertEqual(series.episodes[0].access_state, ACCESS_STATE_FREE)
            self.assertEqual(series.episodes[1].access_state, ACCESS_STATE_REQUIRES_VIP)

    def test_stardusttv_provider_load_series(self):
        """Kiểm tra StardustTVProvider."""
        p = StardustTVProvider()
        mock_data = {
            "name": "StardustTV Series",
            "episodes": [
                {"m3u8": "https://cdn.test/sd1.m3u8"},
                {"m3u8": None},
            ]
        }
        with patch.object(p.session, "get") as mock_get:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = mock_data
            mock_get.return_value = mock_resp

            series = p.load_series("https://stardusttv.com/video/88888")
            self.assertEqual(series.accessible_count, 1)
            self.assertEqual(series.episodes[0].direct_url, "https://cdn.test/sd1.m3u8")
            self.assertEqual(series.episodes[1].access_state, ACCESS_STATE_REQUIRES_VIP)

    def test_download_worker_strictly_rejects_free_first_vip_episodes(self):
        """DownloadWorker phải chặn mọi tập requires_vip của các provider Free-first, không gọi YoutubeDL."""
        locked_ep = Episode(
            num=5,
            title="Tập 5 VIP",
            url="https://shortmax.com/drama/sm_test/5?ep_id=5",
            episode_id="5",
            episode_number=5,
            access_state=ACCESS_STATE_REQUIRES_VIP,
            access_reason="Tập này yêu cầu quyền VIP trên ứng dụng chính thức.",
            locked=True,
            extra={"episode_id": "5"},
        )
        series = Series(
            name="ShortMax Locked Series",
            platform="shortmax",
            series_id="shortmax:sm_test",
            episode_count=5,
            accessible_count=4,
            episodes=[locked_ep],
        )

        worker = DownloadWorker(url=locked_ep.url, options={"output_path": "downloads"})

        with patch("providers.detect_provider") as mock_det, \
             patch("yt_dlp.YoutubeDL") as mock_ydl:
            mock_p = ShortMaxProvider()
            mock_p.load_series = MagicMock(return_value=series)
            mock_det.return_value = mock_p

            with self.assertRaises(ValueError) as ctx:
                worker._download_drama_episode("downloads")

            self.assertIn("không thể tải", str(ctx.exception))
            mock_ydl.assert_not_called()

    def test_authentication_stub_interface_contract(self):
        """Kiểm tra interface xác thực trong tương lai: mặc định trả về False/Free-only."""
        providers_list = [
            HongguoProvider(),
            GoodShortProvider(),
            ShortMaxProvider(),
            NetShortProvider(),
            FreeReelsProvider(),
            DramaWaveProvider(),
            RaptDramaProvider(),
            FlexTVProvider(),
            StardustTVProvider(),
        ]
        free_ep = Episode(num=1, title="T1", url="https://test/1", access_state=ACCESS_STATE_FREE)
        vip_ep = Episode(num=2, title="T2", url="https://test/2", access_state=ACCESS_STATE_REQUIRES_VIP)

        for p in providers_list:
            self.assertFalse(p.authenticate({"token": "fake"}), f"{p.display_name} không được bật auth giả")
            self.assertFalse(p.refresh_session(), f"{p.display_name} không được refresh session giả")
            self.assertTrue(p.validate_entitlement(free_ep), f"{p.display_name} phải cho phép tập free")
            self.assertFalse(p.validate_entitlement(vip_ep), f"{p.display_name} phải từ chối tập VIP")


if __name__ == "__main__":
    unittest.main()
