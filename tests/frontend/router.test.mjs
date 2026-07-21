import test from 'node:test';
import assert from 'node:assert/strict';

import { createRouter } from '../../web/assets/app/core/router.mjs';

function fakeWindow() {
  const listeners = new Map();
  return {
    location: { hash: '#/one' },
    history: { replaceState(_state, _title, hash) { this.lastHash = hash; } },
    addEventListener(type, listener) { listeners.set(type, listener); },
    removeEventListener(type, listener) { if (listeners.get(type) === listener) listeners.delete(type); },
  };
}

test('router aborts the prior page and rejects stale commits', async () => {
  const windowRef = fakeWindow();
  const writes = [];
  let releaseFirst;
  const firstReady = new Promise(resolve => { releaseFirst = resolve; });
  let firstDisposed = 0;
  const routes = {
    one: async (_root, context) => {
      await firstReady;
      context.commit(() => writes.push('stale'));
      return { dispose() { firstDisposed += 1; } };
    },
    two: async (_root, context) => {
      context.commit(() => writes.push('current'));
      return { dispose() {} };
    },
  };
  const router = createRouter({
    root: {},
    routes,
    windowRef,
    resolve: hash => {
      const route = hash.endsWith('two') ? 'two' : 'one';
      return { route, hash: `#/${route}`, redirected: false };
    },
  });

  const first = router.transition('#/one');
  const second = router.transition('#/two');
  releaseFirst();
  const [oldResult, currentResult] = await Promise.all([first, second]);
  assert.equal(oldResult.stale, true);
  assert.equal(currentResult.stale, false);
  assert.deepEqual(writes, ['current']);
  assert.equal(firstDisposed, 1);
  assert.equal(router.current().route, 'two');
  assert.equal(router.stop(), true);
});

test('router rewrites forbidden hashes through the supplied resolver', async () => {
  const windowRef = fakeWindow();
  const router = createRouter({
    root: {},
    routes: { download: async () => ({ dispose() {} }) },
    windowRef,
    resolve: () => ({ route: 'download', hash: '#/download', redirected: true }),
  });
  await router.transition('#/users');
  assert.equal(windowRef.history.lastHash, '#/download');
});
