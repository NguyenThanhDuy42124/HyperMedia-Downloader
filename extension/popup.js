// Popup Script for HyperMedia Helper Extension
document.addEventListener('DOMContentLoaded', async () => {
  const siteBadge = document.getElementById('siteBadge');
  const btnCopySingle = document.getElementById('btnCopySingle');
  const btnStartBatch = document.getElementById('btnStartBatch');
  const btnStopBatch = document.getElementById('btnStopBatch');
  const btnCopyAll = document.getElementById('btnCopyAll');
  const inpLimit = document.getElementById('inpLimit');
  const statusMsg = document.getElementById('statusMsg');
  const txtResults = document.getElementById('txtResults');

  // Lấy tab hiện tại
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (!tab || !tab.url) {
    statusMsg.innerText = 'Không tìm thấy tab hợp lệ!';
    return;
  }

  const url = tab.url;
  let platform = 'Khác';
  if (url.includes('douyin.com')) platform = 'Douyin (抖音)';
  else if (url.includes('tiktok.com')) platform = 'TikTok';
  else if (url.includes('bilibili.com')) platform = 'Bilibili';
  else if (url.includes('youtube.com')) platform = 'YouTube';

  siteBadge.innerText = platform;

  // 1. Copy Link Video Đơn
  btnCopySingle.addEventListener('click', async () => {
    statusMsg.innerText = 'Đang trích xuất link video...';
    try {
      const resp = await chrome.tabs.sendMessage(tab.id, { action: 'GET_SINGLE_VIDEO' });
      if (resp && resp.url) {
        await navigator.clipboard.writeText(resp.url);
        statusMsg.innerText = '✅ Đã copy link video vào Clipboard!';
        txtResults.value = resp.url;
      } else {
        // Fallback lấy url tab
        await navigator.clipboard.writeText(url);
        statusMsg.innerText = '✅ Đã copy link tab hiện tại!';
        txtResults.value = url;
      }
    } catch (e) {
      await navigator.clipboard.writeText(url);
      statusMsg.innerText = '✅ Đã copy URL trang hiện tại!';
      txtResults.value = url;
    }
  });

  // 2. Bắt đầu quét hàng loạt
  btnStartBatch.addEventListener('click', async () => {
    const limit = parseInt(inpLimit.value, 10) || 0;
    statusMsg.innerText = `Đang tự động cuộn trang quét tối đa ${limit === 0 ? 'Tất cả' : limit} video...`;
    btnStartBatch.style.display = 'none';
    btnStopBatch.style.display = 'flex';
    txtResults.value = '';

    try {
      const resp = await chrome.tabs.sendMessage(tab.id, { action: 'START_BATCH_SCAN', limit: limit });
      if (resp && resp.links) {
        handleScanComplete(resp.links);
      }
    } catch (e) {
      statusMsg.innerText = 'Lỗi kết nối trang! Hãy F5 lại trang rồi thử lại.';
      btnStartBatch.style.display = 'flex';
      btnStopBatch.style.display = 'none';
    }
  });

  // 3. Dừng quét
  btnStopBatch.addEventListener('click', async () => {
    try {
      await chrome.tabs.sendMessage(tab.id, { action: 'STOP_BATCH_SCAN' });
    } catch (e) {}
    statusMsg.innerText = 'Đã dừng quét!';
    btnStartBatch.style.display = 'flex';
    btnStopBatch.style.display = 'none';
  });

  // 4. Copy toàn bộ link kết quả
  btnCopyAll.addEventListener('click', async () => {
    if (!txtResults.value) return;
    await navigator.clipboard.writeText(txtResults.value);
    statusMsg.innerText = `✅ Đã copy toàn bộ link vào Clipboard!`;
  });

  function handleScanComplete(links) {
    btnStartBatch.style.display = 'flex';
    btnStopBatch.style.display = 'none';
    if (!links || links.length === 0) {
      statusMsg.innerText = 'Không tìm thấy video nào trên trang này!';
      return;
    }
    const text = links.join('\n');
    txtResults.value = text;
    statusMsg.innerText = `🎉 Quét hoàn tất: ${links.length} video!`;
    btnCopyAll.style.display = 'flex';
    btnCopyAll.innerText = `📋 Copy Toàn Bộ (${links.length} Link)`;
    navigator.clipboard.writeText(text);
  }

  // Lắng nghe cập nhật tiến trình từ content script
  chrome.runtime.onMessage.addListener((msg) => {
    if (msg.action === 'BATCH_PROGRESS') {
      statusMsg.innerText = `Đang quét: ${msg.count} video...`;
      if (msg.links) {
        txtResults.value = msg.links.join('\n');
      }
    } else if (msg.action === 'BATCH_DONE') {
      handleScanComplete(msg.links);
    }
  });
});
