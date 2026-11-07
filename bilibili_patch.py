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
    Đồng thời tự động Fallback trích xuất qua x/web-interface/wbi/view/detail khi Bilibili dùng
    giao diện web mới không nhúng window.__INITIAL_STATE__ trong mã nguồn HTML.
    """
    try:
        from yt_dlp.extractor.bilibili import BiliBiliIE
        from yt_dlp.utils import traverse_obj, int_or_none, parse_qs
    except Exception as e:
        print(f"[PATCH] Không tìm thấy BiliBiliIE: {e}")
        return

    original_extract = getattr(BiliBiliIE, "_real_extract", None)
    if original_extract is None or getattr(original_extract, "_bili_throttle_patched", False):
        return

    def _real_extract(self, url):
        import re
        try:
            res = original_extract(self, url)
        except Exception as e:
            if "Unable to extract initial state" not in str(e):
                raise
            # Bilibili giao diện mới không nhúng INITIAL_STATE trong HTML tĩnh
            print(f"[PATCH] Bilibili giao diện mới không có INITIAL_STATE ({url[:60]}), chuyển sang API view/detail...")
            video_id, prefix = self._match_valid_url(url).group("id", "prefix")
            headers = self.geo_verification_headers()
            headers.update({
                "Referer": "https://www.bilibili.com/",
                "Origin": "https://www.bilibili.com",
            })
            query = {"platform": "web"}
            p_upper = prefix.upper() if prefix else "BV"
            bvid = "BV" + video_id if p_upper == "BV" else video_id
            if p_upper == "BV":
                query["bvid"] = bvid
            else:
                query["aid"] = video_id

            detail = self._download_json(
                "https://api.bilibili.com/x/web-interface/wbi/view/detail", video_id,
                note="Downloading video detail info (API fallback)",
                query=self._sign_wbi(query, video_id), headers=headers)

            view_data = traverse_obj(detail, ("data", "View"))
            if not view_data:
                raise e

            card_data = traverse_obj(detail, ("data", "Card", "card")) or {}
            title = view_data.get("title")
            aid = view_data.get("aid")
            pages = view_data.get("pages") or []
            qs = parse_qs(url)
            p_param = int_or_none(qs.get("p", [None])[-1])

            if len(pages) > 1 and not p_param and getattr(self, "_yes_playlist", lambda *a: True)(video_id, video_id):
                entries = []
                for p in pages:
                    p_cid = p.get("cid")
                    p_num = p.get("page", 1)
                    p_title = f"{title} p{p_num:02d} {p.get('part', '')}".strip()
                    p_play = self._download_playinfo(bvid, p_cid, headers=headers)
                    p_fmts = self.extract_formats(p_play) if p_play else []
                    entries.append({
                        "id": f"{bvid}_p{p_num}",
                        "title": p_title,
                        "formats": p_fmts,
                        "duration": p.get("duration"),
                        "thumbnail": view_data.get("pic"),
                        "http_headers": {"Referer": url},
                    })
                res = self.playlist_result(entries, bvid, title)
            else:
                selected_page = pages[p_param - 1] if (p_param and p_param <= len(pages)) else (pages[0] if pages else {})
                cid = selected_page.get("cid") or view_data.get("cid")
                if p_param and len(pages) > 1:
                    title = f"{title} p{p_param:02d} {selected_page.get('part', '')}".strip()

                play_info = self._download_playinfo(bvid, cid, headers=headers)
                formats = self.extract_formats(play_info) if play_info else []
                subtitles = getattr(self, "_get_subtitles", lambda *a: {})(bvid, cid, aid)
                res = {
                    "id": bvid,
                    "title": title,
                    "formats": formats,
                    "subtitles": subtitles,
                    "thumbnail": view_data.get("pic"),
                    "description": view_data.get("desc"),
                    "duration": view_data.get("duration"),
                    "uploader": card_data.get("name"),
                    "uploader_id": str(card_data.get("mid", "")),
                    "view_count": traverse_obj(view_data, ("stat", "view")),
                    "like_count": traverse_obj(view_data, ("stat", "like")),
                    "http_headers": {"Referer": url},
                }

        # Áp dụng rewrite CDN chống bóp băng thông cho tất cả format
        def _patch_formats(fmts, ref_url):
            for fmt in fmts:
                fmt_url = fmt.get("url") or ""
                if any(k in fmt_url for k in ["akamaized.net", "mcdn.bilivideo.com", "mcdn.bilivideo.cn", "gotcha.bilivideo.com"]):
                    fmt["url"] = re.sub(r'https?://[^/]+/', 'https://upos-sz-mirrorcos.bilivideo.com/', fmt_url)
                fmt_headers = fmt.setdefault("http_headers", {})
                fmt_headers["Referer"] = ref_url
                fmt_headers["Origin"] = "https://www.bilibili.com"

        if isinstance(res, dict):
            video_ref = res.get("webpage_url") or url or "https://www.bilibili.com/"
            if "formats" in res:
                _patch_formats(res.get("formats", []), video_ref)
            elif "entries" in res:
                for entry in res.get("entries", []):
                    if isinstance(entry, dict) and "formats" in entry:
                        _patch_formats(entry.get("formats", []), video_ref)

        return res

    _real_extract._bili_throttle_patched = True
    BiliBiliIE._real_extract = _real_extract
    print("[PATCH] Đã áp dụng fix bóp băng thông CDN Bilibili (Bypass Throttling -> Tencent Cloud Mirror)")

