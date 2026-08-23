import test from 'node:test';
import assert from 'node:assert/strict';

import {
  librarySortValue,
  libraryResponseSignature,
  libraryTagColor,
  splitLibrarySort,
} from '../../web/assets/app/pages/library.mjs';

test('Library sort aliases and explicit directions remain compatible', () => {
  assert.deepEqual(splitLibrarySort('newest'), ['newest', 'desc']);
  assert.deepEqual(splitLibrarySort('oldest'), ['newest', 'asc']);
  assert.deepEqual(splitLibrarySort('duration_asc'), ['duration', 'asc']);
  assert.deepEqual(splitLibrarySort('invalid'), ['newest', 'desc']);
  assert.equal(librarySortValue('group', 'asc'), 'group_asc');
  assert.equal(librarySortValue('invalid', 'desc'), 'newest_desc');
});

test('Library tag colors migrate historical defaults but preserve explicit colors', () => {
  assert.equal(libraryTagColor({ name: '夯', color: '#dc2626' }), '#d4a017');
  assert.equal(libraryTagColor({ name: 'NPC', color: '#64748b' }), '#0f766e');
  assert.equal(libraryTagColor({ name: '自定义', color: '#123456' }), '#123456');
  assert.equal(libraryTagColor({ name: '自定义', color: 'red' }), '#64748b');
});

test('Library response signature ignores wrapper identity but tracks visible row changes', () => {
  const first = {
    page: 1,
    pages: 2,
    total: 40,
    items: [{ id: 'm1', title: '作品', group_id: 'g1', tags: ['夯'] }],
  };
  const same = structuredClone(first);
  assert.equal(libraryResponseSignature(first), libraryResponseSignature(same));
  same.items[0].tags = ['顶级'];
  assert.notEqual(libraryResponseSignature(first), libraryResponseSignature(same));

  const renamedGroup = structuredClone(first);
  renamedGroup.items[0].group_name = '新分组名';
  assert.notEqual(libraryResponseSignature(first), libraryResponseSignature(renamedGroup));

  const refreshedCover = structuredClone(first);
  refreshedCover.items[0].cover = '/new-cover.jpg';
  assert.notEqual(libraryResponseSignature(first), libraryResponseSignature(refreshedCover));
});
