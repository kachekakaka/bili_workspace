import test from 'node:test';
import assert from 'node:assert/strict';

import {
  createVersionChecker,
  versionMismatchReason,
} from '../../web/assets/app/core/version-check.mjs';

test('version mismatch reasons distinguish page, service and legacy service cases', () => {
  assert.equal(versionMismatchReason({ loaded: '2', expected: '1' }), '页面 1 / 脚本 2');
  assert.equal(
    versionMismatchReason({
      loaded: '2', expected: '2', server: { service: 'bili_workspace', frontend_version: '1' },
    }),
    '服务 1 / 脚本 2',
  );
  assert.equal(
    versionMismatchReason({ loaded: '2', expected: '2', server: { service: 'old' } }),
    '服务仍是旧版 / 脚本 2',
  );
  assert.equal(
    versionMismatchReason({
      loaded: '2', expected: '2', server: { service: 'bili_workspace', frontend_version: '2' },
    }),
    '',
  );
});

class FakeTarget {
  constructor(textContent = '') {
    this.textContent = textContent;
    this.className = '';
    this.title = '';
    this.dataset = {};
    this.listeners = new Map();
  }

  addEventListener(type, listener) {
    this.listeners.set(type, listener);
  }

  removeEventListener(type) {
    this.listeners.delete(type);
  }

  click() {
    this.listeners.get('click')?.();
  }
}

test('checker renders explicit recovery and reloads only on mismatch', async () => {
  const badge = new FakeTarget();
  const brand = new FakeTarget('V0.7.0');
  let reloads = 0;
  const windowRef = {
    listeners: new Map(),
    location: { reload: () => { reloads += 1; } },
    addEventListener(type, listener) { this.listeners.set(type, listener); },
    removeEventListener(type) { this.listeners.delete(type); },
  };
  const checker = createVersionChecker({
    badge,
    brandNode: brand,
    loadedVersion: '20260720-2',
    expectedVersion: '20260720-2',
    windowRef,
    fetchImpl: async () => ({
      ok: true,
      async json() {
        return {
          service: 'bili_workspace',
          version: '0.6.2',
          frontend_version: 'old-build',
          build_id: 'abcdef123456',
        };
      },
    }),
  });

  assert.equal(checker.start(), true);
  await checker.refresh();
  assert.match(badge.textContent, /版本不一致/);
  assert.equal(badge.dataset.cacheMatch, 'false');
  assert.equal(badge.dataset.recoveryAction, 'reload');
  badge.click();
  assert.equal(reloads, 1);
  assert.equal(checker.stop(), true);
});
