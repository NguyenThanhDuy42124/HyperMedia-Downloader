// HyperMedia Helper Pro - Page Context Interceptor
// Intercepts AJAX/Fetch API responses & SSR State on Douyin/TikTok to capture 100% direct CDN stream URLs (zjcdn.com, douyinvod.com)
(function() {
  function extractAweme(it) {
    if (!it || typeof it !== 'object') return null;
    const id = it.aweme_id || it.id;
    if (!id) return null;
    const desc = (it.desc || '').trim();

    let cover = '';
    if (it.video && it.video.cover && Array.isArray(it.video.cover.url_list) && it.video.cover.url_list.length > 0) {
      cover = it.video.cover.url_list[0];
    } else if (it.video && it.video.origin_cover && Array.isArray(it.video.origin_cover.url_list) && it.video.origin_cover.url_list.length > 0) {
      cover = it.video.origin_cover.url_list[0];
    }
    if (cover && cover.startsWith('//')) cover = 'https:' + cover;

    let streamUrl = '';
    // 1. Duyệt bit_rate (chọn bitrate cao nhất, tránh audio-only)
    if (it.video && Array.isArray(it.video.bit_rate) && it.video.bit_rate.length > 0) {
      const sorted = [...it.video.bit_rate].sort((a, b) => (b.bit_rate || 0) - (a.bit_rate || 0));
      for (const br of sorted) {
        if (br.play_addr && Array.isArray(br.play_addr.url_list) && br.play_addr.url_list.length > 0) {
          const ul = br.play_addr.url_list;
          const best = ul.find(u => (u.includes('zjcdn.com') || u.includes('douyinvod.com') || u.includes('/video/tos/')) && !u.includes('mime_type=audio') && !u.includes('media-audio'));
          if (best) {
            streamUrl = best;
            break;
          }
        }
      }
    }

    // 2. Fallback sang play_addr
    if (!streamUrl && it.video && it.video.play_addr && Array.isArray(it.video.play_addr.url_list)) {
      const ul = it.video.play_addr.url_list;
      streamUrl = ul.find(u => (u.includes('zjcdn.com') || u.includes('douyinvod.com') || u.includes('/video/tos/')) && !u.includes('mime_type=audio') && !u.includes('media-audio')) || ul[0] || '';
    }

    // 3. Fallback sang snssdk play theo vid
    if (!streamUrl && it.video && it.video.vid) {
      streamUrl = `https://aweme.snssdk.com/aweme/v1/play/?video_id=${it.video.vid}&ratio=1080p&line=0`;
    }

    if (streamUrl && streamUrl.startsWith('//')) streamUrl = 'https:' + streamUrl;

    return {
      id: String(id),
      desc: desc,
      cover: cover,
      streamUrl: streamUrl
    };
  }

  function emitAwemeData(data) {
    try {
      if (!data) return;
      let list = [];
      if (Array.isArray(data)) {
        list = data;
      } else if (Array.isArray(data.aweme_list)) {
        list = data.aweme_list;
      } else if (data.data && Array.isArray(data.data.aweme_list)) {
        list = data.data.aweme_list;
      } else if (Array.isArray(data.itemList)) {
        list = data.itemList;
      } else if (data.aweme_detail) {
        list = [data.aweme_detail];
      }

      if (list.length > 0) {
        const items = [];
        for (const it of list) {
          const item = extractAweme(it);
          if (item && item.id && item.streamUrl) {
            items.push(item);
          }
        }
        if (items.length > 0) {
          window.postMessage({ type: 'HM_DOUYIN_STREAM_BATCH', items: items }, '*');
        }
      }
    } catch (e) {}
  }

  // Quét ngay SSR State trên trang khi script được inject
  function scanInitialPageData() {
    try {
      const el = document.getElementById('__UNIVERSAL_DATA_FOR_REHYDRATION__') ||
                 document.getElementById('RENDER_DATA');
      if (el && el.textContent) {
        const raw = decodeURIComponent(el.textContent);
        const parsed = JSON.parse(raw);
        // Duyệt tìm aweme_list trong object lồng nhau
        function searchObj(obj, depth = 0) {
          if (!obj || depth > 8) return;
          if (Array.isArray(obj.aweme_list)) {
            emitAwemeData(obj.aweme_list);
          }
          if (obj.aweme_detail) {
            emitAwemeData([obj.aweme_detail]);
          }
          if (typeof obj === 'object') {
            for (const k of Object.keys(obj)) {
              if (typeof obj[k] === 'object' && obj[k] !== null) {
                searchObj(obj[k], depth + 1);
              }
            }
          }
        }
        searchObj(parsed);
      }
    } catch (e) {}
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', scanInitialPageData);
  } else {
    setTimeout(scanInitialPageData, 200);
  }

  // 1. Intercept window.fetch
  const origFetch = window.fetch;
  window.fetch = async function(...args) {
    const res = await origFetch.apply(this, args);
    try {
      const u = typeof args[0] === 'string' ? args[0] : (args[0] && args[0].url ? args[0].url : '');
      if (u.includes('aweme') || u.includes('web/aweme') || u.includes('feed') || u.includes('post') || u.includes('item_list')) {
        const clone = res.clone();
        clone.json().then(emitAwemeData).catch(() => {});
      }
    } catch (e) {}
    return res;
  };

  // 2. Intercept XMLHttpRequest
  const origOpen = XMLHttpRequest.prototype.open;
  const origSend = XMLHttpRequest.prototype.send;
  XMLHttpRequest.prototype.open = function(method, url, ...rest) {
    this.__hmUrl = url;
    return origOpen.call(this, method, url, ...rest);
  };
  XMLHttpRequest.prototype.send = function(...args) {
    this.addEventListener('load', function() {
      try {
        if (this.__hmUrl && (this.__hmUrl.includes('aweme') || this.__hmUrl.includes('web/aweme') || this.__hmUrl.includes('feed') || this.__hmUrl.includes('post') || this.__hmUrl.includes('item_list'))) {
          const d = JSON.parse(this.responseText);
          emitAwemeData(d);
        }
      } catch (e) {}
    });
    return origSend.apply(this, args);
  };
})();
