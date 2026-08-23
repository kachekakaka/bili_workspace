import { once } from '../core/lifecycle.mjs';
import { resourceKey } from '../core/resource-cache.mjs';
import { bindCoverFallback, formatBytes, mediaCard, metric } from './shared.mjs';

const SUMMARY_RESOURCE = resourceKey('library-summary');
const RECENT_RESOURCE = resourceKey('library', { page: 1, pageSize: 6, sort: 'recent' });

export async function mount(root, context) {
  const host = document.createElement('div');
  host.innerHTML = `<div id="dashboardStale" class="hidden"></div>
    <div id="dashboardMetrics" class="grid cols-4"></div>
    <div class="enh-dashboard-stack" data-dashboard-sections="stacked" style="margin-top:18px">
      <section class="card"><div class="card-head"><div><h2>最近观看与下载</h2><p>点击作品可进入作品库继续播放。</p></div><button type="button" class="btn small" data-go="library">查看全部</button></div><div id="dashboardRecent" class="media-grid"><div class="loading-card">正在读取最近作品…</div></div></section>
      <section class="card"><div class="card-head"><div><h2>运行状态</h2><p>原始文件优先直放；兼容副本只在需要时手动生成。</p></div></div><div id="dashboardRuntime" class="grid cols-2"></div></section>
    </div>`;
  context.commit(() => root.replaceChildren(host));

  let librarySummary = context.resources.peek(SUMMARY_RESOURCE)?.value || {};
  let recent = context.resources.peek(RECENT_RESOURCE)?.value || [];
  const sharedTaskSummary = context.shared.get().status?.task_summary || {};
  let taskSnapshot = context.taskStream.get('summary');
  if (!Object.keys(taskSnapshot.summary || {}).length) {
    taskSnapshot = { summary: sharedTaskSummary };
  }
  let loadError = null;

  const render = () => {
    if (!context.isCurrent()) return;
    const taskSummary = taskSnapshot?.summary || {};
    const active = taskSummary.active ?? (
      Number(taskSummary.queued || 0) + Number(taskSummary.running || 0)
    );
    host.querySelector('#dashboardMetrics').innerHTML = metric(
      '作品数量', Number(librarySummary.media_count || 0), '已进入私人媒体库',
    ) + metric(
      '媒体占用', formatBytes(librarySummary.total_size), '不包含临时导出与缓存',
    ) + metric(
      '活动任务', Number(active || 0),
      `排队 ${Number(taskSummary.queued || 0)} · 运行 ${Number(taskSummary.running || 0)}`,
    ) + metric('下载失败', Number(taskSummary.failed || 0), '可在任务中心查看日志并重试');

    const recentNode = host.querySelector('#dashboardRecent');
    recentNode.innerHTML = recent.length
      ? recent.map(mediaCard).join('')
      : '<div class="empty">作品库还是空的</div>';
    bindCoverFallback(recentNode, context.signal);

    const status = context.shared.get().status || {};
    host.querySelector('#dashboardRuntime').innerHTML = `<div class="notice"><strong>运行模式</strong><br>${status.server_mode ? 'QNAP / Docker 服务器' : 'Windows 本地'}</div><div class="notice"><strong>Bilibili</strong><br>${status.message || '未检测'}</div><div class="notice"><strong>媒体目录</strong><br>${status.download_dir || '-'}</div><div class="notice"><strong>临时导出</strong><br>完整传输后立即删除；中断保留至 TTL</div>`;

    const staleEntries = [
      context.resources.peek(SUMMARY_RESOURCE),
      context.resources.peek(RECENT_RESOURCE),
    ].filter(entry => entry?.stale);
    const stale = host.querySelector('#dashboardStale');
    if (loadError || staleEntries.length) {
      stale.className = `notice ${recent.length || librarySummary.media_count ? 'warn' : 'bad'}`;
      stale.innerHTML = `数据刷新失败，当前显示${recent.length || librarySummary.media_count ? '最近一次缓存' : '空状态'}。<button type="button" class="btn small" data-dashboard-retry>重试</button>`;
    } else {
      stale.className = 'hidden';
      stale.replaceChildren();
    }
  };

  const refresh = async () => {
    loadError = null;
    try {
      await Promise.all([
        context.resources.refresh(
          SUMMARY_RESOURCE,
          async ({ signal }) => (await context.api('/api/library/summary', { signal })).data || {},
          { signal: context.signal },
        ),
        context.resources.refresh(
          RECENT_RESOURCE,
          async ({ signal }) => (
            (await context.api('/api/library?page=1&page_size=6&sort=recent', { signal })).data?.items || []
          ),
          { signal: context.signal },
        ),
      ]);
    } catch (error) {
      if (error?.name !== 'AbortError') {
        loadError = error;
        render();
      }
    }
  };

  const unsubSummary = context.resources.subscribe(SUMMARY_RESOURCE, entry => {
    if (entry?.value) librarySummary = entry.value;
    render();
  }, { immediate: true });
  const unsubRecent = context.resources.subscribe(RECENT_RESOURCE, entry => {
    if (entry?.value) recent = entry.value;
    render();
  }, { immediate: true });
  const unsubTasks = context.taskStream.subscribe(snapshot => {
    taskSnapshot = Object.keys(snapshot.summary || {}).length
      ? snapshot
      : { summary: sharedTaskSummary };
    render();
  }, { immediate: true, mode: 'summary' });
  const releaseStream = context.taskStream.acquire('summary', { signal: context.signal });

  host.addEventListener('click', event => {
    if (event.target.closest('[data-go="library"]')) context.navigate('library');
    else if (event.target.closest('[data-dashboard-retry]')) void refresh();
  }, { signal: context.signal });
  render();
  void refresh();

  return Object.freeze({
    dispose: once(() => {
      unsubSummary();
      unsubRecent();
      unsubTasks();
      releaseStream();
    }),
  });
}
