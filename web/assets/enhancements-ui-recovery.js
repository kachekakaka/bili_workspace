(() => {
  'use strict';
  const E = window.BiliEnhancements;
  if (!E) return;
  const { state, $, $$, esc, safeColor, currentPage } = E;
  const UNTAGGED = '__untagged__';
  let scheduled = false;

  function dashboardLayout(root) {
    return [...root.children].find(child => {
      if (!(child instanceof HTMLElement)) return false;
      const headings = $$(':scope > .card .card-head h2', child)
        .map(node => node.textContent?.trim() || '');
      return headings.includes('最近观看与下载') && headings.includes('运行状态');
    }) || null;
  }

  function fixDashboard() {
    if (currentPage() !== 'dashboard') return;
    const root = $('#pageRoot');
    if (!root) return;
    const layout = dashboardLayout(root);
    if (!layout) return;
    layout.classList.remove('cols-2');
    layout.classList.add('enh-dashboard-stack');
    layout.dataset.dashboardSections = 'stacked';
    Object.assign(layout.style, {
      display: 'grid',
      gridTemplateColumns: 'minmax(0, 1fr)',
      gap: '18px',
      alignItems: 'start',
    });
  }

  function groupButtons() {
    const selected = String(state.library.groupId || '');
    const all = `<button type="button" class="enh-filter-chip ${selected ? '' : 'active'}" data-recovery-group="">全部分组</button>`;
    return all + state.groups.map(group => (
      `<button type="button" class="enh-filter-chip ${String(group.id) === selected ? 'active' : ''}" data-recovery-group="${esc(group.id)}">${esc(group.display_name)}</button>`
    )).join('');
  }

  function tagButtons() {
    const selected = String(state.library.tag || '');
    const all = `<button type="button" class="enh-filter-chip ${selected ? '' : 'active'}" data-recovery-tag="">全部标签</button>`;
    const untagged = `<button type="button" class="enh-filter-chip enh-untagged-chip ${selected === UNTAGGED ? 'active' : ''}" data-recovery-tag="${UNTAGGED}">无标签</button>`;
    const tags = state.tags.map(tag => (
      `<button type="button" class="enh-filter-chip enh-colored-filter-chip ${String(tag.name) === selected ? 'active' : ''}" style="--tag-color:${safeColor(tag.color)}" data-recovery-tag="${esc(tag.name)}">${esc(tag.name)}</button>`
    )).join('');
    return all + untagged + tags;
  }

  function filterSignature() {
    return JSON.stringify({
      group: state.library.groupId || '',
      tag: state.library.tag || '',
      groups: state.groups.map(group => [group.id, group.display_name]),
      tags: state.tags.map(tag => [tag.name, tag.color]),
    });
  }

  function ensureUntaggedOption(select) {
    if ([...select.options].some(option => option.value === UNTAGGED)) return;
    const option = document.createElement('option');
    option.value = UNTAGGED;
    option.textContent = '无标签';
    select.insertBefore(option, select.options[1] || null);
  }

  function fixLibraryFilters() {
    if (currentPage() !== 'library') return;
    const view = $('[data-enhanced-view="library"]');
    if (!view) return;
    const filterCard = $('.enh-library-filter-card', view);
    const grid = $('.enh-filter-grid', filterCard);
    const groupSelect = $('#enhLibraryGroup', view);
    const tagSelect = $('#enhLibraryTag', view);
    if (!filterCard || !grid || !groupSelect || !tagSelect) return;

    groupSelect.closest('.field')?.classList.add('enh-native-chip-filter');
    tagSelect.closest('.field')?.classList.add('enh-native-chip-filter');
    ensureUntaggedOption(tagSelect);
    groupSelect.value = state.library.groupId || '';
    tagSelect.value = state.library.tag || '';

    let chips = $('#enhLibraryChipFilters', view);
    if (!chips) {
      chips = document.createElement('div');
      chips.id = 'enhLibraryChipFilters';
      chips.className = 'enh-library-chip-filters';
      filterCard.insertBefore(chips, grid);
    }
    const signature = filterSignature();
    if (chips.dataset.signature !== signature || chips.dataset.recovered !== '1') {
      chips.dataset.signature = signature;
      chips.dataset.recovered = '1';
      chips.innerHTML = `<div class="enh-chip-filter-row"><span class="enh-chip-filter-label">▦ 分组</span><div class="enh-chip-strip">${groupButtons()}</div></div><div class="enh-chip-filter-row"><span class="enh-chip-filter-label">⌁ 标签</span><div class="enh-chip-strip">${tagButtons()}</div></div>`;
    }
  }

  function applyLibraryFilter(kind, value) {
    if (kind === 'group') {
      state.library.groupId = value;
      const select = $('#enhLibraryGroup');
      if (select) select.value = value;
    } else {
      state.library.tag = value;
      const select = $('#enhLibraryTag');
      if (select) select.value = value;
    }
    state.library.page = 1;
    const apply = $('#enhLibraryApply');
    if (apply instanceof HTMLButtonElement) apply.click();
  }

  function apply() {
    scheduled = false;
    fixDashboard();
    fixLibraryFilters();
  }

  function schedule() {
    if (scheduled) return;
    scheduled = true;
    requestAnimationFrame(apply);
  }

  // Register before the historical library overlay so this handler owns filter
  // clicks and cannot be double-applied by the compatibility layer.
  document.addEventListener('click', event => {
    const element = event.target instanceof Element ? event.target : null;
    if (!element || currentPage() !== 'library') return;
    const group = element.closest('[data-recovery-group]');
    if (group) {
      event.preventDefault();
      event.stopImmediatePropagation();
      applyLibraryFilter('group', group.dataset.recoveryGroup || '');
      schedule();
      return;
    }
    const tag = element.closest('[data-recovery-tag]');
    if (tag) {
      event.preventDefault();
      event.stopImmediatePropagation();
      applyLibraryFilter('tag', tag.dataset.recoveryTag || '');
      schedule();
    }
  }, true);

  const start = () => {
    const root = $('#pageRoot');
    if (root) new MutationObserver(schedule).observe(root, { childList: true, subtree: true });
    window.addEventListener('hashchange', schedule);
    window.addEventListener('load', schedule, { once: true });
    schedule();
  };
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start, { once: true });
  else start();
})();
