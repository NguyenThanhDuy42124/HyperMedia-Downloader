// Content Script - HyperMedia Helper for Douyin, TikTok, Bilibili, YouTube
(function() {
  let isScanning = false;
  let stopRequested = false;

  // 1. Tạo Nút Nổi Nhanh trên giao diện (Floating Button)
  function createFloatingButton() {
    if (document.getElementById('hm-floating-btn')) return;

    const btn = document.createElement('div');
    btn.id = 'hm-floating-btn';
    btn.className = 'hm-floating-pill';
    btn.innerHTML = `
      <span class="hm-icon">⚡</span>
      <span class="hm-text">Copy Link Video</span>
    `;
    btn.title = 'Bấm để copy link video 1080p vào Clipboard (Dùng cho HyperMedia Downloader)';

    btn.addEventListener('click', (e) => {
      e.stopPropagation();
      copyCurrentVideoLink();
    });

    document.body.appendChild(btn);
  }

  // 2. Trích xuất link video đơn hiện tại
  function getCurrentVideoUrl() {
    const url = window.location.href;

    // Douyin: Tìm link /video/ID
    if (url.includes('douyin.com')) {
      if (url.includes('/video/')) {
        const match = url.match(/\/video\/(\d+)/);
        if (match) return `https://www.douyin.com/video/${match[1]}`;
      }
      // Đang lướt feed Douyin: Tìm video active
      const activeSlide = document.querySelector('.swiper-slide-active a[href*="/video/"]') ||
                          document.querySelector('[data-e2e="feed-active-video"] a[href*="/video/"]') ||
                          document.querySelector('a[href*="/video/"]');
      if (activeSlide && activeSlide.href) {
        const m = activeSlide.href.match(/\/video\/(\d+)/);
        if (m) return `https://www.douyin.com/video/${m[1]}`;
      }
    }

    // TikTok: Tìm video ID
    if (url.includes('tiktok.com')) {
      if (url.includes('/video/')) {
        const match = url.match(/\/video\/(\d+)/);
        if (match) return `https://www.tiktok.com/@user/video/${match[1]}`;
      }
    }

    // Bilibili: Tìm /video/BV
    if (url.includes('bilibili.com')) {
      const match = url.match(/\/video\/(BV[a-zA-Z0-9]+)/);
      if (match) return `https://www.bilibili.com/video/${match[1]}`;
    }

    // YouTube: Tìm watch?v= hoặc shorts/
    if (url.includes('youtube.com')) {
      if (url.includes('watch?v=')) return url.split('&')[0];
      if (url.includes('/shorts/')) return url;
    }

    return url;
  }

  // 3. Sao chép link và hiện Toast thông báo mượt mà
  async function copyCurrentVideoLink() {
    const videoUrl = getCurrentVideoUrl();
    try {
      await navigator.clipboard.writeText(videoUrl);
      showToast(`Đã copy link video: ${videoUrl.substring(0, 45)}...`);
    } catch (err) {
      // Fallback
      const inp = document.createElement('textarea');
      inp.value = videoUrl;
      document.body.appendChild(inp);
      inp.select();
      document.execCommand('copy');
      document.body.removeChild(inp);
      showToast(`Đã copy link video!`);
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

  // 5. Quét toàn bộ video trên Profile / Kênh với tự động cuộn
  async function scanProfileVideos(limit) {
    if (isScanning) return;
    isScanning = true;
    stopRequested = false;

    let collected = new Set();
    let noNewCount = 0;
    let maxRetries = 25;

    showToast('Bắt đầu cuộn trang quét danh sách video...');

    while (!stopRequested) {
      // Thu thập tất cả thẻ link video
      let selector = 'a[href*="/video/"]';
      if (window.location.href.includes('bilibili.com')) {
        selector = 'a[href*="/video/BV"]';
      } else if (window.location.href.includes('youtube.com')) {
        selector = 'a[href*="/watch?v="], a[href*="/shorts/"]';
      }

      const elements = document.querySelectorAll(selector);
      const prevSize = collected.size;

      elements.forEach(el => {
        let href = el.href;
        if (!href) return;
        if (href.includes('douyin.com')) {
          const m = href.match(/\/video\/(\d+)/);
          if (m) collected.add(`https://www.douyin.com/video/${m[1]}`);
        } else if (href.includes('bilibili.com')) {
          const m = href.match(/\/video\/(BV[a-zA-Z0-9]+)/);
          if (m) collected.add(`https://www.bilibili.com/video/${m[1]}`);
        } else if (href.includes('youtube.com')) {
          if (href.includes('watch?v=')) collected.add(href.split('&')[0]);
          else if (href.includes('/shorts/')) collected.add(href);
        } else {
          collected.add(href);
        }
      });

      // Báo tiến trình cho Popup
      chrome.runtime.sendMessage({
        action: 'BATCH_PROGRESS',
        count: collected.size,
        links: Array.from(collected)
      }).catch(() => {});

      if (limit > 0 && collected.size >= limit) {
        break;
      }

      if (collected.size === prevSize) {
        noNewCount++;
        if (noNewCount >= maxRetries) {
          // Đã cuộn đến đáy trang
          break;
        }
      } else {
        noNewCount = 0;
      }

      // Cuộn trang xuống
      window.scrollBy({ top: 1200, behavior: 'smooth' });
      await new Promise(r => setTimeout(r, 600));
    }

    isScanning = false;
    let finalLinks = Array.from(collected);
    if (limit > 0 && finalLinks.length > limit) {
      finalLinks = finalLinks.slice(0, limit);
    }

    chrome.runtime.sendMessage({
      action: 'BATCH_DONE',
      links: finalLinks
    }).catch(() => {});

    showToast(`Đã quét xong: ${finalLinks.length} video!`);
    return finalLinks;
  }

  // Lắng nghe Message từ Extension Popup
  chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
    if (msg.action === 'GET_SINGLE_VIDEO') {
      sendResponse({ url: getCurrentVideoUrl() });
    } else if (msg.action === 'START_BATCH_SCAN') {
      scanProfileVideos(msg.limit || 0).then(links => {
        sendResponse({ links: links });
      });
      return true; // async
    } else if (msg.action === 'STOP_BATCH_SCAN') {
      stopRequested = true;
      isScanning = false;
      sendResponse({ status: 'stopped' });
    }
  });

  // Tự động gắn Nút Nổi khi tải trang
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', createFloatingButton);
  } else {
    createFloatingButton();
  }
})();
