// Popup Script for HyperMedia Helper Extension Pro
document.addEventListener('DOMContentLoaded', async () => {
  const siteBadge = document.getElementById('siteBadge');
  const btnCopySingle = document.getElementById('btnCopySingle');
  const btnStartBatch = document.getElementById('btnStartBatch');
  const btnStopBatch = document.getElementById('btnStopBatch');
  const btnCopyAll = document.getElementById('btnCopyAll');
  const inpLimit = document.getElementById('inpLimit');
  const chkHumanRandom = document.getElementById('chkHumanRandom');
  const chkFloatingBar = document.getElementById('chkFloatingBar');
  const statusMsg = document.getElementById('statusMsg');
  const txtResults = document.getElementById('txtResults');
  const chips = document.querySelectorAll('.chip');

  const appDot = document.getElementById('appDot');
  const appPortText = document.getElementById('appPortText');
  const btnSendSingleToApp = document.getElementById('btnSendSingleToApp');
  const btnSendBatchToApp = document.getElementById('btnSendBatchToApp');
  const btnSyncDirectToApp = document.getElementById('btnSyncDirectToApp');

  let activeAppPort = null;
  const PORT_CANDIDATES = Array.from({ length: 12 }, (_, i) => 42124 + i); // 42124 -> 42135

  const STATUS_ICONS = {
    info: '<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/></svg>',
    success: '<svg viewBox="0 0 24 24"><polyline points="20 6 9 17 4 12"/></svg>',
    warning: '<svg viewBox="0 0 24 24"><path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>',
    error: '<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/></svg>',
    loading: '<svg viewBox="0 0 24 24"><path d="M21 12a9 9 0 1 1-6.219-8.56"/></svg>'
  };

  const STATUS_COLORS = {
    info: '#00E5FF',
    success: '#00E676',
    warning: '#f59e0b',
    error: '#f87171',
    loading: '#38bdf8'
  };

  function setStatus(text, type = 'info') {
    if (!statusMsg) return;
    const icon = STATUS_ICONS[type] || STATUS_ICONS.info;
    const color = STATUS_COLORS[type] || STATUS_COLORS.info;
    statusMsg.style.color = color;
    statusMsg.innerHTML = `${icon}<span>${text}</span>`;
  }

  // Tự động dò tìm cổng App Desktop (Auto Port Hunting)
  async function detectAppPort() {
    // 1. Thử port đã lưu trong cache trước
    const cached = await chrome.storage.local.get('cachedAppPort');
    if (cached && cached.cachedAppPort) {
      try {
        const res = await fetch(`http://127.0.0.1:${cached.cachedAppPort}/api/ping`, { signal: AbortSignal.timeout(600) });
        if (res.ok) {
          const data = await res.json();
          if (data.app && data.app.includes('HyperMedia')) {
            setAppOnline(cached.cachedAppPort);
            return cached.cachedAppPort;
          }
        }
      } catch (e) {}
    }

    // 2. Bắn request song song dò quét dải port
    const checks = PORT_CANDIDATES.map(async (p) => {
      try {
        const res = await fetch(`http://127.0.0.1:${p}/api/ping`, { signal: AbortSignal.timeout(800) });
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
    const foundPort = results.find(p => p !== null);
    if (foundPort) {
      await chrome.storage.local.set({ cachedAppPort: foundPort });
      setAppOnline(foundPort);
      return foundPort;
    } else {
      setAppOffline();
      return null;
    }
  }

  function setAppOnline(port) {
    activeAppPort = port;
    if (appDot) appDot.style.background = '#00E676';
    if (appPortText) {
      appPortText.innerText = `App: Đã kết nối (${port})`;
      appPortText.style.color = '#00E676';
    }
  }

  function setAppOffline() {
    activeAppPort = null;
    if (appDot) appDot.style.background = '#64748B';
    if (appPortText) {
      appPortText.innerText = 'App: Chưa mở Desktop';
      appPortText.style.color = '#94A3B8';
    }
  }

  // Khởi động dò tìm port ngay khi mở popup
  detectAppPort();

  // Load cài đặt Floating Bar
  chrome.storage.local.get({ showFloatingBar: true }, (res) => {
    if (chkFloatingBar) chkFloatingBar.checked = res.showFloatingBar;
  });

  if (chkFloatingBar) {
    chkFloatingBar.addEventListener('change', async () => {
      const show = chkFloatingBar.checked;
      await chrome.storage.local.set({ showFloatingBar: show });
      try {
        const [currTab] = await chrome.tabs.query({ active: true, currentWindow: true });
        if (currTab && currTab.id) {
          chrome.tabs.sendMessage(currTab.id, { action: 'TOGGLE_FLOATING_BAR', show: show }).catch(() => {});
        }
      } catch (e) {}
    });
  }

  chips.forEach(c => {
    c.addEventListener('click', () => {
      chips.forEach(x => x.classList.remove('active'));
      c.classList.add('active');
      inpLimit.value = c.getAttribute('data-val');
    });
  });

  // Lấy Active Tab an toàn không bị chặn
  async function getActiveTab() {
    try {
      const tabs = await chrome.tabs.query({ active: true, currentWindow: true });
      return (tabs && tabs.length > 0) ? tabs[0] : null;
    } catch (e) {
      return null;
    }
  }

  let currentTab = null;

  async function updateSiteBadge() {
    currentTab = await getActiveTab();
    if (!currentTab || !currentTab.url) {
      if (siteBadge) {
        siteBadge.innerHTML = `<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="10"/><path d="M12 2a14.5 14.5 0 0 0 0 20 14.5 14.5 0 0 0 0-20"/><path d="M2 12h20"/></svg> <span>Trang Khác</span>`;
        siteBadge.style.background = '#252538';
        siteBadge.style.color = '#94A3B8';
      }
      return;
    }

    const url = currentTab.url.toLowerCase();
    let platform = 'Trang Khác';
    let badgeBg = '#1f2937';
    let badgeColor = '#94A3B8';
    let badgeIcon = '<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="10"/><path d="M12 2a14.5 14.5 0 0 0 0 20 14.5 14.5 0 0 0 0-20"/><path d="M2 12h20"/></svg>';

    if (url.includes('douyin.com')) {
      platform = 'Douyin (抖音)';
      badgeBg = '#1e1b4b';
      badgeColor = '#818cf8';
      badgeIcon = '<svg viewBox="0 0 24 24"><path d="M9 18V5l12-2v13"/><circle cx="6" cy="18" r="3"/><circle cx="18" cy="16" r="3"/></svg>';
    } else if (url.includes('tiktok.com')) {
      platform = 'TikTok';
      badgeBg = '#042f2e';
      badgeColor = '#2dd4bf';
      badgeIcon = '<svg viewBox="0 0 24 24"><path d="M9 18V5l12-2v13"/><circle cx="6" cy="18" r="3"/><circle cx="18" cy="16" r="3"/></svg>';
    } else if (url.includes('bilibili.com')) {
      platform = 'Bilibili';
      badgeBg = '#003847';
      badgeColor = '#00E5FF';
      badgeIcon = '<svg viewBox="0 0 24 24"><rect width="20" height="15" x="2" y="7" rx="2" ry="2"/><polyline points="17 2 12 7 7 2"/></svg>';
    } else if (url.includes('youtube.com') || url.includes('youtu.be')) {
      platform = 'YouTube';
      badgeBg = '#450a0a';
      badgeColor = '#f87171';
      badgeIcon = '<svg viewBox="0 0 24 24"><polygon points="6 3 20 12 6 21 6 3"/></svg>';
    }

    if (siteBadge) {
      siteBadge.innerHTML = `${badgeIcon} <span>${platform}</span>`;
      siteBadge.style.background = badgeBg;
      siteBadge.style.color = badgeColor;
    }
  }

  // Khởi động nhận diện web ngay tức thì
  updateSiteBadge();

  function cleanUrl(rawUrl) {
    if (!rawUrl) return '';
    let u = rawUrl.trim();
    // Nếu là stream URL CDN trực tiếp (douyinvod, zjcdn, tos, mp4, play) thì giữ nguyên để tải tốc độ cao
    if (u.includes('douyinvod.com') || u.includes('zjcdn.com') || u.includes('/video/tos/') || u.includes('.mp4') || u.includes('/aweme/v1/play/')) {
      return u;
    }
    if (u.includes('douyin.com')) {
      const modalMatch = u.match(/[?&]modal_id=(\d+)/);
      if (modalMatch) return `https://www.douyin.com/video/${modalMatch[1]}`;
      const vidMatch = u.match(/[?&]vid=(\d+)/);
      if (vidMatch) return `https://www.douyin.com/video/${vidMatch[1]}`;
      const vidPath = u.match(/\/video\/(\d+)/);
      if (vidPath) return `https://www.douyin.com/video/${vidPath[1]}`;
    }
    return u;
  }

  // 1. Copy Link Video Đơn
  btnCopySingle.addEventListener('click', async () => {
    setStatus('Đang trích xuất link video...', 'loading');
    const tab = currentTab || await getActiveTab();
    const rawUrl = (tab && tab.url) ? tab.url : '';
    if (!rawUrl) {
      setStatus('Không tìm thấy tab video hợp lệ!', 'error');
      return;
    }
    let targetUrl = rawUrl;
    let singleData = null;
    try {
      singleData = await chrome.tabs.sendMessage(tab.id, { action: 'GET_SINGLE_VIDEO' });
      if (singleData && singleData.url) {
        targetUrl = singleData.url;
      }
    } catch (e) {}

    // Nếu đang ở trang profile mà chưa mở video nào
    if (rawUrl.includes('/user/') && singleData && !singleData.hasModal && !singleData.awemeId) {
      setStatus('Hãy bấm mở xem 1 video trên profile trước khi Copy Link!', 'warning');
      return;
    }

    const isStreamCdn = (
      targetUrl.includes('douyinvod.com') ||
      targetUrl.includes('zjcdn.com') ||
      targetUrl.includes('snssdk.com') ||
      targetUrl.includes('/video/tos/')
    );
    if (!isStreamCdn && !(rawUrl.includes('/user/') && !rawUrl.includes('modal_id'))) {
      try {
        const bgRes = await chrome.runtime.sendMessage({ action: 'GET_TAB_STREAM', tabId: tab.id });
        if (bgRes && bgRes.streamUrl) targetUrl = bgRes.streamUrl;
      } catch (e) {}
    }

    targetUrl = cleanUrl(targetUrl);
    await navigator.clipboard.writeText(targetUrl);
    setStatus('Đã copy link video 1080p!', 'success');
    txtResults.value = targetUrl;
  });

  // 2. Bắt đầu quét hàng loạt với Auto-Scroll & Randomization
  btnStartBatch.addEventListener('click', async () => {
    const tab = currentTab || await getActiveTab();
    if (!tab || !tab.id) {
      setStatus('Không tìm thấy tab để cuộn!', 'error');
      return;
    }
    const limit = parseInt(inpLimit.value, 10) || 0;
    const isRandom = chkHumanRandom.checked;
    setStatus(`Đang tự động cuộn trang quét ${limit === 0 ? 'Tất cả' : limit} video (Random: ${isRandom ? 'Bật' : 'Tắt'})...`, 'loading');
    btnStartBatch.style.display = 'none';
    btnStopBatch.style.display = 'flex';
    txtResults.value = '';

    try {
      const resp = await chrome.tabs.sendMessage(tab.id, {
        action: 'START_BATCH_SCAN',
        limit: limit,
        randomize: isRandom
      });
      if (resp) {
        handleScanComplete(resp.links || [], resp.items || []);
      }
    } catch (e) {
      setStatus('Lỗi kết nối trang! Hãy F5 lại trang rồi thử lại.', 'error');
      btnStartBatch.style.display = 'flex';
      btnStopBatch.style.display = 'none';
    }
  });

  // 3. Dừng quét
  btnStopBatch.addEventListener('click', async () => {
    const tab = currentTab || await getActiveTab();
    if (tab && tab.id) {
      try {
        await chrome.tabs.sendMessage(tab.id, { action: 'STOP_BATCH_SCAN' });
      } catch (e) {}
    }
    setStatus('Đã dừng quét!', 'warning');
    btnStartBatch.style.display = 'flex';
    btnStopBatch.style.display = 'none';
  });

  // 4. Copy toàn bộ link kết quả
  btnCopyAll.addEventListener('click', async () => {
    if (!txtResults.value) return;
    await navigator.clipboard.writeText(txtResults.value);
    setStatus('Đã copy toàn bộ link vào Clipboard!', 'success');
  });

  let lastBatchItems = [];

  function handleScanComplete(links, items = []) {
    btnStartBatch.style.display = 'flex';
    btnStopBatch.style.display = 'none';
    if (!links || links.length === 0) {
      setStatus('Không tìm thấy video nào trên trang này!', 'warning');
      return;
    }
    lastBatchItems = (items && items.length > 0) ? items : links.map(u => ({ url: u, title: '', thumb: '' }));
    const text = links.join('\n');
    txtResults.value = text;
    setStatus(`Quét hoàn tất: ${links.length} video (Đã lấy Tên & Thumb)!`, 'success');
    btnCopyAll.style.display = 'flex';
    btnCopyAll.innerHTML = `<svg viewBox="0 0 24 24"><rect width="14" height="14" x="8" y="8" rx="2" ry="2"/><path d="M4 16c-1.1 0-2-.9-2-2V4c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2"/></svg> <span>Copy (${links.length})</span>`;
    if (btnSendBatchToApp) {
      btnSendBatchToApp.style.display = 'flex';
      btnSendBatchToApp.innerHTML = `<svg viewBox="0 0 24 24"><path d="m22 2-7 20-4-9-9-4Z"/><path d="M22 2 11 13"/></svg> <span>Gửi (${links.length}) Vào App</span>`;
    }
    navigator.clipboard.writeText(text);
  }

  // 5. Xuất Cookies Chuẩn Netscape cho HyperMedia Downloader Pro
  const btnExportCookies = document.getElementById('btnExportCookies');
  const btnExportAllCookies = document.getElementById('btnExportAllCookies');
  const btnCopyCookieText = document.getElementById('btnCopyCookieText');

  function cookiesToNetscape(cookies) {
    let lines = [
      '# Netscape HTTP Cookie File',
      '# http://curl.haxx.se/rfc/cookie_spec.html',
      '# This is a generated file by HyperMedia Helper Pro! Do not edit.',
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

  async function getNetscapeCookies(allSites = false) {
    if (allSites) {
      const targetDomains = ['bilibili.com', 'youtube.com', 'douyin.com', 'tiktok.com'];
      let allCookies = [];
      for (const d of targetDomains) {
        try {
          const list = await chrome.cookies.getAll({ domain: d });
          if (list && list.length > 0) {
            allCookies = allCookies.concat(list);
          }
        } catch (e) {}
      }
      if (allCookies.length === 0) {
        return { success: false, text: '', count: 0, domain: 'Douyin + Bilibili + YouTube' };
      }
      return {
        success: true,
        text: cookiesToNetscape(allCookies),
        count: allCookies.length,
        domain: 'gộp Douyin, Bilibili & YouTube'
      };
    }

    let domainTarget = 'bilibili.com';
    const tab = currentTab || await getActiveTab();
    const currentUrl = ((tab && tab.url) || '').toLowerCase();
    if (currentUrl.includes('youtube.com') || currentUrl.includes('youtu.be')) domainTarget = 'youtube.com';
    else if (currentUrl.includes('douyin.com')) domainTarget = 'douyin.com';
    else if (currentUrl.includes('tiktok.com')) domainTarget = 'tiktok.com';
    else if (currentUrl.includes('bilibili.com')) domainTarget = 'bilibili.com';

    let cookies = [];
    try {
      cookies = await chrome.cookies.getAll({ domain: domainTarget });
    } catch (e) {
      console.error('Lỗi đọc cookies:', e);
    }

    if ((!cookies || cookies.length === 0) && tab && tab.url) {
      try {
        cookies = await chrome.cookies.getAll({ url: tab.url });
      } catch (e) {}
    }

    if (!cookies || cookies.length === 0) {
      return { success: false, text: '', count: 0, domain: domainTarget };
    }

    return {
      success: true,
      text: cookiesToNetscape(cookies),
      count: cookies.length,
      domain: domainTarget
    };
  }

  function downloadTextFile(content, filename) {
    const blob = new Blob([content], { type: 'text/plain;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  }

  if (btnExportCookies) {
    btnExportCookies.addEventListener('click', async () => {
      setStatus('Đang trích xuất cookies trang này...', 'loading');
      const res = await getNetscapeCookies(false);
      if (!res.success) {
        setStatus(`Không tìm thấy cookie cho ${res.domain}. Hãy mở trang và đăng nhập trước!`, 'error');
        return;
      }
      downloadTextFile(res.text, 'cookies.txt');
      setStatus(`Đã xuất ${res.count} cookies (${res.domain}) vào cookies.txt!`, 'success');
    });
  }

  if (btnExportAllCookies) {
    btnExportAllCookies.addEventListener('click', async () => {
      setStatus('Đang gom cookies Douyin + Bilibili + YouTube...', 'loading');
      const res = await getNetscapeCookies(true);
      if (!res.success) {
        setStatus('Chưa đăng nhập trang nào trong 3 trang trên!', 'error');
        return;
      }
      downloadTextFile(res.text, 'cookies.txt');
      setStatus(`Đã xuất gộp ${res.count} cookies (${res.domain}) vào cookies.txt!`, 'success');
    });
  }

  if (btnCopyCookieText) {
    btnCopyCookieText.addEventListener('click', async () => {
      setStatus('Đang đọc cookies...', 'loading');
      const res = await getNetscapeCookies(false);
      if (!res.success) {
        setStatus(`Không tìm thấy cookie cho ${res.domain}!`, 'error');
        return;
      }
      await navigator.clipboard.writeText(res.text);
      setStatus(`Đã copy ${res.count} cookies (${res.domain}) vào Clipboard!`, 'success');
    });
  }

  // 6. Gửi Link Trực Tiếp Sang Desktop App (Không Cần Copy/Paste)
  async function postLinksToDesktop(inputs) {
    const items = inputs.map(x => (typeof x === 'string' ? { url: x, title: '', thumb: '' } : x));
    const urls = items.map(x => x.url);

    setStatus(`Đang gửi ${urls.length} video sang Desktop App...`, 'loading');

    // 1. Thử ủy quyền qua Background Service Worker (Không bị vướng CORS/PNA)
    try {
      const bgResp = await new Promise((resolve) => {
        chrome.runtime.sendMessage({ action: 'SEND_TO_APP', urls, items }, (resp) => {
          if (chrome.runtime.lastError || !resp) {
            resolve(null);
          } else {
            resolve(resp);
          }
        });
      });

      if (bgResp && bgResp.success) {
        setStatus(`Đã gửi ${urls.length} video vào App Desktop! App đang tự động quét...`, 'success');
        if (btnSendSingleToApp) {
          btnSendSingleToApp.innerHTML = `<svg viewBox="0 0 24 24"><polyline points="20 6 9 17 4 12"/></svg> <span>Đã Gửi Thành Công!</span>`;
          setTimeout(() => {
            btnSendSingleToApp.innerHTML = `<svg viewBox="0 0 24 24"><path d="m22 2-7 20-4-9-9-4Z"/><path d="M22 2 11 13"/></svg> <span>Gửi Vào App Ngay</span>`;
          }, 2500);
        }
        return true;
      }
    } catch (e) {}

    // 2. Fallback: fetch trực tiếp tới Local Server
    const port = activeAppPort || await detectAppPort();
    if (!port) {
      setStatus('Chưa mở Desktop App! Hãy khởi động HyperMedia trên máy tính trước.', 'warning');
      return false;
    }

    try {
      const res = await fetch(`http://127.0.0.1:${port}/api/add_links`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ urls, items })
      });
      if (res.ok) {
        setStatus(`Đã gửi ${urls.length} video vào App Desktop! App đang tự động quét...`, 'success');
        if (btnSendSingleToApp) {
          btnSendSingleToApp.innerHTML = `<svg viewBox="0 0 24 24"><polyline points="20 6 9 17 4 12"/></svg> <span>Đã Gửi Thành Công!</span>`;
          setTimeout(() => {
            btnSendSingleToApp.innerHTML = `<svg viewBox="0 0 24 24"><path d="m22 2-7 20-4-9-9-4Z"/><path d="M22 2 11 13"/></svg> <span>Gửi Vào App Ngay</span>`;
          }, 2500);
        }
        return true;
      }
    } catch (e) {
      console.error('Lỗi gửi link sang App:', e);
      setAppOffline();
      setStatus('Không thể kết nối tới App. Vui lòng kiểm tra lại.', 'error');
    }
    return false;
  }

  if (btnSendSingleToApp) {
    btnSendSingleToApp.addEventListener('click', async () => {
      const tab = currentTab || await getActiveTab();
      if (!tab || !tab.url) {
        setStatus('Không tìm thấy tab video nào đang mở!', 'error');
        return;
      }
      let videoUrl = tab.url;
      let videoTitle = (tab.title || '').replace(/\s*[-_]\s*抖音.*$/i, '')
                                       .replace(/_哔哩哔哩.*$/i, '')
                                       .replace(/\s*-\s*YouTube.*$/i, '')
                                       .replace(/\s*\|\s*TikTok.*$/i, '')
                                       .trim();
      let videoThumb = '';
      let singleData = null;

      try {
        singleData = await chrome.tabs.sendMessage(tab.id, { action: 'GET_SINGLE_VIDEO' });
        if (singleData) {
          if (singleData.url) videoUrl = singleData.url;
          if (singleData.title) videoTitle = singleData.title;
          if (singleData.thumb) videoThumb = singleData.thumb;
        }
      } catch (e) {}

      // Nếu đang ở trang profile và người dùng chưa mở modal video nào
      if (tab.url.includes('/user/') && singleData && !singleData.hasModal && !singleData.awemeId) {
        setStatus('Hãy bấm mở xem 1 video trên profile trước khi Gửi Vào App!', 'warning');
        return;
      }

      // Chỉ fallback GET_TAB_STREAM nếu chưa phải là stream CDN và không phải trang profile chung
      const isStreamCdn = (
        videoUrl.includes('douyinvod.com') ||
        videoUrl.includes('zjcdn.com') ||
        videoUrl.includes('snssdk.com') ||
        videoUrl.includes('/video/tos/')
      );
      if (!isStreamCdn && !(tab.url.includes('/user/') && !tab.url.includes('modal_id'))) {
        try {
          const bgRes = await chrome.runtime.sendMessage({ action: 'GET_TAB_STREAM', tabId: tab.id });
          if (bgRes && bgRes.streamUrl) videoUrl = bgRes.streamUrl;
        } catch (e) {}
      }

      videoUrl = cleanUrl(videoUrl);
      if (!videoUrl) {
        setStatus('Không tìm thấy URL video hợp lệ!', 'error');
        return;
      }
      await postLinksToDesktop([{
        url: videoUrl,
        title: videoTitle,
        thumb: videoThumb
      }]);
    });
  }

  if (btnSendBatchToApp) {
    btnSendBatchToApp.addEventListener('click', async () => {
      if (!txtResults.value) {
        setStatus('Hãy cuộn trang quét danh sách video trước!', 'warning');
        return;
      }
      const links = txtResults.value.split('\n').map(x => x.trim()).filter(x => x.length > 0);
      if (links.length > 0) {
        let itemsToSend = lastBatchItems;
        if (!itemsToSend || itemsToSend.length === 0 || itemsToSend.length !== links.length) {
          itemsToSend = links.map(u => ({ url: u, title: '', thumb: '' }));
        }
        await postLinksToDesktop(itemsToSend);
      }
    });
  }

  if (btnSyncDirectToApp) {
    btnSyncDirectToApp.addEventListener('click', async () => {
      setStatus('Đang gom cookies & đồng bộ trực tiếp vào App...', 'loading');

      // 1. Thử qua Background Service Worker
      try {
        const bgSync = await new Promise((resolve) => {
          chrome.runtime.sendMessage({ action: 'FORCE_SYNC_COOKIES' }, (resp) => {
            if (chrome.runtime.lastError || !resp) {
              resolve(null);
            } else {
              resolve(resp);
            }
          });
        });
        if (bgSync && bgSync.success) {
          setStatus(`Đã đồng bộ cookies trực tiếp vào App!`, 'success');
          return;
        }
      } catch (e) {}

      // 2. Fallback trực tiếp
      const port = activeAppPort || await detectAppPort();
      if (!port) {
        setStatus('Chưa mở Desktop App! Hãy khởi động HyperMedia trên máy tính trước.', 'warning');
        return;
      }
      const res = await getNetscapeCookies(true);
      if (!res.success) {
        setStatus('Không tìm thấy cookies đăng nhập nào!', 'error');
        return;
      }
      try {
        const response = await fetch(`http://127.0.0.1:${port}/api/sync_cookies`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ cookies: res.text, domain: res.domain })
        });
        if (response.ok) {
          const result = await response.json();
          setStatus(`Đã đồng bộ ${result.count} cookies trực tiếp vào App!`, 'success');
        } else {
          setStatus('App từ chối nhận cookies.', 'error');
        }
      } catch (e) {
        console.error('Lỗi sync cookie:', e);
        setAppOffline();
        setStatus('Lỗi kết nối tới App Desktop.', 'error');
      }
    });
  }
});
