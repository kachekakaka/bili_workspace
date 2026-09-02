import { esc, formatDate } from './shared.mjs';

export const CREATOR_IMPORT_ACTIVE_STATUSES = Object.freeze([
  'waiting', 'discovering', 'enqueuing', 'stopping',
]);

export function creatorImportStatusLabel(status) {
  return ({
    waiting: '等待中',
    discovering: '正在遍历投稿',
    enqueuing: '正在补充下载任务',
    stopping: '正在停止',
    completed: '已完成入队',
    partial: '部分完成',
    failed: '遍历失败',
    cancelled: '已取消',
  })[status] || status || '未知';
}

export function creatorImportStatusClass(status) {
  if (status === 'completed') return 'good';
  if (['waiting', 'discovering', 'enqueuing', 'stopping'].includes(status)) return 'warn';
  if (['partial', 'failed', 'cancelled'].includes(status)) return 'bad';
  return 'neutral';
}

export function creatorImportProgress(job) {
  const discovered = Math.max(0, Number(job?.discovered || 0));
  const processed = Math.max(0, Number(job?.processed || 0));
  if (job?.phase === 'enqueuing' && discovered > 0) {
    return Math.min(100, processed / discovered * 100);
  }
  const page = Math.max(0, Number(job?.current_page || 0));
  const pages = Math.max(0, Number(job?.total_pages || 0));
  if (pages > 0) return Math.min(100, page / pages * 100);
  return ['completed', 'partial'].includes(job?.status) ? 100 : 0;
}

export function creatorImportCard(job) {
  const percent = creatorImportProgress(job);
  const name = job.creator_name || `UID ${job.uid || '-'}`;
  const waiting = Number(job.wait_position || 0);
  const page = Number(job.current_page || 0);
  const pages = Number(job.total_pages || 0);
  const failures = (job.failures || []).slice(0, 5);
  const actions = [
    job.can_cancel ? `<button type="button" class="btn danger small" data-creator-import-action="cancel" data-creator-import-id="${esc(job.id)}">取消后续入队</button>` : '',
    job.can_resume ? `<button type="button" class="btn primary small" data-creator-import-action="resume" data-creator-import-id="${esc(job.id)}">从失败页继续</button>` : '',
    job.can_retry_failed ? `<button type="button" class="btn primary small" data-creator-import-action="retry-failed" data-creator-import-id="${esc(job.id)}">重试失败投稿</button>` : '',
  ].filter(Boolean).join('');
  const error = job.last_error
    ? `<div class="notice bad compact" style="margin-top:10px">${esc(job.last_error)}${job.failed_page ? `（第 ${Number(job.failed_page)} 页）` : ''}</div>`
    : '';
  const failureList = failures.length
    ? `<div class="metric-foot" style="margin-top:8px">失败投稿：${failures.map(item => `${esc(item.title || item.bvid)}：${esc(item.message)}`).join('；')}${Number(job.failed_count || 0) > failures.length ? '；另有更多' : ''}</div>`
    : '';
  return `<article class="notice creator-import-job" data-creator-import-job="${esc(job.id)}"><div class="card-head"><div><strong>${esc(name)}</strong><div class="media-meta"><span>UID ${esc(job.uid || '-')}</span><span>${esc(job.group_name || '默认分组')}</span><span>最低 ${Number(job.min_height || 0) ? `${Number(job.min_height)}P` : '不限制'}</span></div></div><span class="badge ${creatorImportStatusClass(job.status)}">${esc(creatorImportStatusLabel(job.status))}</span></div><div class="metric-foot">${waiting ? `等待位置 ${waiting} · ` : ''}${page ? `已读第 ${page}${pages ? ` / ${pages}` : ''} 页 · ` : ''}发现 ${Number(job.discovered || 0)} · 已处理 ${Number(job.processed || 0)} · 已入队 ${Number(job.queued || 0)}</div><div class="progress" style="margin-top:9px" title="全量入库作业进度"><span style="width:${percent.toFixed(1)}%"></span></div><div class="metric-foot" style="margin-top:8px">跳过：媒体库已有 ${Number(job.skipped_downloaded || 0)} · 活动任务 ${Number(job.skipped_active || 0)} · 删除历史 ${Number(job.skipped_deleted || 0)} · 单条失败 ${Number(job.failed_count || 0)}</div>${error}${failureList}<div class="media-meta" style="margin-top:8px"><span>创建：${esc(formatDate(job.created_at))}</span>${job.finished_at ? `<span>结束：${esc(formatDate(job.finished_at))}</span>` : ''}</div>${actions ? `<div class="toolbar" style="margin-top:10px">${actions}</div>` : ''}</article>`;
}

export function creatorImportListMarkup(jobs, { uid = '' } = {}) {
  const wanted = String(uid || '');
  const values = (Array.isArray(jobs) ? jobs : []).filter(job => !wanted || String(job.uid || '') === wanted);
  if (!values.length) {
    return `<div class="empty">${wanted ? '当前 UP 主在本次运行期还没有全量入库作业' : '本次运行期还没有全量入库作业'}</div>`;
  }
  return `<div class="creator-import-list">${values.map(creatorImportCard).join('')}</div>`;
}

export function creatorImportConfirmMessage({ creator, total, groupName, minHeight }) {
  const name = creator?.name || `UID ${creator?.uid || '-'}`;
  const quality = Number(minHeight || 0) ? `${Number(minHeight)}P` : '不限制';
  return `${name}（UID ${creator?.uid || '-'}）当前约有 ${Number(total || 0)} 条公开视频投稿。作业会以现在为截止点，固定按发布时间从新到旧遍历，忽略当前标题筛选和页面排序；目标为“${groupName || '默认分组'}”，最低清晰度为 ${quality}。媒体库已有、活动任务和删除历史会分别跳过。确认开始？`;
}

export function createCreatorImportPoller(context, onJobs, { interval = 2500 } = {}) {
  let timer = 0;
  let loading = false;
  let stopped = false;

  const schedule = () => {
    if (stopped || context.signal.aborted) return;
    if (timer) window.clearTimeout(timer);
    timer = window.setTimeout(() => void refresh({ quiet: true }), interval);
  };

  const refresh = async ({ quiet = false } = {}) => {
    if (loading || stopped || context.signal.aborted) return [];
    if (timer) window.clearTimeout(timer);
    timer = 0;
    loading = true;
    try {
      const response = await context.api('/api/bilibili/creator-imports', { signal: context.signal });
      const jobs = response.data?.items || [];
      onJobs(jobs);
      return jobs;
    } catch (error) {
      if (!quiet && error?.name !== 'AbortError') context.toast.show(error.message, 'bad');
      return [];
    } finally {
      loading = false;
      schedule();
    }
  };

  const stop = () => {
    stopped = true;
    if (timer) window.clearTimeout(timer);
  };
  context.signal.addEventListener('abort', stop, { once: true });
  return Object.freeze({ refresh, stop });
}

export async function runCreatorImportAction(context, jobId, action) {
  const allowed = new Set(['cancel', 'resume', 'retry-failed']);
  if (!allowed.has(action)) throw new Error('全量入库操作无效');
  return context.api(`/api/bilibili/creator-imports/${encodeURIComponent(jobId)}/${action}`, {
    method: 'POST',
    body: {},
    signal: context.signal,
  });
}
