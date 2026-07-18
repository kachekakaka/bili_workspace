(() => {
  'use strict';
  if (!window.BiliEnhancements) return;
  const {
    VERSION, state, $, $$, esc, sleep, formatBytes, qualityOptions, groupOptions,
    tagOptions, toast, showModal, api, paginationHtml, tagChips, mapLimit,
    assignTags, bindTagButtons, coverUrl, bindCoverFallback, register,
  } = window.BiliEnhancements;

  const SORT_ALIASES = {
    newest: ['newest', 'desc'], oldest: ['newest', 'asc'], recent: ['recent', 'desc'],
    title: ['title', 'asc'], size: ['size', 'desc'],
  };
  const SORT_FIELDS = new Set(['newest', 'recent', 'title', 'duration', 'size', 'group', 'tag']);

  function splitSort(value) {
    const text = String(value || 'newest');
    if (SORT_ALIASES[text]) return SORT_ALIASES[text];
    const match = text.match(/^(newest|recent|title|duration|size|group|tag)_(asc|desc)$/);
    return match ? [match[1], match[2]] : ['newest', 'desc'];
  }

  function sortValue(field, direction) {
    const safeField = SORT_FIELDS.has(field) ? field : 'newest';
    return `${safeField}_${direction === 'asc' ? 'asc' : 'desc'}`;
  }

  async function renderLibrary(root) {
    const library = state.library;
    const [sortField, sortDirection] = splitSort(library.sort);
    root.innerHTML = `<div data-enhanced-view="library" data-version="${VERSION}">
      <section class="card enh-library-filter-card">
        <div class="card-head"><div><h2>作品库</h2><p>筛选、标签、排序和批量操作都使用 userdata 中的作品数据库。</p></div><span class="badge brand">SQLite 作品库</span></div>
        <div class="enh-filter-grid">
          <div class="field enh-filter-wide"><label>作品关键词</label><div class="enh-input-shell" data-icon="⌕"><input id="enhLibraryQuery" class="input" value="${esc(library.q)}" placeholder="标题、BV号或UP主"></div></div>
          <div class="field"><label>分组</label><div class="enh-select-shell" data-icon="▦"><select id="enhLibraryGroup" class="select">${groupOptions(library.groupId, true)}</select></div></div>
          <div class="field"><label>标签</label><div class="enh-select-shell" data-icon="⌁"><select id="enhLibraryTag" class="select">${tagOptions(library.tag, true)}</select></div></div>
          <div class="field"><label>排序字段</label><div class="enh-select-shell" data-icon="⇅"><select id="enhLibrarySortField" class="select"><option value="newest">下载时间</option><option value="recent">最近观看</option><option value="title">标题</option><option value="duration">时长</option><option value="size">文件大小</option><option value="group">分组</option><option value="tag">标签</option></select></div></div>
          <div class="field"><label>排序方向</label><div class="enh-select-shell" data-icon="↕"><select id="enhLibrarySortDirection" class="select"><option value="desc">降序 / 新→旧 / 大→小</option><option value="asc">升序 / 旧→新 / 小→大</option></select></div></div>
          <div class="field"><label>视频编码</label><div class="enh-select-shell" data-icon="◫"><select id="enhLibraryCodec" class="select"><option value="">全部编码</option><option value="AVC">AVC / H.264</option><option value="HEVC">HEVC / H.265</option><option value="AV1">AV1</option></select></div></div>
          <div class="field"><label>最低实际清晰度</label><div class="enh-select-shell" data-icon="▣"><select id="enhLibraryHeight" class="select">${qualityOptions(library.minHeight)}</select></div></div>
          <div class="field"><label>观看状态</label><div class="enh-select-shell" data-icon="▶"><select id="enhLibraryWatched" class="select"><option value="">全部</option><option value="unwatched">未观看</option><option value="watching">观看中</option><option value="completed">已看完</option></select></div></div>
          <div class="field enh-filter-submit"><button type="button" id="enhLibraryApply" class="btn primary"><span aria-hidden="true">↻</span> 应用筛选</button></div>
        </div>
      </section>
      <section class="enh-library-toolbar" style="margin-top:16px"><div class="enh-batch-layout"><span id="enhLibrarySummary" class="metric-foot">正在读取作品库…</span><div class="enh-batch-actions"><button type="button" id="enhLibrarySelectVisible" class="btn small" title="选择当前页全部作品"><span aria-hidden="true">✓</span> 本页</button><button type="button" id="enhLibraryClear" class="btn small" title="清空跨页选择"><span aria-hidden="true">×</span> 清空</button><div class="enh-select-shell enh-batch-select" data-icon="⌁"><select id="enhLibraryBatchTag" class="select enh-inline-select">${tagOptions()}</select></div><button type="button" id="enhLibraryAddTag" class="btn small"><span aria-hidden="true">＋</span> 标签</button><button type="button" id="enhLibraryRemoveTag" class="btn small"><span aria-hidden="true">－</span> 标签</button><button type="button" id="enhLibraryDownload" class="btn small"><span aria-hidden="true">↓</span> 下载 ${library.selected.size}</button><button type="button" id="enhLibraryDelete" class="btn danger small"><span aria-hidden="true">⌫</span> 删除 ${library.selected.size}</button></div></div></section>
      <section id="enhLibraryResults" style="margin-top:16px"><div class="loading-card">正在读取作品库…</div></section>
    </div>`;
    $('#enhLibrarySortField').value = sortField;
    $('#enhLibrarySortDirection').value = sortDirection;
    $('#enhLibraryCodec').value = library.codec;
    $('#enhLibraryHeight').value = String(library.minHeight || 0);
    $('#enhLibraryWatched').value = library.watched;
    const applyFilters = () => {
      library.q = $('#enhLibraryQuery').value.trim();
      library.groupId = $('#enhLibraryGroup').value;
      library.tag = $('#enhLibraryTag').value;
      library.sort = sortValue($('#enhLibrarySortField').value, $('#enhLibrarySortDirection').value);
      library.codec = $('#enhLibraryCodec').value;
      library.minHeight = Number($('#enhLibraryHeight').value);
      library.watched = $('#enhLibraryWatched').value;
      library.page = 1;
      loadLibrary();
    };
    $('#enhLibraryApply').onclick = applyFilters;
    $('#enhLibraryQuery').onkeydown = event => { if (event.key === 'Enter') applyFilters(); };
    $('#enhLibrarySortField').onchange = applyFilters;
    $('#enhLibrarySortDirection').onchange = applyFilters;
    $('#enhLibrarySelectVisible').onclick = () => {
      for (const item of library.data?.items || []) library.selected.add(item.id);
      renderLibraryResults();
    };
    $('#enhLibraryClear').onclick = () => { library.selected.clear(); renderLibraryResults(); };
    $('#enhLibraryAddTag').onclick = () => batchTagLibrary(true);
    $('#enhLibraryRemoveTag').onclick = () => batchTagLibrary(false);
    $('#enhLibraryDownload').onclick = () => batchDownloadLibrary();
    $('#enhLibraryDelete').onclick = () => batchDeleteLibrary();
    await loadLibrary();
  }

  async function loadLibrary(page = state.library.page) {
    const library = state.library;
    library.page = Math.max(1, Number(page || 1));
    const box = $('#enhLibraryResults');
    if (box) box.innerHTML = '<div class="loading-card">正在读取作品库…</div>';
    const params = new URLSearchParams({
      page: String(library.page), page_size: '36', q: library.q,
      group_id: library.groupId, sort: library.sort, codec: library.codec,
      min_height: String(library.minHeight || 0), watched: library.watched, tag: library.tag,
    });
    try {
      const response = await api(`/api/enhancements/library?${params}`);
      library.data = response.data || { items: [], page: 1, pages: 0, total: 0 };
      library.page = Number(library.data.page || library.page);
      renderLibraryResults();
    } catch (error) {
      if (box) box.innerHTML = `<div class="notice bad">${esc(error.message)}</div>`;
      toast(error.message, 'bad');
    }
  }

  function libraryCard(item) {
    const selected = state.library.selected.has(item.id);
    const progress = Number(item.watch_duration) > 0
      ? Math.min(100, Number(item.watch_position || 0) / Number(item.watch_duration) * 100)
      : 0;
    return `<article class="media-card" data-library-id="${esc(item.id)}"><div class="cover-wrap"><img data-cover-img src="${esc(coverUrl(item.cover))}" alt="${esc(item.title)}" loading="lazy" referrerpolicy="no-referrer"><label class="enh-card-select"><input type="checkbox" data-library-select="${esc(item.id)}" ${selected ? 'checked' : ''}> 选择</label><div class="cover-badges"><span></span><span class="badge brand">${esc(item.selected_quality || item.selected_resolution || '媒体')}</span></div>${item.duration_text ? `<span class="duration-chip">${esc(item.duration_text)}</span>` : ''}</div><div class="media-body"><button type="button" class="media-title enh-title-button" data-library-open="${esc(item.id)}">${esc(item.title || item.bvid || item.source_key)}</button><div class="media-meta"><span>${esc(item.author || '-')}</span><span>${esc(item.bvid || item.source_key)}</span></div><div class="media-meta"><span>${esc(item.group_name || '未分组')}</span><span>${formatBytes(item.total_size)}</span><span>${esc(item.selected_codec || '')}</span></div>${tagChips(item.source_key, item.tags)}${progress ? `<div class="progress" title="观看进度 ${Math.round(progress)}%"><span style="width:${progress}%"></span></div>` : ''}<div class="media-actions"><button type="button" class="btn primary small" data-library-open="${esc(item.id)}">播放</button>${item.primary_file_id ? `<a class="btn small" href="/api/media/${encodeURIComponent(item.primary_file_id)}/download">下载到设备</a>` : ''}</div></div></article>`;
  }

  function renderLibraryResults() {
    const box = $('#enhLibraryResults');
    const data = state.library.data;
    if (!box || !data) return;
    const summary = $('#enhLibrarySummary');
    if (summary) summary.textContent = `共 ${data.total || 0} 个作品 · 第 ${data.page || 1} / ${data.pages || 0} 页 · 已选择 ${state.library.selected.size}`;
    const download = $('#enhLibraryDownload');
    const remove = $('#enhLibraryDelete');
    if (download) download.innerHTML = `<span aria-hidden="true">↓</span> 下载 ${state.library.selected.size}`;
    if (remove) remove.innerHTML = `<span aria-hidden="true">⌫</span> 删除 ${state.library.selected.size}`;
    box.innerHTML = (data.items || []).length
      ? `<div class="media-grid">${data.items.map(libraryCard).join('')}</div>${paginationHtml(data.page || 1, data.pages || 1, 'library')}`
      : '<div class="empty">没有符合条件的作品</div>';
    $$('[data-library-select]', box).forEach(input => {
      input.onchange = () => {
        if (input.checked) state.library.selected.add(input.dataset.librarySelect);
        else state.library.selected.delete(input.dataset.librarySelect);
        renderLibraryResults();
      };
    });
    $$('[data-library-open]', box).forEach(button => { button.onclick = () => openLibraryMedia(button.dataset.libraryOpen); });
    $$('[data-library-page]', box).forEach(button => { button.onclick = () => loadLibrary(Number(button.dataset.libraryPage)); });
    const jump = $('[data-library-jump]', box);
    const jumpButton = $('[data-library-jump-button]', box);
    if (jumpButton) jumpButton.onclick = () => loadLibrary(Math.max(1, Math.min(Number(data.pages || 1), Number(jump.value || 1))));
    bindTagButtons(box, key => (data.items || []).find(item => item.source_key === key), renderLibraryResults);
    bindCoverFallback(box);
  }

  async function selectedLibraryItems() {
    const ids = [...state.library.selected];
    if (!ids.length) return [];
    const response = await api('/api/enhancements/library/items', {
      method: 'POST', body: { media_ids: ids },
    });
    return response.data || [];
  }

  async function batchTagLibrary(add) {
    const tag = $('#enhLibraryBatchTag')?.value || '';
    if (!tag || !state.library.selected.size) {
      toast('请选择标签和作品', 'warn');
      return;
    }
    try {
      const items = await selectedLibraryItems();
      await mapLimit(items, 6, async item => {
        const tags = new Set(item.tags || []);
        if (add) tags.add(tag); else tags.delete(tag);
        item.tags = await assignTags(item.source_key, [...tags], item.id);
      });
      toast(`已${add ? '添加' : '移除'}标签“${tag}”`, 'good');
      await loadLibrary();
    } catch (error) {
      toast(error.message, 'bad');
    }
  }

  async function batchDownloadLibrary() {
    if (!state.library.selected.size) {
      toast('请先选择作品', 'warn');
      return;
    }
    try {
      const items = await selectedLibraryItems();
      const downloadable = items.filter(item => item.primary_file_id);
      if (!downloadable.length) {
        toast('所选作品没有可下载的主文件', 'warn');
        return;
      }
      if (downloadable.length > 5 && !confirm(`浏览器将依次发起 ${downloadable.length} 个文件下载，可能需要允许“多个文件下载”。是否继续？`)) return;
      for (const item of downloadable) {
        const anchor = document.createElement('a');
        anchor.href = `/api/media/${encodeURIComponent(item.primary_file_id)}/download`;
        anchor.download = '';
        document.body.appendChild(anchor);
        anchor.click();
        anchor.remove();
        await sleep(250);
      }
      toast(`已发起 ${downloadable.length} 个下载`, 'good');
    } catch (error) {
      toast(error.message, 'bad');
    }
  }

  async function batchDeleteLibrary() {
    const ids = [...state.library.selected];
    if (!ids.length) {
      toast('请先选择作品', 'warn');
      return;
    }
    if (!confirm(`确定删除选中的 ${ids.length} 个作品及其媒体文件吗？删除前会记录“不要”标签。`)) return;
    try {
      const response = await api('/api/enhancements/library/delete', {
        method: 'POST', body: { media_ids: ids, delete_files: true, mark_tag: '不要' },
      });
      const deleted = response.data?.deleted || [];
      for (const id of deleted) state.library.selected.delete(id);
      const errorCount = Object.keys(response.data?.errors || {}).length;
      toast(`已删除 ${deleted.length} 个作品${errorCount ? `，${errorCount} 个失败` : ''}`, errorCount ? 'warn' : 'good');
      await loadLibrary();
    } catch (error) {
      toast(error.message, 'bad');
    }
  }

  async function openLibraryMedia(mediaId) {
    let player = null;
    let currentFile = null;
    let saveTimer = 0;
    let save = () => {};
    const modal = showModal('作品详情', '<div class="loading-card">正在载入播放器…</div>', { onClose: () => save() });
    try {
      const response = await api(`/api/library/${encodeURIComponent(mediaId)}`);
      const media = response.data || {};
      const files = media.files || [];
      currentFile = files.find(file => file.is_primary) || files.find(file => file.kind === 'media') || files[0];
      if (!currentFile) {
        $('.modal-body', modal.root).innerHTML = '<div class="empty">作品没有可播放文件</div>';
        return;
      }
      $('.modal-head h2', modal.root).textContent = media.title || media.bvid || '作品详情';
      $('.modal-body', modal.root).innerHTML = `<div class="player-shell"><video id="enhMediaPlayer" controls playsinline preload="metadata" poster="${esc(coverUrl(media.cover))}" src="/api/media/${encodeURIComponent(currentFile.id)}/stream"></video></div><div class="card flat" style="margin-top:14px;padding:0"><div class="card-head"><div><h3>${esc(media.title || media.bvid)}</h3><p>${esc(media.bvid || media.source_key)} · ${esc(media.author || '-')} · ${esc(media.duration_text || '-')} · ${esc(media.selected_quality || media.selected_resolution || '-')} · ${esc(media.selected_codec || '-')}</p></div><span class="badge brand">${esc(media.group_name || '未分组')}</span></div><div class="toolbar"><a id="enhDownloadCurrent" class="btn primary" href="/api/media/${encodeURIComponent(currentFile.id)}/download">下载当前文件</a>${media.source_url ? `<a class="btn" href="${esc(media.source_url)}" target="_blank" rel="noopener noreferrer">B站原页面</a>` : ''}<button type="button" id="enhDeleteCurrentMedia" class="btn danger">删除作品</button></div></div><h3 style="margin:20px 0 10px">文件与分 P</h3><div class="file-list">${files.map(file => `<div class="file-row"><div><strong>${esc(file.filename)}</strong><div class="metric-foot">${file.kind === 'compatible' ? '兼容副本' : '原始文件'} · ${formatBytes(file.size)}${file.watch_position > 1 ? ` · 已看 ${Math.round(file.watch_position)} 秒` : ''}</div></div><button type="button" class="btn small ${file.id === currentFile.id ? 'primary' : ''}" data-enh-play-file="${esc(file.id)}">播放</button></div>`).join('')}</div>`;
      player = $('#enhMediaPlayer', modal.root);
      const setResume = file => {
        const position = Number(file?.watch_position || 0);
        if (!player || position <= 1) return;
        const apply = () => {
          try { if (Number.isFinite(player.duration) && position < player.duration - 2) player.currentTime = position; } catch (_) {}
        };
        if (player.readyState >= 1) apply(); else player.addEventListener('loadedmetadata', apply, { once: true });
      };
      save = () => {
        if (!currentFile || !player || !Number.isFinite(player.duration) || player.duration <= 0) return;
        api(`/api/library/${encodeURIComponent(mediaId)}/progress`, {
          method: 'PUT', body: { file_id: currentFile.id, position_sec: player.currentTime, duration_sec: player.duration },
        }).catch(() => {});
      };
      setResume(currentFile);
      player.addEventListener('timeupdate', () => { if (Date.now() - saveTimer > 8000) { saveTimer = Date.now(); save(); } });
      player.addEventListener('pause', save);
      player.addEventListener('ended', save);
      $$('[data-enh-play-file]', modal.root).forEach(button => {
        button.onclick = () => {
          const file = files.find(value => value.id === button.dataset.enhPlayFile);
          if (!file) return;
          save();
          currentFile = file;
          player.pause();
          player.src = `/api/media/${encodeURIComponent(file.id)}/stream`;
          $('#enhDownloadCurrent', modal.root).href = `/api/media/${encodeURIComponent(file.id)}/download`;
          $$('[data-enh-play-file]', modal.root).forEach(node => node.classList.toggle('primary', node === button));
          setResume(file);
          player.play().catch(() => {});
        };
      });
      $('#enhDeleteCurrentMedia', modal.root).onclick = async () => {
        if (!confirm('确定删除这个作品及其媒体文件吗？删除前会记录“不要”标签。')) return;
        try {
          await api('/api/enhancements/library/delete', {
            method: 'POST', body: { media_ids: [mediaId], delete_files: true, mark_tag: '不要' },
          });
          state.library.selected.delete(mediaId);
          modal.close();
          toast('作品已删除', 'good');
          await loadLibrary();
        } catch (error) {
          toast(error.message, 'bad');
        }
      };
    } catch (error) {
      $('.modal-body', modal.root).innerHTML = `<div class="notice bad">${esc(error.message)}</div>`;
    }
  }

  register('library', renderLibrary);
})();
