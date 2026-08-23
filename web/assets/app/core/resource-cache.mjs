import { once } from './lifecycle.mjs';

function stableValue(value) {
  if (Array.isArray(value)) return value.map(stableValue);
  if (!value || typeof value !== 'object') return value;
  return Object.fromEntries(
    Object.keys(value).sort().map(key => [key, stableValue(value[key])]),
  );
}

export function resourceKey(name, params = {}) {
  return `${String(name || '')}:${JSON.stringify(stableValue(params || {}))}`;
}

function abortError() {
  const error = new Error('操作已取消');
  error.name = 'AbortError';
  return error;
}

function freezeEntry(key, value, { updatedAt, stale = false, error = null } = {}) {
  return Object.freeze({
    key,
    value,
    updatedAt: Number(updatedAt || 0),
    stale: Boolean(stale),
    error: error || null,
  });
}

function consume(promise, signal) {
  if (!signal) return promise;
  if (signal.aborted) return Promise.reject(abortError());
  return new Promise((resolve, reject) => {
    const aborted = () => reject(abortError());
    signal.addEventListener('abort', aborted, { once: true });
    promise.then(
      value => {
        signal.removeEventListener('abort', aborted);
        resolve(value);
      },
      error => {
        signal.removeEventListener('abort', aborted);
        reject(error);
      },
    );
  });
}

export function createResourceCache({
  now = Date.now,
  AbortControllerImpl = globalThis.AbortController,
} = {}) {
  const entries = new Map();
  const inFlight = new Map();
  const listeners = new Map();

  const publish = key => {
    const entry = entries.get(key) || null;
    for (const listener of [...(listeners.get(key) || [])]) listener(entry);
  };

  const set = (key, value, options = {}) => {
    const entry = freezeEntry(key, value, {
      updatedAt: options.updatedAt ?? now(),
      stale: options.stale,
      error: options.error,
    });
    entries.set(key, entry);
    publish(key);
    return entry;
  };

  const markStale = (key, error = null) => {
    const current = entries.get(key);
    if (!current) return null;
    const entry = freezeEntry(key, current.value, {
      updatedAt: current.updatedAt,
      stale: true,
      error,
    });
    entries.set(key, entry);
    publish(key);
    return entry;
  };

  const invalidate = (key, { abort = true } = {}) => {
    if (abort) {
      const record = inFlight.get(key);
      if (record) {
        inFlight.delete(key);
        record.controller.abort();
      }
    }
    return markStale(key);
  };

  const refresh = (key, loader, { signal } = {}) => {
    if (typeof loader !== 'function') throw new TypeError('loader must be a function');
    let record = inFlight.get(key);
    if (!record) {
      const controller = new AbortControllerImpl();
      const promise = Promise.resolve()
        .then(() => loader({ key, signal: controller.signal }))
        .then(value => {
          if (controller.signal.aborted) throw abortError();
          if (inFlight.get(key)?.promise === promise) set(key, value);
          return value;
        })
        .catch(error => {
          if (error?.name !== 'AbortError') markStale(key, error);
          throw error;
        })
        .finally(() => {
          if (inFlight.get(key)?.promise === promise) inFlight.delete(key);
        });
      record = Object.freeze({ controller, promise });
      inFlight.set(key, record);
    }
    return consume(record.promise, signal);
  };

  return Object.freeze({
    peek(key) {
      return entries.get(key) || null;
    },
    set,
    update(key, updater, options = {}) {
      if (typeof updater !== 'function') throw new TypeError('updater must be a function');
      return set(key, updater(entries.get(key)?.value), options);
    },
    refresh,
    invalidate,
    invalidateWhere(predicate, options = {}) {
      let changed = 0;
      for (const key of new Set([...entries.keys(), ...inFlight.keys()])) {
        if (!predicate(key, entries.get(key) || null)) continue;
        invalidate(key, options);
        changed += 1;
      }
      return changed;
    },
    subscribe(key, listener, { immediate = false } = {}) {
      if (typeof listener !== 'function') throw new TypeError('listener must be a function');
      if (!listeners.has(key)) listeners.set(key, new Set());
      listeners.get(key).add(listener);
      if (immediate) listener(entries.get(key) || null);
      return once(() => {
        const current = listeners.get(key);
        current?.delete(listener);
        if (!current?.size) listeners.delete(key);
      });
    },
    clear() {
      const keys = new Set([...entries.keys(), ...inFlight.keys()]);
      for (const record of inFlight.values()) record.controller.abort();
      inFlight.clear();
      entries.clear();
      for (const key of keys) publish(key);
    },
    entryCount() {
      return entries.size;
    },
    inFlightCount() {
      return inFlight.size;
    },
  });
}
