(() => {
  'use strict';
  if (!window.BiliEnhancements) return;
  const {
    VERSION, state, $, $$, esc, formatDate, formatPlay, qualityOptions,
    groupOptions, tagOptions, toast, showModal, api, paginationHtml, tagChips,
    mapLimit, assignTags, bindTagButtons, register,
  } = window.BiliEnhancements;

  const BLOCKED_STATUSES = new Set(['downloaded', 'deleted']);
  const FILTER_MODES = new Set(['raw', 'all', 'any']);

  function normalizeText(value) {
    return String(value || '').normalize('NFKC').toLocaleLowerCase();
  }

  function splitTerms(value) {
    const terms = [];
    const seen = new Set();
    for (const raw of String(value || '').split(/[\s,，;；|/\\()（）\[\]{}<>《》]+/)) {
      const term = raw.trim();
      const folded = normalizeText(term);
      if (!term || seen.has(folded)) continue;
      seen.add(folded);
      terms.push(term.slice(0, 50));
      if (terms.length >= 6) break;
    }
    return terms;
  }

  function rawCacheKey(query, order, page) {
    return `${normalizeText(query)}\u0000${order}\u0000${Math.max(1, Number(page || 1))}`;
  }

  function cancelIdlePreload(search) {
    if (!search.preloadHandle) return;
    if (search.preloadHandleType === 'idle' && window.cancelIdleCallback) {
      window.cancelIdleCallback(search.preloadHandle);
    } else {
      window.clearTimeout(search.preloadHandle);
    }
    search.preloadHandle = 0;
    search.preloadHandleType = '';
  }

  function abortSearchRequests() {
    const search = state.search;
    cancelIdlePreload(search);
    if (search.currentController) search.currentController.abort();
    if (search.preloadController) search.preloadController.abort();
    search.currentController = null;
    search.preloadController = null;
  }

  async function fetchRawPage(query, order, page, { fresh = false, signal } = {}) {
    const search = state.search;
    const key = rawCacheKey(query, order, page);
    if (!fresh && search.cache.has(key)) return search.cache.get(key);
    if (fresh) search.cache.delete(key);
    const params = new URLSearchParams({
      q: query,
      order,
      page: String(page),
    });
    if (fresh) params.set('fresh', 'true');
    const response = await api(`/api/search?${params}`, { signal });
    const data = response.data || {};
    search.cache.set(key, data);
    return data;
  }

  function scheduleNextPagePreload(generation) {
    const search = state.search;
    cancelIdlePreload(search);
    if (!search.data || search.page >= search.pages) return;
    if (navigator.connection?.saveData) return;
    const query = search.q;
    const order = search.order;
    const currentPage = search.page;
    const nextPage = currentPage + 1;
    if (search.cache.has(rawCacheKey(query, order, nextPage))) return;

    const run = async () => {
      search.preloadHandle = 0;
      search.preloadHandleType = '';
      if (
        generation !== search.requestGeneration
        || query !== search.q
        || order !== search.order
        || currentPage !== search.page
      ) return;
      const controller = new AbortController();
      search.preloadController = controller;
      try {
        await fetchRawPage(query, order, nextPage, { signal: controller.signal });
      } catch (error) {
        if (error?.name !== 'AbortError') {
          // Preload is best-effort. The visible page remains fully usable.
        }
      } finally {
        if (search.preloadController === controller) search.preloadController = null;
      }
    };

    if (window.requestIdleCallback) {
      search.preloadHandleType = 'idle';
      search.preloadHandle = window.requestIdleCallback(() => void run(), { timeout: 1200 });
    } else {
      search.preloadHandleType = 'timeout';
      search.preloadHandle = window.setTimeout(() => void run(), 120);
    }
  }

  function currentFilterMode() {
    const mode = String(state.search.filterMode || 'raw');
    return FILTER_MODES.has(mode) ? mode : 'raw';
  }

  function titleFilteredItems() {
    const search = state.search;
    const items = search.data?.items || [];
    const mode = currentFilterMode();
    const terms = splitTerms(search.filterText);
    if (mode === 'raw' || !terms.length) return items;
    return items.filter(item => {
      const title = normalizeText(item.title);
      const matches = terms.map(term => title.includes(normalizeText(term)));
      return mode === 'all' ? matches.every(Boolean) : matches.some(Boolean);
    });
  }

  function visibleSearchItems() {
    const filtered = titleFilteredItems();
    if (!state.search.hideDownloaded) return filtered;
    return filtered.filter(item => !BLOCKED_STATUSES.has(String(item.local_status || '')));
  }

  function filterHelpText() {
    const mode = currentFilterMode();
    const terms = splitTerms(state.search.filterText);
    if (mode === 'raw') return '不发送额外请求，直接显示 Bilibili 当前页原始结果。';
    const rule = mode === 'all' ? '当前页标题需包含全部词' : '当前页标题包含任意词即可';
    return `${rule}${terms.length ? `：${terms.join('、')}` : '；未填写时不筛选'}`;
  }

  async function renderSearch(root) {
    const search = state.search;
    if (!FILTER_MODES.has(search.filterMode)) search.filterMode = 'raw';
    root.innerHTML = `<div data-enhanced-view="search" data-version="${VERSION}">
      <section class="card enh-search-panel">
        <div class="card-head"><div><h2>搜索 Bilibili 作品</h2><p>每次只加载 Bilibili 当前页；精准和模糊只在浏览器中筛选当前页标题。</p></div><span class="badge brand">当前页原始结果</span></div>
        <div class="enh-search-primary-grid">
          <div class="field enh-search-query-field"><label>B站关键词</label><input id="enhSearchQuery" class="input" value="${esc(search.q)}" placeholder="输入交给 Bilibili 的原始关键词"></div>
          <div class="field"><label>B站排序</label><select id="enhSearchOrder" class="select"><option value="totalrank">综合排序</option><option value="click">播放最多</option><option value="pubdate">最新发布</option></select></div>
          <div class="field enh-search-primary-actions-field"><label>读取结果</label><div class="enh-search-primary-actions"><button type="button" id="enhSearchButton" class="btn primary">搜索</button><button type="button" id="enhSearchRefresh" class="btn">刷新B站结果</button></div></div>
        </div>
        <div class="enh-search-secondary-grid">
          <div class="field"><label>标题二级筛选</label><div class="segmented enh-search-filter-modes" role="group" aria-label="标题二级筛选模式"><button type="button" data-search-filter-mode="raw">不筛选</button><button type="button" data-search-filter-mode="all" title="精准：标题包含全部词">精准</button><button type="button" data-search-filter-mode="any" title="模糊：标题包含任意词">模糊</button></div></div>
          <div class="field"><label>当前页标题筛选词</label><input id="enhSearchTitleFilter" class="input" value="${esc(search.filterText)}" placeholder="可与 B站关键词不同；修改不会联网"><small id="enhSearchFilterHelp">${esc(filterHelpText())}</small></div>
          <div class="field enh-search-block-field"><label>本地状态</label><label class="enh-check"><input id="enhHideDownloaded" type="checkbox" ${search.hideDownloaded ? 'checked' : ''}> 屏蔽已下载和已删除</label><small>关闭后可辨识并确认重新下载。</small></div>
        </div>
      </section>
      <section class="card enh-search-download-panel" style="margin-top:16px">
        <div class="enh-search-options-grid">
          <div class="field"><label>下载目标</label><select id="enhSearchDestination" class="select"><option value="library">保存到媒体库</option><option value="device">导出到当前设备</option></select></div>
          <div class="field" id="enhSearchGroupField"><label>保存分组</label><select id="enhSearchGroup" class="select">${groupOptions(search.groupId)}</select></div>
          <div class="field"><label>最低清晰度</label><select id="enhSearchQuality" class="select">${qualityOptions(search.minHeight)}</select></div>
        </div>
        <div class="enh-batch-layout enh-search-batch-layout">
          <span id="enhSearchSummary" class="metric-foot">输入关键词后搜索</span>
          <div class="enh-batch-actions"><button type="button" id="enhSearchSelectVisible" class="btn small">全选当前结果</button><button type="button" id="enhSearchClear" class="btn small">清空选择</button><select id="enhSearchBatchTag" class="select enh-inline-select">${tagOptions()}</select><button type="button" id="enhSearchAddTag" class="btn small">给选中项加标签</button><button type="button" id="enhSearchDownloadSelected" class="btn primary small">下载选中（${search.selected.size}）</button></div>
        </div>
      </section>
      <section id="enhSearchResults" style="margin-top:16px"></section>
    </div>`;

    $('#enhSearchOrder').value = search.order;
    $('#enhSearchDestination').value = search.destination;
    const syncDestination = () => {
      search.destination = $('#enhSearchDestination').value;
      $('#enhSearchGroupField').classList.toggle('hidden', search.destination === 'device');
    };
    syncDestination();
    $('#enhSearchDestination').onchange = syncDestination;
    $('#enhSearchGroup').onchange = () => { search.groupId = $('#enhSearchGroup').value; };
    $('#enhSearchQuality').onchange = () => { search.minHeight = Number($('#enhSearchQuality').value); };
    $('#enhHideDownloaded').onchange = () => {
      search.hideDownloaded = $('#enhHideDownloaded').checked;
      renderSearchResults();
    };
    const cancelStaleQueryWork = () => {
      const query = $('#enhSearchQuery')?.value.trim() || '';
      const order = $('#enhSearchOrder')?.value || 'totalrank';
      if (query === search.q && order === search.order) return;
      abortSearchRequests();
      search.requestGeneration += 1;
    };
    $('#enhSearchButton').onclick = () => void startSearch(false);
    $('#enhSearchRefresh').onclick = () => void startSearch(true);
    $('#enhSearchQuery').oninput = cancelStaleQueryWork;
    $('#enhSearchOrder').onchange = cancelStaleQueryWork;
    $('#enhSearchQuery').onkeydown = event => {
      if (event.key === 'Enter') {
        event.preventDefault();
        void startSearch(false);
      }
    };
    $('#enhSearchTitleFilter').oninput = () => {
      search.filterText = $('#enhSearchTitleFilter').value;
      search.filterTouched = true;
      updateFilterControls();
      renderSearchResults();
    };
    $$('[data-search-filter-mode]').forEach(button => {
      button.onclick = () => {
        search.filterMode = button.dataset.searchFilterMode;
        updateFilterControls();
        renderSearchResults();
      };
    });
    $('#enhSearchSelectVisible').onclick = () => {
      for (const item of visibleSearchItems()) search.selected.set(item.bvid, item);
      renderSearchResults();
    };
    $('#enhSearchClear').onclick = () => { search.selected.clear(); renderSearchResults(); };
    $('#enhSearchDownloadSelected').onclick = () => void downloadSearchItems([...search.selected.values()]);
    $('#enhSearchAddTag').onclick = () => void batchTagSearchItems();
    updateFilterControls();

    if (search.data) {
      renderSearchResults();
      scheduleNextPagePreload(search.requestGeneration);
    } else if (search.q) {
      await loadSearchPage(search.page);
    } else {
      $('#enhSearchResults').innerHTML = '<div class="empty">输入关键词开始搜索</div>';
    }
  }

  function updateFilterControls() {
    const mode = currentFilterMode();
    $$('[data-search-filter-mode]').forEach(button => {
      button.classList.toggle('active', button.dataset.searchFilterMode === mode);
    });
    const help = $('#enhSearchFilterHelp');
    if (help) help.textContent = filterHelpText();
  }

  async function startSearch(fresh) {
    const search = state.search;
    const query = $('#enhSearchQuery')?.value.trim() || '';
    const order = $('#enhSearchOrder')?.value || 'totalrank';
    if (!query) {
      toast('请输入关键词', 'warn');
      return;
    }
    const changed = query !== search.q || order !== search.order;
    const previousQuery = search.q;
    search.q = query;
    search.order = order;
    if (changed) {
      search.page = 1;
      search.pages = 0;
      search.total = 0;
      search.data = null;
      search.selected.clear();
      if (!search.filterTouched || search.filterText === previousQuery) search.filterText = query;
      const input = $('#enhSearchTitleFilter');
      if (input) input.value = search.filterText;
      updateFilterControls();
    }
    await loadSearchPage(changed ? 1 : search.page || 1, { fresh });
  }

  async function loadSearchPage(page, { fresh = false } = {}) {
    const search = state.search;
    if (!search.q) return;
    const safePage = Math.max(1, Number(page || 1));
    abortSearchRequests();
    const generation = search.requestGeneration + 1;
    search.requestGeneration = generation;
    const query = search.q;
    const order = search.order;
    const controller = new AbortController();
    search.currentController = controller;
    const box = $('#enhSearchResults');
    if (box) box.innerHTML = '<div class="loading-card">正在读取 Bilibili 当前页…</div>';
    try {
      const data = await fetchRawPage(query, order, safePage, {
        fresh,
        signal: controller.signal,
      });
      if (
        generation !== search.requestGeneration
        || query !== search.q
        || order !== search.order
      ) return;
      search.page = safePage;
      search.data = data;
      search.pages = Number(data.pages || data.numPages || data.num_pages || 0);
      search.total = Number(data.total || data.numResults || data.num_results || 0);
      renderSearchResults();
      scheduleNextPagePreload(generation);
    } catch (error) {
      if (error?.name === 'AbortError') return;
      if (generation === search.requestGeneration && box) {
        box.innerHTML = `<div class="notice bad">${esc(error.message)}</div>`;
        toast(error.message, 'bad');
      }
    } finally {
      if (search.currentController === controller) search.currentController = null;
    }
  }

  function searchStatusClass(status) {
    if (status === 'downloaded') return 'good';
    if (status === 'running' || status === 'queued') return 'warn';
    if (status === 'deleted' || status === 'failed' || status === 'cancelled') return 'bad';
    return 'neutral';
  }

  function searchCard(item) {
    const selected = state.search.selected.has(item.bvid);
    const repeated = BLOCKED_STATUSES.has(String(item.local_status || ''));
    const sourceUrl = item.url || `https://www.bilibili.com/video/${encodeURIComponent(item.bvid || '')}`;
    return `<article class="media-card enh-search-card" data-search-key="${esc(item.bvid)}">
      <div class="cover-wrap"><img data-cover-img src="${esc(coverUrl(item.cover))}" alt="${esc(item.title)}" loading="lazy" referrerpolicy="no-referrer"><label class="enh-card-select"><input type="checkbox" data-search-select="${esc(item.bvid)}" ${selected ? 'checked' : ''}> 选择</label><div class="cover-badges"><span></span><span class="badge ${searchStatusClass(item.local_status)}">${esc(item.local_status_label || '未下载')}</span></div>${item.duration ? `<span class="duration-chip">${esc(item.duration)}</span>` : ''}</div>
      <div class="media-body"><a class="media-title" href="${esc(sourceUrl)}" target="_blank" rel="noopener noreferrer">${esc(item.title || item.bvid)}</a><div class="media-meta"><span>${esc(item.author || '-')}</span><span>${formatPlay(item.play)} 播放</span><span>${formatDate(item.pubdate, true)}</span></div><div class="media-meta"><span>${esc(item.bvid)}</span>${item.local_group ? `<span>分组：${esc(item.local_group)}</span>` : ''}${item.local_quality ? `<span>${esc(item.local_quality)}</span>` : ''}</div>${tagChips(item.bvid, item.tags)}<div class="media-actions"><a class="btn small" href="${esc(sourceUrl)}" target="_blank" rel="noopener noreferrer">B站原页面</a><button type="button" class="btn small" data-search-preview="${esc(item.bvid)}">预览画质</button><button type="button" class="btn primary small" data-search-download="${esc(item.bvid)}">${repeated ? '重新下载' : '下载'}</button></div></div>
    </article>`;
  }

  function coverUrl(value) {
    const text = String(value || '');
    if (text.startsWith('https://')) return `/api/cover?url=${encodeURIComponent(text)}`;
    const svg = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 640 360"><rect width="640" height="360" fill="#e8edf5"/><path d="M275 125l115 55-115 55z" fill="#94a3b8"/><text x="320" y="290" text-anchor="middle" font-family="sans-serif" font-size="23" fill="#64748b">暂无封面</text></svg>';
    return `data:image/svg+xml,${encodeURIComponent(svg)}`;
  }

  function bindCoverFallback(root = document) {
    $$('img[data-cover-img]', root).forEach(image => {
      image.onerror = () => { image.onerror = null; image.src = coverUrl(''); };
    });
  }

  function renderSearchResults() {
    const box = $('#enhSearchResults');
    const search = state.search;
    if (!box) return;
    updateFilterControls();
    if (!search.data) {
      box.innerHTML = '<div class="empty">输入关键词开始搜索</div>';
      return;
    }
    const rawItems = search.data.items || [];
    const filteredItems = titleFilteredItems();
    const items = visibleSearchItems();
    const blockedCount = filteredItems.length - items.length;
    const pages = search.pages || Math.max(1, search.page);
    const summary = $('#enhSearchSummary');
    if (summary) {
      summary.textContent = `第 ${search.page} / ${pages || '?'} 页 · B站共 ${search.total || 0} 条 · 原始 ${rawItems.length} 条 · 筛选后 ${filteredItems.length} 条${blockedCount ? ` · 屏蔽 ${blockedCount} 条` : ''}`;
    }
    const batch = $('#enhSearchDownloadSelected');
    if (batch) batch.textContent = `下载选中（${search.selected.size}）`;

    let content;
    if (items.length) {
      content = `<div class="media-grid">${items.map(searchCard).join('')}</div>`;
    } else if (!filteredItems.length && currentFilterMode() !== 'raw') {
      content = '<div class="empty">本页没有标题匹配项，可查看下一页；系统不会自动抓取全部页面。</div>';
    } else if (blockedCount) {
      content = '<div class="empty">当前页匹配项均已下载或曾被删除；可关闭屏蔽后查看。</div>';
    } else {
      content = '<div class="empty">Bilibili 当前页没有结果</div>';
    }
    box.innerHTML = `${content}${paginationHtml(search.page, pages, 'search')}`;

    $$('[data-search-select]', box).forEach(input => {
      input.onchange = () => {
        const item = rawItems.find(value => value.bvid === input.dataset.searchSelect);
        if (!item) return;
        if (input.checked) search.selected.set(item.bvid, item);
        else search.selected.delete(item.bvid);
        const button = $('#enhSearchDownloadSelected');
        if (button) button.textContent = `下载选中（${search.selected.size}）`;
      };
    });
    $$('[data-search-page]', box).forEach(button => {
      button.onclick = () => void loadSearchPage(Number(button.dataset.searchPage));
    });
    const jump = $('[data-search-jump]', box);
    const jumpButton = $('[data-search-jump-button]', box);
    if (jumpButton) {
      jumpButton.onclick = () => void loadSearchPage(
        Math.max(1, Math.min(pages, Number(jump.value || 1))),
      );
    }
    $$('[data-search-preview]', box).forEach(button => {
      button.onclick = () => void previewSearchItem(rawItems.find(item => item.bvid === button.dataset.searchPreview));
    });
    $$('[data-search-download]', box).forEach(button => {
      button.onclick = () => void downloadSearchItems([
        rawItems.find(item => item.bvid === button.dataset.searchDownload),
      ]);
    });
    bindTagButtons(box, key => rawItems.find(item => item.bvid === key), renderSearchResults);
    bindCoverFallback(box);
  }

  async function previewSearchItem(item) {
    if (!item) return;
    const modal = showModal('画质预览', '<div class="loading-card">正在读取可用视频流…</div>');
    try {
      const response = await api('/api/preview', {
        method: 'POST',
        body: {
          item: {
            bvid: item.bvid, url: item.url, title: item.title, cover: item.cover,
            author: item.author, pubdate: item.pubdate, duration: item.duration,
            play: item.play, preferred_quality: item.preferred_quality || '',
          },
          min_height: Number(state.search.minHeight || 0),
          preferred_quality: item.preferred_quality || '',
        },
      });
      const quality = response.data?.quality || {};
      const parts = quality.parts || [];
      let common = null;
      for (const part of parts) {
        const available = new Set((part.available || []).map(track => track.dfn).filter(Boolean));
        common = common === null ? available : new Set([...common].filter(value => available.has(value)));
      }
      const choices = [...(common || [])];
      $('.modal-body', modal.root).innerHTML = `<div class="notice"><strong>${esc(response.data?.metadata?.title || item.title)}</strong><br>${esc(item.bvid)} · 最高可用：${esc(quality.highest_label || '-')} · ${esc(quality.summary || '')}</div><div class="field" style="margin-top:14px"><label>该作品目标档位</label><select id="enhPreviewPreferred" class="select"><option value="">自动最高</option>${choices.map(label => `<option value="${esc(label)}" ${item.preferred_quality === label ? 'selected' : ''}>${esc(label)}</option>`).join('')}</select><small>选择后会在创建下载任务时严格核对；留空使用自动最高。</small></div><div class="file-list" style="margin-top:14px">${parts.map((part, index) => `<section class="notice"><strong>分 P ${index + 1}</strong><div class="metric-foot">${(part.available || []).map(track => `${esc(track.dfn || track.resolution || '-')} · ${esc(track.codec || '-')}`).join('　')}</div></section>`).join('')}</div>`;
      $('#enhPreviewPreferred', modal.root).onchange = () => {
        item.preferred_quality = $('#enhPreviewPreferred', modal.root).value;
        if (state.search.selected.has(item.bvid)) state.search.selected.set(item.bvid, item);
        toast(item.preferred_quality ? `已选择 ${item.preferred_quality}` : '已恢复自动最高', 'good');
      };
    } catch (error) {
      $('.modal-body', modal.root).innerHTML = `<div class="notice bad">${esc(error.message)}</div>`;
    }
  }

  async function downloadSearchItems(items) {
    const valid = items.filter(Boolean);
    if (!valid.length) {
      toast('请先选择作品', 'warn');
      return;
    }
    const deleted = valid.filter(item => item.local_status === 'deleted');
    const downloaded = valid.filter(item => item.local_status === 'downloaded');
    if (deleted.length) {
      const message = deleted.length === 1
        ? '这个作品以前被你删除过。确定要重新下载吗？'
        : `选中的作品中有 ${deleted.length} 个曾被删除。确定要重新下载吗？`;
      if (!confirm(message)) return;
    }
    if (downloaded.length && !confirm(`选中的作品中有 ${downloaded.length} 个已经下载。继续会事务性重新下载并替换旧文件，是否继续？`)) return;
    const destination = state.search.destination || 'library';
    try {
      const response = await api('/api/download', {
        method: 'POST',
        body: {
          urls: [], bvids: [],
          items: valid.map(item => ({
            bvid: item.bvid, url: item.url, title: item.title, cover: item.cover,
            author: item.author, pubdate: item.pubdate, duration: item.duration,
            play: item.play, preferred_quality: item.preferred_quality || '',
          })),
          force: downloaded.length > 0 || deleted.length > 0,
          group_id: destination === 'library' ? state.search.groupId : '',
          group: '', destination, min_height: Number(state.search.minHeight || 0),
        },
      });
      for (const item of valid) {
        item.local_status = 'queued';
        item.local_status_label = '排队中';
        item.deleted_record = false;
      }
      state.search.selected.clear();
      toast(`已创建 ${response.total || valid.length} 个任务，仍停留在搜索页`, 'good');
      renderSearchResults();
    } catch (error) {
      toast(error.message, 'bad');
    }
  }

  async function batchTagSearchItems() {
    const tag = $('#enhSearchBatchTag')?.value || '';
    const items = [...state.search.selected.values()];
    if (!tag || !items.length) {
      toast('请选择标签和作品', 'warn');
      return;
    }
    try {
      await mapLimit(items, 6, async item => {
        const tags = new Set(item.tags || []);
        tags.add(tag);
        item.tags = await assignTags(item.bvid, [...tags]);
      });
      toast(`已给 ${items.length} 个作品添加“${tag}”标签`, 'good');
      renderSearchResults();
    } catch (error) {
      toast(error.message, 'bad');
    }
  }

  window.BiliEnhancements.coverUrl = coverUrl;
  window.BiliEnhancements.bindCoverFallback = bindCoverFallback;
  register('search', renderSearch);
})();
