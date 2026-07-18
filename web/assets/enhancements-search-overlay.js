(() => {
  'use strict';
  const E = window.BiliEnhancements;
  if (!E) return;
  const { state, $, $$, esc, api, toast, scheduleRender, currentPage } = E;
  const search = state.search;
  const MODE_LABELS = { all: '精准搜索', any: '模糊搜索', raw: '原始搜索' };
  if (!['all', 'any', 'raw'].includes(search.mode)) search.mode = 'all';
  if (!Number.isFinite(Number(search.pageLimit))) search.pageLimit = 10;

  const splitTerms = value => String(value || '')
    .split(/[\s,，;；|/\\()（）\[\]{}<>《》]+/)
    .map(item => item.trim())
    .filter(Boolean)
    .filter((item, index, values) => values.findIndex(value => value.toLowerCase() === item.toLowerCase()) === index)
    .slice(0, 6);

  function termsHtml() {
    if (search.mode === 'raw') return '原始搜索会把输入内容直接交给 B站，不额外过滤。';
    const terms = splitTerms($('#enhSearchQuery')?.value || search.q);
    const chips = terms.map(term => `<span class="enh-query-term">${esc(term)}</span>`).join('');
    return `${search.mode === 'all' ? '必须匹配全部词' : '匹配任意一个词即可'}${chips ? `：${chips}` : ''}`;
  }

  async function decorateTags(data) {
    const keys = (data.items || []).map(item => item.bvid).filter(Boolean);
    if (!keys.length) return data;
    const response = await api('/api/enhancements/tags/bulk', {
      method: 'POST', body: { keys, media_ids: [] },
    });
    const byKey = response.data?.by_key || {};
    for (const item of data.items || []) item.tags = byKey[item.bvid] || [];
    return data;
  }

  async function loadPage(page, fresh = false) {
    const q = ($('#enhSearchQuery')?.value || search.q || '').trim();
    if (!q) {
      toast('请输入关键词', 'warn');
      return;
    }
    search.q = q;
    search.order = $('#enhSearchOrder')?.value || search.order || 'totalrank';
    search.mode = $('#enhSearchModeV2')?.value || search.mode || 'all';
    const safePage = Math.max(1, Number(page || 1));
    const key = `${q}\u0000${search.order}\u0000${search.mode}\u0000${safePage}`;
    const box = $('#enhSearchResults');
    if (box) box.innerHTML = '<div class="loading-card">正在搜索…</div>';
    try {
      let data = fresh ? null : search.cache.get(key);
      if (!data) {
        const params = new URLSearchParams({
          q, order: search.order, page: String(safePage), mode: search.mode,
          fresh: fresh ? 'true' : 'false',
        });
        const response = await api(`/api/search?${params}`);
        data = await decorateTags(response.data || {});
        search.cache.set(key, data);
      }
      search.page = safePage;
      search.data = data;
      search.pages = Number(data.pages || data.numPages || data.num_pages || 0);
      search.total = Number(data.total || data.numResults || data.num_results || 0);
      if (safePage > search.pageLimit) search.pageLimit = Math.ceil(safePage / 10) * 10;
      scheduleRender(10);
    } catch (error) {
      if (box) box.innerHTML = `<div class="notice bad">${esc(error.message)}</div>`;
      toast(error.message, 'bad');
    }
  }

  function startFreshSearch() {
    search.page = 1;
    search.pageLimit = 10;
    search.pages = 0;
    search.total = 0;
    search.data = null;
    search.selected.clear();
    search.cache.clear();
    void loadPage(1, true);
  }

  function paginationHtml() {
    const pages = Math.max(1, Number(search.pages || search.page || 1));
    const limit = Math.min(pages, Math.max(10, Number(search.pageLimit || 10)));
    const buttons = Array.from({ length: limit }, (_, index) => index + 1).map(page => (
      `<button type="button" class="btn small ${page === search.page ? 'primary active' : ''}" data-search-overlay-page="${page}">${page}</button>`
    )).join('');
    const more = limit < pages ? '<button type="button" class="btn small" id="enhSearchMoreTen">＋ 再显示10页</button>' : '';
    return `<div class="enh-pagination enh-search-pagination-v2"><button type="button" class="btn small" data-search-overlay-page="${Math.max(1, search.page - 1)}" ${search.page <= 1 ? 'disabled' : ''}>上一页</button>${buttons}${more}<button type="button" class="btn small" data-search-overlay-page="${Math.min(pages, search.page + 1)}" ${search.page >= pages ? 'disabled' : ''}>下一页</button><input class="input enh-page-jump" id="enhSearchOverlayJump" type="number" min="1" max="${pages}" value="${search.page}"><button type="button" class="btn small" id="enhSearchOverlayJumpButton">跳转</button></div>`;
  }

  function recolorTagChips(view) {
    if (typeof E.catalogTagColor !== 'function') return;
    $$('.enh-tag-chip', view).forEach(chip => {
      const definition = state.tags.find(tag => tag.name === chip.textContent.trim());
      chip.style.setProperty('--tag-color', E.catalogTagColor(definition || chip.textContent.trim()));
    });
  }

  function enhanceView() {
    if (currentPage() !== 'search') return;
    const view = $('[data-enhanced-view="search"]');
    if (!view) return;
    const grid = $('.form-grid', view);
    if (grid && !$('#enhSearchModeV2', view)) {
      const field = document.createElement('div');
      field.className = 'field';
      field.innerHTML = '<label>搜索方式</label><div class="enh-select-shell" data-icon="⌕"><select id="enhSearchModeV2" class="select"><option value="all">精准：匹配全部词</option><option value="any">模糊：匹配任一词</option><option value="raw">原始：B站直接结果</option></select></div>';
      const destination = $('#enhSearchDestination', view)?.closest('.field');
      grid.insertBefore(field, destination || grid.children[1] || null);
      $('#enhSearchModeV2', view).value = search.mode;
      $('#enhSearchModeV2', view).onchange = () => {
        search.mode = $('#enhSearchModeV2', view).value;
        const help = $('#enhSearchTermsHelp', view);
        if (help) help.innerHTML = termsHtml();
      };
    }
    const query = $('#enhSearchQuery', view);
    if (query && !$('#enhSearchTermsHelp', view)) {
      const help = document.createElement('div');
      help.id = 'enhSearchTermsHelp';
      help.className = 'enh-mode-help';
      help.innerHTML = termsHtml();
      query.closest('.field')?.appendChild(help);
      query.addEventListener('input', () => { help.innerHTML = termsHtml(); });
    }

    const box = $('#enhSearchResults', view);
    if (box && search.data && !$('.loading-card', box)) {
      const oldPagination = $('.enh-pagination', box);
      if (oldPagination && !oldPagination.classList.contains('enh-search-pagination-v2')) {
        oldPagination.outerHTML = paginationHtml();
      } else if (!oldPagination) {
        box.insertAdjacentHTML('beforeend', paginationHtml());
      }
    }
    const summary = $('#enhSearchSummary', view);
    if (summary && search.data) {
      const terms = search.data.query_terms || splitTerms(search.q);
      const suffix = search.mode === 'raw' ? 'B站原始结果' : `${MODE_LABELS[search.mode]} · ${terms.length} 个词`;
      if (!summary.textContent.includes(suffix)) summary.textContent += ` · ${suffix}`;
    }
    recolorTagChips(view);
  }

  document.addEventListener('click', event => {
    if (currentPage() !== 'search') return;
    const target = event.target instanceof Element ? event.target.closest('button') : null;
    if (!target) return;
    if (target.id === 'enhSearchButton') {
      event.preventDefault();
      event.stopImmediatePropagation();
      startFreshSearch();
      return;
    }
    if (target.dataset.searchOverlayPage) {
      event.preventDefault();
      void loadPage(Number(target.dataset.searchOverlayPage));
      return;
    }
    if (target.id === 'enhSearchMoreTen') {
      event.preventDefault();
      search.pageLimit = Math.min(Math.max(1, search.pages), Number(search.pageLimit || 10) + 10);
      const pager = $('.enh-search-pagination-v2');
      if (pager) pager.outerHTML = paginationHtml();
      return;
    }
    if (target.id === 'enhSearchOverlayJumpButton') {
      event.preventDefault();
      const pages = Math.max(1, Number(search.pages || 1));
      const page = Math.max(1, Math.min(pages, Number($('#enhSearchOverlayJump')?.value || 1)));
      if (page > search.pageLimit) search.pageLimit = Math.ceil(page / 10) * 10;
      void loadPage(page);
    }
  }, true);

  document.addEventListener('keydown', event => {
    if (currentPage() !== 'search' || event.key !== 'Enter' || event.target?.id !== 'enhSearchQuery') return;
    event.preventDefault();
    event.stopImmediatePropagation();
    startFreshSearch();
  }, true);

  const root = $('#pageRoot');
  if (root) new MutationObserver(() => requestAnimationFrame(enhanceView)).observe(root, { childList: true, subtree: true });
  window.addEventListener('hashchange', () => requestAnimationFrame(enhanceView));
  requestAnimationFrame(enhanceView);
})();
