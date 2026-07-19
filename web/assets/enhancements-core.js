(() => {
  'use strict';

  const VERSION = '2026.07.19.1';
  const ENHANCED_PAGES = new Set(['search', 'library', 'tasks']);
  const AUTO_RENDER_PAGES = new Set(['library', 'tasks']);
  const QUALITY_OPTIONS = [
    [0, '不限制'], [360, '至少 360P'], [480, '至少 480P'], [720, '至少 720P'],
    [1080, '至少 1080P'], [1440, '至少 2K / 1440P'], [2160, '至少 4K'], [4320, '至少 8K'],
  ];
  const COMMON_QUALITY_LABELS = [
    '8K 超高清', '杜比视界', 'HDR 真彩', '4K 超清', '1080P 高码率',
    '1080P 高清', '720P 高清', '480P 清晰', '360P 流畅',
  ];

  const $ = (selector, root = document) => root.querySelector(selector);
  const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
  const esc = value => String(value ?? '').replace(/[&<>\'\"]/g, char => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;',
  }[char]));
  const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));

  const state = {
    csrf: '',
    contextLoadedAt: 0,
    status: null,
    groups: [],
    tags: [],
    rendering: false,
    renderQueued: false,
    search: {
      q: '', order: 'totalrank', page: 1, pages: 0, total: 0,
      data: null, cache: new Map(), selected: new Map(), hideDownloaded: true,
      filterMode: 'raw', filterText: '', filterTouched: false,
      destination: 'library', groupId: '', minHeight: 1080,
      requestGeneration: 0, currentController: null, preloadController: null,
      preloadHandle: 0, preloadHandleType: '',
    },
    library: {
      page: 1, data: null, selected: new Set(),
      q: '', groupId: '', sort: 'newest', codec: '', minHeight: 0, watched: '', tag: '',
    },
    tasks: {
      data: [], summary: {}, selected: new Set(), eventSource: null,
      status: '', destination: '', q: '',
    },
  };

  function currentPage() {
    return (location.hash.replace(/^#\//, '').split('?')[0] || 'dashboard').toLowerCase();
  }

  function formatBytes(value) {
    const number = Number(value);
    if (!Number.isFinite(number) || number < 0) return '-';
    if (number === 0) return '0 B';
    const units = ['B', 'KB', 'MB', 'GB', 'TB', 'PB'];
    const index = Math.min(units.length - 1, Math.floor(Math.log(number) / Math.log(1024)));
    const scaled = number / Math.pow(1024, index);
    const digits = index === 0 || scaled >= 100 ? 0 : scaled >= 10 ? 1 : 2;
    return `${scaled.toFixed(digits)} ${units[index]}`;
  }

  function formatDate(value, onlyDate = false) {
    if (!value) return '-';
    const number = Number(value);
    const date = new Date(number * (number < 1e12 ? 1000 : 1));
    if (Number.isNaN(date.getTime())) return '-';
    return onlyDate ? date.toLocaleDateString() : date.toLocaleString();
  }

  function formatPlay(value) {
    const number = Number(value);
    if (!Number.isFinite(number)) return '-';
    if (number >= 1e8) return `${(number / 1e8).toFixed(number >= 1e9 ? 0 : 1)}亿`;
    if (number >= 1e4) return `${(number / 1e4).toFixed(number >= 1e5 ? 0 : 1)}万`;
    return String(Math.round(number));
  }

  function safeColor(value) {
    return /^#[0-9a-fA-F]{3,8}$/.test(String(value || '')) ? String(value) : '#64748b';
  }

  function qualityOptions(selected = 1080) {
    return QUALITY_OPTIONS.map(([value, label]) => (
      `<option value="${value}" ${Number(selected) === value ? 'selected' : ''}>${esc(label)}</option>`
    )).join('');
  }

  function groupOptions(selected = '', includeAll = false) {
    const prefix = includeAll ? '<option value="">全部分组</option>' : '';
    return prefix + state.groups.map(group => (
      `<option value="${esc(group.id)}" ${String(group.id) === String(selected) ? 'selected' : ''}>${esc(group.display_name)}</option>`
    )).join('');
  }

  function tagOptions(selected = '', includeAll = false) {
    const prefix = includeAll ? '<option value="">全部标签</option>' : '<option value="">选择标签</option>';
    return prefix + state.tags.map(tag => (
      `<option value="${esc(tag.name)}" ${String(tag.name) === String(selected) ? 'selected' : ''}>${esc(tag.name)}</option>`
    )).join('');
  }

  function toast(message, type = '') {
    const root = $('#toastRoot');
    if (!root) return;
    const node = document.createElement('div');
    node.className = `toast ${type}`;
    node.textContent = String(message || '');
    root.appendChild(node);
    setTimeout(() => node.remove(), 4200);
  }

  function showModal(title, body, { narrow = false, onClose = null } = {}) {
    const root = $('#modalRoot');
    if (!root) return { root: document.createElement('div'), close: () => {} };
    root.classList.remove('hidden');
    root.innerHTML = `<section class="modal ${narrow ? 'narrow' : ''}"><header class="modal-head"><h2>${esc(title)}</h2><button type="button" class="close-button" aria-label="关闭">×</button></header><div class="modal-body">${body}</div></section>`;
    let closed = false;
    const close = () => {
      if (closed) return;
      closed = true;
      root.classList.add('hidden');
      root.innerHTML = '';
      if (onClose) onClose();
    };
    $('.close-button', root).onclick = close;
    root.onclick = event => { if (event.target === root) close(); };
    return { root, close };
  }

  async function api(path, { method = 'GET', body, raw = false, signal } = {}) {
    const headers = { Accept: 'application/json' };
    if (body !== undefined) headers['Content-Type'] = 'application/json';
    if (!['GET', 'HEAD'].includes(method) && state.csrf) headers['X-CSRF-Token'] = state.csrf;
    let response;
    try {
      response = await fetch(path, {
        method,
        headers,
        body: body === undefined ? undefined : JSON.stringify(body),
        cache: 'no-store',
        credentials: 'same-origin',
        signal,
      });
    } catch (error) {
      if (error?.name === 'AbortError') throw error;
      throw new Error(`无法连接服务：${error.message || '网络错误'}`);
    }
    if (raw) return response;
    let payload;
    try {
      payload = await response.json();
    } catch (_) {
      throw new Error(`服务返回无效响应（HTTP ${response.status}）`);
    }
    if (!response.ok || !payload.ok) {
      const detail = Array.isArray(payload.detail) ? payload.detail.map(item => item.msg).join('；') : '';
      throw new Error(payload.error || detail || `请求失败（HTTP ${response.status}）`);
    }
    return payload;
  }

  async function ensureContext(force = false) {
    const now = Date.now();
    if (!force && state.status && now - state.contextLoadedAt < 60_000) return;
    const auth = await api('/api/auth/status');
    state.csrf = auth.data?.csrf_token || '';
    const [statusResponse, groupsResponse, tagsResponse] = await Promise.all([
      api('/api/status'), api('/api/groups'), api('/api/enhancements/tags'),
    ]);
    state.status = statusResponse.data || {};
    state.groups = groupsResponse.data?.records || [];
    state.tags = tagsResponse.data?.items || [];
    state.contextLoadedAt = now;

    if (!state.search.groupId || !state.groups.some(group => group.id === state.search.groupId)) {
      const preferred = state.groups.find(group => group.display_name === state.status.default_group) || state.groups[0];
      state.search.groupId = preferred?.id || '';
    }
    if (!Number.isFinite(Number(state.search.minHeight))) {
      state.search.minHeight = Number(state.status.default_min_height || 1080);
    }
  }

  function pageNumbers(page, pages) {
    const total = Math.max(0, Number(pages || 0));
    if (total <= 1) return [1];
    const wanted = new Set([1, total, page - 2, page - 1, page, page + 1, page + 2]);
    const values = [...wanted].filter(value => value >= 1 && value <= total).sort((a, b) => a - b);
    const result = [];
    let previous = 0;
    for (const value of values) {
      if (previous && value - previous > 1) result.push('…');
      result.push(value);
      previous = value;
    }
    return result;
  }

  function paginationHtml(page, pages, prefix) {
    const total = Math.max(1, Number(pages || 1));
    const controls = pageNumbers(page, total).map(value => {
      if (value === '…') return '<span class="enh-page-gap">…</span>';
      return `<button type="button" class="btn small ${Number(value) === Number(page) ? 'primary active' : ''}" data-${prefix}-page="${value}">${value}</button>`;
    }).join('');
    return `<div class="enh-pagination"><button type="button" class="btn small" data-${prefix}-page="${Math.max(1, page - 1)}" ${page <= 1 ? 'disabled' : ''}>上一页</button>${controls}<button type="button" class="btn small" data-${prefix}-page="${Math.min(total, page + 1)}" ${page >= total ? 'disabled' : ''}>下一页</button><input class="input enh-page-jump" type="number" min="1" max="${total}" value="${page}" data-${prefix}-jump><button type="button" class="btn small" data-${prefix}-jump-button>跳转</button></div>`;
  }

  function tagChips(sourceKey, tags = []) {
    const selected = new Set((tags || []).map(value => String(value).toLowerCase()));
    return `<div class="enh-tag-row" data-tag-row="${esc(sourceKey)}">${state.tags.map(tag => {
      const active = selected.has(String(tag.name).toLowerCase());
      return `<button type="button" class="enh-tag-chip ${active ? 'active' : ''}" style="--tag-color:${safeColor(tag.color)}" data-tag-key="${esc(sourceKey)}" data-tag-name="${esc(tag.name)}" aria-pressed="${active ? 'true' : 'false'}">${esc(tag.name)}</button>`;
    }).join('')}</div>`;
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

  function updateTagsEverywhere(sourceKey, tags) {
    for (const data of state.search.cache.values()) {
      for (const item of data.items || []) {
        if (String(item.bvid || '') === String(sourceKey)) item.tags = [...tags];
      }
    }
    const selectedSearch = state.search.selected.get(sourceKey);
    if (selectedSearch) selectedSearch.tags = [...tags];
    for (const item of state.library.data?.items || []) {
      if (String(item.source_key || '') === String(sourceKey)) item.tags = [...tags];
    }
  }

  async function assignTags(sourceKey, tags, mediaId = '') {
    const result = await api('/api/enhancements/tags', {
      method: 'PUT',
      body: { source_key: sourceKey || '', media_id: mediaId || '', tags },
    });
    updateTagsEverywhere(result.data.source_key, result.data.tags || []);
    return result.data.tags || [];
  }

  async function bindTagButtons(root, resolveItem, rerender) {
    $$('[data-tag-key]', root).forEach(button => {
      button.onclick = async () => {
        const sourceKey = button.dataset.tagKey || '';
        const tagName = button.dataset.tagName || '';
        const item = resolveItem(sourceKey);
        if (!item) return;
        const current = new Set((item.tags || []).map(value => String(value)));
        if (current.has(tagName)) current.delete(tagName); else current.add(tagName);
        button.disabled = true;
        try {
          item.tags = await assignTags(sourceKey, [...current], item.id || '');
          rerender();
        } catch (error) {
          toast(error.message, 'bad');
        } finally {
          button.disabled = false;
        }
      };
    });
  }

  const renderers = Object.create(null);

  async function renderPage(page, root = $('#pageRoot')) {
    if (!ENHANCED_PAGES.has(page) || !root) throw new Error(`增强页面不可用：${page}`);
    await ensureContext();
    const renderer = renderers[page];
    if (!renderer) throw new Error(`增强页面尚未注册：${page}`);
    await renderer(root);
    root.dataset.enhancedVersion = VERSION;
  }

  function register(page, renderer) {
    if (!ENHANCED_PAGES.has(page) || typeof renderer !== 'function') return;
    renderers[page] = renderer;
    if (AUTO_RENDER_PAGES.has(page)) scheduleRender(20);
  }

  window.BiliEnhancements = {
    VERSION, COMMON_QUALITY_LABELS, state, $, $$, esc, sleep, currentPage,
    formatBytes, formatDate, formatPlay, safeColor, qualityOptions, groupOptions,
    tagOptions, toast, showModal, api, ensureContext, paginationHtml, tagChips,
    mapLimit, updateTagsEverywhere, assignTags, bindTagButtons, register, renderPage, scheduleRender,
  };

  let renderTimer = 0;
  function scheduleRender(delay = 80) {
    clearTimeout(renderTimer);
    renderTimer = setTimeout(() => renderCurrentPage(), delay);
  }

  async function renderCurrentPage() {
    const page = currentPage();
    if (!AUTO_RENDER_PAGES.has(page)) return;
    const appRoot = $('#appRoot');
    const root = $('#pageRoot');
    if (!root || !appRoot || appRoot.classList.contains('hidden')) {
      scheduleRender(250);
      return;
    }
    if (state.rendering) {
      state.renderQueued = true;
      return;
    }
    if ($(`[data-enhanced-view="${page}"]`, root)) return;
    state.rendering = true;
    try {
      if (currentPage() !== page) return;
      if (!renderers[page]) {
        scheduleRender(120);
        return;
      }
      await renderPage(page, root);
    } catch (error) {
      if (currentPage() === page) {
        root.innerHTML = `<div data-enhanced-view="${page}" class="notice bad">增强页面载入失败：${esc(error.message)}<br><button type="button" class="btn small" id="enhRetryPage" style="margin-top:10px">重试</button></div>`;
        $('#enhRetryPage', root).onclick = () => { root.innerHTML = ''; state.contextLoadedAt = 0; scheduleRender(10); };
      }
    } finally {
      state.rendering = false;
      if (state.renderQueued) {
        state.renderQueued = false;
        scheduleRender(20);
      }
    }
  }

  window.addEventListener('hashchange', () => scheduleRender(120));
  document.addEventListener('DOMContentLoaded', () => {
    const pageRoot = $('#pageRoot');
    const appRoot = $('#appRoot');
    if (pageRoot) {
      new MutationObserver(() => {
        const page = currentPage();
        if (AUTO_RENDER_PAGES.has(page) && !$(`[data-enhanced-view="${page}"]`, pageRoot)) scheduleRender(60);
      }).observe(pageRoot, { childList: true, subtree: false });
    }
    if (appRoot) {
      new MutationObserver(() => scheduleRender(80)).observe(appRoot, { attributes: true, attributeFilter: ['class'] });
    }
    scheduleRender(180);
  });
})();
