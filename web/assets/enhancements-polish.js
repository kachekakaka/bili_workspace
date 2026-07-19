(() => {
  'use strict';
  const E = window.BiliEnhancements;
  if (!E) return;
  const { $, currentPage, api, ensureContext, toast } = E;

  function stackDashboardSections() {
    if (currentPage() !== 'dashboard') return;
    const root = $('#pageRoot');
    if (!root) return;
    for (const child of [...root.children]) {
      if (child.classList?.contains('grid') && child.classList.contains('cols-2')) {
        child.classList.remove('cols-2');
        child.classList.add('enh-dashboard-stack');
      }
    }
  }

  async function submitDownloadForm(form) {
    const button = form.querySelector('button[type="submit"]');
    if (button?.disabled) return;
    if (button) button.disabled = true;
    try {
      await ensureContext();
      const lines = ($('#downloadTargets')?.value || '')
        .split(/\r?\n/)
        .map(value => value.trim())
        .filter(Boolean);
      if (!lines.length) {
        toast('请输入作品链接或编号', 'warn');
        return;
      }
      const bvids = lines.filter(value => /^BV[0-9A-Za-z]+$/i.test(value));
      const urls = lines.filter(value => !/^BV[0-9A-Za-z]+$/i.test(value));
      const destination = $('#downloadDestination')?.value || 'library';
      const result = await api('/api/download', {
        method: 'POST',
        body: {
          urls,
          bvids,
          items: [],
          force: Boolean($('#downloadForce')?.checked),
          group_id: destination === 'library' ? ($('#downloadGroup')?.value || '') : '',
          group: '',
          destination,
          min_height: Number($('#downloadQuality')?.value || 0),
        },
      });
      toast(`已创建 ${result.total || lines.length} 个任务，可继续浏览当前页面`, 'good');
      const target = $('#downloadTargets');
      if (target) target.value = '';
    } catch (error) {
      toast(error.message, 'bad');
    } finally {
      if (button) button.disabled = false;
    }
  }

  document.addEventListener('submit', event => {
    const form = event.target;
    if (!(form instanceof HTMLFormElement) || form.id !== 'downloadForm') return;
    event.preventDefault();
    event.stopImmediatePropagation();
    void submitDownloadForm(form);
  }, true);

  const start = () => {
    const root = $('#pageRoot');
    if (root) {
      const observer = new MutationObserver(() => requestAnimationFrame(stackDashboardSections));
      observer.observe(root, { childList: true, subtree: false });
    }
    window.addEventListener('hashchange', () => requestAnimationFrame(stackDashboardSections));
    stackDashboardSections();
  };
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start, { once: true });
  else start();
})();
