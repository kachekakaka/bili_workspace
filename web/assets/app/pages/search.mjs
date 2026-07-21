import { once } from '../core/lifecycle.mjs';
import {
  filterSearchItems,
  searchPageKey,
  shouldPrefetchNextPage,
  splitTitleTerms,
} from '../core/search-policy.mjs';
import {
  bindCoverFallback,
  coverUrl,
  esc,
  formatDate,
  groupOptions,
  qualityOptions,
} from './shared.mjs';
import { libraryTagColor } from './library.mjs';

const BLOCKED_STATUSES = new Set(['downloaded', 'deleted']);
const FILTER_MODES = new Set(['raw', 'all', 'any']);
const searchState = {
  q: '',
  order: 'totalrank',
  page: 1,
  pages: 0,
  total: 0,
  data: null,
  cache: new Map(),
  selected: new Map(),
  hideDownloaded: true,
  filterMode: 'raw',
  filterText: '',
  filterTouched: false,
  destination: 'library',
  groupId: '',
  minHeight: 1080,
  requestGeneration: 0,
  currentController: null,
  preloadController: null,
  preloadHandle: 0,
  preloadHandleType: '',
};

function policyMode(mode = searchState.filterMode) {
  return mode === 'all' ? 'exact' : mode === 'any' ? 'fuzzy' : 'raw';
}

function currentFilterMode() {
  return FILTER_MODES.has(searchState.filterMode) ? searchState.filterMode : 'raw';
}

function formatPlay(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) return '-';
  if (number >= 1e8) return `${(number / 1e8).toFixed(number >= 1e9 ? 0 : 1)}亿`;
  if (number >= 1e4) return `${(number / 1e4).toFixed(number >= 1e5 ? 0 : 1)}万`;
  return String(Math.round(number));
}

function tagOptions(tags, selected = '') {
  return '<option value="">选择标签</option>' + (tags || []).map(tag => (
    `<option value="${esc(tag.name)}" ${String(tag.name) === String(selected) ? 'selected' : ''}>${esc(tag.name)}</option>`
  )).join('');
}

function tagChips(tags, sourceKey, selectedTags = []) {
  const selected = new Set((selectedTags || []).map(value => String(value).toLowerCase()));
  return `<div class="enh-tag-row" data-tag-row="${esc(sourceKey)}">${(tags || []).map(tag => {
    const active = selected.has(String(tag.name).toLowerCase());
    return `<button type="button" class="enh-tag-chip ${active ? 'active' : ''}" style="--tag-color:${libraryTagColor(tag)}" data-search-tag-key="${esc(sourceKey)}" data-search-tag-name="${esc(tag.name)}" aria-pressed="${active ? 'true' : 'false'}">${esc(tag.name)}</button>`;
  }).join('')}</div>`;
}

function paginationHtml(page, pages) {
  const total = Math.max(1, Number(pages || 1));
  const current = Math.max(1, Math.min(total, Number(page || 1)));
  const wanted = new Set([1, total, current - 2, current - 1, current, current + 1, current + 2]);
  const values = [...wanted].filter(value => value >= 1 && value <= total).sort((a, b) => a - b);
  const controls = [];
  let previous = 0;
  for (const value of values) {
    if (previous && value - previous > 1) controls.push('<span class="enh-page-gap">…</span>');
    controls.push(`<button type="button" class="btn small ${value === current ? 'primary active' : ''}" data-search-page="${value}">${value}</button>`);
    previous = value;
  }
  return `<div class="enh-pagination"><button type="button" class="btn small" data-search-page="${Math.max(1, current - 1)}" ${current <= 1 ? 'disabled' : ''}>上一页</button>${controls.join('')}<button type="button" class="btn small" data-search-page="${Math.min(total, current + 1)}" ${current >= total ? 'disabled' : ''}>下一页</button><input class="input enh-page-jump" type="number" min="1" max="${total}" value="${current}" data-search-jump><button type="button" class="btn small" data-search-jump-button>跳转</button></div>`;
}

function searchStatusClass(status) {
  if (status === 'downloaded') return 'good';
  if (status === 'running' || status === 'queued') return 'warn';
  if (status === 'deleted' || status === 'failed' || status === 'cancelled') return 'bad';
  return 'neutral';
}

function filterHelpText() {
  const mode = currentFilterMode();
  const terms = splitTitleTerms(searchState.filterText);
  if (mode === 'raw') return '不发送额外请求，直接显示 Bilibili 当前页原始结果。';
  const rule = mode === 'all' ? '当前页标题需包含全部词' : '当前页标题包含任意词即可';
  return `${rule}${terms.length ? `：${terms.join('、')}` : '；未填写时不筛选'}`;
}

function titleFilteredItems() {
  return filterSearchItems(
    searchState.data?.items || [],
    searchState.filterText,
    policyMode(),
  );
}

function visibleSearchItems() {
  const filtered = titleFilteredItems();
  if (!searchState.hideDownloaded) return filtered;
  return filtered.filter(item => !BLOCKED_STATUSES.has(String(item.local_status || '')));
}

function searchCard(item, tags) {
  const selected = searchState.selected.has(item.bvid);
  const repeated = BLOCKED_STATUSES.has(String(item.local_status || ''));
  const sourceUrl = item.url || `https://www.bilibili.com/video/${encodeURIComponent(item.bvid || '')}`;
  return `<article class="media-card enh-search-card" data-search-key="${esc(item.bvid)}"><div class="cover-wrap"><img data-cover-img src="${esc(coverUrl(item.cover))}" alt="${esc(item.title)}" loading="lazy" referrerpolicy="no-referrer"><label class="enh-card-select"><input type="checkbox" data-search-select="${esc(item.bvid)}" ${selected ? 'checked' : ''}> 选择</label><div class="cover-badges"><span></span><span class="badge ${searchStatusClass(item.local_status)}">${esc(item.local_status_label || '未下载')}</span></div>${item.duration ? `<span class="duration-chip">${esc(item.duration)}</span>` : ''}</div><div class="media-body"><a class="media-title" href="${esc(sourceUrl)}" target="_blank" rel="noopener noreferrer">${esc(item.title || item.bvid)}</a><div class="media-meta"><span>${esc(item.author || '-')}</span><span>${formatPlay(item.play)} 播放</span><span>${formatDate(item.pubdate, true)}</span></div><div class="media-meta"><span>${esc(item.bvid)}</span>${item.local_group ? `<span>分组：${esc(item.local_group)}</span>` : ''}${item.local_quality ? `<span>${esc(item.local_quality)}</span>` : ''}</div>${tagChips(tags, item.bvid, item.tags)}<div class="media-actions"><a class="btn small" href="${esc(sourceUrl)}" target="_blank" rel="noopener noreferrer">B站原页面</a><button type="button" class="btn small" data-search-preview="${esc(item.bvid)}">预览画质</button><button type="button" class="btn primary small" data-search-download="${esc(item.bvid)}">${repeated ? '重新下载' : '下载'}</button></div></div></article>`;
}

async function mapLimit(items, limit, callback) {
  const queue = [...items];
  const workers = Array.from({ length: Math.min(limit, queue.length) }, async () => {
    while (queue.length) {
      const item = queue.shift();
      await callback(item);
    }
  });
  await Promise.all(workers);
}

export async function mount(root, context) {
  const groups = context.shared.get().groups || [];
  const tags = context.shared.get().tags || [];
  if (!FILTER_MODES.has(searchState.filterMode)) searchState.filterMode = 'raw';
  const host = document.createElement('div');
  host.innerHTML = `<div data-enhanced-view="search"><section class="card enh-search-panel"><div class="card-head"><div><h2>搜索 Bilibili 作品</h2><p>每次只加载 Bilibili 当前页；精准和模糊只在浏览器中筛选当前页标题。</p></div><span class="badge brand">当前页原始结果</span></div><div class="enh-search-primary-grid"><div class="field enh-search-query-field"><label>B站关键词</label><input id="enhSearchQuery" class="input" value="${esc(searchState.q)}" placeholder="输入交给 Bilibili 的原始关键词"></div><div class="field"><label>B站排序</label><select id="enhSearchOrder" class="select"><option value="totalrank">综合排序</option><option value="click">播放最多</option><option value="pubdate">最新发布</option></select></div><div class="field enh-search-primary-actions-field"><label>读取结果</label><div class="enh-search-primary-actions"><button type="button" id="enhSearchButton" class="btn primary">搜索</button><button type="button" id="enhSearchRefresh" class="btn">刷新B站结果</button></div></div></div><div class="enh-search-secondary-grid"><div class="field"><label>标题二级筛选</label><div class="segmented enh-search-filter-modes" role="group" aria-label="标题二级筛选模式"><button type="button" data-search-filter-mode="raw">不筛选</button><button type="button" data-search-filter-mode="all" title="精准：标题包含全部词">精准</button><button type="button" data-search-filter-mode="any" title="模糊：标题包含任意词">模糊</button></div></div><div class="field"><label>当前页标题筛选词</label><input id="enhSearchTitleFilter" class="input" value="${esc(searchState.filterText)}" placeholder="可与 B站关键词不同；修改不会联网"><small id="enhSearchFilterHelp">${esc(filterHelpText())}</small></div><div class="field enh-search-block-field"><label>本地状态</label><label class="enh-check"><input id="enhHideDownloaded" type="checkbox" ${searchState.hideDownloaded ? 'checked' : ''}> 屏蔽已下载和已删除</label><small>关闭后可辨识并确认重新下载。</small></div></div></section><section class="card enh-search-download-panel" style="margin-top:16px"><div class="enh-search-options-grid"><div class="field"><label>下载目标</label><select id="enhSearchDestination" class="select"><option value="library">保存到媒体库</option><option value="device">导出到当前设备</option></select></div><div class="field" id="enhSearchGroupField"><label>保存分组</label><select id="enhSearchGroup" class="select">${groupOptions(groups, searchState.groupId)}</select></div><div class="field"><label>最低清晰度</label><select id="enhSearchQuality" class="select">${qualityOptions(searchState.minHeight)}</select></div></div><div class="enh-batch-layout enh-search-batch-layout"><span id="enhSearchSummary" class="metric-foot">输入关键词后搜索</span><div class="enh-batch-actions"><button type="button" id="enhSearchSelectVisible" class="btn small">全选当前结果</button><button type="button" id="enhSearchClear" class="btn small">清空选择</button><select id="enhSearchBatchTag" class="select enh-inline-select">${tagOptions(tags)}</select><button type="button" id="enhSearchAddTag" class="btn small">给选中项加标签</button><button type="button" id="enhSearchDownloadSelected" class="btn primary small">下载选中（${searchState.selected.size}）</button></div></div></section><section id="enhSearchResults" style="margin-top:16px"></section></div>`;
  context.commit(() => root.replaceChildren(host));

  const results = host.querySelector('#enhSearchResults');
  let ownsModal = false;

  const cancelIdlePreload = () => {
    if (!searchState.preloadHandle) return;
    if (searchState.preloadHandleType === 'idle' && globalThis.cancelIdleCallback) globalThis.cancelIdleCallback(searchState.preloadHandle);
    else globalThis.clearTimeout(searchState.preloadHandle);
    searchState.preloadHandle = 0;
    searchState.preloadHandleType = '';
  };

  const abortSearchRequests = () => {
    cancelIdlePreload();
    searchState.currentController?.abort();
    searchState.preloadController?.abort();
    searchState.currentController = null;
    searchState.preloadController = null;
  };
  context.signal.addEventListener('abort', abortSearchRequests, { once: true });

  const updateTagsEverywhere = (sourceKey, values) => {
    for (const data of searchState.cache.values()) {
      for (const item of data.items || []) {
        if (String(item.bvid || '') === String(sourceKey)) item.tags = [...values];
      }
    }
    const selected = searchState.selected.get(sourceKey);
    if (selected) selected.tags = [...values];
    for (const item of searchState.data?.items || []) {
      if (String(item.bvid || '') === String(sourceKey)) item.tags = [...values];
    }
  };

  const assignTags = async (item, values) => {
    const response = await context.api('/api/enhancements/tags', {
      method: 'PUT',
      body: { source_key: item.bvid || '', media_id: '', tags: values },
      signal: context.signal,
    });
    const next = response.data?.tags || [];
    updateTagsEverywhere(response.data?.source_key || item.bvid, next);
    return next;
  };

  const updateFilterControls = () => {
    const mode = currentFilterMode();
    for (const button of host.querySelectorAll('[data-search-filter-mode]')) {
      button.classList.toggle('active', button.dataset.searchFilterMode === mode);
    }
    host.querySelector('#enhSearchFilterHelp').textContent = filterHelpText();
  };

  const renderSearchResults = () => {
    if (!context.isCurrent()) return;
    updateFilterControls();
    if (!searchState.data) {
      results.innerHTML = '<div class="empty">输入关键词开始搜索</div>';
      return;
    }
    const rawItems = searchState.data.items || [];
    const filteredItems = titleFilteredItems();
    const items = visibleSearchItems();
    const blockedCount = filteredItems.length - items.length;
    const pages = searchState.pages || Math.max(1, searchState.page);
    host.querySelector('#enhSearchSummary').textContent = `第 ${searchState.page} / ${pages || '?'} 页 · B站共 ${searchState.total || 0} 条 · 原始 ${rawItems.length} 条 · 筛选后 ${filteredItems.length} 条${blockedCount ? ` · 屏蔽 ${blockedCount} 条` : ''}`;
    host.querySelector('#enhSearchDownloadSelected').textContent = `下载选中（${searchState.selected.size}）`;
    let content;
    if (items.length) content = `<div class="media-grid">${items.map(item => searchCard(item, tags)).join('')}</div>`;
    else if (!filteredItems.length && currentFilterMode() !== 'raw') content = '<div class="empty">本页没有标题匹配项，可查看下一页；系统不会自动抓取全部页面。</div>';
    else if (blockedCount) content = '<div class="empty">当前页匹配项均已下载或曾被删除；可关闭屏蔽后查看。</div>';
    else content = '<div class="empty">Bilibili 当前页没有结果</div>';
    results.innerHTML = `${content}${paginationHtml(searchState.page, pages)}`;
    bindCoverFallback(results, context.signal);
  };

  const fetchRawPage = async (query, order, page, { fresh = false, signal } = {}) => {
    const key = searchPageKey({ keyword: query, order, page });
    if (!fresh && searchState.cache.has(key)) return searchState.cache.get(key);
    if (fresh) searchState.cache.delete(key);
    const params = new URLSearchParams({ q: query, order, page: String(page) });
    if (fresh) params.set('fresh', 'true');
    const response = await context.api(`/api/search?${params}`, { signal });
    const data = response.data || {};
    searchState.cache.set(key, data);
    return data;
  };

  const scheduleNextPagePreload = generation => {
    cancelIdlePreload();
    const query = searchState.q;
    const order = searchState.order;
    const currentPage = searchState.page;
    const nextPage = currentPage + 1;
    if (!shouldPrefetchNextPage({
      page: currentPage,
      pages: searchState.pages,
      saveData: Boolean(globalThis.navigator?.connection?.saveData),
      currentPageSucceeded: Boolean(searchState.data),
      queryIsCurrent: generation === searchState.requestGeneration,
    })) return;
    if (searchState.cache.has(searchPageKey({ keyword: query, order, page: nextPage }))) return;
    const run = async () => {
      searchState.preloadHandle = 0;
      searchState.preloadHandleType = '';
      if (
        generation !== searchState.requestGeneration
        || query !== searchState.q
        || order !== searchState.order
        || currentPage !== searchState.page
        || context.signal.aborted
      ) return;
      const controller = new AbortController();
      searchState.preloadController = controller;
      const abort = () => controller.abort();
      context.signal.addEventListener('abort', abort, { once: true });
      try {
        await fetchRawPage(query, order, nextPage, { signal: controller.signal });
      } catch (error) {
        if (error?.name !== 'AbortError') {
          // Best-effort only; the visible current page remains authoritative.
        }
      } finally {
        context.signal.removeEventListener('abort', abort);
        if (searchState.preloadController === controller) searchState.preloadController = null;
      }
    };
    if (globalThis.requestIdleCallback) {
      searchState.preloadHandleType = 'idle';
      searchState.preloadHandle = globalThis.requestIdleCallback(() => void run(), { timeout: 1200 });
    } else {
      searchState.preloadHandleType = 'timeout';
      searchState.preloadHandle = globalThis.setTimeout(() => void run(), 120);
    }
  };

  const loadSearchPage = async (page, { fresh = false } = {}) => {
    if (!searchState.q) return;
    const safePage = Math.max(1, Number(page || 1));
    abortSearchRequests();
    const generation = searchState.requestGeneration + 1;
    searchState.requestGeneration = generation;
    const query = searchState.q;
    const order = searchState.order;
    const controller = new AbortController();
    searchState.currentController = controller;
    const abort = () => controller.abort();
    context.signal.addEventListener('abort', abort, { once: true });
    results.innerHTML = '<div class="loading-card">正在读取 Bilibili 当前页…</div>';
    try {
      const data = await fetchRawPage(query, order, safePage, { fresh, signal: controller.signal });
      if (
        generation !== searchState.requestGeneration
        || query !== searchState.q
        || order !== searchState.order
        || !context.isCurrent()
      ) return;
      searchState.page = safePage;
      searchState.data = data;
      searchState.pages = Number(data.pages || data.numPages || data.num_pages || 0);
      searchState.total = Number(data.total || data.numResults || data.num_results || 0);
      renderSearchResults();
      scheduleNextPagePreload(generation);
    } catch (error) {
      if (error?.name === 'AbortError') return;
      if (generation === searchState.requestGeneration && context.isCurrent()) {
        results.innerHTML = `<div class="notice bad">${esc(error.message)}</div>`;
        context.toast.show(error.message, 'bad');
      }
    } finally {
      context.signal.removeEventListener('abort', abort);
      if (searchState.currentController === controller) searchState.currentController = null;
    }
  };

  const startSearch = async fresh => {
    const query = host.querySelector('#enhSearchQuery').value.trim();
    const order = host.querySelector('#enhSearchOrder').value || 'totalrank';
    if (!query) {
      context.toast.show('请输入关键词', 'warn');
      return;
    }
    const changed = query !== searchState.q || order !== searchState.order;
    const previousQuery = searchState.q;
    searchState.q = query;
    searchState.order = order;
    if (changed) {
      searchState.page = 1;
      searchState.pages = 0;
      searchState.total = 0;
      searchState.data = null;
      searchState.selected.clear();
      if (!searchState.filterTouched || searchState.filterText === previousQuery) searchState.filterText = query;
      host.querySelector('#enhSearchTitleFilter').value = searchState.filterText;
      updateFilterControls();
    }
    await loadSearchPage(changed ? 1 : searchState.page || 1, { fresh });
  };

  const previewSearchItem = async item => {
    if (!item) return;
    const modal = context.modal.open({
      title: '画质预览',
      body: '<div class="loading-card">正在读取可用视频流…</div>',
      onClose: () => { ownsModal = false; },
    });
    ownsModal = true;
    try {
      const response = await context.api('/api/preview', {
        method: 'POST',
        body: {
          item: {
            bvid: item.bvid, url: item.url, title: item.title, cover: item.cover,
            author: item.author, pubdate: item.pubdate, duration: item.duration,
            play: item.play, preferred_quality: item.preferred_quality || '',
          },
          min_height: Number(searchState.minHeight || 0),
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
      modal.body.innerHTML = `<div class="notice"><strong>${esc(response.data?.metadata?.title || item.title)}</strong><br>${esc(item.bvid)} · 最高可用：${esc(quality.highest_label || '-')} · ${esc(quality.summary || '')}</div><div class="field" style="margin-top:14px"><label>该作品目标档位</label><select id="enhPreviewPreferred" class="select"><option value="">自动最高</option>${choices.map(label => `<option value="${esc(label)}" ${item.preferred_quality === label ? 'selected' : ''}>${esc(label)}</option>`).join('')}</select><small>选择后会在创建下载任务时严格核对；留空使用自动最高。</small></div><div class="file-list" style="margin-top:14px">${parts.map((part, index) => `<section class="notice"><strong>分 P ${index + 1}</strong><div class="metric-foot">${(part.available || []).map(track => `${esc(track.dfn || track.resolution || '-')} · ${esc(track.codec || '-')}`).join('　')}</div></section>`).join('')}</div>`;
      modal.body.querySelector('#enhPreviewPreferred').addEventListener('change', event => {
        item.preferred_quality = event.currentTarget.value;
        if (searchState.selected.has(item.bvid)) searchState.selected.set(item.bvid, item);
        context.toast.show(item.preferred_quality ? `已选择 ${item.preferred_quality}` : '已恢复自动最高', 'good');
      });
    } catch (error) {
      modal.body.innerHTML = `<div class="notice bad">${esc(error.message)}</div>`;
    }
  };

  const downloadSearchItems = async items => {
    const valid = items.filter(Boolean);
    if (!valid.length) {
      context.toast.show('请先选择作品', 'warn');
      return;
    }
    const deleted = valid.filter(item => item.local_status === 'deleted');
    const downloaded = valid.filter(item => item.local_status === 'downloaded');
    if (deleted.length) {
      const accepted = await context.confirm({
        title: '重新下载已删除作品',
        message: deleted.length === 1 ? '这个作品以前被你删除过。确定要重新下载吗？' : `选中的作品中有 ${deleted.length} 个曾被删除。确定要重新下载吗？`,
        confirmLabel: '重新下载',
      });
      if (!accepted) return;
    }
    if (downloaded.length) {
      const accepted = await context.confirm({
        title: '替换已下载作品',
        message: `选中的作品中有 ${downloaded.length} 个已经下载。继续会事务性重新下载并替换旧文件，是否继续？`,
        confirmLabel: '继续下载',
      });
      if (!accepted) return;
    }
    const destination = searchState.destination || 'library';
    try {
      const response = await context.api('/api/download', {
        method: 'POST',
        body: {
          urls: [],
          bvids: [],
          items: valid.map(item => ({
            bvid: item.bvid, url: item.url, title: item.title, cover: item.cover,
            author: item.author, pubdate: item.pubdate, duration: item.duration,
            play: item.play, preferred_quality: item.preferred_quality || '',
          })),
          force: downloaded.length > 0 || deleted.length > 0,
          group_id: destination === 'library' ? searchState.groupId : '',
          group: '',
          destination,
          min_height: Number(searchState.minHeight || 0),
        },
      });
      for (const item of valid) {
        item.local_status = 'queued';
        item.local_status_label = '排队中';
        item.deleted_record = false;
      }
      searchState.selected.clear();
      context.toast.show(`已创建 ${response.total || response.data?.length || valid.length} 个任务，仍停留在搜索页`, 'good');
      renderSearchResults();
    } catch (error) {
      context.toast.show(error.message, 'bad');
    }
  };

  const batchTagSearchItems = async () => {
    const tag = host.querySelector('#enhSearchBatchTag').value || '';
    const items = [...searchState.selected.values()];
    if (!tag || !items.length) {
      context.toast.show('请选择标签和作品', 'warn');
      return;
    }
    try {
      await mapLimit(items, 6, async item => {
        const values = new Set(item.tags || []);
        values.add(tag);
        item.tags = await assignTags(item, [...values]);
      });
      context.toast.show(`已给 ${items.length} 个作品添加“${tag}”标签`, 'good');
      renderSearchResults();
    } catch (error) {
      context.toast.show(error.message, 'bad');
    }
  };

  host.querySelector('#enhSearchOrder').value = searchState.order;
  host.querySelector('#enhSearchDestination').value = searchState.destination;
  host.querySelector('#enhSearchQuality').value = String(searchState.minHeight || 0);
  const syncDestination = () => {
    searchState.destination = host.querySelector('#enhSearchDestination').value;
    host.querySelector('#enhSearchGroupField').classList.toggle('hidden', searchState.destination === 'device');
  };
  syncDestination();
  updateFilterControls();

  host.querySelector('#enhSearchDestination').addEventListener('change', syncDestination, { signal: context.signal });
  host.querySelector('#enhSearchGroup').addEventListener('change', event => { searchState.groupId = event.currentTarget.value; }, { signal: context.signal });
  host.querySelector('#enhSearchQuality').addEventListener('change', event => { searchState.minHeight = Number(event.currentTarget.value); }, { signal: context.signal });
  host.querySelector('#enhHideDownloaded').addEventListener('change', event => {
    searchState.hideDownloaded = event.currentTarget.checked;
    renderSearchResults();
  }, { signal: context.signal });
  const cancelStaleQueryWork = () => {
    const query = host.querySelector('#enhSearchQuery').value.trim();
    const order = host.querySelector('#enhSearchOrder').value || 'totalrank';
    if (query === searchState.q && order === searchState.order) return;
    abortSearchRequests();
    searchState.requestGeneration += 1;
  };
  host.querySelector('#enhSearchQuery').addEventListener('input', cancelStaleQueryWork, { signal: context.signal });
  host.querySelector('#enhSearchOrder').addEventListener('change', cancelStaleQueryWork, { signal: context.signal });
  host.querySelector('#enhSearchQuery').addEventListener('keydown', event => {
    if (event.key === 'Enter') {
      event.preventDefault();
      void startSearch(false);
    }
  }, { signal: context.signal });
  host.querySelector('#enhSearchTitleFilter').addEventListener('input', event => {
    searchState.filterText = event.currentTarget.value;
    searchState.filterTouched = true;
    renderSearchResults();
  }, { signal: context.signal });

  host.addEventListener('change', event => {
    const input = event.target.closest('[data-search-select]');
    if (!input) return;
    const item = (searchState.data?.items || []).find(value => value.bvid === input.dataset.searchSelect);
    if (!item) return;
    if (input.checked) searchState.selected.set(item.bvid, item);
    else searchState.selected.delete(item.bvid);
    host.querySelector('#enhSearchDownloadSelected').textContent = `下载选中（${searchState.selected.size}）`;
  }, { signal: context.signal });

  host.addEventListener('click', async event => {
    const button = event.target.closest('button');
    if (!button) return;
    if (button.id === 'enhSearchButton') await startSearch(false);
    else if (button.id === 'enhSearchRefresh') await startSearch(true);
    else if (button.dataset.searchFilterMode !== undefined) {
      searchState.filterMode = button.dataset.searchFilterMode;
      renderSearchResults();
    } else if (button.id === 'enhSearchSelectVisible') {
      for (const item of visibleSearchItems()) searchState.selected.set(item.bvid, item);
      renderSearchResults();
    } else if (button.id === 'enhSearchClear') {
      searchState.selected.clear();
      renderSearchResults();
    } else if (button.id === 'enhSearchDownloadSelected') await downloadSearchItems([...searchState.selected.values()]);
    else if (button.id === 'enhSearchAddTag') await batchTagSearchItems();
    else if (button.dataset.searchPage !== undefined) await loadSearchPage(Number(button.dataset.searchPage));
    else if (button.dataset.searchJumpButton !== undefined) {
      const pages = Math.max(1, Number(searchState.pages || 1));
      const page = Math.max(1, Math.min(pages, Number(results.querySelector('[data-search-jump]')?.value || 1)));
      await loadSearchPage(page);
    } else if (button.dataset.searchPreview !== undefined) {
      await previewSearchItem((searchState.data?.items || []).find(item => item.bvid === button.dataset.searchPreview));
    } else if (button.dataset.searchDownload !== undefined) {
      await downloadSearchItems([(searchState.data?.items || []).find(item => item.bvid === button.dataset.searchDownload)]);
    } else if (button.dataset.searchTagKey !== undefined) {
      const item = (searchState.data?.items || []).find(value => value.bvid === button.dataset.searchTagKey);
      if (!item) return;
      const values = new Set(item.tags || []);
      const tagName = button.dataset.searchTagName || '';
      if (values.has(tagName)) values.delete(tagName);
      else values.add(tagName);
      button.disabled = true;
      try {
        item.tags = await assignTags(item, [...values]);
        renderSearchResults();
      } catch (error) {
        context.toast.show(error.message, 'bad');
      } finally {
        button.disabled = false;
      }
    }
  }, { signal: context.signal });

  if (searchState.data) {
    renderSearchResults();
    scheduleNextPagePreload(searchState.requestGeneration);
  } else if (searchState.q) {
    await loadSearchPage(searchState.page);
  } else {
    results.innerHTML = '<div class="empty">输入关键词开始搜索</div>';
  }

  return Object.freeze({
    dispose: once(() => {
      abortSearchRequests();
      if (ownsModal) context.modal.close('route');
    }),
  });
}
