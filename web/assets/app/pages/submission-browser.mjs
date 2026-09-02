import { once } from '../core/lifecycle.mjs';
import { readLru, SEARCH_PAGE_LRU_LIMIT, splitTitleTerms, writeLru } from '../core/search-policy.mjs';
import {
  canSelectSubmission,
  selectableSubmissionItems,
  submissionPageKey,
  submissionScanDecision,
  visibleSubmissionItems,
} from '../core/submission-policy.mjs';
import {
  bindCoverFallback,
  coverUrl,
  esc,
  formatDate,
  groupOptions,
  qualityOptions,
} from './shared.mjs';
import {
  createCreatorImportPoller,
  creatorImportConfirmMessage,
  creatorImportListMarkup,
  runCreatorImportAction,
} from './creator-imports.mjs';

const FILTER_MODES = new Set(['raw', 'all', 'any']);
const browserStates = new Map();

function freshState({ destination, groupId, minHeight }) {
  return {
    locatorMode: 'locator',
    locator: '',
    nameQuery: '',
    namePage: 1,
    namePages: 0,
    nameData: null,
    creator: null,
    uid: '',
    order: 'pubdate',
    page: 1,
    pages: 0,
    total: 0,
    data: null,
    selected: new Map(),
    conflicts: new Map(),
    cache: new Map(),
    hideDownloaded: true,
    filterMode: 'raw',
    filterText: '',
    destination,
    groupId,
    minHeight,
    limits: { selection: 0, auto_scan_pages: 10, page_size: 20, active_tasks: 0 },
    scan: null,
    failedPage: null,
    generation: 0,
    controller: null,
  };
}

export function clearSubmissionSessionState() {
  for (const state of browserStates.values()) state.controller?.abort();
  browserStates.clear();
}

function stateFor(context, surface, defaults) {
  const session = context.session.get();
  const identity = String(session.user?.id || session.username || 'anonymous');
  const key = `${identity}:${surface}`;
  if (!browserStates.has(key)) browserStates.set(key, freshState(defaults));
  return browserStates.get(key);
}

function filterMode(state) {
  return state.filterMode === 'all' ? 'exact' : state.filterMode === 'any' ? 'fuzzy' : 'raw';
}

function filterHelp(state) {
  if (state.filterMode === 'raw') return '不联网，只显示当前投稿页的原始标题结果。';
  const terms = splitTitleTerms(state.filterText);
  const rule = state.filterMode === 'all' ? '标题包含全部词' : '标题包含任意词';
  return `${rule}${terms.length ? `：${terms.join('、')}` : '；未填写时不筛选'}`;
}

function currentVisible(state) {
  return visibleSubmissionItems(state.data?.items || [], {
    filterText: state.filterText,
    filterMode: filterMode(state),
    hideDownloaded: state.hideDownloaded,
  });
}

function currentCandidates(state) {
  return selectableSubmissionItems(state.data?.items || [], {
    filterText: state.filterText,
    filterMode: filterMode(state),
    hideDownloaded: state.hideDownloaded,
  });
}

function formatPlay(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) return '-';
  if (number >= 1e8) return `${(number / 1e8).toFixed(number >= 1e9 ? 0 : 1)}亿`;
  if (number >= 1e4) return `${(number / 1e4).toFixed(number >= 1e5 ? 0 : 1)}万`;
  return String(Math.round(number));
}

function statusClass(status) {
  if (status === 'downloaded') return 'good';
  if (['running', 'queued', 'ready'].includes(status)) return 'warn';
  if (['deleted', 'failed', 'cancelled', 'expired'].includes(status)) return 'bad';
  return 'neutral';
}

function paginationHtml(page, pages, prefix) {
  const total = Math.max(1, Number(pages || 1));
  const current = Math.max(1, Math.min(total, Number(page || 1)));
  return `<div class="enh-pagination"><button type="button" class="btn small" data-${prefix}-page="${current - 1}" ${current <= 1 ? 'disabled' : ''}>上一页</button><span class="badge neutral">第 ${current} / ${total} 页</span><button type="button" class="btn small" data-${prefix}-page="${current + 1}" ${current >= total ? 'disabled' : ''}>下一页</button><input class="input enh-page-jump" type="number" min="1" max="${total}" value="${current}" data-${prefix}-jump><button type="button" class="btn small" data-${prefix}-jump-button>跳转</button></div>`;
}

function creatorCard(item) {
  return `<article class="enh-creator-card"><img data-cover-img src="${esc(coverUrl(item.avatar))}" alt="${esc(item.name || item.uid)}" loading="lazy" referrerpolicy="no-referrer"><div><strong>${esc(item.name || `UID ${item.uid}`)}</strong><div class="media-meta"><span>UID ${esc(item.uid)}</span><span>${Number(item.followers || 0)} 粉丝</span><span>${Number(item.submission_count || 0)} 投稿</span></div><p>${esc(item.bio || '暂无公开简介')}</p><div class="media-actions"><a class="btn small" href="${esc(item.profile_url)}" target="_blank" rel="noopener noreferrer">主页</a><button type="button" class="btn primary small" data-creator-pick="${esc(item.uid)}">查看投稿</button></div></div></article>`;
}

function tagOptions(tags) {
  return '<option value="">选择标签</option>' + (tags || []).map(tag => (
    `<option value="${esc(tag.name)}">${esc(tag.name)}</option>`
  )).join('');
}

function tagChips(tags, item) {
  const selected = new Set((item.tags || []).map(value => String(value).toLocaleLowerCase()));
  return `<div class="enh-tag-row">${(tags || []).map(tag => {
    const active = selected.has(String(tag.name || '').toLocaleLowerCase());
    return `<button type="button" class="enh-tag-chip ${active ? 'active' : ''}" data-submission-tag-key="${esc(item.bvid)}" data-submission-tag-name="${esc(tag.name)}" aria-pressed="${active ? 'true' : 'false'}">${esc(tag.name)}</button>`;
  }).join('')}</div>`;
}

async function mapLimit(items, limit, callback) {
  const queue = [...items];
  const workers = Array.from({ length: Math.min(limit, queue.length) }, async () => {
    while (queue.length) await callback(queue.shift());
  });
  await Promise.all(workers);
}

function submissionCard(item, state, { normalUser, tags }) {
  const key = String(item.bvid || '');
  const selected = state.selected.has(key);
  const selectable = item.selectable !== false;
  const sourceUrl = item.url || `https://www.bilibili.com/video/${encodeURIComponent(key)}`;
  const conflict = state.conflicts.get(key);
  const disabledReason = item.block_reason || (selectable ? '' : '当前作品暂不可创建任务');
  return `<article class="media-card enh-search-card" data-submission-key="${esc(key)}"><div class="cover-wrap"><img data-cover-img src="${esc(coverUrl(item.cover))}" alt="${esc(item.title || key)}" loading="lazy" referrerpolicy="no-referrer"><label class="enh-card-select"><input type="checkbox" data-submission-select="${esc(key)}" ${selected ? 'checked' : ''} ${selectable ? '' : 'disabled'}> 选择</label><div class="cover-badges"><span></span><span class="badge ${statusClass(item.local_status)}">${esc(item.local_status_label || '未下载')}</span></div>${item.duration ? `<span class="duration-chip">${esc(item.duration)}</span>` : ''}</div><div class="media-body"><a class="media-title" href="${esc(sourceUrl)}" target="_blank" rel="noopener noreferrer">${esc(item.title || key)}</a><div class="media-meta"><span>${esc(item.author || '-')}</span><span>${formatPlay(item.play)} 播放</span><span>${formatDate(item.pubdate, true)}</span></div><div class="media-meta"><span>${esc(key)}</span>${item.local_group ? `<span>分组：${esc(item.local_group)}</span>` : ''}${item.local_quality ? `<span>${esc(item.local_quality)}</span>` : ''}</div>${disabledReason ? `<div class="notice warn compact">${esc(disabledReason)}</div>` : ''}${conflict ? `<div class="notice bad compact">${esc(conflict.message || '创建任务时发生冲突')}</div>` : ''}${normalUser ? '' : tagChips(tags, item)}<div class="media-actions"><a class="btn small" href="${esc(sourceUrl)}" target="_blank" rel="noopener noreferrer">B站原页面</a><button type="button" class="btn small" data-submission-preview="${esc(key)}">${normalUser ? '查看画质' : '预览画质'}</button><button type="button" class="btn primary small" data-submission-download="${esc(key)}" ${selectable ? '' : 'disabled'}>${['downloaded', 'deleted'].includes(item.local_status) ? '重新下载' : '下载'}</button></div></div></article>`;
}

function updateEverywhere(state, sourceKey, patch) {
  const apply = data => {
    for (const item of data?.items || []) {
      if (String(item.bvid || '') === String(sourceKey)) Object.assign(item, patch);
    }
  };
  apply(state.data);
  for (const data of state.cache.values()) apply(data);
  const selected = state.selected.get(sourceKey);
  if (selected) Object.assign(selected, patch);
}

export async function mountSubmissionBrowser(root, context, {
  surface = 'creator',
  allowNameSearch = false,
  normalUser = !context.session.isAdmin(),
  groups = [],
  tags = [],
  defaultGroupId = '',
  defaultDestination = normalUser ? 'device' : 'library',
  defaultMinHeight = 1080,
} = {}) {
  const state = stateFor(context, surface, {
    destination: defaultDestination,
    groupId: defaultGroupId,
    minHeight: defaultMinHeight,
  });
  if (!FILTER_MODES.has(state.filterMode)) state.filterMode = 'raw';
  if (normalUser) {
    state.destination = 'device';
    state.minHeight = defaultMinHeight;
  }
  if (!state.groupId) state.groupId = defaultGroupId;

  root.innerHTML = `<section class="card creator-discovery"><div class="card-head"><div><h2>按 UP 主选择投稿</h2><p>${allowNameSearch ? '可按名称选择候选，也可直接输入精确 UID 或主页。' : '请输入精确 UID，或粘贴 https://space.bilibili.com/&lt;UID&gt; 主页地址。普通用户不开放名称搜索。'}</p></div><span class="badge brand">每页 20 条</span></div>${allowNameSearch ? '<div class="segmented creator-locator-modes"><button type="button" data-creator-locator-mode="locator">UID / 主页</button><button type="button" data-creator-locator-mode="name">UP 主名称</button></div>' : ''}<div class="creator-locator-row"><div class="field"><label data-creator-input-label>${state.locatorMode === 'name' ? 'UP 主名称' : '精确 UID 或主页'}</label><input class="input" data-creator-input maxlength="2048" value="${esc(state.locatorMode === 'name' ? state.nameQuery : state.locator)}" placeholder="${state.locatorMode === 'name' ? '输入 UP 主名称' : '例如 123456 或 https://space.bilibili.com/123456'}"></div><div class="field"><label>投稿排序</label><select class="select" data-creator-order><option value="pubdate">最新发布</option><option value="click">播放最多</option></select></div><div class="field creator-locator-action"><label>读取</label><div class="toolbar"><button type="button" class="btn primary" data-creator-start>查找</button><button type="button" class="btn" data-creator-refresh>刷新当前页</button></div></div></div><div data-creator-candidates></div><div data-creator-profile></div><div class="creator-filter-grid"><div class="field"><label>标题筛选</label><div class="segmented"><button type="button" data-submission-filter="raw">不筛选</button><button type="button" data-submission-filter="all">包含全部词</button><button type="button" data-submission-filter="any">包含任意词</button></div></div><div class="field"><label>当前页标题筛选词</label><input class="input" data-submission-filter-text value="${esc(state.filterText)}" placeholder="只筛选当前页，不额外联网"><small data-submission-filter-help></small></div><div class="field"><label>本地状态</label><label class="enh-check"><input type="checkbox" data-submission-hide ${state.hideDownloaded ? 'checked' : ''}> 隐藏已下载和已删除</label><small>若本页没有可选作品，会按需继续读取下一页。</small></div></div>${normalUser ? `<div class="notice warn">下载目标固定为当前设备；自动选择最高可用画质，最低门槛由管理员全局设置为 ${Number(defaultMinHeight || 0)}P。</div>` : `<div class="enh-search-options-grid"><div class="field"><label>下载目标</label><select class="select" data-submission-destination><option value="library">保存到 NAS 媒体库</option><option value="device">导出到当前设备</option></select></div><div class="field" data-submission-group-field><label>保存分组</label><select class="select" data-submission-group>${groupOptions(groups, state.groupId)}</select></div><div class="field"><label>最低清晰度</label><select class="select" data-submission-quality>${qualityOptions(state.minHeight)}</select></div></div>${tags.length ? `<div class="toolbar"><select class="select enh-inline-select" data-submission-batch-tag>${tagOptions(tags)}</select><button type="button" class="btn" data-submission-add-tag>给选中作品添加标签</button></div>` : ''}`}<div class="toolbar creator-selection-toolbar"><span class="badge neutral" data-submission-summary>尚未读取投稿</span><button type="button" class="btn" data-submission-select-visible>选择本页可选项</button><button type="button" class="btn" data-submission-clear>清空选择</button><button type="button" class="btn primary" data-submission-download-selected>下载选中（${state.selected.size}）</button></div><div data-submission-results><div class="empty">先定位一个 UP 主</div></div></section>`;

  const candidatesRoot = root.querySelector('[data-creator-candidates]');
  const profileRoot = root.querySelector('[data-creator-profile]');
  const resultsRoot = root.querySelector('[data-submission-results]');
  const importRoot = normalUser ? null : document.createElement('section');
  if (importRoot) {
    importRoot.className = 'card creator-import-panel';
    importRoot.dataset.creatorImportPanel = '';
    profileRoot.after(importRoot);
  }
  let ownsModal = false;
  let importJobs = [];

  const renderImportPanel = () => {
    if (!importRoot) return;
    const available = Boolean(state.uid && state.destination === 'library');
    importRoot.classList.toggle('hidden', state.destination !== 'library');
    importRoot.innerHTML = `<div class="card-head"><div><h3>UP 主全量入库</h3><p>后台按发布时间遍历全部公开视频；作业完成只表示投稿已入队或被明确跳过。</p></div><button type="button" class="btn primary" data-creator-import-start ${available ? '' : 'disabled'}>全部加入媒体库</button></div><div data-creator-import-current>${creatorImportListMarkup(importJobs, { uid: state.uid })}</div>`;
  };

  const importPoller = importRoot
    ? createCreatorImportPoller(context, jobs => {
      importJobs = jobs;
      renderImportPanel();
    })
    : null;

  const assignTags = async (item, values) => {
    const response = await context.api('/api/enhancements/tags', {
      method: 'PUT',
      body: { source_key: item.bvid || '', media_id: '', tags: values },
      signal: context.signal,
    });
    const next = response.data?.tags || [];
    updateEverywhere(state, response.data?.source_key || item.bvid, { tags: [...next] });
    return next;
  };

  const abortCurrent = () => {
    state.controller?.abort();
    state.controller = null;
  };
  context.signal.addEventListener('abort', abortCurrent, { once: true });

  const syncStaticControls = () => {
    for (const button of root.querySelectorAll('[data-creator-locator-mode]')) {
      button.classList.toggle('active', button.dataset.creatorLocatorMode === state.locatorMode);
    }
    for (const button of root.querySelectorAll('[data-submission-filter]')) {
      button.classList.toggle('active', button.dataset.submissionFilter === state.filterMode);
    }
    root.querySelector('[data-submission-filter-help]').textContent = filterHelp(state);
    root.querySelector('[data-creator-order]').value = state.order;
    const destination = root.querySelector('[data-submission-destination]');
    if (destination) destination.value = state.destination;
    const group = root.querySelector('[data-submission-group]');
    if (group) group.value = state.groupId;
    const quality = root.querySelector('[data-submission-quality]');
    if (quality) quality.value = String(state.minHeight || 0);
    root.querySelector('[data-submission-group-field]')?.classList.toggle('hidden', state.destination === 'device');
    renderImportPanel();
  };

  const renderCandidates = () => {
    if (!allowNameSearch || state.locatorMode !== 'name') {
      candidatesRoot.innerHTML = '';
      return;
    }
    if (!state.nameData) {
      candidatesRoot.innerHTML = '<div class="empty">输入名称后选择准确的 UP 主候选</div>';
      return;
    }
    const items = state.nameData.items || [];
    const content = items.length
      ? `<div class="enh-creator-grid">${items.map(creatorCard).join('')}</div>`
      : '<div class="empty">没有找到同名候选，可改用精确 UID 或主页</div>';
    candidatesRoot.innerHTML = `<div class="notice">名称搜索只用于管理员选择候选；创建下载前仍会锁定候选的唯一 UID。</div>${content}${paginationHtml(state.namePage, state.namePages, 'creator-name')}`;
    bindCoverFallback(candidatesRoot, context.signal);
  };

  const renderProfile = () => {
    if (!state.creator) {
      profileRoot.innerHTML = '';
      return;
    }
    const creator = state.creator;
    profileRoot.innerHTML = `<section class="notice creator-profile"><img data-cover-img src="${esc(coverUrl(creator.avatar))}" alt="${esc(creator.name || creator.uid)}" referrerpolicy="no-referrer"><div><strong>${esc(creator.name || `UID ${creator.uid}`)}</strong><div class="media-meta"><span>UID ${esc(creator.uid)}</span><span>${Number(creator.followers || 0)} 粉丝</span><span>${Number(creator.submission_count || state.total || 0)} 投稿</span></div><p>${esc(creator.bio || '暂无公开简介')}</p><a href="${esc(creator.profile_url)}" target="_blank" rel="noopener noreferrer">打开 Bilibili 主页</a></div></section>`;
    bindCoverFallback(profileRoot, context.signal);
  };

  const renderResults = () => {
    syncStaticControls();
    renderProfile();
    if (!state.data) {
      root.querySelector('[data-submission-summary]').textContent = '尚未读取投稿';
      resultsRoot.innerHTML = '<div class="empty">先定位一个 UP 主</div>';
      return;
    }
    const raw = state.data.items || [];
    const visible = currentVisible(state);
    const selectable = currentCandidates(state);
    const hidden = raw.length - visible.length;
    const limit = Number(state.limits.selection || 0);
    root.querySelector('[data-submission-summary]').textContent = `第 ${state.page} / ${Math.max(1, state.pages)} 页 · 共 ${state.total} 条 · 本页可选 ${selectable.length} 条${hidden ? ` · 隐藏 ${hidden} 条` : ''} · 还能创建 ${limit} 个任务`;
    root.querySelector('[data-submission-download-selected]').textContent = `下载选中（${state.selected.size}）`;
    let content = '';
    if (visible.length) {
      content = `<div class="media-grid">${visible.map(item => submissionCard(item, state, { normalUser, tags })).join('')}</div>`;
    } else if (raw.length && state.hideDownloaded) {
      content = '<div class="empty">本页作品均已下载或已删除，已继续查找下一页；也可关闭隐藏查看。</div>';
    } else {
      content = '<div class="empty">这一页没有符合标题筛选的公开投稿</div>';
    }
    let scanNotice = '';
    if (state.scan?.scanned > 1 || ['limit', 'stopped'].includes(state.scan?.reason)) {
      const reason = state.scan.reason === 'candidate'
        ? '首个有可选作品的页面'
        : state.scan.reason === 'end'
          ? '投稿末页'
          : state.scan.reason === 'stopped'
            ? '用户停止的位置'
            : '单次 10 页上限';
      scanNotice = `<div class="notice">本次按需检查了第 ${state.scan.startPage}–${state.scan.endPage} 页，跳过 ${Number(state.scan.skippedItems || 0)} 个不可选结果，停在${reason}；没有合并不同页面。</div>`;
    }
    const mayContinue = currentCandidates(state).length === 0 && state.page < state.pages;
    const continueButton = mayContinue
      ? `<button type="button" class="btn primary" data-submission-continue data-next-page="${Number(state.scan?.nextPage || state.page + 1)}">${state.scan?.reason === 'limit' ? '继续查找下一批' : '查找后续匹配'}</button>`
      : '';
    resultsRoot.innerHTML = `${scanNotice}${content}<div class="toolbar creator-pagination-row">${paginationHtml(state.page, state.pages, 'submission')}${continueButton}</div>`;
    bindCoverFallback(resultsRoot, context.signal);
  };

  const applyData = data => {
    state.data = data || {};
    state.page = Number(data?.page || 1);
    state.pages = Number(data?.pages || 0);
    state.total = Number(data?.total || 0);
    state.limits = { ...state.limits, ...(data?.limits || {}) };
  };

  const fetchPage = async (page, { fresh = false, signal } = {}) => {
    const key = submissionPageKey({
      uid: state.uid,
      order: state.order,
      page,
      destination: state.destination,
    });
    if (!fresh) {
      const cached = readLru(state.cache, key);
      if (cached !== undefined) return cached;
    } else {
      state.cache.delete(key);
    }
    const params = new URLSearchParams({
      order: state.order,
      page: String(page),
      destination: state.destination,
    });
    if (fresh) params.set('fresh', 'true');
    const response = await context.api(`/api/bilibili/creators/${encodeURIComponent(state.uid)}/submissions?${params}`, { signal });
    const data = response.data || {};
    writeLru(state.cache, key, data, SEARCH_PAGE_LRU_LIMIT);
    return data;
  };

  const loadWithScan = async (startPage, { fresh = false, initialData = null } = {}) => {
    if (!state.uid) return;
    abortCurrent();
    const generation = state.generation + 1;
    state.generation = generation;
    const controller = new AbortController();
    state.controller = controller;
    const abort = () => controller.abort();
    context.signal.addEventListener('abort', abort, { once: true });
    resultsRoot.innerHTML = '<div class="loading-card">正在按需读取 UP 主投稿… <button type="button" class="btn small" data-submission-stop>停止</button></div>';
    const start = Math.max(1, Number(startPage || 1));
    let page = start;
    let scanned = 0;
    let skippedItems = 0;
    let data = initialData;
    try {
      while (true) {
        if (!data) data = await fetchPage(page, { fresh: fresh && scanned === 0, signal: controller.signal });
        if (generation !== state.generation || context.signal.aborted) return;
        applyData(data);
        scanned += 1;
        const candidateCount = currentCandidates(state).length;
        if (candidateCount === 0) skippedItems += (state.data?.items || []).length;
        state.scan = {
          startPage: start,
          endPage: state.page,
          scanned,
          reason: 'scanning',
          nextPage: state.page + 1,
          skippedItems,
        };
        const decision = submissionScanDecision({
          page: state.page,
          pages: state.pages,
          candidateCount,
          scanned,
          limit: Number(state.limits.auto_scan_pages || 10),
        });
        if (decision.action === 'next') {
          page = decision.nextPage;
          data = null;
          continue;
        }
        state.scan = {
          ...state.scan,
          reason: decision.action,
          nextPage: decision.nextPage || null,
        };
        state.failedPage = null;
        renderResults();
        return;
      }
    } catch (error) {
      if (error?.name === 'AbortError') return;
      if (generation === state.generation) {
        state.failedPage = page;
        resultsRoot.innerHTML = `<div class="notice bad">第 ${page} 页读取失败：${esc(error.message)} <button type="button" class="btn small" data-submission-retry-page="${page}">重试本页</button></div>`;
        context.toast.show(error.message, 'bad');
      }
    } finally {
      context.signal.removeEventListener('abort', abort);
      if (state.controller === controller) state.controller = null;
    }
  };

  const resolveCreator = async ({ fresh = false } = {}) => {
    const input = root.querySelector('[data-creator-input]').value.trim();
    if (!input) {
      context.toast.show('请输入精确 UID 或 UP 主主页', 'warn');
      return;
    }
    state.order = root.querySelector('[data-creator-order]').value === 'click' ? 'click' : 'pubdate';
    abortCurrent();
    const controller = new AbortController();
    state.controller = controller;
    const params = new URLSearchParams({
      locator: input,
      order: state.order,
      destination: state.destination,
    });
    if (fresh) params.set('fresh', 'true');
    profileRoot.innerHTML = '<div class="loading-card">正在确认 UP 主身份…</div>';
    resultsRoot.innerHTML = '<div class="loading-card">正在读取投稿…</div>';
    try {
      const response = await context.api(`/api/bilibili/creators/resolve?${params}`, { signal: controller.signal });
      const payload = response.data || {};
      const nextUid = String(payload.creator?.uid || '');
      if (state.uid && nextUid !== state.uid && state.selected.size) {
        const accepted = await context.confirm({
          title: '更换 UP 主',
          message: `更换 UP 主会清空已选的 ${state.selected.size} 个作品，是否继续？`,
          confirmLabel: '更换并清空',
        });
        if (!accepted) {
          renderProfile();
          renderResults();
          return;
        }
      }
      const creatorChanged = Boolean(state.uid && nextUid !== state.uid);
      state.locator = input;
      state.creator = payload.creator || null;
      state.uid = nextUid;
      if (creatorChanged) {
        state.selected.clear();
        state.conflicts.clear();
      }
      state.cache.clear();
      const submissions = payload.submissions || {};
      writeLru(
        state.cache,
        submissionPageKey({ uid: state.uid, order: state.order, page: 1, destination: state.destination }),
        submissions,
        SEARCH_PAGE_LRU_LIMIT,
      );
      renderProfile();
      await loadWithScan(1, { fresh: false, initialData: submissions });
    } catch (error) {
      if (error?.name === 'AbortError') return;
      profileRoot.innerHTML = '';
      resultsRoot.innerHTML = `<div class="notice bad">${esc(error.message)}</div>`;
      context.toast.show(error.message, 'bad');
    } finally {
      if (state.controller === controller) state.controller = null;
    }
  };

  const searchNames = async (page = 1, { fresh = false } = {}) => {
    const query = root.querySelector('[data-creator-input]').value.trim();
    if (!query) {
      context.toast.show('请输入 UP 主名称', 'warn');
      return;
    }
    state.nameQuery = query;
    abortCurrent();
    const controller = new AbortController();
    state.controller = controller;
    candidatesRoot.innerHTML = '<div class="loading-card">正在读取名称候选…</div>';
    try {
      const params = new URLSearchParams({ q: query, page: String(page) });
      if (fresh) params.set('fresh', 'true');
      const response = await context.api(`/api/bilibili/creators/search?${params}`, { signal: controller.signal });
      state.nameData = response.data || {};
      state.namePage = Number(state.nameData.page || page);
      state.namePages = Number(state.nameData.pages || 0);
      renderCandidates();
    } catch (error) {
      if (error?.name === 'AbortError') return;
      candidatesRoot.innerHTML = `<div class="notice bad">${esc(error.message)}</div>`;
      context.toast.show(error.message, 'bad');
    } finally {
      if (state.controller === controller) state.controller = null;
    }
  };

  const previewItem = async item => {
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
            play: item.play, preferred_quality: normalUser ? '' : (item.preferred_quality || ''),
          },
          min_height: Number(state.minHeight || 0),
          preferred_quality: normalUser ? '' : (item.preferred_quality || ''),
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
      modal.body.innerHTML = `<div class="notice"><strong>${esc(response.data?.metadata?.title || item.title)}</strong><br>${esc(item.bvid)} · 最高可用：${esc(quality.highest_label || '-')} · ${esc(quality.summary || '')}</div>${normalUser ? '<div class="notice warn" style="margin-top:14px">普通用户下载时固定自动选择最高可用档位，此处只读展示。</div>' : `<div class="field" style="margin-top:14px"><label>该作品目标档位</label><select class="select" data-preview-quality><option value="">自动最高</option>${choices.map(label => `<option value="${esc(label)}" ${item.preferred_quality === label ? 'selected' : ''}>${esc(label)}</option>`).join('')}</select></div>`}<div class="file-list" style="margin-top:14px">${parts.map((part, index) => `<section class="notice"><strong>分 P ${index + 1}</strong><div class="metric-foot">${(part.available || []).map(track => `${esc(track.dfn || track.resolution || '-')} · ${esc(track.codec || '-')}`).join('　')}</div></section>`).join('')}</div>`;
      modal.body.querySelector('[data-preview-quality]')?.addEventListener('change', event => {
        item.preferred_quality = event.currentTarget.value;
        if (state.selected.has(item.bvid)) state.selected.set(item.bvid, item);
      });
    } catch (error) {
      modal.body.innerHTML = `<div class="notice bad">${esc(error.message)}</div>`;
    }
  };

  const downloadItems = async items => {
    const valid = items.filter(item => item && item.selectable !== false);
    if (!valid.length) {
      context.toast.show('请先选择可下载的投稿', 'warn');
      return;
    }
    const limit = Number(state.limits.selection || 0);
    if (valid.length > limit) {
      context.toast.show(`当前最多还能创建 ${limit} 个任务`, 'warn');
      return;
    }
    const repeated = valid.filter(item => ['downloaded', 'deleted'].includes(item.local_status));
    if (repeated.length) {
      const accepted = await context.confirm({
        title: '确认重新下载',
        message: `选中的作品中有 ${repeated.length} 个已经下载或曾被删除，是否重新下载？`,
        confirmLabel: '重新下载',
      });
      if (!accepted) return;
    }
    try {
      const response = await context.api('/api/download/selection', {
        method: 'POST',
        body: {
          urls: [],
          bvids: [],
          items: valid.map(item => ({
            bvid: item.bvid,
            url: item.url,
            title: item.title,
            cover: item.cover,
            author: item.author,
            pubdate: item.pubdate,
            duration: item.duration,
            play: item.play,
            preferred_quality: normalUser ? '' : (item.preferred_quality || ''),
          })),
          force: !normalUser && repeated.length > 0,
          group_id: !normalUser && state.destination === 'library' ? state.groupId : '',
          group: '',
          destination: normalUser ? 'device' : state.destination,
          min_height: normalUser ? defaultMinHeight : Number(state.minHeight || 0),
        },
        signal: context.signal,
      });
      for (const item of valid) {
        updateEverywhere(state, item.bvid, {
          local_status: 'queued',
          local_status_label: '排队中',
          selectable: false,
          block_reason: '同一作品已有活动任务',
        });
      }
      state.selected.clear();
      state.conflicts.clear();
      if (normalUser) {
        state.limits.selection = Math.max(0, limit - Number(response.total || valid.length));
      }
      context.toast.show(`已原子创建 ${response.total || valid.length} 个任务`, 'good');
      renderResults();
    } catch (error) {
      state.conflicts.clear();
      for (const conflict of error?.payload?.data?.items || []) {
        const key = String(conflict.source_key || conflict.bvid || '');
        if (key) state.conflicts.set(key, conflict);
      }
      renderResults();
      context.toast.show(error.message, 'bad');
    }
  };

  const rememberImportJob = job => {
    if (!job?.id) return;
    const remaining = importJobs.filter(item => String(item.id) !== String(job.id));
    importJobs = [job, ...remaining];
    renderImportPanel();
  };

  const startCreatorImport = async button => {
    if (!importRoot || !state.uid || state.destination !== 'library') return;
    const group = groups.find(item => String(item.id) === String(state.groupId));
    const accepted = await context.confirm({
      title: '开始 UP 主全量入库',
      message: creatorImportConfirmMessage({
        creator: state.creator || { uid: state.uid },
        total: state.total,
        groupName: group?.display_name || '默认分组',
        minHeight: state.minHeight,
      }),
      confirmLabel: '开始后台遍历',
    });
    if (!accepted) return;
    button.disabled = true;
    try {
      const response = await context.api('/api/bilibili/creator-imports', {
        method: 'POST',
        body: {
          uid: state.uid,
          group_id: state.groupId || '',
          min_height: Number(state.minHeight || 0),
        },
        signal: context.signal,
      });
      const job = response.data?.job;
      rememberImportJob(job);
      context.toast.show(
        response.data?.created ? '全量入库作业已开始' : '这个 UP 主已有活动作业，已显示现有进度',
        response.data?.created ? 'good' : 'warn',
      );
      await importPoller?.refresh({ quiet: true });
    } catch (error) {
      if (error?.name !== 'AbortError') context.toast.show(error.message, 'bad');
    } finally {
      if (button.isConnected) button.disabled = false;
    }
  };

  const handleCreatorImportAction = async button => {
    const action = button.dataset.creatorImportAction || '';
    const jobId = button.dataset.creatorImportId || '';
    if (!action || !jobId) return;
    if (action === 'cancel') {
      const accepted = await context.confirm({
        title: '取消全量入库作业',
        message: '只停止后续投稿发现和入队；已经创建的下载任务会继续执行。确认取消？',
        confirmLabel: '取消后续入队',
        danger: true,
      });
      if (!accepted) return;
    }
    button.disabled = true;
    try {
      const response = await runCreatorImportAction(context, jobId, action);
      rememberImportJob(response.data);
      context.toast.show(action === 'cancel' ? '已请求停止后续入队' : '作业已重新进入等待队列', 'good');
      await importPoller?.refresh({ quiet: true });
    } catch (error) {
      if (error?.name !== 'AbortError') context.toast.show(error.message, 'bad');
    } finally {
      if (button.isConnected) button.disabled = false;
    }
  };

  root.addEventListener('change', event => {
    const select = event.target.closest('[data-submission-select]');
    if (select) {
      const key = select.dataset.submissionSelect;
      const item = (state.data?.items || []).find(value => value.bvid === key);
      if (!item || item.selectable === false) {
        select.checked = false;
        return;
      }
      if (select.checked) {
        if (!canSelectSubmission({
          selectedCount: state.selected.size,
          limit: state.limits.selection,
          alreadySelected: state.selected.has(key),
        })) {
          select.checked = false;
          context.toast.show(`当前最多选择 ${state.limits.selection} 个作品`, 'warn');
          return;
        }
        state.selected.set(key, item);
      } else {
        state.selected.delete(key);
      }
      root.querySelector('[data-submission-download-selected]').textContent = `下载选中（${state.selected.size}）`;
      return;
    }
    if (event.target.matches('[data-creator-order]')) {
      state.order = event.target.value === 'click' ? 'click' : 'pubdate';
      if (state.uid) void loadWithScan(1);
    } else if (event.target.matches('[data-submission-hide]')) {
      state.hideDownloaded = event.target.checked;
      renderResults();
    } else if (event.target.matches('[data-submission-destination]')) {
      state.destination = event.target.value === 'device' ? 'device' : 'library';
      syncStaticControls();
      if (state.uid) void loadWithScan(state.page || 1);
    } else if (event.target.matches('[data-submission-group]')) {
      state.groupId = event.target.value;
    } else if (event.target.matches('[data-submission-quality]')) {
      state.minHeight = Number(event.target.value || 0);
    }
  }, { signal: context.signal });

  root.querySelector('[data-submission-filter-text]').addEventListener('input', event => {
    state.filterText = event.currentTarget.value;
    renderResults();
  }, { signal: context.signal });
  root.querySelector('[data-submission-filter-text]').addEventListener('keydown', event => {
    if (event.key !== 'Enter' || currentCandidates(state).length > 0 || state.page >= state.pages) return;
    event.preventDefault();
    void loadWithScan(state.page + 1);
  }, { signal: context.signal });

  root.querySelector('[data-creator-input]').addEventListener('keydown', event => {
    if (event.key !== 'Enter') return;
    event.preventDefault();
    if (state.locatorMode === 'name') void searchNames(1);
    else void resolveCreator();
  }, { signal: context.signal });

  root.addEventListener('click', async event => {
    const button = event.target.closest('button');
    if (!button) return;
    if (button.dataset.creatorLocatorMode !== undefined) {
      if (!allowNameSearch) return;
      state.locatorMode = button.dataset.creatorLocatorMode === 'name' ? 'name' : 'locator';
      const input = root.querySelector('[data-creator-input]');
      input.value = state.locatorMode === 'name' ? state.nameQuery : state.locator;
      input.placeholder = state.locatorMode === 'name' ? '输入 UP 主名称' : '例如 123456 或 https://space.bilibili.com/123456';
      root.querySelector('[data-creator-input-label]').textContent = state.locatorMode === 'name' ? 'UP 主名称' : '精确 UID 或主页';
      syncStaticControls();
      renderCandidates();
    } else if (button.dataset.creatorImportStart !== undefined) {
      await startCreatorImport(button);
    } else if (button.dataset.creatorImportAction !== undefined) {
      await handleCreatorImportAction(button);
    } else if (button.dataset.creatorStart !== undefined) {
      if (state.locatorMode === 'name') await searchNames(1);
      else await resolveCreator();
    } else if (button.dataset.creatorRefresh !== undefined) {
      if (state.locatorMode === 'name') await searchNames(state.namePage, { fresh: true });
      else if (state.uid) await loadWithScan(state.page, { fresh: true });
      else await resolveCreator({ fresh: true });
    } else if (button.dataset.creatorPick !== undefined) {
      state.locatorMode = 'locator';
      root.querySelector('[data-creator-input]').value = button.dataset.creatorPick;
      root.querySelector('[data-creator-input-label]').textContent = '精确 UID 或主页';
      syncStaticControls();
      renderCandidates();
      await resolveCreator();
    } else if (button.dataset.creatorNamePage !== undefined) {
      await searchNames(Number(button.dataset.creatorNamePage));
    } else if (button.dataset.creatorNameJumpButton !== undefined) {
      const page = Math.max(1, Math.min(Math.max(1, state.namePages), Number(candidatesRoot.querySelector('[data-creator-name-jump]')?.value || 1)));
      await searchNames(page);
    } else if (button.dataset.submissionTagKey !== undefined) {
      const item = (state.data?.items || []).find(value => value.bvid === button.dataset.submissionTagKey);
      if (!item || normalUser) return;
      const values = new Set(item.tags || []);
      const name = button.dataset.submissionTagName || '';
      if (values.has(name)) values.delete(name);
      else values.add(name);
      button.disabled = true;
      try {
        await assignTags(item, [...values]);
        renderResults();
      } catch (error) {
        context.toast.show(error.message, 'bad');
      } finally {
        button.disabled = false;
      }
    } else if (button.dataset.submissionAddTag !== undefined) {
      if (normalUser) return;
      const name = root.querySelector('[data-submission-batch-tag]')?.value || '';
      const items = [...state.selected.values()];
      if (!name || !items.length) {
        context.toast.show('请选择标签和作品', 'warn');
        return;
      }
      button.disabled = true;
      try {
        await mapLimit(items, 6, async item => {
          const values = new Set(item.tags || []);
          values.add(name);
          await assignTags(item, [...values]);
        });
        context.toast.show(`已给 ${items.length} 个作品添加“${name}”标签`, 'good');
        renderResults();
      } catch (error) {
        context.toast.show(error.message, 'bad');
      } finally {
        button.disabled = false;
      }
    } else if (button.dataset.submissionFilter !== undefined) {
      state.filterMode = FILTER_MODES.has(button.dataset.submissionFilter) ? button.dataset.submissionFilter : 'raw';
      renderResults();
    } else if (button.dataset.submissionSelectVisible !== undefined) {
      let capped = false;
      for (const item of currentCandidates(state)) {
        if (!canSelectSubmission({
          selectedCount: state.selected.size,
          limit: state.limits.selection,
          alreadySelected: state.selected.has(item.bvid),
        })) {
          capped = true;
          break;
        }
        state.selected.set(item.bvid, item);
      }
      if (capped) context.toast.show(`已达到当前选择上限 ${state.limits.selection}`, 'warn');
      renderResults();
    } else if (button.dataset.submissionClear !== undefined) {
      state.selected.clear();
      state.conflicts.clear();
      renderResults();
    } else if (button.dataset.submissionDownloadSelected !== undefined) {
      await downloadItems([...state.selected.values()]);
    } else if (button.dataset.submissionPage !== undefined) {
      await loadWithScan(Number(button.dataset.submissionPage));
    } else if (button.dataset.submissionJumpButton !== undefined) {
      const page = Math.max(1, Math.min(Math.max(1, state.pages), Number(resultsRoot.querySelector('[data-submission-jump]')?.value || 1)));
      await loadWithScan(page);
    } else if (button.dataset.submissionContinue !== undefined) {
      await loadWithScan(Number(button.dataset.nextPage || state.page + 1));
    } else if (button.dataset.submissionStop !== undefined) {
      abortCurrent();
      state.generation += 1;
      if (state.data) {
        state.scan = {
          startPage: state.scan?.startPage || state.page,
          endPage: state.page,
          scanned: state.scan?.scanned || 1,
          reason: 'stopped',
          nextPage: state.page + 1,
          skippedItems: state.scan?.skippedItems || 0,
        };
      }
      renderResults();
    } else if (button.dataset.submissionRetryPage !== undefined) {
      await loadWithScan(Number(button.dataset.submissionRetryPage), { fresh: true });
    } else if (button.dataset.submissionPreview !== undefined) {
      await previewItem((state.data?.items || []).find(item => item.bvid === button.dataset.submissionPreview));
    } else if (button.dataset.submissionDownload !== undefined) {
      await downloadItems([(state.data?.items || []).find(item => item.bvid === button.dataset.submissionDownload)]);
    }
  }, { signal: context.signal });

  syncStaticControls();
  renderCandidates();
  renderResults();
  void importPoller?.refresh();

  return Object.freeze({
    selectionCount: () => state.selected.size,
    clearSelection: () => {
      state.selected.clear();
      state.conflicts.clear();
      renderResults();
    },
    dispose: once(() => {
      abortCurrent();
      importPoller?.stop();
      if (ownsModal) context.modal.close('route');
    }),
  });
}
