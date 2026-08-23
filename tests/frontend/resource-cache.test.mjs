import test from 'node:test';
import assert from 'node:assert/strict';

import {
  createResourceCache,
  resourceKey,
} from '../../web/assets/app/core/resource-cache.mjs';

test('resource keys are stable across parameter insertion order', () => {
  assert.equal(
    resourceKey('library', { page: 1, filters: { q: 'x', group: 'g' } }),
    resourceKey('library', { filters: { group: 'g', q: 'x' }, page: 1 }),
  );
});

test('in-flight requests coalesce while route abort only cancels that consumer', async () => {
  const cache = createResourceCache();
  const firstRoute = new AbortController();
  const secondRoute = new AbortController();
  let calls = 0;
  let sharedSignal = null;
  let resolveLoader;
  const loader = ({ signal }) => {
    calls += 1;
    sharedSignal = signal;
    return new Promise(resolve => { resolveLoader = resolve; });
  };

  const first = cache.refresh('shared', loader, { signal: firstRoute.signal });
  const second = cache.refresh('shared', loader, { signal: secondRoute.signal });
  await Promise.resolve();
  assert.equal(calls, 1);
  firstRoute.abort();
  await assert.rejects(first, error => error.name === 'AbortError');
  assert.equal(sharedSignal.aborted, false);

  resolveLoader({ value: 42 });
  assert.deepEqual(await second, { value: 42 });
  assert.deepEqual(cache.peek('shared').value, { value: 42 });
  assert.equal(cache.inFlightCount(), 0);
});

test('failed background refresh keeps cached data and marks it stale', async () => {
  const cache = createResourceCache({ now: () => 123 });
  cache.set('status', { ready: true });
  await assert.rejects(
    cache.refresh('status', async () => { throw new Error('offline'); }),
    /offline/,
  );
  const entry = cache.peek('status');
  assert.deepEqual(entry.value, { ready: true });
  assert.equal(entry.stale, true);
  assert.equal(entry.error.message, 'offline');
  assert.equal(entry.updatedAt, 123);
});

test('explicit invalidation aborts the cache-owned request and clear drops session data', async () => {
  const cache = createResourceCache();
  cache.set('groups', [{ id: 'g1' }]);
  let sharedSignal;
  const pending = cache.refresh('groups', ({ signal }) => {
    sharedSignal = signal;
    return new Promise((_resolve, reject) => {
      signal.addEventListener('abort', () => {
        const error = new Error('aborted');
        error.name = 'AbortError';
        reject(error);
      }, { once: true });
    });
  });
  await Promise.resolve();
  cache.invalidate('groups');
  assert.equal(sharedSignal.aborted, true);
  assert.equal(cache.peek('groups').stale, true);
  await assert.rejects(pending, error => error.name === 'AbortError');
  cache.clear();
  assert.equal(cache.peek('groups'), null);
  assert.equal(cache.entryCount(), 0);
});

test('refresh after invalidation starts a new generation and ignores late old data', async () => {
  const cache = createResourceCache();
  let resolveOld;
  const oldRequest = cache.refresh('library', () => new Promise(resolve => {
    resolveOld = resolve;
  }));
  await Promise.resolve();
  cache.invalidate('library');

  const fresh = await cache.refresh('library', async () => 'fresh');
  assert.equal(fresh, 'fresh');
  resolveOld('late-old-value');
  await assert.rejects(oldRequest, error => error.name === 'AbortError');
  assert.equal(cache.peek('library').value, 'fresh');
});
