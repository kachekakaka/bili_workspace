(() => {
  'use strict';

  const LOADED_FRONTEND_VERSION = '20260719-2';

  function applicationVersion() {
    const text = document.querySelector('#brandMode')?.textContent || '';
    const match = text.match(/V([0-9]+(?:\.[0-9]+)*)/i);
    return match?.[1] || '';
  }

  function renderVersion() {
    const badge = document.querySelector('#browserVersionBadge');
    if (!badge) return;

    const expected = document.documentElement.dataset.frontendVersion || '';
    const application = applicationVersion();
    const enhancement = String(window.BiliEnhancements?.VERSION || '未加载');
    const mismatch = Boolean(expected && expected !== LOADED_FRONTEND_VERSION);
    const text = mismatch
      ? `缓存不一致 · 页面 ${expected} / 已载入 ${LOADED_FRONTEND_VERSION}`
      : `${application ? `应用 ${application} · ` : ''}前端 ${LOADED_FRONTEND_VERSION}`;
    const className = `badge ${mismatch ? 'warn' : 'neutral'} browser-version-badge`;
    const title = mismatch
      ? `浏览器缓存版本不一致：页面要求 ${expected}，当前版本脚本为 ${LOADED_FRONTEND_VERSION}。请强制刷新。`
      : `应用版本：${application || '连接后显示'}；前端资源版本：${LOADED_FRONTEND_VERSION}；增强核心：${enhancement}`;

    if (badge.textContent !== text) badge.textContent = text;
    if (badge.className !== className) badge.className = className;
    if (badge.title !== title) badge.title = title;
    badge.dataset.loadedFrontendVersion = LOADED_FRONTEND_VERSION;
    badge.dataset.expectedFrontendVersion = expected;
    badge.dataset.cacheMatch = mismatch ? 'false' : 'true';
  }

  function start() {
    renderVersion();
    const brandMode = document.querySelector('#brandMode');
    if (brandMode) {
      new MutationObserver(renderVersion).observe(brandMode, {
        childList: true,
        characterData: true,
        subtree: true,
      });
    }
    window.addEventListener('pageshow', renderVersion);
    window.addEventListener('hashchange', renderVersion);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', start, { once: true });
  } else {
    start();
  }
})();
