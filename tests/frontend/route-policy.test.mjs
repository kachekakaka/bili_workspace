import test from 'node:test';
import assert from 'node:assert/strict';

import {
  ADMIN_ROUTES,
  USER_ROUTES,
  parseHashRoute,
  resolveRoute,
} from '../../web/assets/app/core/route-policy.mjs';

test('admin and user route sets stay role scoped', () => {
  assert.deepEqual(USER_ROUTES, ['download', 'tasks']);
  assert.ok(ADMIN_ROUTES.includes('users'));
  assert.ok(!USER_ROUTES.includes('users'));
});

test('hash parsing ignores query strings and normalizes case', () => {
  assert.equal(parseHashRoute('#/Search?q=test'), 'search');
  assert.equal(parseHashRoute('#/library/ignored'), 'library');
  assert.equal(parseHashRoute('#/%E0%A4%A'), '');
});

test('forbidden user routes fall back to download', () => {
  assert.deepEqual(resolveRoute('#/users', 'user'), {
    requested: 'users',
    route: 'download',
    fallback: 'download',
    redirected: true,
    hash: '#/download',
  });
});
