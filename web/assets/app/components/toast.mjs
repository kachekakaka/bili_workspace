import { once } from '../core/lifecycle.mjs';

export function createToastService(root, {
  documentRef = globalThis.document,
  setTimeoutImpl = globalThis.setTimeout,
  clearTimeoutImpl = globalThis.clearTimeout,
} = {}) {
  if (!root) throw new TypeError('toast root is required');
  const entries = new Set();

  const dismiss = record => {
    if (!record || !entries.has(record)) return false;
    entries.delete(record);
    if (record.timer) clearTimeoutImpl(record.timer);
    record.node.remove();
    return true;
  };

  return Object.freeze({
    show(message, type = '', { duration = 3800 } = {}) {
      const node = documentRef.createElement('div');
      node.className = `toast ${String(type || '')}`.trim();
      node.textContent = String(message ?? '');
      root.appendChild(node);
      const record = { node, timer: 0 };
      entries.add(record);
      if (Number(duration) > 0) record.timer = setTimeoutImpl(() => dismiss(record), Number(duration));
      return Object.freeze({ node, dismiss: once(() => dismiss(record)) });
    },
    clear() {
      for (const record of [...entries]) dismiss(record);
    },
    size() {
      return entries.size;
    },
    dispose() {
      for (const record of [...entries]) dismiss(record);
    },
  });
}
