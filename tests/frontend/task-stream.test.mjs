import test from 'node:test';
import assert from 'node:assert/strict';

import {
  createTaskStream,
  reduceTaskStreamPayload,
} from '../../web/assets/app/core/task-stream.mjs';

class FakeEventSource {
  static instances = [];

  constructor(url) {
    this.url = url;
    this.listeners = new Map();
    this.closed = false;
    FakeEventSource.instances.push(this);
  }

  addEventListener(type, listener) {
    if (!this.listeners.has(type)) this.listeners.set(type, []);
    this.listeners.get(type).push(listener);
  }

  emit(type, data = '') {
    for (const listener of this.listeners.get(type) || []) listener({ data });
  }

  close() {
    this.closed = true;
  }
}

test('task payload reducer replaces task data and preserves explicit summary', () => {
  const next = reduceTaskStreamPayload(
    { tasks: [{ id: 'old' }], summary: { all: 1 } },
    { tasks: [{ id: 'new' }], summary: { all: 2 }, grouped: [] },
    123,
  );
  assert.deepEqual(next.tasks, [{ id: 'new' }]);
  assert.equal(next.summary.all, 2);
  assert.equal(next.receivedAt, 123);
});

test('TaskStream start is idempotent and owns only one EventSource', () => {
  FakeEventSource.instances = [];
  const stream = createTaskStream({ EventSourceImpl: FakeEventSource, now: () => 456 });
  const values = [];
  stream.subscribe(value => values.push(value));
  const first = stream.start();
  const second = stream.start();
  assert.equal(first, second);
  assert.equal(FakeEventSource.instances.length, 1);
  assert.equal(stream.activeSourceCount(), 1);
  assert.equal(first.url, '/api/events');
  first.emit('tasks', JSON.stringify({ tasks: [{ id: 'task-1' }], summary: { all: 1 } }));
  assert.equal(values.at(-1).tasks[0].id, 'task-1');
  stream.stop({ clear: true });
  assert.equal(first.closed, true);
  assert.equal(stream.activeSourceCount(), 0);
  assert.deepEqual(stream.get().tasks, []);
});

test('entering and leaving a task view ten times only changes subscribers', () => {
  FakeEventSource.instances = [];
  const stream = createTaskStream({ EventSourceImpl: FakeEventSource });
  stream.start();
  for (let index = 0; index < 10; index += 1) {
    const unsubscribeTasks = stream.subscribe(() => {});
    const unsubscribeConnection = stream.subscribeConnection(() => {});
    assert.equal(stream.activeSourceCount(), 1);
    assert.equal(unsubscribeTasks(), true);
    assert.equal(unsubscribeTasks(), false);
    assert.equal(unsubscribeConnection(), true);
    assert.equal(unsubscribeConnection(), false);
  }
  assert.equal(FakeEventSource.instances.length, 1);
  stream.stop();
});
