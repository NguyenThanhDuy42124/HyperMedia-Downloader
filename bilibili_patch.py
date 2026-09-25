"""Monkey-patch extractor yt-dlp để xử lý các vấn đề đặc thù của Bilibili."""


def patch_bilibili_extractor():
    """Monkey-patch yt-dlp's BiliBili extractor to bypass HTTP 412 anti-bot.

    Bilibili's risk-control sometimes returns 412 on x/player/wbi/playurl even
    with a valid browser UA. The community-confirmed workaround is retrying the
    same signed query against the legacy (non-wbi) endpoint.
    """
    try:
        from yt_dlp.extractor.bilibili import BiliBiliIE
    except Exception as e:
        print(f"[PATCH] Không tìm thấy extractor BiliBili: {e}")
        return

    original = getattr(BiliBiliIE, "_download_playinfo", None)
    if original is None or getattr(original, "_bili_412_patched", False):
        return

    def _download_playinfo(self, bvid, cid, headers=None, query=None, fatal=True):
        try:
            return original(self, bvid, cid, headers=headers, query=query, fatal=fatal)
        except Exception as e:
            err_str = str(e) or ""
            if "412" in err_str or "Precondition Failed" in err_str:
                print("[PATCH] BiliBili 412, thử lại với endpoint playurl cũ...")
                params = {
                    "bvid": bvid,
                    "cid": cid,
                    "fnval": 4048,
                    **getattr(self, "_dm_params", {}),
                    **(query or {}),
                }
                if getattr(self, "is_logged_in", False):
                    params.pop("try_look", None)
                qn = params.get("qn")
                note = (
                    f"Downloading video format {qn} for cid {cid}"
                    if qn
                    else "Downloading video formats for cid {cid}"
                )
                try:
                    return self._download_json(
                        "https://api.bilibili.com/x/player/playurl", bvid,
                        query=self._sign_wbi(params, bvid),
                        headers=headers, note=note)["data"]
                except Exception:
                    raise e
            raise

    _download_playinfo._bili_412_patched = True
    BiliBiliIE._download_playinfo = _download_playinfo
    print("[PATCH] Đã áp dụng fix HTTP 412 cho BiliBili")


def patch_bilibili_space_titles():
    """Monkey-patch BilibiliSpaceVideoIE so flat-mode scan keeps titles/thumbnails.

    The stock extractor only yields url_result (id + url) for each video, so
    scanning a space page with extract_flat=True makes every item show
    'Unknown'. The space API already returns title/pic, we just attach them.
    """
    try:
        from yt_dlp.extractor import bilibili as _b
        from yt_dlp.utils import unescapeHTML
    except Exception as e:
        print(f"[PATCH] Không tìm thấy extractor BilibiliSpaceVideoIE: {e}")
        return

    IE = _b.BilibiliSpaceVideoIE
    if getattr(IE, "_bili_space_titles_patched", False):
        return

    def _real_extract(self, url):
        playlist_id, is_video_url = self._match_valid_url(url).group("id", "video")
        if not is_video_url:
            self.to_screen(
                "A channel URL was given. Only the channel's videos will be downloaded. "
                'To download audios, add a "/upload/audio" to the URL'
            )

        def fetch_page(page_idx):
            query = {
                "keyword": "",
                "mid": playlist_id,
                "order": _b.traverse_obj(_b.parse_qs(url), ("order", 0)) or "pubdate",
                "order_avoided": "true",
                "platform": "web",
                "pn": page_idx + 1,
                "ps": 30,
                "tid": 0,
                "web_location": "333.1387",
                "special_type": "",
                "index": 0,
                **self._dm_params,
            }
            try:
                response = self._download_json(
                    "https://api.bilibili.com/x/space/wbi/arc/search",
                    playlist_id,
                    query=self._sign_wbi(query, playlist_id),
                    note=f"Downloading space page {page_idx}",
                    headers={
                        "Referer": url,
                        "Origin": "https://space.bilibili.com",
                        "Accept-Language": "en,zh-CN;q=0.9,zh;q=0.8",
                    },
                )
            except _b.ExtractorError as e:
                if isinstance(e.cause, _b.HTTPError) and e.cause.status == 412:
                    raise _b.ExtractorError(
                        "Request is blocked by server (412), please wait and try later.",
                        expected=True,
                    )
                raise
            status_code = response["code"]
            if status_code == -401:
                raise _b.ExtractorError(
                    "Request is blocked by server (401), please wait and try later.",
                    expected=True,
                )
            elif status_code == -352:
                raise _b.ExtractorError("Request is rejected by server (352)", expected=True)
            elif status_code != 0:
                raise _b.ExtractorError(
                    f'Request failed ({status_code}): {response.get("message") or "Unknown error"}'
                )
            return response["data"]

        def get_metadata(page_data):
            page_size = page_data["page"]["ps"]
            entry_count = page_data["page"]["count"]
            return {
                "page_count": _b.math.ceil(entry_count / page_size),
                "page_size": page_size,
            }

        def get_entries(page_data):
            for entry in _b.traverse_obj(page_data, ("list", "vlist", ..., {dict})):
                if _b.traverse_obj(entry, ("meta", "attribute")) == 156:
                    yield self.url_result(
                        f'https://space.bilibili.com/{entry["mid"]}/lists/{entry["meta"]["id"]}?type=season',
                        _b.BilibiliCollectionListIE,
                        f'{entry["mid"]}_{entry["meta"]["id"]}',
                    )
                else:
                    bvid = entry["bvid"]
                    r = self.url_result(
                        f"https://www.bilibili.com/video/{bvid}", _b.BiliBiliIE, bvid
                    )
                    if entry.get("title"):
                        r["title"] = unescapeHTML(entry["title"])
                    if entry.get("pic"):
                        r["thumbnail"] = entry["pic"]
                    yield r

        _, paged_list = self._extract_playlist(fetch_page, get_metadata, get_entries)
        return self.playlist_result(paged_list, playlist_id)

    _real_extract._bili_space_titles_patched = True
    IE._real_extract = _real_extract
    print("[PATCH] Đã áp dụng fix title/thumbnail cho trang space Bilibili")


def patch_bilibili_list_titles():
    """Monkey-patch BilibiliSpaceListBaseIE so flat-mode list scan keeps titles.

    Collection/Series/Favorites list extractors only yield url_result (bvid),
    so scanning e.g. `space.bilibili.com/<mid>/lists/<sid>` shows 'Unknown'.
    The list API already returns title/cover per archive — attach them.
    """
    try:
        from yt_dlp.extractor import bilibili as _b
        from yt_dlp.utils import traverse_obj, unescapeHTML, variadic
    except Exception as e:
        print(f"[PATCH] Không tìm thấy extractor BilibiliSpaceListBaseIE: {e}")
        return

    IE = _b.BilibiliSpaceListBaseIE
    if getattr(IE, "_bili_list_titles_patched", False):
        return

    def _get_entries(self, page_data, bvid_keys, ending_key="bvid"):
        paths = variadic(bvid_keys, (str, bytes, dict, set))
        by_bvid = {}
        for p in paths:
            if isinstance(p, str):
                p = (p,)
            if not isinstance(p, (tuple, list)):
                continue
            for node in traverse_obj(page_data, (*p, ..., {dict})) or []:
                b = node.get(ending_key)
                if isinstance(b, str):
                    by_bvid.setdefault(b, node)
        seen = set()
        for bvid in traverse_obj(
            page_data,
            (*paths, ..., ending_key, {str}),
        ):
            if bvid in seen:
                continue
            seen.add(bvid)
            r = self.url_result(
                f"https://www.bilibili.com/video/{bvid}", _b.BiliBiliIE, bvid
            )
            node = by_bvid.get(bvid)
            if node:
                if node.get("title"):
                    r["title"] = unescapeHTML(node["title"])
                cover = node.get("cover") or node.get("pic")
                if cover:
                    r["thumbnail"] = cover
            yield r

    IE._get_entries = _get_entries
    print("[PATCH] Đã áp dụng fix title/thumbnail cho list Bilibili (合集/series/fav)")


def patch_bilibili_anti_throttling():
    """Monkey-patch BiliBiliIE format parser to bypass CDN speed throttling and play-time limits.

    Rewrites low-speed P2P CDN URLs (mcdn.bilivideo.com) to high-speed mainland/global
    mirrors (upos-sz-staticacg.bilivideo.com), and enforces optimal headers.
    """
    try:
        from yt_dlp.extractor.bilibili import BiliBiliIE
    except Exception as e:
        print(f"[PATCH] Không tìm thấy BiliBiliIE: {e}")
        return

    original_extract = getattr(BiliBiliIE, "_real_extract", None)
    if original_extract is None or getattr(original_extract, "_bili_throttle_patched", False):
        return

    def _real_extract(self, url):
        import re
        res = original_extract(self, url)
        if isinstance(res, dict) and "formats" in res:
            # Xác định URL referer chuẩn của video này
            video_ref = res.get("webpage_url") or url or "https://www.bilibili.com/"
            for fmt in res.get("formats", []):
                fmt_url = fmt.get("url") or ""
                # Chuyển đổi CDN P2P (mcdn, gotcha) và Akamai throttled sang Tencent Cloud MirrorCOS (Cực ổn định, không drop socket)
                if any(k in fmt_url for k in ["akamaized.net", "mcdn.bilivideo.com", "mcdn.bilivideo.cn", "gotcha.bilivideo.com"]):
                    fmt["url"] = re.sub(r'https?://[^/]+/', 'https://upos-sz-mirrorcos.bilivideo.com/', fmt_url)
                # Đảm bảo gán đầy đủ HTTP Headers chống giới hạn tốc độ và bóp băng thông
                fmt_headers = fmt.setdefault("http_headers", {})
                fmt_headers["Referer"] = video_ref
                fmt_headers["Origin"] = "https://www.bilibili.com"
        return res

    _real_extract._bili_throttle_patched = True
    BiliBiliIE._real_extract = _real_extract
    print("[PATCH] Đã áp dụng fix bóp băng thông CDN Bilibili (Bypass Throttling -> Tencent Cloud Mirror)")

