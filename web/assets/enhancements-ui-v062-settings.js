(() => {
  'use strict';

  const E = window.BiliEnhancements;
  if (!E) return;
  const { $, currentPage } = E;

  const ADVANCED_FIELD_IDS = ['cfgTimeout', 'cfgPoll', 'cfgDfn', 'cfgEncoding'];

  function applySettingsLayout() {
    if (currentPage() !== 'settings') return;
    const form = $('#settingsForm');
    if (!form || form.dataset.v062SettingsLayout === '1') return;
    const advancedFields = ADVANCED_FIELD_IDS
      .map(id => $(`#${id}`, form)?.closest('.field'))
      .filter(Boolean);
    if (!advancedFields.length) return;

    form.dataset.v062SettingsLayout = '1';
    const submitField = form.querySelector('button[type="submit"], button:not([type])')?.closest('.field');
    const details = document.createElement('details');
    details.className = 'v062-settings-advanced field full';
    details.innerHTML = '<summary><span><strong>高级设置</strong><small>任务超时、轮询和下载策略；不熟悉时保持默认即可。</small></span><span class="v062-details-caret" aria-hidden="true">⌄</span></summary><div class="form-grid v062-settings-advanced-grid"></div>';
    const grid = details.querySelector('.v062-settings-advanced-grid');
    advancedFields.forEach(field => grid.appendChild(field));
    form.insertBefore(details, submitField || null);
  }

  function schedule() {
    requestAnimationFrame(applySettingsLayout);
  }

  const start = () => {
    const root = $('#pageRoot');
    if (root) new MutationObserver(schedule).observe(root, { childList: true, subtree: true });
    window.addEventListener('hashchange', schedule);
    schedule();
  };

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start, { once: true });
  else start();
})();
