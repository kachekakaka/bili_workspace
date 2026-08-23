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

test('full and summary reducers have disjoint payload shapes', () => {
  const full = reduceTaskStreamPayload(
    { tasks: [{ id: 'old' }], summary: { all: 1 } },
    { tasks: [{ id: 'new' }], summary: { all: 2 }, grouped: [] },
    123,
  );
  assert.deepEqual(full.tasks, [{ id: 'new' }]);
  assert.equal(full.summary.all, 2);
  assert.equal(full.receivedAt, 123);

  const summary = reduceTaskStreamPayload(
    { tasks: [{ id: 'must-not-survive' }], grouped: [{ owner: 'x' }] },
    { summary: { active: 3 } },
    456,
    'summary',
  );
  assert.deepEqual(Object.keys(summary).sort(), ['receivedAt', 'summary']);
  assert.equal(summary.summary.active, 3);
});

test('TaskStream has zero sources without a page lease', () => {
  FakeEventSource.instances = [];
  const stream = createTaskStream({ EventSourceImpl: FakeEventSource });
  assert.equal(stream.activeSourceCount(), 0);
  assert.equal(stream.leaseCount(), 0);
  assert.equal(FakeEventSource.instances.length, 0);
});

test('summary lease uses summary endpoint and never retains full task data', () => {
  FakeEventSource.instances = [];
  const stream = createTaskStream({ EventSourceImpl: FakeEventSource, now: () => 456 });
  const values = [];
  stream.subscribe(value => values.push(value), { mode: 'summary' });
  const release = stream.acquire('summary');
  const source = FakeEventSource.instances[0];
  assert.equal(source.url, '/api/events?view=summary');
  source.emit('tasks', JSON.stringify({ summary: { all: 7 }, tasks: [{ id: 'leak' }] }));
  assert.equal(values.at(-1).summary.all, 7);
  assert.equal('tasks' in values.at(-1), false);
  release();
  assert.equal(source.closed, true);
  assert.equal(stream.activeSourceCount(), 0);
});

test('full lease preempts summary with one source and snapshots reset on mode return', () => {
  FakeEventSource.instances = [];
  const stream = createTaskStream({ EventSourceImpl: FakeEventSource });
  const releaseSummary = stream.acquire('summary');
  const firstSummary = FakeEventSource.instances.at(-1);
  firstSummary.emit('tasks', JSON.stringify({ summary: { all: 1 } }));

  const releaseFull = stream.acquire('full');
  const firstFull = FakeEventSource.instances.at(-1);
  assert.equal(firstSummary.closed, true);
  assert.equal(stream.activeMode(), 'full');
  assert.equal(stream.activeSourceCount(), 1);
  firstFull.emit('tasks', JSON.stringify({ tasks: [{ id: 'old-full' }], summary: { all: 1 } }));
  assert.equal(stream.get('full').tasks[0].id, 'old-full');

  releaseFull();
  const secondSummary = FakeEventSource.instances.at(-1);
  assert.equal(firstFull.closed, true);
  assert.equal(secondSummary.url, '/api/events?view=summary');
  assert.deepEqual(stream.get('summary').summary, {});

  const releaseFullAgain = stream.acquire('full');
  assert.equal(secondSummary.closed, true);
  assert.deepEqual(stream.get('full').tasks, []);
  assert.equal(stream.activeSourceCount(), 1);
  releaseFullAgain();
  releaseSummary();
  assert.equal(stream.activeSourceCount(), 0);
});

test('route abort releases a lease immediately even before a mount handle exists', () => {
  FakeEventSource.instances = [];
  const stream = createTaskStream({ EventSourceImpl: FakeEventSource });
  for (let index = 0; index < 10; index += 1) {
    const controller = new AbortController();
    stream.acquire('full', { signal: controller.signal });
    assert.equal(stream.activeSourceCount(), 1);
    controller.abort();
    assert.equal(stream.activeSourceCount(), 0);
    assert.equal(stream.leaseCount(), 0);
  }
  assert.equal(FakeEventSource.instances.length, 10);
});
