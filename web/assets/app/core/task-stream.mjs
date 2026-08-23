import { once } from './lifecycle.mjs';

const MODES = new Set(['full', 'summary']);

function emptySnapshot(mode) {
  if (mode === 'summary') {
    return Object.freeze({ summary: Object.freeze({}), receivedAt: 0 });
  }
  return Object.freeze({
    tasks: Object.freeze([]),
    summary: Object.freeze({}),
    grouped: Object.freeze([]),
    receivedAt: 0,
  });
}

export function reduceTaskStreamPayload(previous, payload, receivedAt = Date.now(), mode = 'full') {
  const current = previous && typeof previous === 'object' ? previous : {};
  const value = payload && typeof payload === 'object' ? payload : {};
  if (mode === 'summary') {
    return Object.freeze({
      summary: Object.freeze({ ...(value.summary || current.summary || {}) }),
      receivedAt: Number(receivedAt || 0),
    });
  }
  return Object.freeze({
    tasks: Object.freeze([...(value.tasks || value.data || current.tasks || [])]),
    summary: Object.freeze({ ...(value.summary || current.summary || {}) }),
    grouped: Object.freeze([...(value.grouped || current.grouped || [])]),
    receivedAt: Number(receivedAt || 0),
  });
}

function modeUrl(url, mode) {
  if (mode === 'full') return url;
  const separator = url.includes('?') ? '&' : '?';
  return `${url}${separator}view=summary`;
}

export function createTaskStream({
  EventSourceImpl = globalThis.EventSource,
  url = '/api/events',
  parse = JSON.parse,
  now = Date.now,
} = {}) {
  let source = null;
  let sourceMode = '';
  let connection = 'idle';
  let legacyRelease = null;
  const snapshots = new Map([
    ['full', emptySnapshot('full')],
    ['summary', emptySnapshot('summary')],
  ]);
  const listeners = new Map([
    ['full', new Set()],
    ['summary', new Set()],
  ]);
  const connectionListeners = new Set();
  const leases = new Map();

  const emitSnapshot = mode => {
    const snapshot = snapshots.get(mode);
    for (const listener of [...listeners.get(mode)]) listener(snapshot);
  };
  const setConnection = value => {
    if (connection === value) return;
    connection = value;
    for (const listener of [...connectionListeners]) listener(connection);
  };
  const desiredMode = () => {
    const modes = new Set(leases.values());
    if (modes.has('full')) return 'full';
    if (modes.has('summary')) return 'summary';
    return '';
  };
  const closeSource = () => {
    source?.close();
    source = null;
    sourceMode = '';
  };

  const reconcile = () => {
    const desired = desiredMode();
    if (!desired) {
      closeSource();
      setConnection('closed');
      return null;
    }
    if (source && sourceMode === desired) return source;
    closeSource();
    if (typeof EventSourceImpl !== 'function') throw new TypeError('EventSource is unavailable');
    snapshots.set(desired, emptySnapshot(desired));
    emitSnapshot(desired);
    sourceMode = desired;
    source = new EventSourceImpl(modeUrl(url, desired));
    setConnection('connecting');
    const current = source;
    const currentMode = desired;
    current.addEventListener?.('open', () => {
      if (source === current) setConnection('open');
    });
    current.addEventListener?.('tasks', event => {
      if (source !== current || sourceMode !== currentMode) return;
      try {
        snapshots.set(
          currentMode,
          reduceTaskStreamPayload(snapshots.get(currentMode), parse(event.data), now(), currentMode),
        );
        emitSnapshot(currentMode);
      } catch {
        setConnection('error');
      }
    });
    current.onerror = () => {
      if (source === current) setConnection('reconnecting');
    };
    return source;
  };

  const acquire = (mode = 'full', { signal } = {}) => {
    if (!MODES.has(mode)) throw new TypeError(`unsupported task stream mode: ${mode}`);
    if (signal?.aborted) return once();
    const token = Symbol(mode);
    leases.set(token, mode);
    let release = null;
    const onAbort = () => release?.();
    release = once(() => {
      signal?.removeEventListener?.('abort', onAbort);
      leases.delete(token);
      reconcile();
    });
    signal?.addEventListener?.('abort', onAbort, { once: true });
    reconcile();
    return release;
  };

  const stop = ({ clear = false } = {}) => {
    legacyRelease = null;
    leases.clear();
    closeSource();
    setConnection('closed');
    if (clear) {
      for (const mode of MODES) {
        snapshots.set(mode, emptySnapshot(mode));
        emitSnapshot(mode);
      }
    }
  };

  return Object.freeze({
    acquire,
    start(mode = 'full') {
      if (!legacyRelease) legacyRelease = acquire(mode);
      return source;
    },
    stop,
    clear(mode = null) {
      const modes = mode ? [mode] : [...MODES];
      for (const item of modes) {
        if (!MODES.has(item)) continue;
        snapshots.set(item, emptySnapshot(item));
        emitSnapshot(item);
      }
    },
    get(mode = 'full') {
      return snapshots.get(mode) || emptySnapshot(mode);
    },
    connection() {
      return connection;
    },
    activeMode() {
      return sourceMode;
    },
    activeSourceCount() {
      return source ? 1 : 0;
    },
    leaseCount() {
      return leases.size;
    },
    subscribe(listener, { immediate = false, mode = 'full' } = {}) {
      if (typeof listener !== 'function') throw new TypeError('listener must be a function');
      if (!MODES.has(mode)) throw new TypeError(`unsupported task stream mode: ${mode}`);
      listeners.get(mode).add(listener);
      if (immediate) listener(snapshots.get(mode));
      return once(() => listeners.get(mode).delete(listener));
    },
    subscribeConnection(listener, { immediate = false } = {}) {
      if (typeof listener !== 'function') throw new TypeError('listener must be a function');
      connectionListeners.add(listener);
      if (immediate) listener(connection);
      return once(() => connectionListeners.delete(listener));
    },
  });
}
