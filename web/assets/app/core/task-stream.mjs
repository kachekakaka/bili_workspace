import { once } from './lifecycle.mjs';

export function reduceTaskStreamPayload(previous, payload, receivedAt = Date.now()) {
  const current = previous && typeof previous === 'object' ? previous : {};
  const value = payload && typeof payload === 'object' ? payload : {};
  return Object.freeze({
    tasks: Object.freeze([...(value.tasks || value.data || current.tasks || [])]),
    summary: Object.freeze({ ...(value.summary || current.summary || {}) }),
    grouped: Object.freeze([...(value.grouped || current.grouped || [])]),
    receivedAt: Number(receivedAt || 0),
  });
}

export function createTaskStream({
  EventSourceImpl = globalThis.EventSource,
  url = '/api/events',
  parse = JSON.parse,
  now = Date.now,
} = {}) {
  let source = null;
  let connection = 'idle';
  let snapshot = reduceTaskStreamPayload(null, {}, 0);
  const listeners = new Set();
  const connectionListeners = new Set();

  const emitSnapshot = () => {
    for (const listener of [...listeners]) listener(snapshot);
  };
  const setConnection = value => {
    if (connection === value) return;
    connection = value;
    for (const listener of [...connectionListeners]) listener(connection);
  };

  const start = () => {
    if (source) return source;
    if (typeof EventSourceImpl !== 'function') throw new TypeError('EventSource is unavailable');
    source = new EventSourceImpl(url);
    setConnection('connecting');
    const current = source;
    current.addEventListener?.('open', () => {
      if (source === current) setConnection('open');
    });
    current.addEventListener?.('tasks', event => {
      if (source !== current) return;
      try {
        snapshot = reduceTaskStreamPayload(snapshot, parse(event.data), now());
        emitSnapshot();
      } catch {
        setConnection('error');
      }
    });
    current.onerror = () => {
      if (source === current) setConnection('reconnecting');
    };
    return source;
  };

  const stop = ({ clear = false } = {}) => {
    if (source) source.close();
    source = null;
    setConnection('closed');
    if (clear) {
      snapshot = reduceTaskStreamPayload(null, {}, 0);
      emitSnapshot();
    }
  };

  return Object.freeze({
    start,
    stop,
    clear() {
      snapshot = reduceTaskStreamPayload(null, {}, 0);
      emitSnapshot();
    },
    get() {
      return snapshot;
    },
    connection() {
      return connection;
    },
    activeSourceCount() {
      return source ? 1 : 0;
    },
    subscribe(listener, { immediate = false } = {}) {
      if (typeof listener !== 'function') throw new TypeError('listener must be a function');
      listeners.add(listener);
      if (immediate) listener(snapshot);
      return once(() => listeners.delete(listener));
    },
    subscribeConnection(listener, { immediate = false } = {}) {
      if (typeof listener !== 'function') throw new TypeError('listener must be a function');
      connectionListeners.add(listener);
      if (immediate) listener(connection);
      return once(() => connectionListeners.delete(listener));
    },
  });
}
