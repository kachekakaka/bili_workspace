import test from 'node:test';
import assert from 'node:assert/strict';

import { createSessionStore } from '../../web/assets/app/core/auth-session.mjs';
import { createContextStore } from '../../web/assets/app/core/context-store.mjs';

test('context store subscriptions can be cancelled idempotently', () => {
  const store = createContextStore({ count: 1 });
  const values = [];
  const unsubscribe = store.subscribe(value => values.push(value.count));
  store.patch({ count: 2 });
  assert.equal(unsubscribe(), true);
  assert.equal(unsubscribe(), false);
  store.patch({ count: 3 });
  assert.deepEqual(values, [2]);
  assert.equal(store.listenerCount(), 0);
});

test('session store normalizes user role, permissions and CSRF token', () => {
  const store = createSessionStore();
  store.set({
    authenticated: true,
    csrf_token: 'csrf',
    permissions: ['admin:*'],
    user: { id: 'u1', username: 'admin', display_name: '管理员', role: 'admin' },
  });
  assert.equal(store.get().username, 'admin');
  assert.equal(store.get().displayName, '管理员');
  assert.equal(store.get().csrfToken, 'csrf');
  assert.equal(store.isAdmin(), true);
  assert.equal(store.can('anything'), true);
  store.clear();
  assert.equal(store.get().authenticated, false);
});
