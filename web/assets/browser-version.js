(() => {
  'use strict';

  const LOADED_FRONTEND_VERSION = '20260719-3';
  let serverInfo = null;
  let serverError = '';

  function applicationVersion() {
    const fromServer = String(serverInfo?.version || '').trim();
    if (fromServer) return fromServer;
    const text = document.querySelector('#brandMode')?.textContent || '';
    const match = text.match(/V([0-9]+(?:\.[0-9]+)*)/i);
    return match?.[1] || '';
  }

  function mismatchReason(expected) {
    if (expected && expected !== LOADED_FRONTEND_VERSION) {
      return `页面 ${expected} / 脚本 ${LOADED_FRONTEND_VERSION}`;
    }
    if (!serverInfo && serverError) return '无法读取服务版本';
    if (!serverInfo) return '';
    if (serverInfo.service !== 'bili_workspace' || !serverInfo.frontend_version) {
      return `服务仍是旧版 / 脚本 ${LOADED_FRONTEND_VERSION}`;
    }
    if (String(serverInfo.frontend_version) !== LOADED_FRONTEND_VERSION) {
      return `服务 ${serverInfo.frontend_version} / 脚本 ${LOADED_FRONTEND_VERSION}`;
    }
    return '';
  }

  function renderVersion() {
    const badge = document.querySelector('#browserVersionBadge');
    if (!badge) return;

    const expected = document.documentElement.dataset.frontendVersion || '';
    const application = applicationVersion();
    const enhancement = String(window.BiliEnhancements?.VERSION || '未加载');
    const reason = mismatchReason(expected);
    const build = String(serverInfo?.build_id || '');
    const serverFrontend = String(serverInfo?.frontend_version || '');
    const waiting = !serverInfo && !serverError;

    let text;
    if (reason) {
      text = `版本不一致 · ${reason}`;
    } else if (waiting) {
      text = `前端 ${LOADED_FRONTEND_VERSION} · 检查服务`;
    } else {
      text = `${application ? `应用 ${application} · ` : ''}前端 ${LOADED_FRONTEND_VERSION}`;
      if (build) text += ` · 构建 ${build.slice(0, 8)}`;
    }

    const className = `badge ${reason ? 'warn' : 'neutral'} browser-version-badge`;
    const title = reason
      ? `浏览器、页面或正在运行的服务版本不一致：${reason}。请先重新运行 start.bat；仍不一致时再强制刷新。`
      : `应用版本：${application || '连接后显示'}；页面资源：${expected || '未声明'}；已载入脚本：${LOADED_FRONTEND_VERSION}；服务资源：${serverFrontend || '读取中'}；服务构建：${build || '读取中'}；增强核心：${enhancement}`;

    if (badge.textContent !== text) badge.textContent = text;
    if (badge.className !== className) badge.className = className;
    if (badge.title !== title) badge.title = title;
    badge.dataset.loadedFrontendVersion = LOADED_FRONTEND_VERSION;
    badge.dataset.expectedFrontendVersion = expected;
    badge.dataset.serverFrontendVersion = serverFrontend;
    badge.dataset.serverBuildId = build;
    badge.dataset.cacheMatch = reason ? 'false' : waiting ? 'checking' : 'true';
  }

  async function refreshServerInfo() {
    try {
      const response = await fetch(`/healthz?_=${Date.now()}`, {
        cache: 'no-store',
        credentials: 'same-origin',
        headers: { Accept: 'application/json', 'Cache-Control': 'no-cache' },
      });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const payload = await response.json();
      serverInfo = payload && typeof payload === 'object' ? payload : null;
      serverError = serverInfo ? '' : 'invalid payload';
    } catch (error) {
      serverInfo = null;
      serverError = String(error?.message || error || 'unknown error');
    }
    renderVersion();
  }

  function start() {
    renderVersion();
    void refreshServerInfo();
    const brandMode = document.querySelector('#brandMode');
    if (brandMode) {
      new MutationObserver(renderVersion).observe(brandMode, {
        childList: true,
        characterData: true,
        subtree: true,
      });
    }
    window.addEventListener('pageshow', () => void refreshServerInfo());
    window.addEventListener('hashchange', renderVersion);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', start, { once: true });
  } else {
    start();
  }
})();
