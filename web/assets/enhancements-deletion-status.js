(() => {
  'use strict';
  const E = window.BiliEnhancements;
  if (!E) return;
  const { state, $, $$, esc, currentPage } = E;
  const BLOCKED = new Set(['downloaded', 'deleted']);
  let scheduled = false;

  const splitTerms = value => String(value || '')
    .split(/[\s,，;；|/\\()（）\[\]{}<>《》]+/)
    .map(item => item.trim())
    .filter(Boolean)
    .filter((item, index, values) => values.findIndex(value => value.toLowerCase() === item.toLowerCase()) === index)
    .slice(0, 6);

  function modeHelp() {
    const mode = $('#enhSearchModeV2')?.value || state.search.mode || 'all';
    const terms = splitTerms($('#enhSearchQuery')?.value || state.search.q);
    const chips = terms.map(term => `<span class="enh-query-term">${esc(term)}</span>`).join('');
    if (mode === 'raw') return '把输入内容原样交给 B站，直接显示 B站返回的结果。';
    const rule = mode === 'all'
      ? '先使用原始关键词搜索 B站，再仅保留标题同时包含全部词的作品'
      : '先使用原始关键词搜索 B站，再仅保留标题包含任意一个词的作品';
    return `${rule}${chips ? `：${chips}` : ''}`;
  }

  function updateModeCopy(view) {
    const select = $('#enhSearchModeV2', view);
    if (select) {
      const labels = {
        all: '精准：标题匹配全部词',
        any: '模糊：标题匹配任一词',
        raw: '原始：B站直接结果',
      };
      for (const option of select.options) {
        if (labels[option.value] && option.textContent !== labels[option.value]) {
          option.textContent = labels[option.value];
        }
      }
    }
    const help = $('#enhSearchTermsHelp', view);
    const html = modeHelp();
    if (help && help.innerHTML !== html) help.innerHTML = html;
  }

  function updateBlockCheckbox(view) {
    const checkbox = $('#enhHideDownloaded', view);
    if (!checkbox) return;
    checkbox.checked = Boolean(state.search.hideDownloaded);
    const label = checkbox.closest('label');
    if (label && label.dataset.catalogBlockLabel !== '1') {
      for (const node of [...label.childNodes]) {
        if (node.nodeType === Node.TEXT_NODE) node.remove();
      }
      label.appendChild(document.createTextNode(' 屏蔽已下载和已删除'));
      label.dataset.catalogBlockLabel = '1';
      label.title = '开启后隐藏当前页中已经下载完成或曾被你删除的作品';
    }
  }

  function updateCards(view) {
    const items = state.search.data?.items || [];
    const byKey = new Map(items.map(item => [String(item.bvid || ''), item]));
    const shouldBlock = Boolean(state.search.hideDownloaded);
    for (const card of $$('[data-search-key]', view)) {
      const item = byKey.get(String(card.dataset.searchKey || ''));
      if (!item) continue;
      const status = String(item.local_status || '');
      card.hidden = shouldBlock && BLOCKED.has(status);
      if (status === 'deleted') {
        const badge = $('.cover-badges .badge:last-child', card);
        if (badge) {
          badge.textContent = '已删除';
          badge.classList.remove('neutral', 'good', 'warn', 'brand');
          badge.classList.add('bad');
        }
        const download = $('[data-search-download]', card);
        if (download) {
          download.textContent = '重新下载';
          download.title = '这个作品以前被删除过，重新下载前会再次确认';
        }
      }
    }

    const summary = $('#enhSearchSummary', view);
    if (summary && state.search.data) {
      const blockedCount = items.filter(item => BLOCKED.has(String(item.local_status || ''))).length;
      let text = summary.textContent
        .replace(/\s*· 已隐藏 \d+ 条已下载作品/g, '')
        .replace(/\s*· 屏蔽 \d+ 条已下载\/已删除作品/g, '');
      if (shouldBlock && blockedCount) text += ` · 屏蔽 ${blockedCount} 条已下载/已删除作品`;
      if (summary.textContent !== text) summary.textContent = text;
    }
  }

  function apply() {
    scheduled = false;
    if (currentPage() !== 'search') return;
    const view = $('[data-enhanced-view="search"]');
    if (!view) return;
    updateModeCopy(view);
    updateBlockCheckbox(view);
    updateCards(view);
  }

  function schedule() {
    if (scheduled) return;
    scheduled = true;
    requestAnimationFrame(apply);
  }

  function selectedItemsForButton(button) {
    if (button.id === 'enhSearchDownloadSelected' || button.id === 'batchDownload') {
      return [...state.search.selected.values()];
    }
    const key = button.dataset.searchDownload || button.dataset.download || '';
    return (state.search.data?.items || []).filter(item => String(item.bvid || '') === String(key));
  }

  // Window capture runs before the existing document-level download handler.
  window.addEventListener('click', event => {
    if (currentPage() !== 'search') return;
    const element = event.target instanceof Element ? event.target : null;
    const button = element?.closest('#enhSearchDownloadSelected,[data-search-download],#batchDownload,[data-download]');
    if (!(button instanceof HTMLButtonElement)) return;
    const deleted = selectedItemsForButton(button).filter(item => item?.local_status === 'deleted');
    if (!deleted.length) return;
    const message = deleted.length === 1
      ? '这个作品以前被你删除过。确定要重新下载吗？'
      : `选中的作品中有 ${deleted.length} 个曾被删除。确定要重新下载吗？`;
    if (!confirm(message)) {
      event.preventDefault();
      event.stopImmediatePropagation();
    }
  }, true);

  document.addEventListener('input', event => {
    if (event.target?.id === 'enhSearchQuery') schedule();
  });
  document.addEventListener('change', event => {
    if (['enhSearchModeV2', 'enhHideDownloaded'].includes(event.target?.id)) schedule();
  });

  const root = $('#pageRoot');
  if (root) new MutationObserver(schedule).observe(root, { childList: true, subtree: true });
  window.addEventListener('hashchange', schedule);
  schedule();
})();
