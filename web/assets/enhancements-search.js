(() => {
  'use strict';
  if (!window.BiliEnhancements) return;
  const {
    VERSION, state, $, $$, esc, formatDate, formatPlay, qualityOptions,
    groupOptions, tagOptions, toast, showModal, api, paginationHtml, tagChips,
    mapLimit, assignTags, bindTagButtons, register,
  } = window.BiliEnhancements;

  async function renderSearch(root) {
    const search = state.search;
    root.innerHTML = `<div data-enhanced-view="search" data-version="${VERSION}">
      <section class="card">
        <div class="card-head"><div><h2>搜索 Bilibili 作品</h2><p>页码结果会在浏览器和服务端短期缓存；返回已访问页不会重复搜索。</p></div><span class="badge brand">增强搜索</span></div>
        <div class="form-grid">
          <div class="field full"><label>搜索关键词</label><div class="toolbar"><input id="enhSearchQuery" class="input" style="flex:1" value="${esc(search.q)}" placeholder="作品标题、UP主或关键词"><select id="enhSearchOrder" class="select" style="width:auto"><option value="totalrank">综合排序</option><option value="click">播放最多</option><option value="pubdate">最新发布</option></select><button type="button" id="enhSearchButton" class="btn primary">搜索</button></div></div>
          <div class="field"><label>下载目标</label><select id="enhSearchDestination" class="select"><option value="library">保存到媒体库</option><option value="device">导出到当前设备</option></select></div>
          <div class="field" id="enhSearchGroupField"><label>保存分组</label><select id="enhSearchGroup" class="select">${groupOptions(search.groupId)}</select></div>
          <div class="field"><label>最低清晰度</label><select id="enhSearchQuality" class="select">${qualityOptions(search.minHeight)}</select></div>
          <div class="field"><label>结果过滤</label><label class="enh-check"><input id="enhHideDownloaded" type="checkbox" ${search.hideDownloaded ? 'checked' : ''}> 隐藏已经下载过的作品</label></div>
          <div class="field full"><div class="enh-batch-bar"><span id="enhSearchSummary" class="metric-foot">输入关键词后搜索</span><span class="enh-spacer"></span><button type="button" id="enhSearchSelectVisible" class="btn small">全选当前结果</button><button type="button" id="enhSearchClear" class="btn small">清空选择</button><select id="enhSearchBatchTag" class="select enh-inline-select">${tagOptions()}</select><button type="button" id="enhSearchAddTag" class="btn small">给选中项加标签</button><button type="button" id="enhSearchDownloadSelected" class="btn primary small">下载选中（${search.selected.size}）</button></div></div>
        </div>
      </section>
      <section id="enhSearchResults" style="margin-top:18px"></section>
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
    $('#enhHideDownloaded').onchange = () => { search.hideDownloaded = $('#enhHideDownloaded').checked; renderSearchResults(); };
    $('#enhSearchButton').onclick = () => startSearch();
    $('#enhSearchQuery').onkeydown = event => { if (event.key === 'Enter') startSearch(); };
    $('#enhSearchSelectVisible').onclick = () => {
      for (const item of visibleSearchItems()) search.selected.set(item.bvid, item);
      renderSearchResults();
    };
    $('#enhSearchClear').onclick = () => { search.selected.clear(); renderSearchResults(); };
    $('#enhSearchDownloadSelected').onclick = () => downloadSearchItems([...search.selected.values()]);
    $('#enhSearchAddTag').onclick = () => batchTagSearchItems();

    if (search.data) renderSearchResults();
    else if (search.q) await loadSearchPage(search.page);
    else $('#enhSearchResults').innerHTML = '<div class="empty">输入关键词开始搜索</div>';
  }

  async function startSearch() {
    const search = state.search;
    const q = $('#enhSearchQuery')?.value.trim() || '';
    const order = $('#enhSearchOrder')?.value || 'totalrank';
    if (!q) {
      toast('请输入关键词', 'warn');
      return;
    }
    if (q !== search.q || order !== search.order) {
      search.q = q;
      search.order = order;
      search.page = 1;
      search.pages = 0;
      search.total = 0;
      search.data = null;
      search.selected.clear();
      search.cache.clear();
    }
    await loadSearchPage(1);
  }

  async function decorateSearchTags(data) {
    const keys = (data.items || []).map(item => item.bvid).filter(Boolean);
    if (!keys.length) return data;
    const response = await api('/api/enhancements/tags/bulk', {
      method: 'POST', body: { keys, media_ids: [] },
    });
    const byKey = response.data?.by_key || {};
    for (const item of data.items || []) item.tags = byKey[item.bvid] || [];
    return data;
  }

  async function loadSearchPage(page) {
    const search = state.search;
    if (!search.q) return;
    const safePage = Math.max(1, Number(page || 1));
    const key = `${search.q}\u0000${search.order}\u0000${safePage}`;
    const box = $('#enhSearchResults');
    if (box) box.innerHTML = '<div class="loading-card">正在搜索…</div>';
    try {
      let data = search.cache.get(key);
      if (!data) {
        const response = await api(`/api/search?q=${encodeURIComponent(search.q)}&order=${encodeURIComponent(search.order)}&page=${safePage}`);
        data = await decorateSearchTags(response.data || {});
        search.cache.set(key, data);
      }
      search.page = safePage;
      search.data = data;
      search.pages = Number(data.pages || data.numPages || data.num_pages || 0);
      search.total = Number(data.total || data.numResults || data.num_results || 0);
      renderSearchResults();
    } catch (error) {
      if (box) box.innerHTML = `<div class="notice bad">${esc(error.message)}</div>`;
      toast(error.message, 'bad');
    }
  }

  function visibleSearchItems() {
    const items = state.search.data?.items || [];
    return state.search.hideDownloaded ? items.filter(item => item.local_status !== 'downloaded') : items;
  }

  function searchStatusClass(status) {
    if (status === 'downloaded') return 'good';
    if (status === 'running' || status === 'queued') return 'warn';
    if (status === 'failed' || status === 'cancelled') return 'bad';
    return 'neutral';
  }

  function searchCard(item) {
    const selected = state.search.selected.has(item.bvid);
    const downloaded = item.local_status === 'downloaded';
    const sourceUrl = item.url || `https://www.bilibili.com/video/${encodeURIComponent(item.bvid || '')}`;
    return `<article class="media-card enh-search-card" data-search-key="${esc(item.bvid)}">
      <div class="cover-wrap"><img data-cover-img src="${esc(coverUrl(item.cover))}" alt="${esc(item.title)}" loading="lazy" referrerpolicy="no-referrer"><label class="enh-card-select"><input type="checkbox" data-search-select="${esc(item.bvid)}" ${selected ? 'checked' : ''}> 选择</label><div class="cover-badges"><span></span><span class="badge ${searchStatusClass(item.local_status)}">${esc(item.local_status_label || '未下载')}</span></div>${item.duration ? `<span class="duration-chip">${esc(item.duration)}</span>` : ''}</div>
      <div class="media-body"><a class="media-title" href="${esc(sourceUrl)}" target="_blank" rel="noopener noreferrer">${esc(item.title || item.bvid)}</a><div class="media-meta"><span>${esc(item.author || '-')}</span><span>${formatPlay(item.play)} 播放</span><span>${formatDate(item.pubdate, true)}</span></div><div class="media-meta"><span>${esc(item.bvid)}</span>${item.local_group ? `<span>分组：${esc(item.local_group)}</span>` : ''}${item.local_quality ? `<span>${esc(item.local_quality)}</span>` : ''}</div>${tagChips(item.bvid, item.tags)}<div class="media-actions"><a class="btn small" href="${esc(sourceUrl)}" target="_blank" rel="noopener noreferrer">B站原页面</a><button type="button" class="btn small" data-search-preview="${esc(item.bvid)}">预览画质</button><button type="button" class="btn primary small" data-search-download="${esc(item.bvid)}">${downloaded ? '重新下载' : '下载'}</button></div></div>
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
    if (!search.data) {
      box.innerHTML = '<div class="empty">输入关键词开始搜索</div>';
      return;
    }
    const items = visibleSearchItems();
    const hiddenCount = (search.data.items || []).length - items.length;
    const pages = search.pages || Math.max(1, search.page);
    const summary = $('#enhSearchSummary');
    if (summary) summary.textContent = `第 ${search.page} / ${pages || '?'} 页 · 共 ${search.total || 0} 条${hiddenCount ? ` · 已隐藏 ${hiddenCount} 条已下载作品` : ''}`;
    const batch = $('#enhSearchDownloadSelected');
    if (batch) batch.textContent = `下载选中（${search.selected.size}）`;
    box.innerHTML = items.length
      ? `<div class="media-grid">${items.map(searchCard).join('')}</div>${paginationHtml(search.page, pages, 'search')}`
      : '<div class="empty">当前页没有符合过滤条件的作品</div>';

    $$('[data-search-select]', box).forEach(input => {
      input.onchange = () => {
        const item = (search.data.items || []).find(value => value.bvid === input.dataset.searchSelect);
        if (!item) return;
        if (input.checked) search.selected.set(item.bvid, item); else search.selected.delete(item.bvid);
        const button = $('#enhSearchDownloadSelected');
        if (button) button.textContent = `下载选中（${search.selected.size}）`;
      };
    });
    $$('[data-search-page]', box).forEach(button => { button.onclick = () => loadSearchPage(Number(button.dataset.searchPage)); });
    const jump = $('[data-search-jump]', box);
    const jumpButton = $('[data-search-jump-button]', box);
    if (jumpButton) jumpButton.onclick = () => loadSearchPage(Math.max(1, Math.min(pages, Number(jump.value || 1))));
    $$('[data-search-preview]', box).forEach(button => {
      button.onclick = () => previewSearchItem((search.data.items || []).find(item => item.bvid === button.dataset.searchPreview));
    });
    $$('[data-search-download]', box).forEach(button => {
      button.onclick = () => downloadSearchItems([(search.data.items || []).find(item => item.bvid === button.dataset.searchDownload)]);
    });
    bindTagButtons(box, key => (search.data.items || []).find(item => item.bvid === key), renderSearchResults);
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
    const downloaded = valid.filter(item => item.local_status === 'downloaded');
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
          force: downloaded.length > 0,
          group_id: destination === 'library' ? state.search.groupId : '',
          group: '', destination, min_height: Number(state.search.minHeight || 0),
        },
      });
      toast(`已处理 ${response.total || valid.length} 个任务`, 'good');
      state.search.selected.clear();
      location.hash = '#/tasks';
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
