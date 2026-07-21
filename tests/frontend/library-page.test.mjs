import test from 'node:test';
import assert from 'node:assert/strict';

import {
  librarySortValue,
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
