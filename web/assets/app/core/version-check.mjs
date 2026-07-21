function text(value) {
  return String(value ?? '').trim();
}

function applicationVersion(brandNode) {
  const match = text(brandNode?.textContent).match(/V([0-9]+(?:\.[0-9]+)*)/i);
  return match?.[1] || '';
}

export function versionMismatchReason({ loaded, expected, server, error = '' } = {}) {
  if (expected && expected !== loaded) return `页面 ${expected} / 脚本 ${loaded}`;
  if (!server && error) return '无法读取服务版本';
  if (!server) return '';
  if (server.service !== 'bili_workspace' || !server.frontend_version) return `服务仍是旧版 / 脚本 ${loaded}`;
  if (text(server.frontend_version) !== loaded) return `服务 ${server.frontend_version} / 脚本 ${loaded}`;
  return '';
}

export function createVersionChecker({
  badge,
  brandNode,
  loadedVersion,
  expectedVersion,
  fetchImpl = globalThis.fetch,
  windowRef = globalThis.window,
} = {}) {
  if (!badge) throw new TypeError('badge is required');
  if (typeof fetchImpl !== 'function') throw new TypeError('fetchImpl is required');
  const loaded = text(loadedVersion);
  const expected = text(expectedVersion);
  let server = null;
  let error = '';
  let started = false;
  let mismatch = '';

  const render = () => {
    mismatch = versionMismatchReason({ loaded, expected, server, error });
    const application = text(server?.version) || applicationVersion(brandNode);
    const build = text(server?.build_id);
    const serverFrontend = text(server?.frontend_version);
    const waiting = !server && !error;
    badge.className = `badge ${mismatch ? 'warn' : 'neutral'} browser-version-badge`;
    badge.textContent = mismatch
      ? `版本不一致 · ${mismatch} · 点击恢复`
      : waiting
        ? `前端 ${loaded} · 检查服务`
        : `${application ? `应用 ${application} · ` : ''}前端 ${loaded}${build ? ` · 构建 ${build.slice(0, 8)}` : ''}`;
    badge.title = mismatch
      ? `浏览器页面与服务资源不一致：${mismatch}。请先重新启动服务，再点击这里强制刷新页面资源。`
      : `应用版本：${application || '连接后显示'}；页面资源：${expected || '未声明'}；已载入脚本：${loaded}；服务资源：${serverFrontend || '读取中'}；服务构建：${build || '读取中'}`;
    badge.dataset.loadedFrontendVersion = loaded;
    badge.dataset.expectedFrontendVersion = expected;
    badge.dataset.serverFrontendVersion = serverFrontend;
    badge.dataset.serverBuildId = build;
    badge.dataset.cacheMatch = mismatch ? 'false' : waiting ? 'checking' : 'true';
    badge.dataset.recoveryAction = mismatch ? 'reload' : '';
    return mismatch;
  };

  const refresh = async () => {
    try {
      const response = await fetchImpl(`/healthz?_=${Date.now()}`, {
        cache: 'no-store',
        credentials: 'same-origin',
        headers: { Accept: 'application/json', 'Cache-Control': 'no-cache' },
      });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const payload = await response.json();
      server = payload && typeof payload === 'object' ? payload : null;
      error = server ? '' : 'invalid payload';
    } catch (caught) {
      server = null;
      error = text(caught?.message || caught || 'unknown error');
    }
    render();
    return Object.freeze({ server, error, mismatch });
  };

  const onPageShow = () => { void refresh(); };
  const onClick = () => {
    if (!mismatch) return;
    try { windowRef?.location?.reload?.(); } catch {}
  };

  return Object.freeze({
    start() {
      if (started) return false;
      started = true;
      badge.addEventListener('click', onClick);
      windowRef?.addEventListener?.('pageshow', onPageShow);
      render();
      void refresh();
      return true;
    },
    stop() {
      if (!started) return false;
      started = false;
      badge.removeEventListener('click', onClick);
      windowRef?.removeEventListener?.('pageshow', onPageShow);
      return true;
    },
    refresh,
    render,
    get() {
      return Object.freeze({ server, error, mismatch });
    },
  });
}
