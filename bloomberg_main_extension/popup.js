const status = document.getElementById('status');
let workerReady = false;
async function showError(message) {
  await chrome.storage.local.set({ captureStatus: message });
  status.textContent = message;
}
async function verifyWorker() {
  try {
    const response = await chrome.runtime.sendMessage({ action: 'info' });
    if (response?.api_version !== 3 || response?.capture_version !== 2) {
      throw new Error('后台采集器仍是旧版本。请在 chrome://extensions 找到本扩展，点击圆形箭头“重新加载”，再打开此弹窗。');
    }
    document.getElementById('version').textContent = `扩展 v${response.extension_version} · 后台已连接`;
    workerReady = true;
    return true;
  } catch (error) {
    document.getElementById('version').textContent = '后台版本检查失败';
    await showError(error.message);
    return false;
  }
}
const ready = verifyWorker();
async function refresh() {
  if (!workerReady) return;
  const { captureStatus } = await chrome.storage.local.get('captureStatus');
  if (captureStatus) status.textContent = captureStatus;
}
for (const action of ['capture', 'batch', 'tech', 'stop']) {
  document.getElementById(action).addEventListener('click', async () => {
    try {
      if (!await ready) return;
      if (action !== 'stop') await showError(action === 'tech' ? '正在启动 Tech 栏目采集...' : '正在启动采集...');
      const response = await chrome.runtime.sendMessage({ action });
      if (response.error) await showError(response.error);
      else await refresh();
    } catch (error) { await showError(error.message); }
  });
}
ready.then(refresh);
setInterval(refresh, 1000);
