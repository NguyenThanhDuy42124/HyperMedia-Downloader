// HyperMedia Helper Pro - Background Service Worker
// Tự động lắng nghe yêu cầu từ Desktop App và đồng bộ Live Cookies tức thì

const PORT_CANDIDATES = Array.from({ length: 12 }, (_, i) => 42124 + i); // 42124 -> 42135
let activeAppPort = null;
let isPolling = false;

// Bộ nhớ lưu URL stream CDN bắt được qua WebRequest theo từng tabId
const tabStreamMap = new Map();

if (chrome.webRequest && chrome.webRequest.onBeforeRequest) {
  chrome.webRequest.onBeforeRequest.addListener(
    (details) => {
      const u = details.url || '';
      // Bỏ qua file audio-only (cả theo tên lẫn theo mime_type param)
      const isAudio = (
        u.includes('media-audio') || u.includes('-audio-') || u.includes('audio_mp4') ||
        u.includes('mime_type=audio') ||
        (u.includes('zjcdn.com') && u.includes('mime_type=') && !u.includes('mime_type=video'))
      );
      if (isAudio) return;

      const isMedia = (
        u.includes('douyinvod.com') ||
        u.includes('snssdk.com') ||
        u.includes('zjcdn.com') ||
        u.includes('/video/tos/') ||
        (u.includes('.douyin.com/') && u.includes('/play/')) ||
        (u.includes('tiktokcdn') && u.includes('.mp4'))
      );
      if (isMedia && !u.includes('.m3u8') && !u.includes('.js')) {
        if (details.tabId && details.tabId > 0) {
          // Nếu có asset vid dạng v0..., tạo ngay link phát full 1080p có tiếng
          const vidMatch = u.match(/(v0[0-9a-zA-Z]{15,})/);
          if (vidMatch) {
            const fullUrl = `https://aweme.snssdk.com/aweme/v1/play/?video_id=${vidMatch[1]}&ratio=1080p&line=0`;
            tabStreamMap.set(details.tabId, fullUrl);
          } else {
            tabStreamMap.set(details.tabId, u);
          }
        }
      }
    },
    { urls: ["<all_urls>"] }
  );

  chrome.tabs.onRemoved.addListener((tabId) => {
    tabStreamMap.delete(tabId);
  });

  chrome.tabs.onUpdated.addListener((tabId, changeInfo, tab) => {
    if (changeInfo.url) {
      // Khi tab đổi URL (chuyển video / mở modal mới), xóa stream cũ để không nạp nhầm video trước
      tabStreamMap.delete(tabId);
    }
  });
}

// Chuyển cookies thành định dạng chuẩn Netscape cho yt-dlp
function cookiesToNetscape(cookies) {
  let lines = [
    '# Netscape HTTP Cookie File',
    '# http://curl.haxx.se/rfc/cookie_spec.html',
    '# Auto-Generated & Live Refreshed by HyperMedia Background Service Worker',
    ''
  ];

  for (const c of cookies) {
    const domain = c.domain.startsWith('.') ? c.domain : '.' + c.domain;
    const flag = 'TRUE';
    const path = c.path || '/';
    const secure = c.secure ? 'TRUE' : 'FALSE';
    const expiry = c.expirationDate ? Math.round(c.expirationDate) : Math.round(Date.now() / 1000 + 86400 * 365);
    const name = c.name;
    const val = c.value;
    lines.push(`${domain}\t${flag}\t${path}\t${secure}\t${expiry}\t${name}\t${val}`);
  }
  return lines.join('\n');
}

// Lấy tất cả cookies sống từ trình duyệt cho các trang hỗ trợ
async function extractLiveCookies(requestedDomain = 'all') {
  const targetDomains = requestedDomain === 'all' 
    ? ['bilibili.com', 'youtube.com', 'douyin.com', 'tiktok.com']
    : [requestedDomain, 'bilibili.com', 'youtube.com'];

  let allCookies = [];
  for (const d of targetDomains) {
    try {
      const list = await chrome.cookies.getAll({ domain: d });
      if (list && list.length > 0) {
        allCookies = allCookies.concat(list);
      }
    } catch (e) {
      console.warn(`[HyperMedia BG] Lỗi đọc cookie ${d}:`, e);
    }
  }

  // Bổ sung: gom cả cookies của tab đang hoạt động nếu là trang video được hỗ trợ
  try {
    const tabs = await chrome.tabs.query({ active: true });
    if (tabs && tabs.length > 0) {
      const allowedDomains = ['bilibili.com', 'douyin.com', 'youtube.com', 'tiktok.com'];
      for (const t of tabs) {
        if (t.url && allowedDomains.some(d => t.url.includes(d))) {
          const tabList = await chrome.cookies.getAll({ url: t.url });
          if (tabList && tabList.length > 0) {
            allCookies = allCookies.concat(tabList);
          }
        }
      }
    }
  } catch (e) {}

  // Lọc trùng lặp
  const seen = new Set();
  const uniqueCookies = [];
  for (const c of allCookies) {
    const key = `${c.domain}|${c.path}|${c.name}`;
    if (!seen.has(key)) {
      seen.add(key);
      uniqueCookies.push(c);
    }
  }
  return uniqueCookies;
}

// Tự động tìm port đang chạy của Desktop App (Auto Port Hunting)
async function detectAppPort() {
  const cached = await chrome.storage.local.get('cachedAppPort');
  if (cached && cached.cachedAppPort) {
    try {
      const res = await fetch(`http://127.0.0.1:${cached.cachedAppPort}/api/ping`, { signal: AbortSignal.timeout(350) });
      if (res.ok) {
        const data = await res.json();
        if (data.app && data.app.includes('HyperMedia')) {
          activeAppPort = cached.cachedAppPort;
          return activeAppPort;
        }
      }
    } catch (e) {}
  }

  const checks = PORT_CANDIDATES.map(async (p) => {
    try {
      const res = await fetch(`http://127.0.0.1:${p}/api/ping`, { signal: AbortSignal.timeout(400) });
      if (res.ok) {
        const data = await res.json();
        if (data.app && data.app.includes('HyperMedia')) {
          return p;
        }
      }
    } catch (e) {}
    return null;
  });

  const results = await Promise.all(checks);
  const found = results.find(p => p !== null);
  if (found) {
    activeAppPort = found;
    await chrome.storage.local.set({ cachedAppPort: found });
    return found;
  }
  activeAppPort = null;
  return null;
}

// Xử lý gửi live cookies vào App Desktop
async function syncCookiesToApp(port, domain = 'all', reason = '') {
  try {
    const cookies = await extractLiveCookies(domain);
    if (!cookies || cookies.length === 0) {
      console.warn(`[HyperMedia BG] Không tìm thấy cookie trong trình duyệt cho ${domain}`);
      return false;
    }

    const netscapeText = cookiesToNetscape(cookies);
    let targetPort = port;
    let res;
    try {
      res = await fetch(`http://127.0.0.1:${targetPort}/api/sync_cookies`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ cookies: netscapeText, domain: domain }),
        signal: AbortSignal.timeout(4000)
      });
    } catch (fetchErr) {
      // Port cũ có thể đã đóng, tiến hành dò lại ngay lập tức
      activeAppPort = null;
      await chrome.storage.local.remove('cachedAppPort');
      const freshPort = await detectAppPort();
      if (freshPort && freshPort !== targetPort) {
        targetPort = freshPort;
        res = await fetch(`http://127.0.0.1:${targetPort}/api/sync_cookies`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ cookies: netscapeText, domain: domain }),
          signal: AbortSignal.timeout(4000)
        });
      } else {
        throw fetchErr;
      }
    }

    if (res && res.ok) {
      const data = await res.json();
      console.log(`[HyperMedia BG] Đã tự động cấp mới ${data.count} cookies sống vào Desktop App tại port ${targetPort}! (Lý do: ${reason})`);
      
      // Hiển thị badge xanh báo hiệu đồng bộ thành công trên icon extension
      try {
        chrome.action.setBadgeText({ text: 'SYNC' });
        chrome.action.setBadgeBackgroundColor({ color: '#00E676' });
        setTimeout(() => {
          chrome.action.setBadgeText({ text: '' });
        }, 3000);
      } catch (e) {}
      return true;
    }
  } catch (e) {
    console.error('[HyperMedia BG] Lỗi sync cookies vào App:', e);
  }
  return false;
}

// Vòng lặp Long-Polling / Heartbeat kiểm tra sự kiện từ App
async function pollAppEvents() {
  if (isPolling) return;
  isPolling = true;

  try {
    const port = activeAppPort || await detectAppPort();
    if (!port) {
      // App chưa mở -> Thử lại sau 5 giây để nhanh chóng kết nối khi App khởi động
      setTimeout(() => {
        isPolling = false;
        pollAppEvents();
      }, 5000);
      return;
    }

    const res = await fetch(`http://127.0.0.1:${port}/api/poll_events`, {
      signal: AbortSignal.timeout(12000)
    });

    if (res.ok) {
      const data = await res.json();
      if (data.events && data.events.length > 0) {
        for (const ev of data.events) {
          if (ev.action === 'REQUEST_COOKIES') {
            console.log(`[HyperMedia BG] Nhận yêu cầu cấp Live Cookies từ App:`, ev);
            await syncCookiesToApp(port, ev.domain || 'all', ev.reason || 'App requested');
          }
        }
      }
      // Long-polling tiếp tục ngay sau 300ms
      setTimeout(() => {
        isPolling = false;
        pollAppEvents();
      }, 300);
      return;
    } else {
      activeAppPort = null;
    }
  } catch (e) {
    activeAppPort = null;
  }

  // Nếu gặp lỗi mạng (App tắt hoặc đổi port), đợi 4s trước khi dò lại
  setTimeout(() => {
    isPolling = false;
    pollAppEvents();
  }, 4000);
}

// Khởi chạy Heartbeat / Keep-Alive bằng Alarm
chrome.alarms.create('hypermedia_poll_heartbeat', { periodInMinutes: 0.5 });
chrome.alarms.onAlarm.addListener((alarm) => {
  if (alarm.name === 'hypermedia_poll_heartbeat') {
    pollAppEvents();
  }
});

chrome.runtime.onStartup.addListener(() => {
  pollAppEvents();
});

chrome.runtime.onInstalled.addListener(() => {
  pollAppEvents();
});

// Lắng nghe yêu cầu gửi link từ Content Script hoặc Popup
chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
  if (request.action === 'KEEP_ALIVE') {
    pollAppEvents();
    sendResponse({ status: 'alive' });
    return false;
  }

  if (request.action === 'FORCE_SYNC_COOKIES') {
    (async () => {
      let port = request.targetPort || activeAppPort || await detectAppPort();
      if (!port) {
        sendResponse({ success: false, error: 'Chưa mở Desktop App!' });
        return;
      }
      if (request.targetPort) {
        activeAppPort = request.targetPort;
        await chrome.storage.local.set({ cachedAppPort: request.targetPort });
      }
      const ok = await syncCookiesToApp(port, 'all', 'Content Script / Hub Triggered');
      sendResponse({ success: ok, port: port });
    })();
    return true; // Asynchronous response
  }

  if (request.action === 'GET_TAB_STREAM') {
    const tabId = request.tabId || (sender.tab && sender.tab.id);
    const stream = tabId ? tabStreamMap.get(tabId) : null;
    sendResponse({ streamUrl: stream || null });
    return false;
  }

  if (request.action === 'SEND_TO_APP') {
    (async () => {
      let port = activeAppPort || await detectAppPort();
      if (!port) {
        sendResponse({ success: false, error: 'Chưa mở Desktop App! Hãy khởi động HyperMedia trước.' });
        return;
      }
      try {
        const tabId = request.tabId || (sender.tab && sender.tab.id);
        let urls = Array.isArray(request.urls) ? request.urls : [request.url];

        // Nếu là 1 video đơn từ Douyin và background đã tóm được stream CDN gốc, ưu tiên dùng stream CDN!
        if (urls.length === 1 && tabId && tabStreamMap.has(tabId)) {
          const stream = tabStreamMap.get(tabId);
          const isAlreadyCdn = (
            urls[0].includes('douyinvod.com') ||
            urls[0].includes('zjcdn.com') ||
            urls[0].includes('snssdk.com')
          );
          // Không đè stream cũ lên trang profile chung hoặc URL đã có modal_id cụ thể
          const isProfilePage = urls[0].includes('/user/') && !urls[0].includes('modal_id');
          if (urls[0].includes('douyin.com') && !isAlreadyCdn && !isProfilePage) {
            console.log(`[HyperMedia BG] Tự động nâng cấp URL trang web Douyin thành luồng stream CDN:`, stream);
            urls = [stream];
          }
        }

        // Tự động đồng bộ Live Cookies cùng lúc gửi link
        syncCookiesToApp(port, 'all', 'Auto-sync on Send to App').catch(() => {});

        const title = request.title || '';
        const thumb = request.thumb || '';
        let items = request.items;
        if (!items || (Array.isArray(items) && items.length === 1 && urls.length === 1 && items[0].url !== urls[0])) {
          items = urls.map(u => ({
            url: u,
            title: title || (request.items && request.items[0] ? request.items[0].title : ''),
            thumb: thumb || (request.items && request.items[0] ? request.items[0].thumb : '')
          }));
        }

        let res;
        try {
          res = await fetch(`http://127.0.0.1:${port}/api/add_links`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ urls, items }),
            signal: AbortSignal.timeout(3500)
          });
        } catch (fetchErr) {
          // Port có thể đã đổi, dò lại và retry
          activeAppPort = null;
          await chrome.storage.local.remove('cachedAppPort');
          const freshPort = await detectAppPort();
          if (freshPort) {
            port = freshPort;
            res = await fetch(`http://127.0.0.1:${port}/api/add_links`, {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ urls, items }),
              signal: AbortSignal.timeout(3500)
            });
          } else {
            throw fetchErr;
          }
        }

        if (res && res.ok) {
          sendResponse({ success: true, port: port, count: urls.length, isStream: urls[0].includes('douyinvod.com') });
        } else {
          sendResponse({ success: false, error: 'App từ chối nhận link.' });
        }
      } catch (e) {
        sendResponse({ success: false, error: 'Không thể kết nối tới App Desktop.' });
      }
    })();
    return true; // Asynchronous response
  }
});

// Chạy ngay khi service worker được nạp
pollAppEvents();
