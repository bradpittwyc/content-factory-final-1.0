const status = document.getElementById('status');
for (const action of ['capture', 'batch', 'stop']) {
  document.getElementById(action).addEventListener('click', async () => {
    status.textContent = '正在执行...';
    try {
      const result = await chrome.runtime.sendMessage({ action, section: document.getElementById('section').value });
      status.textContent = result.error || result.message || JSON.stringify(result);
      if (action === 'capture' && result.saved) window.close();
    } catch (error) { status.textContent = error.message; }
  });
}
