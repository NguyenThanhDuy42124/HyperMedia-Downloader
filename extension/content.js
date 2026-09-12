// Content Script - HyperMedia Helper Pro
(function() {
  let isScanning = false;
  let stopRequested = false;

  // 1. Tạo Thanh Điều Khiển Nổi Trực Tiếp Trên Trang Douyin/TikTok/Bilibili
  function createFloatingControls() {
    if (document.getElementById('hm-floating-container')) return;

    const container = document.createElement('div');
    container.id = 'hm-floating-container';
    container.innerHTML = `
      <div class="hm-floating-bar">
        <button id="hm-btn-single" class="hm-btn-pill" title="Copy link video 1080p đang xem">
          <span class="hm-icon">🎬</span>
          <span>Copy Video Này</span>
        </button>
        <button id="hm-btn-20" class="hm-btn-pill hm-btn-cyan" title="Tự động cuộn & Lấy 20 video">
          <span class="hm-icon">⚡</span>
          <span>Cuộn 20 Video</span>
        </button>
        <button id="hm-btn-50" class="hm-btn-pill hm-btn-cyan" title="Tự động cuộn & Lấy 50 video">
          <span class="hm-icon">⚡</span>
          <span>Cuộn 50 Video</span>
        </button>
        <button id="hm-btn-all" class="hm-btn-pill hm-btn-green" title="Tự động cuộn đến hết trang">
          <span class="hm-icon">🚀</span>
          <span>Quét Hết</span>
        </button>
      </div>
      <div id="hm-progress-banner" class="hm-banner" style="display:none;">
        <span id="hm-progress-text">Đang tự động cuộn trang...</span>
        <button id="hm-btn-stop" class="hm-btn-stop">Dừng</button>
      </div>
    `;

    document.body.appendChild(container);

    // Gắn sự kiện
    document.getElementById('hm-btn-single').addEventListener('click', () => copyCurrentVideoLink());
    document.getElementById('hm-btn-20').addEventListener('click', () => scanProfileVideos(20));
    document.getElementById('hm-btn-50').addEventListener('click', () => scanProfileVideos(50));
    document.getElementById('hm-btn-all').addEventListener('click', () => scanProfileVideos(0));
    document.getElementById('hm-btn-stop').addEventListener('click', () => {
      stopRequested = true;
      isScanning = false;
    });
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
      const activeSlide = document.querySelector('.swiper-slide-active a[href*="/video/"]') ||
                          document.querySelector('[data-e2e="feed-active-video"] a[href*="/video/"]') ||
                          document.querySelector('a[href*="/video/"]');
      if (activeSlide) {
        let h = activeSlide.getAttribute('href') || activeSlide.href;
        if (h) {
          const m = h.match(/\/video\/(\d+)/);
          if (m) return `https://www.douyin.com/video/${m[1]}`;
        }
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

  // 3. Sao chép link và hiện Toast thông báo
  async function copyCurrentVideoLink() {
    const videoUrl = getCurrentVideoUrl();
    try {
      await navigator.clipboard.writeText(videoUrl);
      showToast(`✅ Đã copy link: ${videoUrl.substring(0, 48)}...`);
    } catch (err) {
      const inp = document.createElement('textarea');
      inp.value = videoUrl;
      document.body.appendChild(inp);
      inp.select();
      document.execCommand('copy');
      document.body.removeChild(inp);
      showToast(`✅ Đã copy link video!`);
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

  // 5. Thu thập link hiện tại trên DOM (Khối code chuẩn xác của Douyin)
  function collectCurrentLinks(collected) {
    const elements = document.querySelectorAll('a[href*="/video/"], a[href*="/watch?v="], a[href*="/shorts/"]');
    elements.forEach(el => {
      let href = el.getAttribute('href') || el.href;
      if (!href) return;

      if (href.includes('/video/')) {
        if (href.startsWith('/video/')) {
          collected.add('https://www.douyin.com' + href.split('?')[0]);
        } else if (href.includes('/video/')) {
          let part = href.split('/video/')[1].split('?')[0].split('/')[0];
          collected.add('https://www.douyin.com/video/' + part);
        }
      } else if (href.includes('bilibili.com')) {
        const m = href.match(/\/video\/(BV[a-zA-Z0-9]+)/);
        if (m) collected.add(`https://www.bilibili.com/video/${m[1]}`);
      } else if (href.includes('youtube.com')) {
        if (href.includes('watch?v=')) collected.add(href.split('&')[0]);
        else if (href.includes('/shorts/')) collected.add(href);
      }
    });
  }

  // 6. Động cơ Auto-Scroll thông minh cuộn trang cho tới khi đủ số lượng
  async function scanProfileVideos(limit) {
    if (isScanning) return;
    isScanning = true;
    stopRequested = false;

    const banner = document.getElementById('hm-progress-banner');
    const progressText = document.getElementById('hm-progress-text');
    if (banner) banner.style.display = 'flex';

    let collected = new Set();
    collectCurrentLinks(collected);

    let noNewCount = 0;
    let maxRetries = 20;

    showToast(`Bắt đầu tự động cuộn trang quét ${limit === 0 ? 'toàn bộ' : limit} video...`);

    while (!stopRequested) {
      collectCurrentLinks(collected);
      const count = collected.size;

      if (progressText) {
        progressText.innerText = `Đang cuộn: Đã lấy ${count} ${limit > 0 ? '/ ' + limit : ''} video...`;
      }

      chrome.runtime.sendMessage({
        action: 'BATCH_PROGRESS',
        count: count,
        links: Array.from(collected)
      }).catch(() => {});

      if (limit > 0 && count >= limit) {
        break;
      }

      // Cuộn xuống từ từ để kích hoạt lazy loading của Douyin
      const scrollStep = 900 + Math.floor(Math.random() * 300);
      window.scrollBy({ top: scrollStep, behavior: 'smooth' });

      // Đợi DOM render
      await new Promise(r => setTimeout(r, 650));

      const afterCount = collected.size;
      collectCurrentLinks(collected);

      if (collected.size === afterCount) {
        noNewCount++;
        if (noNewCount >= maxRetries) {
          // Đã tới đáy trang
          break;
        }
      } else {
        noNewCount = 0;
      }
    }

    isScanning = false;
    if (banner) banner.style.display = 'none';

    let finalLinks = Array.from(collected);
    if (limit > 0 && finalLinks.length > limit) {
      finalLinks = finalLinks.slice(0, limit);
    }

    const text = finalLinks.join('\n');
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

    chrome.runtime.sendMessage({
      action: 'BATCH_DONE',
      links: finalLinks
    }).catch(() => {});

    showToast(`🎉 Đã cuộn xong & Copy ${finalLinks.length} video vào Clipboard!`);
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
      return true;
    } else if (msg.action === 'STOP_BATCH_SCAN') {
      stopRequested = true;
      isScanning = false;
      sendResponse({ status: 'stopped' });
    }
  });

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', createFloatingControls);
  } else {
    createFloatingControls();
  }
})();
