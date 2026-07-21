export function createConfirmDialog(modalService) {
  if (!modalService?.open) throw new TypeError('modalService is required');

  return function confirmDialog({
    title = '请确认',
    message = '',
    confirmLabel = '确定',
    cancelLabel = '取消',
    danger = false,
  } = {}) {
    return new Promise(resolve => {
      let settled = false;
      const settle = value => {
        if (settled) return;
        settled = true;
        resolve(Boolean(value));
      };
      const modal = modalService.open({
        title,
        narrow: true,
        body: '<div class="notice" data-confirm-message></div><div class="v062-modal-actions" style="margin-top:16px"><button type="button" class="btn" data-confirm-cancel></button><button type="button" class="btn" data-confirm-accept></button></div>',
        onClose: () => settle(false),
      });
      modal.body.querySelector('[data-confirm-message]').textContent = String(message || '');
      const cancel = modal.body.querySelector('[data-confirm-cancel]');
      const accept = modal.body.querySelector('[data-confirm-accept]');
      cancel.textContent = String(cancelLabel || '取消');
      accept.textContent = String(confirmLabel || '确定');
      accept.classList.add(danger ? 'danger' : 'primary');
      cancel.onclick = () => { settle(false); modal.close('cancel'); };
      accept.onclick = () => { settle(true); modal.close('accept'); };
      requestAnimationFrame(() => accept.focus());
    });
  };
}
