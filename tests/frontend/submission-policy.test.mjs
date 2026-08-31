import test from 'node:test';
import assert from 'node:assert/strict';

import {
  canSelectSubmission,
  selectableSubmissionItems,
  submissionPageKey,
  submissionScanDecision,
  visibleSubmissionItems,
} from '../../web/assets/app/core/submission-policy.mjs';

test('default submission view hides downloaded and deleted but keeps live state visible', () => {
  const items = [
    { bvid: 'new', title: '目标 新作', local_status: 'not_downloaded', selectable: true },
    { bvid: 'downloaded', title: '目标 已下', local_status: 'downloaded', selectable: true },
    { bvid: 'deleted', title: '目标 不要', local_status: 'deleted', selectable: true },
    { bvid: 'active', title: '目标 活动', local_status: 'queued', selectable: false },
  ];
  assert.deepEqual(
    visibleSubmissionItems(items, { filterText: '目标', filterMode: 'exact' }).map(item => item.bvid),
    ['new', 'active'],
  );
  assert.deepEqual(
    selectableSubmissionItems(items, { filterText: '目标', filterMode: 'exact' }).map(item => item.bvid),
    ['new'],
  );
  assert.equal(visibleSubmissionItems(items, { hideDownloaded: false }).length, 4);
});

test('demand scan stops at candidate, end, or the ten-page boundary', () => {
  assert.deepEqual(
    submissionScanDecision({ page: 2, pages: 20, candidateCount: 0, scanned: 2, limit: 10 }),
    { action: 'next', page: 2, nextPage: 3 },
  );
  assert.deepEqual(
    submissionScanDecision({ page: 3, pages: 20, candidateCount: 1, scanned: 3, limit: 10 }),
    { action: 'candidate', page: 3 },
  );
  assert.deepEqual(
    submissionScanDecision({ page: 20, pages: 20, candidateCount: 0, scanned: 4, limit: 10 }),
    { action: 'end', page: 20 },
  );
  assert.deepEqual(
    submissionScanDecision({ page: 10, pages: 20, candidateCount: 0, scanned: 10, limit: 10 }),
    { action: 'limit', page: 10, nextPage: 11 },
  );
});

test('cross-page selection respects remaining capacity and page cache identity', () => {
  assert.equal(canSelectSubmission({ selectedCount: 9, limit: 10 }), true);
  assert.equal(canSelectSubmission({ selectedCount: 10, limit: 10 }), false);
  assert.equal(canSelectSubmission({ selectedCount: 10, limit: 10, alreadySelected: true }), true);
  assert.notEqual(
    submissionPageKey({ uid: '123', order: 'pubdate', page: 1, destination: 'device' }),
    submissionPageKey({ uid: '123', order: 'pubdate', page: 2, destination: 'device' }),
  );
});
