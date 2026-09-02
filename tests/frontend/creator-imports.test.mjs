import test from 'node:test';
import assert from 'node:assert/strict';

import {
  creatorImportCard,
  creatorImportConfirmMessage,
  creatorImportListMarkup,
  creatorImportProgress,
  creatorImportStatusLabel,
} from '../../web/assets/app/pages/creator-imports.mjs';
import {
  LIBRARY_OPEN_REQUEST_KEY,
  storeLibraryOpenRequest,
  takeLibraryOpenRequest,
} from '../../web/assets/app/core/library-navigation.mjs';

test('dashboard media request is consumed exactly once', () => {
  const values = new Map();
  const storage = {
    getItem: key => values.get(key) || null,
    setItem: (key, value) => values.set(key, value),
    removeItem: key => values.delete(key),
  };

  assert.equal(storeLibraryOpenRequest(storage, 'media-42'), true);
  assert.equal(values.get(LIBRARY_OPEN_REQUEST_KEY), 'media-42');
  assert.equal(takeLibraryOpenRequest(storage), 'media-42');
  assert.equal(takeLibraryOpenRequest(storage), '');
});

test('creator import progress follows discovery pages then enqueue classification', () => {
  assert.equal(creatorImportProgress({ phase: 'discovering', current_page: 2, total_pages: 4 }), 50);
  assert.equal(creatorImportProgress({ phase: 'enqueuing', processed: 3, discovered: 4 }), 75);
  assert.equal(creatorImportProgress({ status: 'completed', phase: 'completed' }), 100);
});

test('creator import cards expose only valid lifecycle actions', () => {
  const running = creatorImportCard({
    id: 'job-1', uid: '123', status: 'discovering', phase: 'discovering', can_cancel: true,
  });
  const failed = creatorImportCard({
    id: 'job-2', uid: '456', status: 'failed', phase: 'failed', can_resume: true,
  });
  const partial = creatorImportCard({
    id: 'job-3', uid: '789', status: 'partial', phase: 'partial', can_retry_failed: true,
  });

  assert.match(running, /data-creator-import-action="cancel"/);
  assert.doesNotMatch(running, /retry-failed/);
  assert.match(failed, /data-creator-import-action="resume"/);
  assert.match(partial, /data-creator-import-action="retry-failed"/);
  assert.equal(creatorImportStatusLabel('completed'), '已完成入队');
});

test('creator page filters runtime jobs to the current uid and escapes content', () => {
  const markup = creatorImportListMarkup([
    { id: 'a', uid: '1', creator_name: '<script>', status: 'completed' },
    { id: 'b', uid: '2', creator_name: '另一个 UP', status: 'waiting' },
  ], { uid: '1' });

  assert.match(markup, /&lt;script&gt;/);
  assert.doesNotMatch(markup, /另一个 UP/);
});

test('confirmation states the one-time scope and skip rules', () => {
  const message = creatorImportConfirmMessage({
    creator: { uid: '123', name: '测试 UP' }, total: 88, groupName: '收藏', minHeight: 1080,
  });
  assert.match(message, /以现在为截止点/);
  assert.match(message, /忽略当前标题筛选和页面排序/);
  assert.match(message, /媒体库已有、活动任务和删除历史/);
  assert.match(message, /收藏/);
  assert.match(message, /1080P/);
});
