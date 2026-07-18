(() => {
  'use strict';
  const E = window.BiliEnhancements;
  if (!E) return;
  const { state, $, currentPage, api, ensureContext, toast, scheduleRender } = E;

  function stackDashboardSections() {
    if (currentPage() !== 'dashboard') return;
    const root = $('#pageRoot');
    if (!root) return;
    for (const child of [...root.children]) {
      if (child.classList?.contains('grid') && child.classList.contains('cols-2')) {
        child.classList.remove('cols-2');
        child.classList.add('enh-dashboard-stack');
      }
    }
  }

  async function submitDownloadForm(form) {
    const button = form.querySelector('button[type="submit"]');
    if (button?.disabled) return;
    if (button) button.disabled = true;
    try {
      await ensureContext();
      const lines = ($('#downloadTargets')?.value || '')
        .split(/\r?\n/)
        .map(value => value.trim())
        .filter(Boolean);
      if (!lines.length) {
        toast('请输入作品链接或编号', 'warn');
        return;
      }
      const bvids = lines.filter(value => /^BV[0-9A-Za-z]+$/i.test(value));
      const urls = lines.filter(value => !/^BV[0-9A-Za-z]+$/i.test(value));
      const destination = $('#downloadDestination')?.value || 'library';
      const result = await api('/api/download', {
        method: 'POST',
        body: {
          urls,
          bvids,
          items: [],
          force: Boolean($('#downloadForce')?.checked),
          group_id: destination === 'library' ? ($('#downloadGroup')?.value || '') : '',
          group: '',
          destination,
          min_height: Number($('#downloadQuality')?.value || 0),
        },
      });
      toast(`已创建 ${result.total || lines.length} 个任务，可继续浏览当前页面`, 'good');
      const target = $('#downloadTargets');
      if (target) target.value = '';
    } catch (error) {
      toast(error.message, 'bad');
    } finally {
      if (button) button.disabled = false;
    }
  }

  function searchItemsForButton(button) {
    const search = state.search;
    if (button.id === 'enhSearchDownloadSelected' || button.id === 'batchDownload') {
      return [...search.selected.values()];
    }
    const key = button.dataset.searchDownload || button.dataset.download || '';
    return (search.data?.items || []).filter(item => String(item.bvid || '') === String(key));
  }

  async function submitSearchDownloads(button) {
    if (button.disabled) return;
    const valid = searchItemsForButton(button).filter(Boolean);
    if (!valid.length) {
      toast('请先选择作品', 'warn');
      return;
    }
    const downloaded = valid.filter(item => item.local_status === 'downloaded');
    if (downloaded.length && !confirm(`选中的作品中有 ${downloaded.length} 个已经下载。继续会事务性重新下载并替换旧文件，是否继续？`)) return;
    button.disabled = true;
    try {
      await ensureContext();
      const destination = $('#enhSearchDestination')?.value || $('#downloadDestination')?.value || state.search.destination || 'library';
      const groupId = $('#enhSearchGroup')?.value || $('#searchGroup')?.value || state.search.groupId || '';
      const minHeight = Number($('#enhSearchQuality')?.value || $('#searchQuality')?.value || state.search.minHeight || 0);
      state.search.destination = destination;
      state.search.groupId = groupId;
      state.search.minHeight = minHeight;
      const response = await api('/api/download', {
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
            preferred_quality: item.preferred_quality || '',
          })),
          force: downloaded.length > 0,
          group_id: destination === 'library' ? groupId : '',
          group: '',
          destination,
          min_height: minHeight,
        },
      });
      for (const item of valid) {
        item.local_status = 'queued';
        item.local_status_label = '排队中';
      }
      state.search.selected.clear();
      toast(`已创建 ${response.total || valid.length} 个任务，仍停留在搜索页`, 'good');
      scheduleRender(10);
    } catch (error) {
      toast(error.message, 'bad');
    } finally {
      button.disabled = false;
    }
  }

  document.addEventListener('submit', event => {
    const form = event.target;
    if (!(form instanceof HTMLFormElement) || form.id !== 'downloadForm') return;
    event.preventDefault();
    event.stopImmediatePropagation();
    void submitDownloadForm(form);
  }, true);

  document.addEventListener('click', event => {
    if (currentPage() !== 'search') return;
    const button = event.target instanceof Element
      ? event.target.closest('#enhSearchDownloadSelected,[data-search-download],#batchDownload,[data-download]')
      : null;
    if (!(button instanceof HTMLButtonElement)) return;
    event.preventDefault();
    event.stopImmediatePropagation();
    void submitSearchDownloads(button);
  }, true);

  const start = () => {
    const root = $('#pageRoot');
    if (root) {
      const observer = new MutationObserver(() => requestAnimationFrame(stackDashboardSections));
      observer.observe(root, { childList: true, subtree: false });
    }
    window.addEventListener('hashchange', () => requestAnimationFrame(stackDashboardSections));
    stackDashboardSections();
  };
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start, { once: true });
  else start();
})();
