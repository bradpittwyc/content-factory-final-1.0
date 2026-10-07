const status = document.getElementById('status');
let workerReady = false;
async function showError(message) {
  await chrome.storage.local.set({ captureStatus: message });
  status.textContent = message;
}
async function verifyWorker() {
  try {
    const response = await chrome.runtime.sendMessage({ action: 'info' });
    if (response?.api_version !== 5 || response?.capture_version !== 2) {
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
      else if (action === 'capture' && response.saved) window.close();
      else await refresh();
    } catch (error) { await showError(error.message); }
  });
}
ready.then(refresh);
setInterval(refresh, 1000);

async function refreshAutomation() {
  const element = document.getElementById('auto_state');
  if (!element || !workerReady) return;
  try {
    const result = await chrome.runtime.sendMessage({ action: 'auto_status' });
    if (result.error) throw new Error(result.error);
    const date = value => value ? new Date(value * 1000).toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai' }) : '未安排';
    const select = document.getElementById('column_select');
    if (select && result.columns) {
      const selected = select.value;
      select.replaceChildren(...result.columns.map(column => {
        const option = document.createElement('option');
        option.value = column.id;
        option.textContent = column.name + (column.enabled ? '' : '（自动未启用）');
        return option;
      }));
      if (result.columns.some(column => column.id === selected)) select.value = selected;
    }
    const enabled = (result.columns || []).filter(column => column.enabled).map(column => column.name).join('、');
    element.textContent = `${result.enabled ? '自动计划已开启' : '自动计划已关闭'}${result.pause_reason ? ' · ' + result.pause_reason : ''}\n间隔：${result.interval_minutes} 分钟，每轮最多 1 篇\n轮流采集：${enabled || '无启用专栏'}\n下次计划：${date(result.next_due_at)}（北京时间）\n最近结果：${result.last_run?.result || '暂无'}`;
    element.style.whiteSpace = 'pre-wrap';
  } catch (error) { element.textContent = `自动计划连接失败：${error.message}`; }
}
for (const action of ['auto_enable', 'auto_run', 'auto_stop']) {
  document.getElementById(action)?.addEventListener('click', async () => {
    try {
      if (!await ready) return;
      const result = await chrome.runtime.sendMessage({ action, ...(action === 'auto_run' ? { column: document.getElementById('column_select')?.value || 'tech' } : {}) });
      if (result.error) throw new Error(result.error);
      await refreshAutomation();
      await refresh();
    } catch (error) { await showError(error.message); }
  });
}
ready.then(refreshAutomation);
setInterval(refreshAutomation, 10000);
document.getElementById('column_batch')?.addEventListener('click', async () => {
  try {
    if (!await ready) return;
    const response = await chrome.runtime.sendMessage({ action: 'column_batch', column: document.getElementById('column_select').value });
    if (response.error) throw new Error(response.error);
    await refresh();
  } catch (error) { await showError(error.message); }
});
