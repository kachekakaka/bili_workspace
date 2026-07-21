import { once } from '../core/lifecycle.mjs';

export function createModalService(root, { documentRef = globalThis.document } = {}) {
  if (!root) throw new TypeError('modal root is required');
  let active = null;

  const close = reason => {
    if (!active) return false;
    const record = active;
    active = null;
    record.disposeListeners();
    root.classList.add('hidden');
    root.replaceChildren();
    record.onClose?.(reason);
    return true;
  };

  const open = ({ title = '', body = '', narrow = false, onClose = null } = {}) => {
    close('replace');
    root.classList.remove('hidden');
    root.innerHTML = `<section class="modal ${narrow ? 'narrow' : ''}" role="dialog" aria-modal="true"><header class="modal-head"><h2></h2><button type="button" class="close-button" aria-label="关闭">×</button></header><div class="modal-body"></div></section>`;
    const dialog = root.querySelector('.modal');
    const heading = root.querySelector('.modal-head h2');
    const content = root.querySelector('.modal-body');
    heading.textContent = String(title || '');
    if (typeof body === 'string') content.innerHTML = body;
    else if (body) content.append(body);

    const controller = new AbortController();
    const disposeListeners = once(() => controller.abort());
    const closeButton = root.querySelector('.close-button');
    closeButton.addEventListener('click', () => close('button'), { signal: controller.signal });
    root.addEventListener('click', event => {
      if (event.target === root) close('backdrop');
    }, { signal: controller.signal });
    documentRef?.addEventListener?.('keydown', event => {
      if (event.key === 'Escape') close('escape');
    }, { signal: controller.signal });

    active = { dialog, content, onClose, disposeListeners };
    return Object.freeze({
      root,
      dialog,
      body: content,
      close: once(reason => close(reason || 'api')),
    });
  };

  return Object.freeze({
    open,
    close,
    active() {
      return active;
    },
    dispose() {
      close('dispose');
    },
  });
}
