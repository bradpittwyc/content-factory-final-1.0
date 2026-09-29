document.getElementById('btnSync').addEventListener('click', async () => {
  const statusEl = document.getElementById('status');
  statusEl.innerText = "正在读取当前已登录凭证...";
  
  try {
    const cookies = await chrome.cookies.getAll({ domain: "ft.com" });
    if (!cookies || cookies.length === 0) {
      statusEl.style.color = "#f43f5e";
      statusEl.innerText = "未在当前浏览器找到 FT Cookies，请先打开 ft.com 登录";
      return;
    }

    const cookieParts = cookies.map(c => `${c.name}=${c.value}`);
    const cookieStr = cookieParts.join("; ");

    // Also get accounts.ft.com cookies specifically
    const accCookies = await chrome.cookies.getAll({ domain: "accounts.ft.com" });
    const allCookies = [...cookies, ...accCookies];
    const fullCookieStr = Array.from(new Set(allCookies.map(c => `${c.name}=${c.value}`))).join("; ");

    statusEl.innerText = `正在向后台推送 ${allCookies.length} 个授权凭证...`;

    const res = await fetch("http://127.0.0.1:8000/api/ft/cookie", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ cookie: fullCookieStr })
    });
    const data = await res.json();
    if (data.success) {
      statusEl.style.color = "#10b981";
      statusEl.innerText = `🎉 同步成功！共 ${allCookies.length} 个核心授权凭证已永久存入系统！`;
    } else {
      statusEl.style.color = "#f43f5e";
      statusEl.innerText = "同步失败: " + data.message;
    }
  } catch(e) {
    statusEl.style.color = "#f43f5e";
    statusEl.innerText = "同步异常: " + e.message;
  }
});
