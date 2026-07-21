import { once } from '../core/lifecycle.mjs';
import {
  bindCoverFallback,
  bindDialogCancel,
  coverUrl,
  esc,
  formatBytes,
  groupOptions,
  modalActions,
  qualityOptions,
} from './shared.mjs';

const UNTAGGED = '__untagged__';
const SORT_ALIASES = Object.freeze({
  newest: ['newest', 'desc'],
  oldest: ['newest', 'asc'],
  recent: ['recent', 'desc'],
  title: ['title', 'asc'],
  size: ['size', 'desc'],
});
const SORT_FIELDS = new Set(['newest', 'recent', 'title', 'duration', 'size', 'group', 'tag']);
const OLD_COLORS = Object.freeze({
  '夯': '#dc2626',
  '顶级': '#7c3aed',
  '人上人': '#2563eb',
  'NPC': '#64748b',
  '不要': '#111827',
});
const DEFAULT_COLORS = Object.freeze({
  '夯': '#d4a017',
  '顶级': '#7c3aed',
  '人上人': '#2563eb',
  'NPC': '#0f766e',
  '不要': '#dc2626',
});
const libraryState = {
  page: 1,
  data: null,
  selected: new Set(),
  q: '',
  groupId: '',
  sort: 'newest',
  codec: '',
  minHeight: 0,
  watched: '',
  tag: '',
};

export function splitLibrarySort(value) {
  const text = String(value || 'newest');
  if (SORT_ALIASES[text]) return [...SORT_ALIASES[text]];
  const match = text.match(/^(newest|recent|title|duration|size|group|tag)_(asc|desc)$/);
  return match ? [match[1], match[2]] : ['newest', 'desc'];
}

export function librarySortValue(field, direction) {
  const safeField = SORT_FIELDS.has(field) ? field : 'newest';
  return `${safeField}_${direction === 'asc' ? 'asc' : 'desc'}`;
}

function safeColor(value) {
  return /^#[0-9a-fA-F]{3,8}$/.test(String(value || '')) ? String(value) : '#64748b';
}

export function libraryTagColor(tag) {
  const name = String(tag?.name || tag || '');
  const configured = String(tag?.color || '').toLowerCase();
  const old = String(OLD_COLORS[name] || '').toLowerCase();
  if (DEFAULT_COLORS[name] && (!configured || configured === old)) return DEFAULT_COLORS[name];
  return safeColor(tag?.color || DEFAULT_COLORS[name] || '#64748b');
}

function tagOptions(tags, selected = '', includeAll = false) {
  const prefix = includeAll ? '<option value="">全部标签</option><option value="__untagged__">无标签</option>' : '<option value="">选择标签</option>';
  return prefix + (tags || []).map(tag => (
    `<option value="${esc(tag.name)}" ${String(tag.name) === String(selected) ? 'selected' : ''}>${esc(tag.name)}</option>`
  )).join('');
}

function tagChips(tags, sourceKey, selectedTags = []) {
  const selected = new Set((selectedTags || []).map(value => String(value).toLowerCase()));
  return `<div class="enh-tag-row" data-tag-row="${esc(sourceKey)}">${(tags || []).map(tag => {
    const active = selected.has(String(tag.name).toLowerCase());
    return `<button type="button" class="enh-tag-chip ${active ? 'active' : ''}" style="--tag-color:${libraryTagColor(tag)}" data-tag-key="${esc(sourceKey)}" data-tag-name="${esc(tag.name)}" aria-pressed="${active ? 'true' : 'false'}">${esc(tag.name)}</button>`;
  }).join('')}</div>`;
}

function groupFilterChips(groups) {
  const current = String(libraryState.groupId || '');
  return `<button type="button" class="enh-filter-chip ${current ? '' : 'active'}" data-library-group-chip="">全部分组</button>${(groups || []).map(group => (
    `<button type="button" class="enh-filter-chip ${String(group.id) === current ? 'active' : ''}" data-library-group-chip="${esc(group.id)}">${esc(group.display_name)}</button>`
  )).join('')}`;
}

function tagFilterChips(tags) {
  const current = String(libraryState.tag || '');
  const all = `<button type="button" class="enh-filter-chip ${current ? '' : 'active'}" data-library-tag-chip="">全部标签</button>`;
  const untagged = `<button type="button" class="enh-filter-chip enh-untagged-chip ${current === UNTAGGED ? 'active' : ''}" data-library-tag-chip="${UNTAGGED}">无标签</button>`;
  const values = (tags || []).map(tag => (
    `<button type="button" class="enh-filter-chip enh-colored-filter-chip ${String(tag.name) === current ? 'active' : ''}" style="--tag-color:${libraryTagColor(tag)}" data-library-tag-chip="${esc(tag.name)}">${esc(tag.name)}</button>`
  )).join('');
  return all + untagged + values;
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
    controls.push(`<button type="button" class="btn small ${value === current ? 'primary active' : ''}" data-library-page="${value}">${value}</button>`);
    previous = value;
  }
  return `<div class="enh-pagination"><button type="button" class="btn small" data-library-page="${Math.max(1, current - 1)}" ${current <= 1 ? 'disabled' : ''}>上一页</button>${controls.join('')}<button type="button" class="btn small" data-library-page="${Math.min(total, current + 1)}" ${current >= total ? 'disabled' : ''}>下一页</button><input class="input enh-page-jump" type="number" min="1" max="${total}" value="${current}" data-library-jump><button type="button" class="btn small" data-library-jump-button>跳转</button></div>`;
}

function libraryCard(item, tags) {
  const selected = libraryState.selected.has(item.id);
  const progress = Number(item.watch_duration) > 0
    ? Math.min(100, Number(item.watch_position || 0) / Number(item.watch_duration) * 100)
    : 0;
  return `<article class="media-card" data-library-id="${esc(item.id)}"><div class="cover-wrap"><img data-cover-img src="${esc(coverUrl(item.cover))}" alt="${esc(item.title)}" loading="lazy" referrerpolicy="no-referrer"><label class="enh-card-select"><input type="checkbox" data-library-select="${esc(item.id)}" ${selected ? 'checked' : ''}> 选择</label><div class="cover-badges"><span></span><span class="badge brand">${esc(item.selected_quality || item.selected_resolution || '媒体')}</span></div>${item.duration_text ? `<span class="duration-chip">${esc(item.duration_text)}</span>` : ''}</div><div class="media-body"><button type="button" class="media-title enh-title-button" data-library-open="${esc(item.id)}">${esc(item.title || item.bvid || item.source_key)}</button><div class="media-meta"><span>${esc(item.author || '-')}</span><span>${esc(item.bvid || item.source_key)}</span></div><div class="media-meta"><span>${esc(item.group_name || '未分组')}</span><span>${formatBytes(item.total_size)}</span><span>${esc(item.selected_codec || '')}</span></div>${tagChips(tags, item.source_key, item.tags)}${progress ? `<div class="progress" title="观看进度 ${Math.round(progress)}%"><span style="width:${progress}%"></span></div>` : ''}<div class="media-actions"><button type="button" class="btn primary small" data-library-open="${esc(item.id)}">播放</button><button type="button" class="btn small" data-library-move="${esc(item.id)}">▦ 改分组</button>${item.primary_file_id ? `<a class="btn small" href="/api/media/${encodeURIComponent(item.primary_file_id)}/download">下载到设备</a>` : ''}</div></div></article>`;
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

function requestedQuery() {
  try {
    const value = sessionStorage.getItem('bili-v070-library-query') || '';
    if (value) sessionStorage.removeItem('bili-v070-library-query');
    return value;
  } catch {
    return '';
  }
}

export async function mount(root, context) {
  const groups = context.shared.get().groups || [];
  const tags = context.shared.get().tags || [];
  const requested = requestedQuery();
  if (requested) {
    libraryState.q = requested;
    libraryState.page = 1;
  }

  const [sortField, sortDirection] = splitLibrarySort(libraryState.sort);
  const host = document.createElement('div');
  host.innerHTML = `<div data-enhanced-view="library">
    <section class="card enh-library-filter-card">
      <div class="card-head"><div><h2>作品库</h2><p>筛选、标签、排序和批量操作都使用 userdata 中的作品数据库。</p></div><span class="badge brand">SQLite 作品库</span></div>
      <div id="enhLibraryChipFilters" class="enh-library-chip-filters"><div class="enh-chip-filter-row"><span class="enh-chip-filter-label">▦ 分组</span><div class="enh-chip-strip">${groupFilterChips(groups)}</div></div><div class="enh-chip-filter-row"><span class="enh-chip-filter-label">⌁ 标签</span><div class="enh-chip-strip">${tagFilterChips(tags)}</div></div></div>
      <div class="enh-filter-grid">
        <div class="field enh-filter-wide"><label>作品关键词</label><div class="enh-input-shell" data-icon="⌕"><input id="enhLibraryQuery" class="input" value="${esc(libraryState.q)}" placeholder="标题、BV号或UP主"></div></div>
        <div class="field enh-native-chip-filter"><label>分组</label><select id="enhLibraryGroup" class="select">${groupOptions(groups, libraryState.groupId, true)}</select></div>
        <div class="field enh-native-chip-filter"><label>标签</label><select id="enhLibraryTag" class="select">${tagOptions(tags, libraryState.tag, true)}</select></div>
        <div class="field"><label>排序字段</label><div class="enh-select-shell" data-icon="⇅"><select id="enhLibrarySortField" class="select"><option value="newest">下载时间</option><option value="recent">最近观看</option><option value="title">标题</option><option value="duration">时长</option><option value="size">文件大小</option><option value="group">分组</option><option value="tag">标签</option></select></div></div>
        <div class="field"><label>排序方向</label><div class="enh-select-shell" data-icon="↕"><select id="enhLibrarySortDirection" class="select"><option value="desc">降序 / 新→旧 / 大→小</option><option value="asc">升序 / 旧→新 / 小→大</option></select></div></div>
        <div class="field"><label>视频编码</label><div class="enh-select-shell" data-icon="◫"><select id="enhLibraryCodec" class="select"><option value="">全部编码</option><option value="AVC">AVC / H.264</option><option value="HEVC">HEVC / H.265</option><option value="AV1">AV1</option></select></div></div>
        <div class="field"><label>最低实际清晰度</label><div class="enh-select-shell" data-icon="▣"><select id="enhLibraryHeight" class="select">${qualityOptions(libraryState.minHeight)}</select></div></div>
        <div class="field"><label>观看状态</label><div class="enh-select-shell" data-icon="▶"><select id="enhLibraryWatched" class="select"><option value="">全部</option><option value="unwatched">未观看</option><option value="watching">观看中</option><option value="completed">已看完</option></select></div></div>
        <div class="field enh-filter-submit"><button type="button" id="enhLibraryApply" class="btn primary"><span aria-hidden="true">↻</span> 应用筛选</button></div>
      </div>
    </section>
    <section class="enh-library-toolbar" style="margin-top:16px"><div class="enh-batch-layout"><span id="enhLibrarySummary" class="metric-foot">正在读取作品库…</span><div class="enh-batch-actions"><button type="button" id="enhLibrarySelectVisible" class="btn small" title="选择当前页全部作品"><span aria-hidden="true">✓</span> 本页</button><button type="button" id="enhLibraryClear" class="btn small" title="清空跨页选择"><span aria-hidden="true">×</span> 清空</button><div class="enh-select-shell enh-batch-select" data-icon="⌁"><select id="enhLibraryBatchTag" class="select enh-inline-select">${tagOptions(tags)}</select></div><button type="button" id="enhLibraryAddTag" class="btn small"><span aria-hidden="true">＋</span> 标签</button><button type="button" id="enhLibraryRemoveTag" class="btn small"><span aria-hidden="true">－</span> 标签</button><button type="button" id="enhLibraryDownload" class="btn small"><span aria-hidden="true">↓</span> 下载 ${libraryState.selected.size}</button><button type="button" id="enhLibraryDelete" class="btn danger small"><span aria-hidden="true">⌫</span> 删除 ${libraryState.selected.size}</button></div></div></section>
    <section id="enhLibraryResults" style="margin-top:16px"><div class="loading-card">正在读取作品库…</div></section>
  </div>`;
  context.commit(() => root.replaceChildren(host));

  let ownsModal = false;
  const results = host.querySelector('#enhLibraryResults');
  const summary = host.querySelector('#enhLibrarySummary');
  host.querySelector('#enhLibrarySortField').value = sortField;
  host.querySelector('#enhLibrarySortDirection').value = sortDirection;
  host.querySelector('#enhLibraryCodec').value = libraryState.codec;
  host.querySelector('#enhLibraryHeight').value = String(libraryState.minHeight || 0);
  host.querySelector('#enhLibraryWatched').value = libraryState.watched;

  const renderResults = () => {
    if (!context.isCurrent()) return;
    const data = libraryState.data || { items: [], page: 1, pages: 0, total: 0 };
    const validIds = new Set((data.items || []).map(item => String(item.id)));
    for (const id of [...libraryState.selected]) {
      if (!validIds.has(String(id)) && data.pages <= 1) libraryState.selected.delete(id);
    }
    summary.textContent = `共 ${data.total || 0} 个作品 · 第 ${data.page || 1} / ${data.pages || 0} 页 · 已选择 ${libraryState.selected.size}`;
    host.querySelector('#enhLibraryDownload').innerHTML = `<span aria-hidden="true">↓</span> 下载 ${libraryState.selected.size}`;
    host.querySelector('#enhLibraryDelete').innerHTML = `<span aria-hidden="true">⌫</span> 删除 ${libraryState.selected.size}`;
    results.innerHTML = (data.items || []).length
      ? `<div class="media-grid">${data.items.map(item => libraryCard(item, tags)).join('')}</div>${paginationHtml(data.page || 1, data.pages || 1)}`
      : '<div class="empty">没有符合条件的作品</div>';
    bindCoverFallback(results, context.signal);
  };

  const loadLibrary = async (page = libraryState.page) => {
    libraryState.page = Math.max(1, Number(page || 1));
    results.innerHTML = '<div class="loading-card">正在读取作品库…</div>';
    const params = new URLSearchParams({
      page: String(libraryState.page),
      page_size: '36',
      q: libraryState.q,
      group_id: libraryState.groupId,
      sort: libraryState.sort,
      codec: libraryState.codec,
      min_height: String(libraryState.minHeight || 0),
      watched: libraryState.watched,
      tag: libraryState.tag,
    });
    const response = await context.api(`/api/enhancements/library?${params}`, { signal: context.signal });
    libraryState.data = response.data || { items: [], page: 1, pages: 0, total: 0 };
    libraryState.page = Number(libraryState.data.page || libraryState.page);
    renderResults();
  };

  const assignTags = async (item, values) => {
    const response = await context.api('/api/enhancements/tags', {
      method: 'PUT',
      body: { source_key: item.source_key || '', media_id: item.id || '', tags: values },
      signal: context.signal,
    });
    item.tags = response.data?.tags || [];
    return item.tags;
  };

  const selectedLibraryItems = async () => {
    const ids = [...libraryState.selected];
    if (!ids.length) return [];
    const response = await context.api('/api/enhancements/library/items', {
      method: 'POST',
      body: { media_ids: ids },
      signal: context.signal,
    });
    return response.data || [];
  };

  const batchTag = async add => {
    const tag = host.querySelector('#enhLibraryBatchTag')?.value || '';
    if (!tag || !libraryState.selected.size) {
      context.toast.show('请选择标签和作品', 'warn');
      return;
    }
    try {
      const items = await selectedLibraryItems();
      await mapLimit(items, 6, async item => {
        const values = new Set(item.tags || []);
        if (add) values.add(tag);
        else values.delete(tag);
        await assignTags(item, [...values]);
      });
      context.toast.show(`已${add ? '添加' : '移除'}标签“${tag}”`, 'good');
      await loadLibrary();
    } catch (error) {
      if (error?.name !== 'AbortError') context.toast.show(error.message, 'bad');
    }
  };

  const moveMedia = async mediaId => {
    const item = (libraryState.data?.items || []).find(value => String(value.id) === String(mediaId));
    const modal = context.modal.open({
      title: '修改作品分组',
      narrow: true,
      onClose: () => { ownsModal = false; },
      body: `<form id="enhMoveMediaForm" class="form-grid"><div class="field full"><label>目标分组</label><select id="enhMoveMediaGroup" class="select">${groupOptions(groups, item?.group_id || '')}</select><small>修改的是作品库逻辑分组，不会重复下载媒体文件。</small></div><div class="field full">${modalActions('保存分组')}</div></form>`,
    });
    ownsModal = true;
    bindDialogCancel(modal);
    modal.body.querySelector('#enhMoveMediaForm').addEventListener('submit', async event => {
      event.preventDefault();
      const button = event.currentTarget.querySelector('button[type="submit"]');
      button.disabled = true;
      try {
        const groupId = modal.body.querySelector('#enhMoveMediaGroup').value;
        await context.api(`/api/library/${encodeURIComponent(mediaId)}/move`, {
          method: 'POST',
          body: { group_id: groupId },
        });
        modal.close('saved');
        context.toast.show('作品分组已修改', 'good');
        await loadLibrary();
      } catch (error) {
        context.toast.show(error.message, 'bad');
      } finally {
        button.disabled = false;
      }
    });
  };

  const deleteMedia = async ids => {
    const accepted = await context.confirm({
      title: ids.length > 1 ? '批量删除作品' : '删除作品',
      message: `确定删除选中的 ${ids.length} 个作品及其媒体文件吗？删除历史会被记录。`,
      confirmLabel: '删除作品',
      danger: true,
    });
    if (!accepted) return false;
    const response = await context.api('/api/enhancements/library/delete', {
      method: 'POST',
      body: { media_ids: ids, delete_files: true, mark_tag: '' },
    });
    const deleted = response.data?.deleted || [];
    for (const id of deleted) libraryState.selected.delete(id);
    const errorCount = Object.keys(response.data?.errors || {}).length;
    context.toast.show(`已删除 ${deleted.length} 个作品${errorCount ? `，${errorCount} 个失败` : ''}`, errorCount ? 'warn' : 'good');
    await loadLibrary();
    return true;
  };

  const openMedia = async mediaId => {
    let player = null;
    let currentFile = null;
    let saveTimer = 0;
    let save = () => {};
    const modal = context.modal.open({
      title: '作品详情',
      body: '<div class="loading-card">正在载入播放器…</div>',
      onClose: () => {
        ownsModal = false;
        save();
      },
    });
    ownsModal = true;
    try {
      const response = await context.api(`/api/library/${encodeURIComponent(mediaId)}`);
      const media = response.data || {};
      const files = media.files || [];
      currentFile = files.find(file => file.is_primary) || files.find(file => file.kind === 'media') || files[0];
      if (!currentFile) {
        modal.body.innerHTML = '<div class="empty">作品没有可播放文件</div>';
        return;
      }
      modal.root.querySelector('.modal-head h2').textContent = media.title || media.bvid || '作品详情';
      modal.body.innerHTML = `<div class="player-shell"><video id="enhMediaPlayer" controls playsinline preload="metadata" poster="${esc(coverUrl(media.cover))}" src="/api/media/${encodeURIComponent(currentFile.id)}/stream"></video></div><div class="card flat" style="margin-top:14px;padding:0"><div class="card-head"><div><h3>${esc(media.title || media.bvid)}</h3><p>${esc(media.bvid || media.source_key)} · ${esc(media.author || '-')} · ${esc(media.duration_text || '-')} · ${esc(media.selected_quality || media.selected_resolution || '-')} · ${esc(media.selected_codec || '-')}</p></div><span class="badge brand">${esc(media.group_name || '未分组')}</span></div><div class="toolbar"><a id="enhDownloadCurrent" class="btn primary" href="/api/media/${encodeURIComponent(currentFile.id)}/download">下载当前文件</a>${media.source_url ? `<a class="btn" href="${esc(media.source_url)}" target="_blank" rel="noopener noreferrer">B站原页面</a>` : ''}<button type="button" id="enhMoveCurrentMediaGroup" class="btn">▦ 修改分组</button><button type="button" id="enhDeleteCurrentMedia" class="btn danger">删除作品</button></div></div><h3 style="margin:20px 0 10px">文件与分 P</h3><div class="file-list">${files.map(file => `<div class="file-row"><div><strong>${esc(file.filename)}</strong><div class="metric-foot">${file.kind === 'compatible' ? '兼容副本' : '原始文件'} · ${formatBytes(file.size)}${file.watch_position > 1 ? ` · 已看 ${Math.round(file.watch_position)} 秒` : ''}</div></div><button type="button" class="btn small ${file.id === currentFile.id ? 'primary' : ''}" data-enh-play-file="${esc(file.id)}">播放</button></div>`).join('')}</div>`;
      player = modal.body.querySelector('#enhMediaPlayer');
      const setResume = file => {
        const position = Number(file?.watch_position || 0);
        if (!player || position <= 1) return;
        const apply = () => {
          try {
            if (Number.isFinite(player.duration) && position < player.duration - 2) player.currentTime = position;
          } catch {}
        };
        if (player.readyState >= 1) apply();
        else player.addEventListener('loadedmetadata', apply, { once: true });
      };
      save = () => {
        if (!currentFile || !player || !Number.isFinite(player.duration) || player.duration <= 0) return;
        context.api(`/api/library/${encodeURIComponent(mediaId)}/progress`, {
          method: 'PUT',
          body: { file_id: currentFile.id, position_sec: player.currentTime, duration_sec: player.duration },
        }).catch(() => {});
      };
      setResume(currentFile);
      player.addEventListener('timeupdate', () => {
        if (Date.now() - saveTimer > 8000) {
          saveTimer = Date.now();
          save();
        }
      });
      player.addEventListener('pause', save);
      player.addEventListener('ended', save);
      modal.body.addEventListener('click', event => {
        const button = event.target.closest('[data-enh-play-file]');
        if (!button) return;
        const file = files.find(value => String(value.id) === String(button.dataset.enhPlayFile));
        if (!file) return;
        save();
        currentFile = file;
        player.pause();
        player.src = `/api/media/${encodeURIComponent(file.id)}/stream`;
        modal.body.querySelector('#enhDownloadCurrent').href = `/api/media/${encodeURIComponent(file.id)}/download`;
        for (const node of modal.body.querySelectorAll('[data-enh-play-file]')) node.classList.toggle('primary', node === button);
        setResume(file);
        player.play().catch(() => {});
      });
      modal.body.querySelector('#enhMoveCurrentMediaGroup').addEventListener('click', () => {
        modal.close('move');
        void moveMedia(mediaId);
      });
      modal.body.querySelector('#enhDeleteCurrentMedia').addEventListener('click', async () => {
        modal.close('delete-confirm');
        await deleteMedia([mediaId]);
      });
    } catch (error) {
      modal.body.innerHTML = `<div class="notice bad">${esc(error.message)}</div>`;
    }
  };

  const applyFilters = async () => {
    libraryState.q = host.querySelector('#enhLibraryQuery').value.trim();
    libraryState.groupId = host.querySelector('#enhLibraryGroup').value;
    libraryState.tag = host.querySelector('#enhLibraryTag').value;
    libraryState.sort = librarySortValue(
      host.querySelector('#enhLibrarySortField').value,
      host.querySelector('#enhLibrarySortDirection').value,
    );
    libraryState.codec = host.querySelector('#enhLibraryCodec').value;
    libraryState.minHeight = Number(host.querySelector('#enhLibraryHeight').value);
    libraryState.watched = host.querySelector('#enhLibraryWatched').value;
    libraryState.page = 1;
    await loadLibrary();
  };

  host.querySelector('#enhLibraryApply').addEventListener('click', () => void applyFilters(), { signal: context.signal });
  host.querySelector('#enhLibraryQuery').addEventListener('keydown', event => {
    if (event.key !== 'Enter') return;
    event.preventDefault();
    void applyFilters();
  }, { signal: context.signal });
  host.querySelector('#enhLibrarySortField').addEventListener('change', () => void applyFilters(), { signal: context.signal });
  host.querySelector('#enhLibrarySortDirection').addEventListener('change', () => void applyFilters(), { signal: context.signal });

  host.addEventListener('change', event => {
    const input = event.target.closest('[data-library-select]');
    if (!input) return;
    if (input.checked) libraryState.selected.add(input.dataset.librarySelect);
    else libraryState.selected.delete(input.dataset.librarySelect);
    renderResults();
  }, { signal: context.signal });

  host.addEventListener('click', async event => {
    const target = event.target.closest('button');
    if (!target) return;
    if (target.dataset.libraryGroupChip !== undefined) {
      libraryState.groupId = target.dataset.libraryGroupChip || '';
      host.querySelector('#enhLibraryGroup').value = libraryState.groupId;
      libraryState.page = 1;
      await loadLibrary();
    } else if (target.dataset.libraryTagChip !== undefined) {
      libraryState.tag = target.dataset.libraryTagChip || '';
      host.querySelector('#enhLibraryTag').value = libraryState.tag;
      libraryState.page = 1;
      await loadLibrary();
    } else if (target.dataset.tagKey !== undefined) {
      const item = (libraryState.data?.items || []).find(value => String(value.source_key) === String(target.dataset.tagKey));
      if (!item) return;
      const values = new Set(item.tags || []);
      const tagName = target.dataset.tagName || '';
      if (values.has(tagName)) values.delete(tagName);
      else values.add(tagName);
      target.disabled = true;
      try {
        await assignTags(item, [...values]);
        renderResults();
      } catch (error) {
        context.toast.show(error.message, 'bad');
      } finally {
        target.disabled = false;
      }
    } else if (target.dataset.libraryOpen !== undefined) {
      await openMedia(target.dataset.libraryOpen);
    } else if (target.dataset.libraryMove !== undefined) {
      await moveMedia(target.dataset.libraryMove);
    } else if (target.dataset.libraryPage !== undefined) {
      await loadLibrary(Number(target.dataset.libraryPage));
    } else if (target.dataset.libraryJumpButton !== undefined) {
      const total = Math.max(1, Number(libraryState.data?.pages || 1));
      const value = Math.max(1, Math.min(total, Number(results.querySelector('[data-library-jump]')?.value || 1)));
      await loadLibrary(value);
    } else if (target.id === 'enhLibrarySelectVisible') {
      for (const item of libraryState.data?.items || []) libraryState.selected.add(item.id);
      renderResults();
    } else if (target.id === 'enhLibraryClear') {
      libraryState.selected.clear();
      renderResults();
    } else if (target.id === 'enhLibraryAddTag') {
      await batchTag(true);
    } else if (target.id === 'enhLibraryRemoveTag') {
      await batchTag(false);
    } else if (target.id === 'enhLibraryDownload') {
      if (!libraryState.selected.size) {
        context.toast.show('请先选择作品', 'warn');
        return;
      }
      try {
        const items = await selectedLibraryItems();
        const downloadable = items.filter(item => item.primary_file_id);
        if (!downloadable.length) {
          context.toast.show('所选作品没有可下载的主文件', 'warn');
          return;
        }
        if (downloadable.length > 5) {
          const accepted = await context.confirm({
            title: '批量下载',
            message: `浏览器将依次发起 ${downloadable.length} 个文件下载，可能需要允许“多个文件下载”。是否继续？`,
            confirmLabel: '继续下载',
          });
          if (!accepted) return;
        }
        for (const item of downloadable) {
          const anchor = document.createElement('a');
          anchor.href = `/api/media/${encodeURIComponent(item.primary_file_id)}/download`;
          anchor.download = '';
          host.appendChild(anchor);
          anchor.click();
          anchor.remove();
          await new Promise(resolve => setTimeout(resolve, 250));
        }
        context.toast.show(`已发起 ${downloadable.length} 个下载`, 'good');
      } catch (error) {
        context.toast.show(error.message, 'bad');
      }
    } else if (target.id === 'enhLibraryDelete') {
      const ids = [...libraryState.selected];
      if (!ids.length) context.toast.show('请先选择作品', 'warn');
      else await deleteMedia(ids);
    }
  }, { signal: context.signal });

  await loadLibrary();
  return Object.freeze({
    dispose: once(() => {
      if (ownsModal) context.modal.close('route');
    }),
  });
}
