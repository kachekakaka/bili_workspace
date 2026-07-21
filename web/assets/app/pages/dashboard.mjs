import { bindCoverFallback, formatBytes, mediaCard, metric } from './shared.mjs';
import { once } from '../core/lifecycle.mjs';

export async function mount(root, context) {
  const [summaryResponse, recentResponse] = await Promise.all([
    context.api('/api/library/summary', { signal: context.signal }),
    context.api('/api/library?page=1&page_size=6&sort=recent', { signal: context.signal }),
  ]);
  const summary = summaryResponse.data || {};
  const recent = recentResponse.data?.items || [];
  const host = document.createElement('div');
  const renderMetrics = snapshot => {
    const box = host.querySelector('#dashboardMetrics');
    if (!box) return;
    const taskSummary = snapshot?.summary || {};
    box.innerHTML = metric('作品数量', Number(summary.media_count || 0), '已进入私人媒体库')
      + metric('媒体占用', formatBytes(summary.total_size), '不包含临时导出与缓存')
      + metric('活动任务', Number(taskSummary.active || taskSummary.queued || 0) + Number(taskSummary.running || 0), `排队 ${Number(taskSummary.queued || 0)} · 运行 ${Number(taskSummary.running || 0)}`)
      + metric('下载失败', Number(taskSummary.failed || 0), '可在任务中心查看日志并重试');
  };
  host.innerHTML = `<div id="dashboardMetrics" class="grid cols-4"></div>
    <div class="enh-dashboard-stack" data-dashboard-sections="stacked" style="margin-top:18px">
      <section class="card"><div class="card-head"><div><h2>最近观看与下载</h2><p>点击作品可进入作品库继续播放。</p></div><button type="button" class="btn small" data-go="library">查看全部</button></div><div class="media-grid">${recent.length ? recent.map(mediaCard).join('') : '<div class="empty">作品库还是空的</div>'}</div></section>
      <section class="card"><div class="card-head"><div><h2>运行状态</h2><p>原始文件优先直放；兼容副本只在需要时手动生成。</p></div></div><div class="grid cols-2"><div class="notice"><strong>运行模式</strong><br>${context.shared.get().status?.server_mode ? 'QNAP / Docker 服务器' : 'Windows 本地'}</div><div class="notice"><strong>Bilibili</strong><br>${context.shared.get().status?.message || '未检测'}</div><div class="notice"><strong>媒体目录</strong><br>${context.shared.get().status?.download_dir || '-'}</div><div class="notice"><strong>临时导出</strong><br>完整传输后立即删除；中断保留至 TTL</div></div></section>
    </div>`;
  context.commit(() => root.replaceChildren(host));
  renderMetrics(context.taskStream.get());
  bindCoverFallback(host, context.signal);
  host.querySelector('[data-go="library"]')?.addEventListener('click', () => context.navigate('library'), { signal: context.signal });
  const unsubscribe = context.taskStream.subscribe(renderMetrics);
  return Object.freeze({ dispose: once(unsubscribe) });
}
