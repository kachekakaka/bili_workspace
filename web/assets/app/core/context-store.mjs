function freezeValue(value) {
  if (!value || typeof value !== 'object') return Object.freeze({});
  return Object.freeze({ ...value });
}

export function createContextStore(initial = {}) {
  let snapshot = freezeValue(initial);
  const listeners = new Set();

  const publish = previous => {
    for (const listener of [...listeners]) listener(snapshot, previous);
  };

  return Object.freeze({
    get() {
      return snapshot;
    },
    replace(value) {
      const previous = snapshot;
      snapshot = freezeValue(value);
      publish(previous);
      return snapshot;
    },
    patch(value) {
      return this.replace({ ...snapshot, ...(value || {}) });
    },
    clear() {
      return this.replace({});
    },
    subscribe(listener, { immediate = false } = {}) {
      if (typeof listener !== 'function') throw new TypeError('listener must be a function');
      listeners.add(listener);
      if (immediate) listener(snapshot, snapshot);
      let active = true;
      return () => {
        if (!active) return false;
        active = false;
        listeners.delete(listener);
        return true;
      };
    },
    listenerCount() {
      return listeners.size;
    },
  });
}
