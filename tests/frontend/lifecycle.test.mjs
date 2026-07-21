import test from 'node:test';
import assert from 'node:assert/strict';

import {
  createAbortScope,
  createGenerationGate,
  once,
} from '../../web/assets/app/core/lifecycle.mjs';

test('only the current generation may commit', () => {
  const gate = createGenerationGate();
  const stale = gate.begin();
  const current = gate.begin();
  const writes = [];
  assert.equal(gate.commit(stale, () => writes.push('stale')), false);
  assert.equal(gate.commit(current, () => writes.push('current')), true);
  assert.deepEqual(writes, ['current']);
});

test('dispose wrappers are idempotent', () => {
  let calls = 0;
  const dispose = once(() => { calls += 1; });
  assert.equal(dispose(), true);
  assert.equal(dispose(), false);
  assert.equal(calls, 1);
});

test('abort scope aborts once', () => {
  const scope = createAbortScope();
  assert.equal(scope.signal.aborted, false);
  assert.equal(scope.dispose(), true);
  assert.equal(scope.signal.aborted, true);
  assert.equal(scope.dispose(), false);
});
