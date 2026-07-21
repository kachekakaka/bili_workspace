import test from 'node:test';
import assert from 'node:assert/strict';

import {
  ApiError,
  AuthExpiredError,
  createApiClient,
} from '../../web/assets/app/core/api.mjs';

function jsonResponse(payload, status = 200) {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

test('API client sends JSON and the single CSRF token source', async () => {
  let received = null;
  const api = createApiClient({
    getCsrfToken: () => 'csrf-one',
    fetchImpl: async (path, options) => {
      received = { path, options };
      return jsonResponse({ ok: true, data: { saved: true } });
    },
  });
  const payload = await api('/api/config', { method: 'PUT', body: { value: 1 } });
  assert.equal(payload.data.saved, true);
  assert.equal(received.path, '/api/config');
  assert.equal(received.options.headers['X-CSRF-Token'], 'csrf-one');
  assert.equal(received.options.body, '{"value":1}');
});

test('HTTP 401 becomes AuthExpiredError and invokes the shell callback', async () => {
  let callbackError = null;
  const api = createApiClient({
    fetchImpl: async () => jsonResponse({ ok: false, code: 'unauthorized', error: '会话失效' }, 401),
    onAuthExpired: error => { callbackError = error; },
  });
  await assert.rejects(() => api('/api/tasks'), error => {
    assert.ok(error instanceof AuthExpiredError);
    assert.equal(error.status, 401);
    assert.equal(error.message, '会话失效');
    return true;
  });
  assert.ok(callbackError instanceof AuthExpiredError);
});

test('error envelopes retain code and status', async () => {
  const api = createApiClient({
    fetchImpl: async () => jsonResponse({ ok: false, code: 'invalid', error: '参数错误' }, 422),
  });
  await assert.rejects(() => api('/api/example'), error => {
    assert.ok(error instanceof ApiError);
    assert.equal(error.code, 'invalid');
    assert.equal(error.status, 422);
    return true;
  });
});
