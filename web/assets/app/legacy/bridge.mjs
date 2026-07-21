import { once } from '../core/lifecycle.mjs';

const globalRef = globalThis.window;

function legacyEnhancements() {
  return globalRef?.BiliEnhancements || null;
}

async function mountLegacyPage(page, root, context = {}) {
  const legacy = legacyEnhancements();
  if (!legacy?.renderPage) throw new Error(`旧页面适配器未加载：${page}`);
  if (context.signal?.aborted) return Object.freeze({ dispose: () => false });
  const host = globalRef.document.createElement('div');
  host.dataset.enhancedView = page;
  if (typeof context.commit === 'function') context.commit(() => root.replaceChildren(host));
  else root.replaceChildren(host);
  await legacy.renderPage(page, host);
  if (context.signal?.aborted || (typeof context.isCurrent === 'function' && !context.isCurrent())) {
    host.remove();
    return Object.freeze({ dispose: () => false });
  }
  return Object.freeze({
    dispose: once(() => host.remove()),
  });
}

export function createLegacyBridge(windowRef = globalRef) {
  if (!windowRef) throw new TypeError('window is unavailable');
  return Object.freeze({
    mode() {
      return windowRef.document?.documentElement?.dataset?.appShell || 'legacy';
    },
    currentPage() {
      return String(windowRef.location?.hash || '').replace(/^#\/?/, '').split('?', 1)[0];
    },
    navigate(page, { replace = false } = {}) {
      const hash = `#/${String(page || '').replace(/^#\/?/, '')}`;
      if (replace) windowRef.history?.replaceState?.(null, '', hash);
      else windowRef.location.hash = hash;
      return hash;
    },
    refresh() {
      const button = windowRef.document?.querySelector('#refreshButton');
      if (button instanceof windowRef.HTMLButtonElement) button.click();
    },
    mount: mountLegacyPage,
    state() {
      return legacyEnhancements()?.state || null;
    },
    api(path, options) {
      const legacy = legacyEnhancements();
      if (!legacy?.api) throw new Error('旧 API 适配器未加载');
      return legacy.api(path, options);
    },
    toast(message, type) {
      return legacyEnhancements()?.toast?.(message, type);
    },
    showModal(title, body, options) {
      const legacy = legacyEnhancements();
      if (!legacy?.showModal) throw new Error('旧 Modal 适配器未加载');
      return legacy.showModal(title, body, options);
    },
  });
}

export const legacyBridge = createLegacyBridge();

if (globalRef && !globalRef.BiliLegacyApp) {
  Object.defineProperty(globalRef, 'BiliLegacyApp', {
    value: legacyBridge,
    configurable: true,
    enumerable: false,
    writable: false,
  });
}
