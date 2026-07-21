import { once } from '../core/lifecycle.mjs';
import {
  bindDialogCancel,
  esc,
  formatBytes,
  formatDate,
  modalActions,
  qualityOptions,
} from './shared.mjs';

const TASK_STATUSES = new Set(['queued', 'running', 'success', 'skipped', 'failed', 'cancelled']);
const TASK_SORTS = new Set(['created_at', 'finished_at', 'user', 'status', 'destination']);
const COMMON_QUALITY_LABELS = Object.freeze([
  '127', '126', '125', '120', '116', '112', '80', '74', '64', '32', '16',
]);
const viewState = {
  data: [],
  summary: {},
  users: [],
  selected: new Set(),
  ownerUserId: '',
  status: '',
  destination: '',
  q: '',
  sort: 'created_at',
  direction: 'desc',
  groupByUser: false,
  connection: 'idle',
};

function ownerLabel(task) {
  return String(task.owner_label || task.owner?.display_name || task.owner?.username || task.owner_user_id || '未知用户');
}

function userOptions(selected = '') {
  return '<option value="">全部用户</option>' + viewState.users.map(user => {
    const label = `${user.display_name || user.username}（${user.username}）`;
    return `<option value="${esc(user.id)}" ${String(user.id) === String(selected) ? 'selected' : ''}>${esc(label)}</option>`;
  }).join('');
}

function isPausedTask(task) {
  return task.status === 'cancelled' && String(task.error || task.progress_message || '').includes('已暂停');
}

function taskStatusLabel(task) {
  if (isPausedTask(task)) return '已暂停';
  return ({
    queued: '排队中', running: '下载中', success: '已完成', skipped: '已跳过',
    failed: '失败', cancelled: '已取消',
  })[task.status] || task.status || '未知';
}

function taskStatusClass(task) {
  if (task.status === 'success') return 'good';
  if (isPausedTask(task) || task.status === 'queued' || task.status === 'running') return 'warn';
  if (task.status === 'failed' || task.status === 'cancelled') return 'bad';
  return 'neutral';
}

export function filterAndSortTasks(items, filters, admin) {
  const query = String(filters.q || '').trim().toLowerCase();
  const result = (Array.isArray(items) ? items : []).filter(task => {
    const effectiveStatus = isPausedTask(task) ? 'cancelled' : task.status;
    if (filters.status && effectiveStatus !== filters.status) return false;
    if (admin && filters.ownerUserId && String(task.owner_user_id || '') !== String(filters.ownerUserId)) return false;
    if (admin && filters.destination && task.destination !== filters.destination) return false;
    if (query) {
      const text = [
        task.title, task.display_title, task.bvid, task.key, task.group,
        task.error, task.progress_message, ownerLabel(task),
      ].join(' ').toLowerCase();
      if (!text.includes(query)) return false;
    }
    return true;
  });
  const direction = filters.direction === 'asc' ? 1 : -1;
  const sort = TASK_SORTS.has(filters.sort) ? filters.sort : 'created_at';
  return result.sort((a, b) => {
    const values = {
      created_at: [Number(a.created_at || 0), Number(b.created_at || 0)],
      finished_at: [Number(a.finished_at || 0), Number(b.finished_at || 0)],
      user: [ownerLabel(a).toLowerCase(), ownerLabel(b).toLowerCase()],
      status: [String(a.status || ''), String(b.status || '')],
      destination: [String(a.destination || ''), String(b.destination || '')],
    }[sort];
    return (values[0] < values[1] ? -1 : values[0] > values[1] ? 1 : 0) * direction;
  });
}

function filterMarkup(admin) {
  const adminFields = admin ? `<div class="enh-select-shell" data-icon="♙" title="按任务拥有者筛选"><select id="enhTaskOwner" class="select">${userOptions(viewState.ownerUserId)}</select></div>
    <div class="enh-select-shell" data-icon="⇩" title="按下载目标筛选"><select id="enhTaskDestination" class="select"><option value="">全部目标</option><option value="library">媒体库</option><option value="device">设备导出</option></select></div>` : '';
  const sortFields = admin ? `<div class="enh-select-shell" data-icon="↕" title="任务排序字段"><select id="enhTaskSort" class="select"><option value="created_at">创建时间</option><option value="finished_at">完成时间</option><option value="user">用户</option><option value="status">状态</option><option value="destination">目标</option></select></div>
    <div class="enh-select-shell" data-icon="⇅" title="任务排序方向"><select id="enhTaskDirection" class="select"><option value="desc">降序</option><option value="asc">升序</option></select></div>` : '';
  return `<div class="enh-task-filter-strip ${admin ? 'enh-task-filter-admin' : 'enh-task-filter-user'}">
    ${adminFields}
    <div class="enh-select-shell" data-icon="◉" title="按任务状态筛选"><select id="enhTaskStatus" class="select"><option value="">全部状态</option><option value="running">下载中</option><option value="queued">排队中</option><option value="success">已完成</option><option value="failed">失败</option><option value="cancelled">已取消</option><option value="skipped">已跳过</option></select></div>
    ${sortFields}
    <div class="enh-input-shell enh-task-query-shell" data-icon="⌕"><input id="enhTaskQuery" class="input" value="${esc(viewState.q)}" placeholder="搜索标题、BV、分组、错误或进度"></div>
    <button type="button" id="enhTaskResetFilters" class="icon-button enh-filter-reset" title="清除筛选" aria-label="清除筛选">×</button>
  </div>${admin ? `<label class="enh-task-group-toggle"><input type="checkbox" id="enhTaskGroupByUser" ${viewState.groupByUser ? 'checked' : ''}> 按用户分组显示</label>` : ''}`;
}

function taskCard(task, admin) {
  const selected = viewState.selected.has(task.id);
  const active = ['queued', 'running'].includes(task.status);
  const paused = isPausedTask(task);
  const terminal = ['success', 'skipped', 'failed', 'cancelled'].includes(task.status);
  const percent = task.progress_percent == null ? null : Math.max(0, Math.min(100, Number(task.progress_percent)));
  const size = task.downloaded_bytes != null ? `${formatBytes(task.downloaded_bytes)}${task.total_bytes ? ` / ${formatBytes(task.total_bytes)}` : ''}` : '';
  const part = task.part_total ? `分 P ${task.current_part || '?'} / ${task.part_total}` : '';
  const quality = [task.selected_quality, task.selected_resolution, task.selected_codec, task.selected_fps].filter(Boolean).join(' · ');
  const exportReady = task.destination === 'device' && task.status === 'success' && task.export_state !== 'downloaded';
  const owner = admin ? `<div class="enh-task-owner">用户：${esc(ownerLabel(task))}</div>` : '';
  return `<article class="task-card" data-task-id="${esc(task.id)}" data-owner-user-id="${esc(task.owner_user_id || '')}"><div class="task-main"><div class="toolbar"><label class="enh-task-selector"><input type="checkbox" data-task-select="${esc(task.id)}" ${selected ? 'checked' : ''}> 选择</label><span class="badge ${taskStatusClass(task)}">${esc(taskStatusLabel(task))}</span><span class="badge ${task.destination === 'device' ? 'warn' : 'brand'}">${esc(task.destination_label || (task.destination === 'device' ? '设备导出' : '媒体库'))}</span>${task.selected_quality ? `<span class="badge neutral">${esc(task.selected_quality)}</span>` : ''}</div>${owner}<div class="task-title" style="margin-top:9px">${esc(task.display_title || task.title || task.bvid || task.key)}</div><div class="task-sub"><span>${esc(task.bvid || task.key)}</span>${task.destination === 'library' ? `<span>分组：${esc(task.group || '未分组')}</span>` : ''}<span>最低：${esc(task.min_height_label || task.min_height || '不限制')}</span><span>${task.preferred_quality ? `指定：${esc(task.preferred_quality)}` : '自动最高'}</span>${task.duration ? `<span>时长：${esc(task.duration)}</span>` : ''}${part ? `<span>${esc(part)}</span>` : ''}<span>${esc(task.phase_label || '')}</span>${task.created_at ? `<span>创建：${esc(formatDate(task.created_at))}</span>` : ''}</div><div class="enh-task-meta">${size ? `<span>当前大小 <strong>${esc(size)}</strong></span>` : ''}${task.speed_text ? `<span>速度 <strong>${esc(task.speed_text)}</strong></span>` : ''}${task.eta_text ? `<span>剩余 <strong>${esc(task.eta_text)}</strong></span>` : ''}${percent != null ? `<span>进度 <strong>${percent.toFixed(percent >= 10 ? 0 : 1)}%</strong></span>` : ''}${task.queue_position ? `<span>队列位置 <strong>${task.queue_position}</strong></span>` : ''}${task.elapsed_sec ? `<span>耗时 <strong>${Math.round(task.elapsed_sec)} 秒</strong></span>` : ''}</div>${quality ? `<div class="metric-foot" style="margin-top:7px">实际：${esc(quality)}</div>` : ''}${active ? `<div class="progress ${percent == null ? 'indeterminate' : ''}" title="${esc(task.progress_message || task.phase_label || '')}"><span style="width:${percent == null ? 38 : percent}%"></span></div>` : ''}${paused && size ? `<div class="progress"><span style="width:${percent == null ? 0 : percent}%"></span></div>` : ''}${task.progress_message && active ? `<div class="metric-foot enh-progress-message">${esc(task.progress_message)}</div>` : ''}${task.error && ['failed', 'cancelled'].includes(task.status) ? `<div class="notice ${paused ? 'warn' : 'bad'}" style="margin-top:10px">${esc(task.error)}</div>` : ''}</div><div class="task-side"><button type="button" class="btn small" data-task-log="${esc(task.id)}">日志</button>${active ? `<button type="button" class="btn small" data-task-action="pause" data-task-action-id="${esc(task.id)}">暂停</button><button type="button" class="btn danger small" data-task-action="cancel" data-task-action-id="${esc(task.id)}">取消</button>` : ''}${paused ? `<button type="button" class="btn primary small" data-task-action="resume" data-task-action-id="${esc(task.id)}">继续</button><button type="button" class="btn small" data-task-edit-retry="${esc(task.id)}">编辑后重试</button>` : ''}${task.status === 'failed' || (task.status === 'cancelled' && !paused) ? `<button type="button" class="btn primary small" data-task-action="retry" data-task-action-id="${esc(task.id)}">重试</button><button type="button" class="btn small" data-task-edit-retry="${esc(task.id)}">编辑画质</button>` : ''}${terminal && !active ? `<button type="button" class="btn danger small" data-task-action="delete" data-task-action-id="${esc(task.id)}">删除记录</button>` : ''}${admin && task.destination === 'library' && task.status === 'success' ? `<button type="button" class="btn small" data-task-library="${esc(task.bvid || task.key)}">作品库</button>` : ''}${exportReady ? `<a class="btn primary small" href="/api/exports/${encodeURIComponent(task.id)}/download">下载到设备</a><button type="button" class="btn danger small" data-task-discard-export="${esc(task.id)}">删除临时文件</button>` : ''}</div></article>`;
}

function groupedMarkup(tasks, admin) {
  const groups = new Map();
  for (const task of tasks) {
    const key = String(task.owner_user_id || 'unknown');
    if (!groups.has(key)) groups.set(key, { label: ownerLabel(task), items: [] });
    groups.get(key).items.push(task);
  }
  return [...groups.values()].map(group => `<section class="enh-task-user-group"><div class="enh-task-user-group-head"><h3>${esc(group.label)}</h3><span class="badge neutral">${group.items.length} 个任务</span></div><div class="task-list">${group.items.map(task => taskCard(task, admin)).join('')}</div></section>`).join('');
}

function queryString(admin) {
  const params = new URLSearchParams();
  if (admin && viewState.ownerUserId) params.set('owner_user_id', viewState.ownerUserId);
  if (viewState.status) params.set('status', viewState.status);
  if (admin && viewState.destination) params.set('destination', viewState.destination);
  if (viewState.q) params.set('q', viewState.q);
  if (admin) {
    params.set('sort', TASK_SORTS.has(viewState.sort) ? viewState.sort : 'created_at');
    params.set('direction', viewState.direction === 'asc' ? 'asc' : 'desc');
    if (viewState.groupByUser) params.set('group_by_user', 'true');
  }
  return params.toString();
}

export async function mount(root, context) {
  const admin = context.session.isAdmin();
  const host = document.createElement('div');
  host.innerHTML = `<div data-enhanced-view="tasks" data-task-role="${admin ? 'admin' : 'user'}">
    <section class="card"><div class="card-head"><div><h2>${admin ? '任务中心' : '我的任务'}</h2><p>${admin ? '按用户、状态、目标和时间查看全部任务；所有操作仍由后端校验任务所有权。' : '这里只显示当前账号创建的设备导出任务。'}</p></div><span class="badge brand">实时任务</span></div><div id="enhTaskFilters"><div class="loading-card">正在读取筛选项…</div></div><div class="enh-batch-layout" style="margin-top:14px"><span id="enhTaskSummary" class="metric-foot">正在读取任务…</span><div class="enh-batch-actions"><button type="button" id="enhTaskSelectVisible" class="btn small"><span aria-hidden="true">✓</span> 当前</button><button type="button" id="enhTaskSelectFailed" class="btn small"><span aria-hidden="true">!</span> 失败</button><button type="button" id="enhTaskClearSelection" class="btn small"><span aria-hidden="true">×</span> 清空</button><button type="button" data-enh-task-batch="retry" class="btn small"><span aria-hidden="true">↻</span> 重试</button><button type="button" id="enhTaskRetryAllFailed" class="btn small">全部重试失败</button><button type="button" data-enh-task-batch="pause" class="btn small"><span aria-hidden="true">Ⅱ</span> 暂停</button><button type="button" data-enh-task-batch="resume" class="btn small"><span aria-hidden="true">▶</span> 继续</button><button type="button" data-enh-task-batch="cancel" class="btn danger small"><span aria-hidden="true">■</span> 取消</button><button type="button" data-enh-task-batch="delete" class="btn danger small"><span aria-hidden="true">⌫</span> 删除</button><button type="button" id="enhTaskClearFailed" class="btn danger small">清理失败/取消</button></div></div></section>
    <section id="enhTaskResults" style="margin-top:16px"><div class="loading-card">正在读取任务…</div></section>
  </div>`;
  context.commit(() => root.replaceChildren(host));
  context.taskStream.start();

  const results = host.querySelector('#enhTaskResults');
  const summaryNode = host.querySelector('#enhTaskSummary');
  const visibleTasks = () => filterAndSortTasks(viewState.data, viewState, admin);
  const renderResults = () => {
    if (!context.isCurrent()) return;
    const tasks = visibleTasks();
    const validIds = new Set(viewState.data.map(task => task.id));
    for (const id of [...viewState.selected]) if (!validIds.has(id)) viewState.selected.delete(id);
    const summary = viewState.summary || {};
    const connectionNote = ['reconnecting', 'error'].includes(viewState.connection) ? ' · 实时连接正在重连' : '';
    summaryNode.textContent = `共 ${summary.all ?? viewState.data.length} 个 · 排队 ${summary.queued || 0} · 下载 ${summary.running || 0} · 失败 ${summary.failed || 0} · 已选择 ${viewState.selected.size}${connectionNote}`;
    results.innerHTML = tasks.length ? (admin && viewState.groupByUser ? groupedMarkup(tasks, admin) : `<div class="task-list">${tasks.map(task => taskCard(task, admin)).join('')}</div>`) : '<div class="empty">没有符合条件的任务</div>';
  };

  const reload = async () => {
    const query = queryString(admin);
    const response = await context.api(`/api/tasks${query ? `?${query}` : ''}`, { signal: context.signal });
    viewState.data = response.data || [];
    viewState.summary = response.summary || {};
    renderResults();
  };

  if (admin) {
    const usersResponse = await context.api('/api/admin/users', { signal: context.signal });
    viewState.users = usersResponse.data?.items || [];
  } else {
    viewState.users = [];
    viewState.ownerUserId = '';
    viewState.destination = '';
    viewState.groupByUser = false;
  }
  host.querySelector('#enhTaskFilters').innerHTML = filterMarkup(admin);
  host.querySelector('#enhTaskStatus').value = TASK_STATUSES.has(viewState.status) ? viewState.status : '';
  if (admin) {
    host.querySelector('#enhTaskOwner').value = viewState.ownerUserId;
    host.querySelector('#enhTaskDestination').value = viewState.destination;
    host.querySelector('#enhTaskSort').value = TASK_SORTS.has(viewState.sort) ? viewState.sort : 'created_at';
    host.querySelector('#enhTaskDirection').value = viewState.direction === 'asc' ? 'asc' : 'desc';
  }

  const updateFilter = async (key, value) => {
    viewState[key] = value;
    await reload();
  };
  host.querySelector('#enhTaskStatus').addEventListener('change', event => void updateFilter('status', event.currentTarget.value), { signal: context.signal });
  host.querySelector('#enhTaskQuery').addEventListener('change', event => void updateFilter('q', event.currentTarget.value.trim()), { signal: context.signal });
  host.querySelector('#enhTaskQuery').addEventListener('keydown', event => {
    if (event.key !== 'Enter') return;
    event.preventDefault();
    void updateFilter('q', event.currentTarget.value.trim());
  }, { signal: context.signal });
  if (admin) {
    host.querySelector('#enhTaskOwner').addEventListener('change', event => void updateFilter('ownerUserId', event.currentTarget.value), { signal: context.signal });
    host.querySelector('#enhTaskDestination').addEventListener('change', event => void updateFilter('destination', event.currentTarget.value), { signal: context.signal });
    host.querySelector('#enhTaskSort').addEventListener('change', event => void updateFilter('sort', event.currentTarget.value), { signal: context.signal });
    host.querySelector('#enhTaskDirection').addEventListener('change', event => void updateFilter('direction', event.currentTarget.value), { signal: context.signal });
    host.querySelector('#enhTaskGroupByUser').addEventListener('change', event => {
      viewState.groupByUser = event.currentTarget.checked;
      renderResults();
    }, { signal: context.signal });
  }
  host.querySelector('#enhTaskResetFilters').addEventListener('click', () => {
    Object.assign(viewState, { status: '', destination: '', q: '', ownerUserId: '', sort: 'created_at', direction: 'desc', groupByUser: false });
    void context.remount();
  }, { signal: context.signal });

  const singleTaskAction = async (taskId, action, body = {}) => {
    try {
      await context.api(`/api/enhancements/tasks/${encodeURIComponent(taskId)}/${encodeURIComponent(action)}`, {
        method: 'POST', body: { force: false, min_height: null, preferred_quality: null, ...body },
      });
      context.toast.show(({ retry: '任务已原地重试', pause: '已提交暂停', resume: '任务已继续', cancel: '已提交取消', delete: '任务记录已删除' })[action] || '操作完成', 'good');
      if (action === 'delete') viewState.selected.delete(taskId);
      await reload();
    } catch (error) {
      context.toast.show(error.message, 'bad');
    }
  };

  const batchTaskAction = async (action, ids = [...viewState.selected]) => {
    const unique = [...new Set(ids)].filter(Boolean);
    if (!unique.length) {
      context.toast.show('请先勾选任务', 'warn');
      return;
    }
    if (['delete', 'cancel'].includes(action)) {
      const accepted = await context.confirm({
        title: action === 'delete' ? '删除任务记录' : '取消任务',
        message: `确定对选中的 ${unique.length} 个任务执行“${action === 'delete' ? '删除记录' : '取消'}”吗？`,
        confirmLabel: action === 'delete' ? '删除' : '取消任务',
        danger: true,
      });
      if (!accepted) return;
    }
    try {
      const response = await context.api('/api/enhancements/tasks/batch', {
        method: 'POST', body: { task_ids: unique, action, force: false, min_height: null, preferred_quality: null },
      });
      const done = response.data?.items?.length || 0;
      const errors = Object.keys(response.data?.errors || {}).length;
      if (action === 'delete') for (const id of unique) viewState.selected.delete(id);
      context.toast.show(`已处理 ${done} 个任务${errors ? `，${errors} 个失败` : ''}`, errors ? 'warn' : 'good');
      await reload();
    } catch (error) {
      context.toast.show(error.message, 'bad');
    }
  };

  const openTaskLog = async taskId => {
    const modal = context.modal.open({ title: '任务日志', body: '<div class="loading-card">正在读取日志…</div>' });
    try {
      const response = await context.api(`/api/tasks/${encodeURIComponent(taskId)}/log?tail=250000`);
      modal.body.innerHTML = `<div class="toolbar" style="margin-bottom:10px"><a class="btn small" href="/api/tasks/${encodeURIComponent(taskId)}/log/download">下载完整日志</a><button type="button" id="enhCopyTaskLog" class="btn small">复制</button></div><pre class="log-box">${esc(response.data?.text || '暂无日志')}</pre>`;
      modal.body.querySelector('#enhCopyTaskLog').addEventListener('click', async () => {
        try {
          await navigator.clipboard.writeText(response.data?.text || '');
          context.toast.show('日志已复制', 'good');
        } catch {
          context.toast.show('浏览器不允许复制', 'bad');
        }
      });
    } catch (error) {
      modal.body.innerHTML = `<div class="notice bad">${esc(error.message)}</div>`;
    }
  };

  const openRetryEditor = async taskId => {
    const modal = context.modal.open({ title: '编辑画质并重试', narrow: true, body: '<div class="loading-card">正在读取任务…</div>' });
    try {
      const response = await context.api(`/api/tasks/${encodeURIComponent(taskId)}`);
      const task = response.data || {};
      modal.body.innerHTML = `<form id="enhRetryForm" class="form-grid"><div class="notice full"><strong>${esc(task.display_title || task.title || task.bvid || task.key)}</strong><br>${esc(task.bvid || task.key)} · 当前最低 ${esc(task.min_height_label || task.min_height || '不限制')}</div><div class="field full"><label>最低清晰度</label><select id="enhRetryHeight" class="select">${qualityOptions(task.min_height || 0)}</select></div><div class="field full"><label>指定画质档位</label><select id="enhRetryPreferred" class="select"><option value="">自动最高</option>${COMMON_QUALITY_LABELS.map(label => `<option value="${esc(label)}" ${task.preferred_quality === label ? 'selected' : ''}>${esc(label)}</option>`).join('')}</select><small>可先读取该作品实际可用的共同画质，再选择严格档位。</small></div><div class="field full"><button type="button" id="enhRetryLoadQuality" class="btn">读取实际可用画质</button></div><div class="field full">${modalActions('保存并使用原任务 ID 重试')}</div></form>`;
      bindDialogCancel(modal);
      modal.body.querySelector('#enhRetryLoadQuality').addEventListener('click', async event => {
        const button = event.currentTarget;
        button.disabled = true;
        button.textContent = '正在读取…';
        try {
          const preview = await context.api('/api/preview', {
            method: 'POST',
            body: {
              item: {
                bvid: task.bvid, url: task.url, title: task.title, cover: task.cover,
                author: task.author, pubdate: task.pubdate, duration: task.duration,
                play: task.play, preferred_quality: '',
              },
              min_height: Number(modal.body.querySelector('#enhRetryHeight').value || 0),
              preferred_quality: '',
            },
          });
          const parts = preview.data?.quality?.parts || [];
          let common = null;
          for (const part of parts) {
            const available = new Set((part.available || []).map(track => track.dfn).filter(Boolean));
            common = common === null ? available : new Set([...common].filter(value => available.has(value)));
          }
          const choices = [...(common || [])];
          const select = modal.body.querySelector('#enhRetryPreferred');
          const current = select.value;
          select.innerHTML = `<option value="">自动最高</option>${choices.map(label => `<option value="${esc(label)}">${esc(label)}</option>`).join('')}`;
          if (choices.includes(current)) select.value = current;
          context.toast.show(`读取到 ${choices.length} 个所有分 P 共同可用档位`, 'good');
        } catch (error) {
          context.toast.show(error.message, 'bad');
        } finally {
          button.disabled = false;
          button.textContent = '重新读取实际可用画质';
        }
      });
      modal.body.querySelector('#enhRetryForm').addEventListener('submit', async event => {
        event.preventDefault();
        const submit = event.currentTarget.querySelector('button[type="submit"]');
        submit.disabled = true;
        try {
          await context.api(`/api/enhancements/tasks/${encodeURIComponent(taskId)}/retry`, {
            method: 'POST',
            body: {
              force: false,
              min_height: Number(modal.body.querySelector('#enhRetryHeight').value || 0),
              preferred_quality: modal.body.querySelector('#enhRetryPreferred').value,
            },
          });
          modal.close('retried');
          context.toast.show('画质已更新，任务已使用原 ID 重新排队', 'good');
          await reload();
        } catch (error) {
          context.toast.show(error.message, 'bad');
        } finally {
          submit.disabled = false;
        }
      });
    } catch (error) {
      modal.body.innerHTML = `<div class="notice bad">${esc(error.message)}</div>`;
    }
  };

  host.addEventListener('change', event => {
    const input = event.target.closest('[data-task-select]');
    if (!input) return;
    if (input.checked) viewState.selected.add(input.dataset.taskSelect);
    else viewState.selected.delete(input.dataset.taskSelect);
    renderResults();
  }, { signal: context.signal });

  host.addEventListener('click', async event => {
    const button = event.target.closest('button');
    if (!button) return;
    if (button.id === 'enhTaskSelectVisible') {
      for (const task of visibleTasks()) viewState.selected.add(task.id);
      renderResults();
    } else if (button.id === 'enhTaskSelectFailed') {
      for (const task of viewState.data) if (['failed', 'cancelled'].includes(task.status)) viewState.selected.add(task.id);
      renderResults();
    } else if (button.id === 'enhTaskClearSelection') {
      viewState.selected.clear();
      renderResults();
    } else if (button.dataset.enhTaskBatch) {
      await batchTaskAction(button.dataset.enhTaskBatch);
    } else if (button.id === 'enhTaskRetryAllFailed') {
      const ids = viewState.data.filter(task => task.status === 'failed').map(task => task.id);
      if (!ids.length) context.toast.show('当前没有失败任务', 'warn');
      else if (await context.confirm({ title: '重试全部失败任务', message: `确定原地重试全部 ${ids.length} 个失败任务吗？`, confirmLabel: '全部重试' })) await batchTaskAction('retry', ids);
    } else if (button.id === 'enhTaskClearFailed') {
      const accepted = await context.confirm({ title: '清理任务记录', message: '确定清理所有失败和已取消任务记录吗？媒体库中的已完成文件不会删除。', confirmLabel: '清理', danger: true });
      if (!accepted) return;
      try {
        const response = await context.api('/api/enhancements/tasks/clear', { method: 'POST', body: { statuses: ['failed', 'cancelled'], destination: 'all' } });
        viewState.selected.clear();
        context.toast.show(`已清理 ${response.data?.removed || 0} 个任务记录`, 'good');
        await reload();
      } catch (error) {
        context.toast.show(error.message, 'bad');
      }
    } else if (button.dataset.taskLog) {
      await openTaskLog(button.dataset.taskLog);
    } else if (button.dataset.taskAction) {
      await singleTaskAction(button.dataset.taskActionId, button.dataset.taskAction);
    } else if (button.dataset.taskEditRetry) {
      await openRetryEditor(button.dataset.taskEditRetry);
    } else if (button.dataset.taskLibrary !== undefined) {
      try {
        sessionStorage.setItem('bili-v070-library-query', button.dataset.taskLibrary || '');
      } catch {}
      context.navigate('library');
    } else if (button.dataset.taskDiscardExport) {
      const accepted = await context.confirm({ title: '删除临时文件', message: '确定删除这个设备导出的临时文件吗？', confirmLabel: '删除', danger: true });
      if (!accepted) return;
      try {
        await context.api(`/api/exports/${encodeURIComponent(button.dataset.taskDiscardExport)}`, { method: 'DELETE' });
        context.toast.show('临时文件已清理', 'good');
        await reload();
      } catch (error) {
        context.toast.show(error.message, 'bad');
      }
    }
  }, { signal: context.signal });

  const unsubscribeTasks = context.taskStream.subscribe(snapshot => {
    viewState.data = [...(snapshot.tasks || [])];
    viewState.summary = { ...(snapshot.summary || {}) };
    renderResults();
  });
  const unsubscribeConnection = context.taskStream.subscribeConnection(connection => {
    viewState.connection = connection;
    renderResults();
  }, { immediate: true });

  await reload();
  return Object.freeze({
    dispose: once(() => {
      unsubscribeTasks();
      unsubscribeConnection();
    }),
  });
}
