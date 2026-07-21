import test from 'node:test';
import assert from 'node:assert/strict';

import {
  formatBytes,
  formatPlayCount,
  toEpochMilliseconds,
} from '../../web/assets/app/core/format.mjs';

test('byte formatting preserves the V0.6 display contract', () => {
  assert.equal(formatBytes(0), '0 B');
  assert.equal(formatBytes(1024), '1.00 KB');
  assert.equal(formatBytes(10 * 1024), '10.0 KB');
  assert.equal(formatBytes(-1), '-');
});

test('play counts use Chinese units', () => {
  assert.equal(formatPlayCount(12_345), '1.2万');
  assert.equal(formatPlayCount(123_456_789), '1.2亿');
});

test('epoch seconds and milliseconds normalize consistently', () => {
  assert.equal(toEpochMilliseconds(1_700_000_000), 1_700_000_000_000);
  assert.equal(toEpochMilliseconds(1_700_000_000_000), 1_700_000_000_000);
  assert.equal(toEpochMilliseconds('bad'), null);
});
