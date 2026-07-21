export function createGenerationGate(initialGeneration = 0) {
  let generation = Number.isSafeInteger(initialGeneration) && initialGeneration >= 0
    ? initialGeneration
    : 0;

  return Object.freeze({
    begin() {
      generation += 1;
      return generation;
    },
    current() {
      return generation;
    },
    isCurrent(candidate) {
      return Number(candidate) === generation;
    },
    commit(candidate, callback) {
      if (Number(candidate) !== generation) return false;
      callback();
      return true;
    },
    invalidate() {
      generation += 1;
      return generation;
    },
  });
}

export function once(dispose) {
  let disposed = false;
  return () => {
    if (disposed) return false;
    disposed = true;
    if (typeof dispose === 'function') dispose();
    return true;
  };
}

export function createAbortScope() {
  const controller = new AbortController();
  const dispose = once(() => controller.abort());
  return Object.freeze({
    controller,
    signal: controller.signal,
    dispose,
  });
}
