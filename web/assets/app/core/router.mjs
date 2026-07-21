import { createGenerationGate, once } from './lifecycle.mjs';

function normalizeHandle(value) {
  const dispose = typeof value === 'function' ? value : value?.dispose;
  return Object.freeze({ dispose: once(typeof dispose === 'function' ? () => dispose.call(value) : null) });
}

export function createRouter({
  root,
  routes,
  resolve,
  windowRef = globalThis.window,
  AbortControllerImpl = globalThis.AbortController,
  onError = null,
} = {}) {
  if (!root) throw new TypeError('root is required');
  if (!routes || typeof routes !== 'object') throw new TypeError('routes are required');
  if (typeof resolve !== 'function') throw new TypeError('resolve is required');
  if (!windowRef?.addEventListener) throw new TypeError('windowRef is required');

  const gate = createGenerationGate();
  let started = false;
  let active = null;

  const disposeActive = () => {
    if (!active) return;
    active.controller.abort();
    active.handle?.dispose();
    active = null;
  };

  const transition = async (hashValue = windowRef.location.hash, { replaceInvalid = true } = {}) => {
    const decision = resolve(hashValue);
    const route = decision?.route;
    const mount = routes[route];
    if (typeof mount !== 'function') throw new Error(`页面不存在：${route || ''}`);
    if (decision.redirected && replaceInvalid && windowRef.location.hash !== decision.hash) {
      windowRef.history?.replaceState?.(null, '', decision.hash);
    }

    disposeActive();
    const controller = new AbortControllerImpl();
    const generation = gate.begin();
    const record = { route, generation, controller, handle: null };
    active = record;
    root.innerHTML = '<div class="loading-card">正在载入…</div>';
    const context = Object.freeze({
      route,
      generation,
      signal: controller.signal,
      isCurrent: () => active === record && gate.isCurrent(generation) && !controller.signal.aborted,
      commit(callback) {
        if (active !== record || controller.signal.aborted) return false;
        return gate.commit(generation, callback);
      },
    });

    try {
      const value = await mount(root, context);
      const handle = normalizeHandle(value);
      if (active !== record || controller.signal.aborted || !gate.isCurrent(generation)) {
        handle.dispose();
        return Object.freeze({ route, generation, stale: true });
      }
      record.handle = handle;
      return Object.freeze({ route, generation, stale: false });
    } catch (error) {
      if (error?.name === 'AbortError' || active !== record || controller.signal.aborted) {
        return Object.freeze({ route, generation, stale: true });
      }
      if (typeof onError === 'function') onError(error, { route, generation });
      else throw error;
      return Object.freeze({ route, generation, stale: false, error });
    }
  };

  const onHashChange = () => { void transition(); };

  return Object.freeze({
    start() {
      if (started) return false;
      started = true;
      windowRef.addEventListener('hashchange', onHashChange);
      void transition();
      return true;
    },
    stop() {
      if (!started && !active) return false;
      started = false;
      windowRef.removeEventListener('hashchange', onHashChange);
      gate.invalidate();
      disposeActive();
      return true;
    },
    transition,
    navigate(route, { replace = false } = {}) {
      const hash = `#/${String(route || '').replace(/^#\/?/, '')}`;
      if (replace) windowRef.history?.replaceState?.(null, '', hash);
      else windowRef.location.hash = hash;
      return hash;
    },
    current() {
      return active ? Object.freeze({ route: active.route, generation: active.generation }) : null;
    },
  });
}
