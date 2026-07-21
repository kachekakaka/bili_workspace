import test from 'node:test';
import assert from 'node:assert/strict';

import { filterAndSortTasks } from '../../web/assets/app/pages/tasks.mjs';

const tasks = [
  { id: 'a', title: '管理员作品', owner_user_id: 'u1', owner_label: '甲', status: 'failed', destination: 'library', created_at: 1 },
  { id: 'b', title: '普通设备导出', owner_user_id: 'u2', owner_label: '乙', status: 'success', destination: 'device', created_at: 3 },
  { id: 'c', title: '暂停中的任务', owner_user_id: 'u2', owner_label: '乙', status: 'cancelled', error: '已暂停', destination: 'device', created_at: 2 },
];

function filters(overrides = {}) {
  return {
    ownerUserId: '', status: '', destination: '', q: '', sort: 'created_at', direction: 'desc',
    ...overrides,
  };
}

test('admin filters by owner, destination and query before sorting', () => {
  const result = filterAndSortTasks(tasks, filters({ ownerUserId: 'u2', destination: 'device', q: '普通' }), true);
  assert.deepEqual(result.map(task => task.id), ['b']);
});

test('normal users cannot activate admin-only owner and destination filters', () => {
  const result = filterAndSortTasks(tasks, filters({ ownerUserId: 'u1', destination: 'library' }), false);
  assert.deepEqual(result.map(task => task.id), ['b', 'c', 'a']);
});

test('paused tasks remain selectable through the cancelled status filter', () => {
  const result = filterAndSortTasks(tasks, filters({ status: 'cancelled', direction: 'asc' }), true);
  assert.deepEqual(result.map(task => task.id), ['c']);
});
