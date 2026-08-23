import test from 'node:test';
import assert from 'node:assert/strict';

import {
  filterSearchItems,
  normalizeSearchText,
  readLru,
  SEARCH_PAGE_LRU_LIMIT,
  searchPageKey,
  shouldPrefetchNextPage,
  splitTitleTerms,
  titleMatches,
  writeLru,
} from '../../web/assets/app/core/search-policy.mjs';

test('exact and fuzzy filtering only inspect titles', () => {
  const items = [
    { title: '测试 原因 完整讲解', author: '无关' },
    { title: '测试工具', author: '原因' },
    { title: '完全无关', author: '测试 原因' },
  ];
  assert.deepEqual(splitTitleTerms(' 测试，原因 / 测试 '), ['测试', '原因']);
  assert.deepEqual(filterSearchItems(items, '测试 原因', 'exact'), [items[0]]);
  assert.deepEqual(filterSearchItems(items, '测试 原因', 'fuzzy'), [items[0], items[1]]);
  assert.equal(titleMatches(items[2].title, '测试 原因', 'fuzzy'), false);
  assert.equal(normalizeSearchText('ＡＢＣ'), 'abc');
});

test('title-only filters do not alter the Bilibili page cache key', () => {
  const first = searchPageKey({ keyword: 'Ａ猫', order: 'click', page: 2 });
  const second = searchPageKey({ keyword: 'a猫', order: 'click', page: 2 });
  assert.equal(first, second);
});

test('prefetch allows exactly the immediate next page opportunity', () => {
  assert.equal(shouldPrefetchNextPage({
    page: 1, pages: 5, currentPageSucceeded: true, queryIsCurrent: true,
  }), true);
  assert.equal(shouldPrefetchNextPage({
    page: 5, pages: 5, currentPageSucceeded: true, queryIsCurrent: true,
  }), false);
  assert.equal(shouldPrefetchNextPage({
    page: 1, pages: 5, saveData: true, currentPageSucceeded: true, queryIsCurrent: true,
  }), false);
  assert.equal(shouldPrefetchNextPage({
    page: 1, pages: 5, currentPageSucceeded: true, queryIsCurrent: false,
  }), false);
});

test('search page LRU keeps at most 24 entries and refreshes access order', () => {
  assert.equal(SEARCH_PAGE_LRU_LIMIT, 24);
  const cache = new Map();
  for (let index = 0; index < SEARCH_PAGE_LRU_LIMIT; index += 1) {
    writeLru(cache, `page-${index}`, index);
  }
  assert.equal(readLru(cache, 'page-0'), 0);
  writeLru(cache, 'page-24', 24);
  assert.equal(cache.size, 24);
  assert.equal(cache.has('page-0'), true);
  assert.equal(cache.has('page-1'), false);
  assert.equal([...cache.keys()].at(-1), 'page-24');
});
