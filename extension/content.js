// Content Script - HyperMedia Helper Pro with Humanized Randomization Engine
(function() {
  let isScanning = false;
  let stopRequested = false;

  // 1. Inject interceptor.js vào Page Context nếu chưa có
  function ensureInterceptorInjected() {
    if (!document.getElementById('hm-interceptor-script')) {
      try {
        const s = document.createElement('script');
        s.id = 'hm-interceptor-script';
        s.src = chrome.runtime.getURL('interceptor.js');
        s.onload = function() { this.remove(); };
        (document.head || document.documentElement).appendChild(s);
      } catch (e) {}
    }
  }
  ensureInterceptorInjected();

  // 2. Bộ nhớ lưu trữ stream CDN được chặn từ API AJAX/Fetch (/aweme/v1/web/aweme/post/, detail...)
  const interceptedStreamMap = new Map();
  window.addEventListener('message', (event) => {
    if (event.source !== window) return;
    if (event.data && event.data.type === 'HM_DOUYIN_STREAM_BATCH' && Array.isArray(event.data.items)) {
      for (const item of event.data.items) {
        if (item && item.id) {
          interceptedStreamMap.set(String(item.id), item);
        }
      }
    }
  });

  // Trích xuất toàn bộ thông tin video đang active / modal đang mở (Đặc biệt xử lý chính xác trang Profile tác giả)
  function getActiveVideoData() {
    const pageUrl = window.location.href;
    let awemeId = null;

    // 1. Kiểm tra URL xem có modal_id hoặc vid hoặc video ID không
    const modalMatch = pageUrl.match(/[?&]modal_id=(\d+)/) ||
                       pageUrl.match(/[?&]vid=(\d+)/) ||
                       pageUrl.match(/[?&]video_id=(\d+)/);
    if (modalMatch) {
      awemeId = modalMatch[1];
    } else {
      const vidMatch = pageUrl.match(/\/video\/(\d+)/);
      if (vidMatch) {
        awemeId = vidMatch[1];
      }
    }

    // 2. Tìm container modal nếu có (khi người dùng click xem video trên trang Profile / Kênh)
    const modalSelectors = [
      '[data-e2e="modal-container"]',
      '.modal-container',
      '[data-e2e="user-modal"]',
      '.video-detail-container',
      'div[id^="slider-video"]',
      '[data-e2e="feed-active-video"]',
      '.swiper-slide-active'
    ];
    let modalEl = null;
    for (const sel of modalSelectors) {
      const el = document.querySelector(sel);
      if (el && (el.offsetWidth > 0 || el.offsetHeight > 0 || el.getClientRects().length > 0)) {
        modalEl = el;
        break;
      }
    }

    // Nếu chưa có awemeId từ URL, thử tìm trong modalEl
    if (!awemeId && modalEl) {
      const linkEl = modalEl.querySelector('a[href*="/video/"]') || modalEl.querySelector('a[href*="modal_id="]');
      if (linkEl) {
        const h = linkEl.getAttribute('href') || linkEl.href || '';
        const m = h.match(/\/video\/(\d+)/) || h.match(/[?&]modal_id=(\d+)/);
        if (m) awemeId = m[1];
      }
    }

    // 3. Trích xuất Tiêu Đề
    let title = '';
    // Nếu có modal, BẮT BUỘC ưu tiên tìm tiêu đề BÊN TRONG modal container
    if (modalEl) {
      const titleCandidates = modalEl.querySelectorAll(
        '[data-e2e="detail-video-title"], [data-e2e="video-desc"], .video-info-detail, .title-wrapper, .video-desc, .account-video-detail, h1'
      );
      for (const el of titleCandidates) {
        const txt = (el.innerText || '').trim();
        if (txt && !txt.includes('关注') && !txt.includes('Follow') && txt.length > 1) {
          title = txt;
          break;
        }
      }
    }

    // 4. Trích xuất Dữ liệu Hydrate SSR Douyin theo awemeId nếu có
    let rehydrateData = null;
    if (awemeId) {
      try {
        const reEl = document.getElementById('__UNIVERSAL_DATA_FOR_REHYDRATION__') ||
                     document.getElementById('RENDER_DATA');
        if (reEl && reEl.textContent) {
          const raw = decodeURIComponent(reEl.textContent);
          if (raw.includes(awemeId)) {
            // Cắt đoạn JSON xung quanh awemeId để lấy chính xác thông tin tập này
            const pos = raw.indexOf(awemeId);
            const start = Math.max(0, pos - 500);
            const end = Math.min(raw.length, pos + 4000);
            const chunk = raw.substring(start, end);

            // Tiêu đề từ chunk
            if (!title) {
              const tm = chunk.match(/"desc"\s*:\s*"([^"\\]*(?:\\.[^"\\]*)*)"/);
              if (tm) {
                try { title = JSON.parse(`"${tm[1]}"`); } catch (e) { title = tm[1]; }
              }
            }

            // Thumbnail từ chunk
            let chunkThumb = '';
            const cm = chunk.match(/"(?:cover|origin_cover)"\s*:\s*\{[^}]*"url_list"\s*:\s*\[\s*"([^"]+)"/);
            if (cm) {
              chunkThumb = cm[1].replace(/\\u002F/g, '/').replace(/\\/g, '');
            } else {
              const im = chunk.match(/https?:\\\/\\\/[^\s"'<>\\]*(?:douyinpic\.com|byteimg\.com)[^\s"'<>\\]*/i);
              if (im) chunkThumb = im[0].replace(/\\u002F/g, '/').replace(/\\/g, '');
            }

            // Stream URL từ chunk (TOS key v0... hoặc CDN douyinvod)
            let chunkStream = '';
            const vm = chunk.match(/(v0[0-9a-zA-Z]{15,})/);
            if (vm) {
              chunkStream = `https://aweme.snssdk.com/aweme/v1/play/?video_id=${vm[1]}&ratio=1080p&line=0`;
            } else {
              const dm = chunk.match(/https?:\\\/\\\/[^\s"'<>\\]*douyinvod\.com[^\s"'<>\\]*/i);
              if (dm) chunkStream = dm[0].replace(/\\u002F/g, '/').replace(/\\/g, '');
            }

            rehydrateData = { title, thumb: chunkThumb, streamUrl: chunkStream };
          }
        }
      } catch (e) {}
    }

    // 5. Nếu chưa có tiêu đề, tìm trên toàn trang (chỉ khi không có modal)
    if (!title && !modalEl) {
      const epTitleEl = document.querySelector('[data-e2e="detail-video-title"]') ||
                        document.querySelector('[data-e2e="video-desc"]') ||
                        document.querySelector('.video-info-detail') ||
                        document.querySelector('.title-wrapper') ||
                        document.querySelector('.video-desc') ||
                        document.querySelector('h1');
      if (epTitleEl && epTitleEl.innerText && epTitleEl.innerText.trim()) {
        title = epTitleEl.innerText.trim();
      }
    }

    // Xử lý tuyển tập / series
    const mixEl = (modalEl ? modalEl.querySelector('.mix-title, [data-e2e="series-title"], .collection-title') : null) ||
                  document.querySelector('.mix-title') ||
                  document.querySelector('[data-e2e="series-title"]') ||
                  document.querySelector('.collection-title');
    if (mixEl && mixEl.innerText && mixEl.innerText.trim()) {
      const mixText = mixEl.innerText.trim();
      if (!title) {
        title = mixText;
      } else if (!title.includes(mixText)) {
        title = `${mixText} - ${title}`;
      }
    }

    if (!title && !pageUrl.includes('/user/')) {
      title = document.title || '';
    }
    if (!title && awemeId) {
      title = `Douyin Video ${awemeId}`;
    }

    // Làm sạch tiêu đề
    title = (title || '')
      .replace(/\s*[-_]\s*抖音.*$/i, '')
      .replace(/_哔哩哔哩.*$/i, '')
      .replace(/\s*-\s*YouTube.*$/i, '')
      .replace(/\s*\|\s*TikTok.*$/i, '')
      .replace(/[\r\n\t]+/g, ' ')
      .trim();

    // 6. Trích xuất Thumbnail
    let thumb = (rehydrateData && rehydrateData.thumb) ? rehydrateData.thumb : '';

    // Tìm trong modalEl trước
    const targetVideo = (modalEl ? modalEl.querySelector('video') : null) || document.querySelector('video');

    if (!thumb && targetVideo && targetVideo.poster && targetVideo.poster.startsWith('http')) {
      thumb = targetVideo.poster;
    }

    if (!thumb && modalEl) {
      const xgPoster = modalEl.querySelector('.xgplayer-poster');
      if (xgPoster && xgPoster.style && xgPoster.style.backgroundImage) {
        const bgm = xgPoster.style.backgroundImage.match(/url\(["']?(https?:\/\/[^"')]+)["']?\)/);
        if (bgm && bgm[1].startsWith('http')) thumb = bgm[1];
      }

      if (!thumb) {
        const imgs = modalEl.querySelectorAll('img');
        for (const img of imgs) {
          const src = img.src || '';
          if (!src || !src.startsWith('http')) continue;
          const isAvatar = (
            src.includes('avatar') || src.includes('user-avatar') || src.includes('100x100') ||
            img.closest('[data-e2e="user-avatar"]') || img.closest('.author-avatar') || img.closest('.avatar')
          );
          if (isAvatar) continue;
          const w = img.naturalWidth || img.width || img.clientWidth || 0;
          const h = img.naturalHeight || img.height || img.clientHeight || 0;
          if (w > 0 && w < 150 && h > 0 && h < 150) continue;
          thumb = src;
          break;
        }
      }
    }

    // Fallback: Chụp Canvas từ targetVideo (nếu video đang phát trong modal hoặc trên trang)
    if (!thumb && targetVideo && targetVideo.videoWidth > 50 && targetVideo.videoHeight > 50) {
      try {
        const canvas = document.createElement('canvas');
        canvas.width = 320;
        canvas.height = Math.round(320 * (targetVideo.videoHeight / targetVideo.videoWidth));
        const ctx = canvas.getContext('2d');
        ctx.drawImage(targetVideo, 0, 0, canvas.width, canvas.height);
        const dataUrl = canvas.toDataURL('image/jpeg', 0.85);
        if (dataUrl && dataUrl.startsWith('data:image')) {
          thumb = dataUrl;
        }
      } catch (e) {}
    }

    // 7. Trích xuất Stream URL hoặc Link Video
    let videoUrl = '';
    // A0. Ưu tiên số 1: Dữ liệu stream trực tiếp từ Interceptor API
    if (awemeId && interceptedStreamMap.has(awemeId)) {
      const it = interceptedStreamMap.get(awemeId);
      if (!title && it.desc) title = it.desc;
      if (!thumb && it.cover) thumb = it.cover;
      if (it.streamUrl) videoUrl = it.streamUrl;
    }

    // A. Nếu có stream URL từ SSR chunk của đúng awemeId
    if (!videoUrl && rehydrateData && rehydrateData.streamUrl) {
      videoUrl = rehydrateData.streamUrl;
    }

    // B. Kiểm tra thẻ targetVideo (nếu không phải blob)
    if (!videoUrl && targetVideo) {
      if (targetVideo.src && targetVideo.src.startsWith('http') && !targetVideo.src.startsWith('blob:')) {
        videoUrl = targetVideo.src;
      } else if (targetVideo.currentSrc && targetVideo.currentSrc.startsWith('http') && !targetVideo.currentSrc.startsWith('blob:')) {
        videoUrl = targetVideo.currentSrc;
      }
    }

    // C. Tìm từ window.performance resource timing (lấy chunk tải gần nhất)
    if (!videoUrl) {
      try {
        const perfEntries = performance.getEntriesByType('resource');
        for (let i = perfEntries.length - 1; i >= 0; i--) {
          const name = perfEntries[i].name || '';
          if (name.includes('media-audio') || name.includes('-audio-') || name.includes('audio_mp4')) continue;
          if (name && (name.includes('douyinvod.com') || name.includes('zjcdn.com') || name.includes('/video/tos/')) && !name.includes('.m3u8')) {
            const vm = name.match(/(v0[0-9a-zA-Z]{15,})/);
            if (vm) {
              videoUrl = `https://aweme.snssdk.com/aweme/v1/play/?video_id=${vm[1]}&ratio=1080p&line=0`;
            } else {
              videoUrl = name;
            }
            break;
          }
        }
      } catch (e) {}
    }

    // D. Nếu vẫn chưa có stream trực tiếp, trả về link video chính xác theo awemeId
    if (!videoUrl) {
      if (awemeId) {
        videoUrl = `https://www.douyin.com/video/${awemeId}`;
      } else {
        videoUrl = pageUrl;
      }
    }

    return {
      url: videoUrl,
      title: title,
      thumb: thumb,
      awemeId: awemeId,
      hasModal: !!modalEl
    };
  }

  function getPageVideoMetadata() {
    const data = getActiveVideoData();
    return { title: data.title, thumb: data.thumb };
  }

  // 1. Tạo Thanh Điều Khiển Nổi Trực Tiếp Trên Trang
  function createFloatingControls() {
    const host = (window.location.hostname || '').toLowerCase();
    const isMedia = host.includes('douyin.com') || host.includes('tiktok.com') || host.includes('bilibili.com') || host.includes('youtube.com');
    if (!isMedia) return;
    if (document.getElementById('hm-floating-container')) return;

    const container = document.createElement('div');
    container.id = 'hm-floating-container';
    container.innerHTML = `
      <div class="hm-bar-card">
        <div class="hm-brand-badge">
          <span class="hm-icon-svg"><svg viewBox="0 0 24 24"><polygon points="6 3 20 12 6 21 6 3"/></svg></span>
          <span>HyperMedia</span>
        </div>
        <button id="hm-btn-single" class="hm-btn-pill hm-btn-cyan" title="Sao chép link video hiện tại">
          <span class="hm-icon-svg"><svg viewBox="0 0 24 24"><rect width="14" height="14" x="8" y="8" rx="2" ry="2"/><path d="M4 16c-1.1 0-2-.9-2-2V4c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2"/></svg></span>
          <span>Copy Link</span>
        </button>
        <button id="hm-btn-send-app" class="hm-btn-pill hm-btn-purple" title="Gửi link trực tiếp sang HyperMedia Downloader Desktop">
          <span class="hm-icon-svg"><svg viewBox="0 0 24 24"><path d="m22 2-7 20-4-9-9-4Z"/><path d="M22 2 11 13"/></svg></span>
          <span>Gửi Vào App</span>
        </button>
        <div class="hm-divider"></div>
        <span class="hm-label">Quét Profile:</span>
        <button id="hm-btn-20" class="hm-btn-pill" title="Tự động cuộn lấy 20 video mới nhất">20</button>
        <button id="hm-btn-50" class="hm-btn-pill" title="Tự động cuộn lấy 50 video mới nhất">50</button>
        <button id="hm-btn-all" class="hm-btn-pill hm-btn-green" title="Tự động cuộn đến hết trang">
          <span class="hm-icon-svg"><svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="10"/><path d="M12 2a14.5 14.5 0 0 0 0 20 14.5 14.5 0 0 0 0-20"/><path d="M2 12h20"/></svg></span>
          <span>Hết Trang</span>
        </button>
        <button id="hm-btn-close" class="hm-btn-close" title="Ẩn thanh công cụ (Bật lại trong icon Extension)">
          <span class="hm-icon-svg" style="width:12px;height:12px;"><svg viewBox="0 0 24 24"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg></span>
        </button>
      </div>
      <div id="hm-progress-banner" class="hm-banner" style="display:none;">
        <span id="hm-progress-text">Đang cuộn ngẫu nhiên như người thật...</span>
        <button id="hm-btn-stop" class="hm-btn-stop" style="display:inline-flex;align-items:center;gap:4px;">
          <span class="hm-icon-svg" style="width:11px;height:11px;"><svg viewBox="0 0 24 24"><rect width="18" height="18" x="3" y="3" rx="2"/></svg></span>
          <span>Dừng</span>
        </button>
      </div>
    `;

    document.body.appendChild(container);

    // Kiểm tra cài đặt hiển thị từ storage
    chrome.storage.local.get({ showFloatingBar: true }, (res) => {
      container.style.display = res.showFloatingBar ? 'flex' : 'none';
    });

    // Gắn sự kiện
    document.getElementById('hm-btn-single').addEventListener('click', () => copyCurrentVideoLink());
    document.getElementById('hm-btn-send-app').addEventListener('click', () => {
      const data = getActiveVideoData();
      if (!data || !data.url) {
        showToast('Không tìm thấy link video trên trang này!');
        return;
      }
      if (window.location.href.includes('/user/') && !data.hasModal && !data.awemeId) {
        showToast('Hãy bấm mở xem 1 video trước khi Gửi Vào App!');
        return;
      }
      showToast('Đang gửi video sang Desktop App...');
      chrome.runtime.sendMessage({
        action: 'SEND_TO_APP',
        url: data.url,
        title: data.title,
        thumb: data.thumb
      }, (response) => {
        if (response && response.success) {
          showToast(`Đã gửi "${data.title ? data.title.substring(0, 20) + '...' : 'video'}" vào App!`);
        } else {
          showToast(response && response.error ? response.error : 'Chưa mở Desktop App! Hãy khởi động HyperMedia trước.');
        }
      });
    });
    document.getElementById('hm-btn-20').addEventListener('click', () => scanProfileVideos(20, true));
    document.getElementById('hm-btn-50').addEventListener('click', () => scanProfileVideos(50, true));
    document.getElementById('hm-btn-all').addEventListener('click', () => scanProfileVideos(0, true));
    document.getElementById('hm-btn-stop').addEventListener('click', () => {
      stopRequested = true;
      isScanning = false;
    });
    document.getElementById('hm-btn-close').addEventListener('click', () => {
      container.style.display = 'none';
      chrome.storage.local.set({ showFloatingBar: false });
      showToast('Đã ẩn thanh công cụ. Bật lại trong icon Extension bất cứ lúc nào!');
    });
  }

  // 2. Trích xuất link video đơn hiện tại
  function getCurrentVideoUrl() {
    const data = getActiveVideoData();
    return data ? data.url : window.location.href;
  }

  // 3. Sao chép link và hiện Toast thông báo
  async function copyCurrentVideoLink() {
    const data = getActiveVideoData();
    if (!data || !data.url) {
      showToast('Không tìm thấy link video!');
      return;
    }
    if (window.location.href.includes('/user/') && !data.hasModal && !data.awemeId) {
      showToast('Hãy bấm mở xem 1 video trước khi Copy Link!');
      return;
    }
    const videoUrl = data.url;
    try {
      await navigator.clipboard.writeText(videoUrl);
      showToast(`Đã copy link: ${videoUrl.substring(0, 48)}...`);
    } catch (err) {
      const inp = document.createElement('textarea');
      inp.value = videoUrl;
      document.body.appendChild(inp);
      inp.select();
      document.execCommand('copy');
      document.body.removeChild(inp);
      showToast('Đã copy link video!');
    }
  }

  // 4. Toast Thông Báo
  function showToast(text) {
    let toast = document.getElementById('hm-toast');
    if (!toast) {
      toast = document.createElement('div');
      toast.id = 'hm-toast';
      document.body.appendChild(toast);
    }
    toast.innerText = text;
    toast.className = 'hm-toast-show';
    setTimeout(() => {
      toast.className = toast.className.replace('hm-toast-show', '');
    }, 2800);
  }

  // 5. Bộ nhớ đệm SSR Hydrate Data của trang (Douyin / TikTok)
  let ssrAwemeMap = null;

  function parseSsrData() {
    if (ssrAwemeMap) return ssrAwemeMap;
    ssrAwemeMap = new Map();
    try {
      const el = document.getElementById('__UNIVERSAL_DATA_FOR_REHYDRATION__') ||
                 document.getElementById('RENDER_DATA');
      if (el && el.textContent) {
        const raw = decodeURIComponent(el.textContent);
        const regex = /"aweme_id"\s*:\s*"(\d+)"/g;
        let match;
        while ((match = regex.exec(raw)) !== null) {
          const id = match[1];
          if (ssrAwemeMap.has(id)) continue;
          const pos = match.index;
          const chunk = raw.substring(Math.max(0, pos - 200), Math.min(raw.length, pos + 3500));

          let desc = '';
          const tm = chunk.match(/"desc"\s*:\s*"([^"\\]*(?:\\.[^"\\]*)*)"/);
          if (tm) {
            try { desc = JSON.parse(`"${tm[1]}"`); } catch(e) { desc = tm[1]; }
          }

          let cover = '';
          const cm = chunk.match(/"(?:cover|origin_cover)"\s*:\s*\{[^}]*"url_list"\s*:\s*\[\s*"([^"]+)"/);
          if (cm) {
            cover = cm[1].replace(/\\u002F/g, '/').replace(/\\/g, '');
          } else {
            const anyImg = chunk.match(/https?:\\\/\\\/[^\s"'<>\\]*(?:douyinpic\.com|byteimg\.com)[^\s"'<>\\]*/i);
            if (anyImg) cover = anyImg[0].replace(/\\u002F/g, '/').replace(/\\/g, '');
          }

          let streamUrl = '';
          const zm = chunk.match(/https?:\\\/\\\/[^\s"'<>\\]*(?:zjcdn\.com|douyinvod\.com)[^\s"'<>\\]*/i);
          const vm = chunk.match(/(v0[0-9a-zA-Z]{15,})/);
          if (zm) {
            streamUrl = zm[0].replace(/\\u002F/g, '/').replace(/\\/g, '');
          } else if (vm) {
            streamUrl = `https://aweme.snssdk.com/aweme/v1/play/?video_id=${vm[1]}&ratio=1080p&line=0`;
          }

          ssrAwemeMap.set(id, { desc, cover, streamUrl });
        }
      }
    } catch (e) {}
    return ssrAwemeMap;
  }

  // 6. Thu thập video hiện tại trên DOM kèm đầy đủ Tiêu Đề và Thumbnail
  function collectCurrentItems(itemMap) {
    const ssrMap = parseSsrData();

    // Hỗ trợ tất cả các dạng selector card trên Douyin, Bilibili, YouTube, TikTok
    const selectors = [
      'a[href*="/video/"]',
      'a[href*="modal_id="]',
      'a[href*="vid="]',
      '[data-e2e="user-post-item"]',
      '[data-e2e="scroll-list"] > div',
      'ul[class*="post"] > li',
      'a[href*="/watch?v="]',
      'a[href*="/shorts/"]'
    ];
    const elements = document.querySelectorAll(selectors.join(', '));

    elements.forEach(el => {
      let href = el.getAttribute('href') || el.href || '';
      if (!href) {
        const subA = el.querySelector('a[href*="/video/"], a[href*="modal_id="], a[href*="vid="], a[href*="/watch?v="], a[href*="/shorts/"]');
        if (subA) href = subA.getAttribute('href') || subA.href || '';
      }
      if (!href) return;

      let canonicalUrl = '';
      let awemeId = '';

      // === DOUYIN / TIKTOK ===
      if (href.includes('douyin.com') || (!href.includes('http') && (href.includes('/video/') || href.includes('modal_id=') || href.includes('vid=')))) {
        const m = href.match(/\/video\/(\d+)/) || href.match(/[?&]modal_id=(\d+)/) || href.match(/[?&]vid=(\d+)/);
        if (m) {
          awemeId = m[1];
          canonicalUrl = `https://www.douyin.com/video/${m[1]}`;
        }
      } else if (href.includes('tiktok.com')) {
        const m = href.match(/\/video\/(\d+)/);
        if (m) {
          awemeId = m[1];
          canonicalUrl = `https://www.tiktok.com/@user/video/${m[1]}`;
        }
      }
      // === BILIBILI ===
      else if (href.includes('bilibili.com') || href.includes('/video/BV')) {
        const m = href.match(/\/video\/(BV[a-zA-Z0-9]+)/);
        if (m) canonicalUrl = `https://www.bilibili.com/video/${m[1]}`;
      }
      // === YOUTUBE ===
      else if (href.includes('youtube.com') || href.includes('/watch?v=') || href.includes('/shorts/')) {
        if (href.includes('watch?v=')) canonicalUrl = href.split('&')[0];
        else if (href.includes('/shorts/')) canonicalUrl = href.split('?')[0];
      }

      if (!canonicalUrl) return;

      // Tìm container của card để trích xuất Title và Thumbnail
      const cardEl = el.closest('[data-e2e="user-post-item"]') ||
                     el.closest('li') ||
                     el.closest('ytd-rich-item-renderer, ytd-grid-video-renderer') ||
                     el.closest('.bili-video-card') ||
                     el;

      // A. Trích xuất Title, Thumb, StreamUrl
      let title = '';
      let thumb = '';
      let streamUrl = '';

      // 1. Ưu tiên số 1: Dữ liệu bắt trực tiếp từ AJAX/Fetch API qua interceptor
      if (awemeId && interceptedStreamMap.has(awemeId)) {
        const it = interceptedStreamMap.get(awemeId);
        if (it.desc) title = it.desc;
        if (it.cover) thumb = it.cover;
        if (it.streamUrl) streamUrl = it.streamUrl;
      }

      // 2. Ưu tiên số 2: SSR Data
      if (awemeId && ssrMap && ssrMap.has(awemeId)) {
        const s = ssrMap.get(awemeId);
        if (!title && s.desc) title = s.desc;
        if (!thumb && s.cover) thumb = s.cover;
        if (!streamUrl && s.streamUrl) streamUrl = s.streamUrl;
      }

      if (!title) {
        const img = cardEl.querySelector('img') || (cardEl.tagName === 'IMG' ? cardEl : null);
        if (img && img.alt && img.alt.trim().length > 1 && !img.alt.includes('avatar') && !img.alt.includes('头像')) {
          title = img.alt.trim();
        }
      }
      if (!title && cardEl.getAttribute('title')) {
        title = cardEl.getAttribute('title').trim();
      }
      if (!title) {
        const textCandidates = cardEl.querySelectorAll('p, [class*="desc"], [class*="title"], [data-e2e*="desc"], span');
        for (const te of textCandidates) {
          const txt = (te.innerText || '').trim();
          if (txt && txt.length > 2 && !txt.match(/^[\d\.\s,wkwk]+$/i) && !txt.includes('置顶') && !txt.includes('关注')) {
            title = txt;
            break;
          }
        }
      }

      // Làm sạch tiêu đề
      title = (title || '')
        .replace(/\s*[-_]\s*抖音.*$/i, '')
        .replace(/_哔哩哔哩.*$/i, '')
        .replace(/\s*-\s*YouTube.*$/i, '')
        .replace(/\s*\|\s*TikTok.*$/i, '')
        .replace(/[\r\n\t]+/g, ' ')
        .trim();

      // B. Trích xuất Thumbnail nếu chưa có
      if (!thumb) {
        const imgs = cardEl.querySelectorAll('img');
        for (const img of imgs) {
          const src = img.src || img.getAttribute('data-src') || (img.getAttribute('srcset') ? img.getAttribute('srcset').split(' ')[0] : '') || '';
          if (!src || !src.startsWith('http')) continue;
          const isAvatar = (
            src.includes('avatar') || src.includes('user-avatar') || src.includes('100x100') ||
            img.closest('[data-e2e="user-avatar"]') || img.closest('.author-avatar') || img.closest('.avatar')
          );
          if (isAvatar) continue;
          const w = img.naturalWidth || img.width || img.clientWidth || 0;
          const h = img.naturalHeight || img.height || img.clientHeight || 0;
          if (w > 0 && w < 80 && h > 0 && h < 80) continue;
          thumb = src;
          break;
        }
      }

      const targetUrl = streamUrl || canonicalUrl;

      if (!itemMap.has(canonicalUrl)) {
        itemMap.set(canonicalUrl, {
          url: targetUrl,
          canonicalUrl: canonicalUrl,
          title: title || (awemeId ? `Douyin Video ${awemeId}` : ''),
          thumb: thumb,
          awemeId: awemeId
        });
      } else {
        const existing = itemMap.get(canonicalUrl);
        if (streamUrl && (!existing.url || existing.url.includes('douyin.com/video/') || existing.url.includes('tiktok.com/@'))) {
          existing.url = streamUrl;
        }
        if (!existing.title && title) existing.title = title;
        if (!existing.thumb && thumb) existing.thumb = thumb;
      }
    });
  }

  // 7. Động cơ Auto-Scroll với cơ chế Randomize như Người Thật (Chống Bot 100%)
  async function scanProfileVideos(limit, randomize = true) {
    if (isScanning) return { links: [], items: [] };
    isScanning = true;
    stopRequested = false;

    const banner = document.getElementById('hm-progress-banner');
    if (banner) {
      banner.style.display = 'flex';
      banner.innerHTML = `
        <span id="hm-progress-text">Đang chuẩn bị cuộn...</span>
        <button id="hm-btn-stop" class="hm-btn-stop" style="display:inline-flex;align-items:center;gap:4px;">
          <span class="hm-icon-svg" style="width:11px;height:11px;"><svg viewBox="0 0 24 24"><rect width="18" height="18" x="3" y="3" rx="2"/></svg></span>
          <span>Dừng</span>
        </button>
      `;
      document.getElementById('hm-btn-stop').addEventListener('click', () => {
        stopRequested = true;
        isScanning = false;
      });
    }

    let itemMap = new Map();
    collectCurrentItems(itemMap);

    let noNewCount = 0;
    let maxRetries = 25;
    let scrollCount = 0;

    showToast(`Bắt đầu cuộn ${randomize ? 'Random Người Thật' : 'Tự Động'} quét ${limit === 0 ? 'toàn bộ' : limit} video...`);

    while (!stopRequested) {
      collectCurrentItems(itemMap);
      const count = itemMap.size;
      scrollCount++;

      const pText = document.getElementById('hm-progress-text');
      if (pText) {
        pText.innerText = `Đang cuộn (${randomize ? 'Random' : 'Chuẩn'}): Đã lấy ${count} ${limit > 0 ? '/ ' + limit : ''} video...`;
      }

      chrome.runtime.sendMessage({
        action: 'BATCH_PROGRESS',
        count: count,
        links: Array.from(itemMap.values()).map(x => x.url || x.canonicalUrl),
        items: Array.from(itemMap.values())
      }).catch(() => {});

      if (limit > 0 && count >= limit) {
        break;
      }

      // THUẬT TOÁN RANDOMIZE BIÊN ĐỘ CUỘN & ĐỘ TRỄ:
      let scrollStep;
      let delayMs;

      if (randomize) {
        scrollStep = 550 + Math.floor(Math.random() * 600);
        if (Math.random() < 0.15 && scrollCount > 2) {
          const backStep = 60 + Math.floor(Math.random() * 60);
          window.scrollBy({ top: -backStep, behavior: 'smooth' });
          await new Promise(r => setTimeout(r, 200 + Math.floor(Math.random() * 200)));
        }
        delayMs = 550 + Math.floor(Math.random() * 550);
        if (scrollCount % 6 === 0) {
          delayMs += 1000 + Math.floor(Math.random() * 1000);
        }
      } else {
        scrollStep = 1000;
        delayMs = 700;
      }

      window.scrollBy({ top: scrollStep, behavior: 'smooth' });
      await new Promise(r => setTimeout(r, delayMs));

      const afterCount = itemMap.size;
      collectCurrentItems(itemMap);

      if (itemMap.size === afterCount) {
        noNewCount++;
        if (noNewCount >= maxRetries) {
          break; // Đã tới tận đáy trang
        }
      } else {
        noNewCount = 0;
      }
    }

    isScanning = false;

    let finalItems = Array.from(itemMap.values());
    if (limit > 0 && finalItems.length > limit) {
      finalItems = finalItems.slice(0, limit);
    }

    const links = finalItems.map(x => x.url || x.canonicalUrl);
    const text = links.join('\n');

    try {
      await navigator.clipboard.writeText(text);
    } catch (e) {
      const inp = document.createElement('textarea');
      inp.value = text;
      document.body.appendChild(inp);
      inp.select();
      document.execCommand('copy');
      document.body.removeChild(inp);
    }

    // Hiển thị Banner kết quả trực tiếp trên trang với nút "Gửi Vào App"
    if (banner) {
      banner.style.display = 'flex';
      banner.innerHTML = `
        <span style="color:#00E676;font-weight:600;display:inline-flex;align-items:center;gap:4px;">
          <svg style="width:14px;height:14px;stroke:#00E676;fill:none;stroke-width:2.5" viewBox="0 0 24 24"><polyline points="20 6 9 17 4 12"/></svg>
          Đã quét ${finalItems.length} video (Đủ Tên & Thumb)!
        </span>
        <button id="hm-btn-banner-send-app" class="hm-btn-pill hm-btn-purple" style="font-weight:600;box-shadow:0 2px 8px rgba(124,58,237,0.4);" title="Gửi toàn bộ ${finalItems.length} video (kèm Tên + Thumb) sang Desktop App">
          <span class="hm-icon-svg" style="width:12px;height:12px;"><svg viewBox="0 0 24 24"><path d="m22 2-7 20-4-9-9-4Z"/><path d="M22 2 11 13"/></svg></span>
          <span>Gửi Vào App (${finalItems.length})</span>
        </button>
        <button id="hm-btn-banner-copy" class="hm-btn-pill hm-btn-cyan" title="Copy link vào Clipboard">Copy Link</button>
        <button id="hm-btn-banner-close" class="hm-btn-close" title="Đóng">
          <span class="hm-icon-svg" style="width:12px;height:12px;"><svg viewBox="0 0 24 24"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg></span>
        </button>
      `;

      document.getElementById('hm-btn-banner-send-app').addEventListener('click', () => {
        showToast(`Đang gửi ${finalItems.length} video sang Desktop App...`);
        chrome.runtime.sendMessage({
          action: 'SEND_TO_APP',
          urls: finalItems.map(x => x.url),
          items: finalItems
        }, (res) => {
          if (res && res.success) {
            showToast(`Đã gửi thành công ${finalItems.length} video vào App!`);
            banner.style.display = 'none';
          } else {
            showToast(res && res.error ? res.error : 'Chưa mở Desktop App! Hãy khởi động HyperMedia trước.');
          }
        });
      });

      document.getElementById('hm-btn-banner-copy').addEventListener('click', () => {
        navigator.clipboard.writeText(text);
        showToast(`Đã copy ${finalItems.length} link vào Clipboard!`);
      });

      document.getElementById('hm-btn-banner-close').addEventListener('click', () => {
        banner.style.display = 'none';
      });
    }

    chrome.runtime.sendMessage({
      action: 'BATCH_DONE',
      links: links,
      items: finalItems
    }).catch(() => {});

    showToast(`Đã quét xong & Copy ${finalItems.length} video vào Clipboard!`);
    return { links, items: finalItems };
  }

  // Lắng nghe Message từ Extension Popup
  chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
    if (msg.action === 'GET_SINGLE_VIDEO') {
      const data = getActiveVideoData();
      sendResponse({
        url: data.url,
        title: data.title,
        thumb: data.thumb,
        hasModal: data.hasModal,
        awemeId: data.awemeId
      });
    } else if (msg.action === 'START_BATCH_SCAN') {
      scanProfileVideos(msg.limit || 0, msg.randomize !== false).then(result => {
        sendResponse({ links: result.links, items: result.items });
      });
      return true;
    } else if (msg.action === 'STOP_BATCH_SCAN') {
      stopRequested = true;
      isScanning = false;
      sendResponse({ status: 'stopped' });
    } else if (msg.action === 'TOGGLE_FLOATING_BAR') {
      const container = document.getElementById('hm-floating-container');
      if (container) {
        container.style.display = msg.show ? 'flex' : 'none';
      }
      sendResponse({ status: 'ok' });
    }
  });

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', createFloatingControls);
  } else {
    createFloatingControls();
  }

  // Tự động kích hoạt đồng bộ khi mở trên Sync Hub của Local Server
  if (window.location.hostname === '127.0.0.1' || window.location.hostname === 'localhost') {
    if (window.location.pathname.includes('sync_hub')) {
      const hubPort = parseInt(window.location.port) || 42124;
      console.log('[HyperMedia Content] Phát hiện trang Sync Hub tại cổng ' + hubPort + ', tự động kích hoạt đồng bộ Live Cookies...');
      chrome.runtime.sendMessage({ action: 'FORCE_SYNC_COOKIES', targetPort: hubPort }, (res) => {
        console.log('[HyperMedia Content] Kết quả FORCE_SYNC_COOKIES:', res);
      });
      window.addEventListener('message', (e) => {
        if (e.data && e.data.type === 'HM_TRIGGER_COOKIE_SYNC') {
          chrome.runtime.sendMessage({ action: 'FORCE_SYNC_COOKIES', targetPort: hubPort });
        }
      });
    }
  } else {
    // Khi mở các trang Bilibili, Douyin, YouTube, TikTok:
    // Định kỳ gửi KEEP_ALIVE mỗi 20 giây để duy trì Service Worker không bị sleep
    setInterval(() => {
      try {
        chrome.runtime.sendMessage({ action: 'KEEP_ALIVE' });
      } catch (e) {}
    }, 20000);
  }
})();
