(() => {
  'use strict';
  const E = window.BiliEnhancements;
  if (!E) return;
  const {
    VERSION, state, $, $$, esc, currentPage, formatBytes, formatDate,
    toast, api, register, isAdmin,
  } = E;
  const actionApi = () => E.taskActions;
  const TASK_STATUSES = new Set(['queued', 'running', 'success', 'skipped', 'failed', 'cancelled']);
  const TASK_SORTS = new Set(['created_at', 'finished_at', 'user', 'status', 'destination']);

  function ownerLabel(task) {
    return String(task.owner_label || task.owner?.display_name || task.owner?.username || task.owner_user_id || '未知用户');
  }

  function userOptions(selected = '') {
    return '<option value="">全部用户</option>' + state.tasks.users.map(user => {
      const label = `${user.display_name || user.username}（${user.username}）`;
      return `<option value="${esc(user.id)}" ${String(user.id) === String(selected) ? 'selected' : ''}>${esc(label)}</option>`;
    }).join('');
  }

  async function loadTaskUsers() {
    if (!isAdmin()) {
      state.tasks.users = [];
      state.tasks.ownerUserId = '';
      return;
    }
    try {
      const response = await api('/api/admin/users');
      state.tasks.users = response.data?.items || [];
    } catch (error) {
      state.tasks.users = [];
      toast(error.message, 'bad');
    }
  }

  function filterMarkup(admin) {
    const tasks = state.tasks;
    const adminFields = admin ? `<div class="enh-select-shell" data-icon="♙" title="按任务拥有者筛选"><select id="enhTaskOwner" class="select">${userOptions(tasks.ownerUserId)}</select></div>
      <div class="enh-select-shell" data-icon="⇩" title="按下载目标筛选"><select id="enhTaskDestination" class="select"><option value="">全部目标</option><option value="library">媒体库</option><option value="device">设备导出</option></select></div>` : '';
    const sortFields = admin ? `<div class="enh-select-shell" data-icon="↕" title="任务排序字段"><select id="enhTaskSort" class="select"><option value="created_at">创建时间</option><option value="finished_at">完成时间</option><option value="user">用户</option><option value="status">状态</option><option value="destination">目标</option></select></div>
      <div class="enh-select-shell" data-icon="⇅" title="任务排序方向"><select id="enhTaskDirection" class="select"><option value="desc">降序</option><option value="asc">升序</option></select></div>` : '';
    return `<div class="enh-task-filter-strip ${admin ? 'enh-task-filter-admin' : 'enh-task-filter-user'}">
      ${adminFields}
      <div class="enh-select-shell" data-icon="◉" title="按任务状态筛选"><select id="enhTaskStatus" class="select"><option value="">全部状态</option><option value="running">下载中</option><option value="queued">排队中</option><option value="success">已完成</option><option value="failed">失败</option><option value="cancelled">已取消</option><option value="skipped">已跳过</option></select></div>
      ${sortFields}
      <div class="enh-input-shell enh-task-query-shell" data-icon="⌕"><input id="enhTaskQuery" class="input" value="${esc(tasks.q)}" placeholder="搜索标题、BV、分组、错误或进度"></div>
      <button type="button" id="enhTaskResetFilters" class="icon-button enh-filter-reset" title="清除筛选" aria-label="清除筛选">×</button>
    </div>${admin ? `<label class="enh-task-group-toggle"><input type="checkbox" id="enhTaskGroupByUser" ${tasks.groupByUser ? 'checked' : ''}> 按用户分组显示</label>` : ''}`;
  }

  async function renderTasks(root) {
    const admin = isAdmin();
    await loadTaskUsers();
    root.innerHTML = `<div data-enhanced-view="tasks" data-task-role="${admin ? 'admin' : 'user'}" data-version="${VERSION}">
      <section class="card">
        <div class="card-head"><div><h2>${admin ? '任务中心' : '我的任务'}</h2><p>${admin ? '按用户、状态、目标和时间查看全部任务；所有操作仍由后端校验任务所有权。' : '这里只显示当前账号创建的设备导出任务。'}</p></div><span class="badge brand">实时任务</span></div>
        ${filterMarkup(admin)}
        <div class="enh-batch-layout" style="margin-top:14px"><span id="enhTaskSummary" class="metric-foot">正在读取任务…</span><div class="enh-batch-actions"><button type="button" id="enhTaskSelectVisible" class="btn small"><span aria-hidden="true">✓</span> 当前</button><button type="button" id="enhTaskSelectFailed" class="btn small"><span aria-hidden="true">!</span> 失败</button><button type="button" id="enhTaskClearSelection" class="btn small"><span aria-hidden="true">×</span> 清空</button><button type="button" data-enh-task-batch="retry" class="btn small"><span aria-hidden="true">↻</span> 重试</button><button type="button" id="enhTaskRetryAllFailed" class="btn small">全部重试失败</button><button type="button" data-enh-task-batch="pause" class="btn small"><span aria-hidden="true">Ⅱ</span> 暂停</button><button type="button" data-enh-task-batch="resume" class="btn small"><span aria-hidden="true">▶</span> 继续</button><button type="button" data-enh-task-batch="cancel" class="btn danger small"><span aria-hidden="true">■</span> 取消</button><button type="button" data-enh-task-batch="delete" class="btn danger small"><span aria-hidden="true">⌫</span> 删除</button><button type="button" id="enhTaskClearFailed" class="btn danger small">清理失败/取消</button></div></div>
      </section>
      <section id="enhTaskResults" style="margin-top:16px"><div class="loading-card">正在读取任务…</div></section>
    </div>`;
    bindFilters(admin);
    bindBatchActions();
    await loadTasks();
    ensureTaskEvents();
  }

  function bindFilters(admin) {
    const tasks = state.tasks;
    $('#enhTaskStatus').value = TASK_STATUSES.has(tasks.status) ? tasks.status : '';
    $('#enhTaskStatus').onchange = () => { tasks.status = $('#enhTaskStatus').value; loadTasks(); };
    $('#enhTaskQuery').onchange = () => { tasks.q = $('#enhTaskQuery').value.trim(); loadTasks(); };
    $('#enhTaskQuery').onkeydown = event => { if (event.key === 'Enter') { event.preventDefault(); tasks.q = event.currentTarget.value.trim(); loadTasks(); } };
    if (admin) {
      $('#enhTaskOwner').value = tasks.ownerUserId;
      $('#enhTaskDestination').value = tasks.destination;
      $('#enhTaskSort').value = TASK_SORTS.has(tasks.sort) ? tasks.sort : 'created_at';
      $('#enhTaskDirection').value = tasks.direction === 'asc' ? 'asc' : 'desc';
      $('#enhTaskOwner').onchange = () => { tasks.ownerUserId = $('#enhTaskOwner').value; loadTasks(); };
      $('#enhTaskDestination').onchange = () => { tasks.destination = $('#enhTaskDestination').value; loadTasks(); };
      $('#enhTaskSort').onchange = () => { tasks.sort = $('#enhTaskSort').value; loadTasks(); };
      $('#enhTaskDirection').onchange = () => { tasks.direction = $('#enhTaskDirection').value; loadTasks(); };
      $('#enhTaskGroupByUser').onchange = () => { tasks.groupByUser = $('#enhTaskGroupByUser').checked; loadTasks(); };
    }
    $('#enhTaskResetFilters').onclick = () => {
      Object.assign(tasks, { status: '', destination: '', q: '', ownerUserId: '', sort: 'created_at', direction: 'desc', groupByUser: false });
      renderTasks($('#pageRoot'));
    };
  }

  function bindBatchActions() {
    $('#enhTaskSelectVisible').onclick = () => { for (const task of filteredTasks()) state.tasks.selected.add(task.id); renderTaskResults(); };
    $('#enhTaskSelectFailed').onclick = () => { for (const task of state.tasks.data) if (['failed', 'cancelled'].includes(task.status)) state.tasks.selected.add(task.id); renderTaskResults(); };
    $('#enhTaskClearSelection').onclick = () => { state.tasks.selected.clear(); renderTaskResults(); };
    $$('[data-enh-task-batch]').forEach(button => { button.onclick = () => actionApi().batchTaskAction(button.dataset.enhTaskBatch); });
    $('#enhTaskRetryAllFailed').onclick = () => actionApi().retryAllFailedTasks();
    $('#enhTaskClearFailed').onclick = () => actionApi().clearFailedTasks();
  }

  function taskQueryParams() {
    const tasks = state.tasks;
    const params = new URLSearchParams();
    if (isAdmin() && tasks.ownerUserId) params.set('owner_user_id', tasks.ownerUserId);
    if (tasks.status) params.set('status', tasks.status);
    if (isAdmin() && tasks.destination) params.set('destination', tasks.destination);
    if (tasks.q) params.set('q', tasks.q);
    if (isAdmin()) {
      params.set('sort', TASK_SORTS.has(tasks.sort) ? tasks.sort : 'created_at');
      params.set('direction', tasks.direction === 'asc' ? 'asc' : 'desc');
      if (tasks.groupByUser) params.set('group_by_user', 'true');
    }
    return params.toString();
  }

  async function loadTasks() {
    try {
      const query = taskQueryParams();
      const response = await api(`/api/tasks${query ? `?${query}` : ''}`);
      state.tasks.data = response.data || [];
      state.tasks.summary = response.summary || {};
      state.tasks.grouped = response.grouped || [];
      renderTaskResults();
    } catch (error) {
      const box = $('#enhTaskResults');
      if (box) box.innerHTML = `<div class="notice bad">${esc(error.message)}</div>`;
      toast(error.message, 'bad');
    }
  }

  function ensureTaskEvents() {
    if (state.tasks.eventSource) return;
    const events = new EventSource('/api/events');
    state.tasks.eventSource = events;
    events.addEventListener('tasks', event => {
      try {
        const payload = JSON.parse(event.data);
        state.tasks.data = payload.tasks || [];
        state.tasks.summary = payload.summary || {};
        state.tasks.grouped = [];
        if (currentPage() === 'tasks' && $('[data-enhanced-view="tasks"]')) renderTaskResults();
      } catch (_) {}
    });
    events.onerror = () => {
      const summary = $('#enhTaskSummary');
      if (summary) summary.textContent = '实时连接正在重连…';
    };
  }

  function isPausedTask(task) {
    return task.status === 'cancelled' && String(task.error || task.progress_message || '').includes('已暂停');
  }

  function filteredTasks() {
    const filter = state.tasks;
    const query = String(filter.q || '').trim().toLowerCase();
    const items = filter.data.filter(task => {
      const effectiveStatus = isPausedTask(task) ? 'cancelled' : task.status;
      if (filter.status && effectiveStatus !== filter.status) return false;
      if (isAdmin() && filter.ownerUserId && String(task.owner_user_id || '') !== filter.ownerUserId) return false;
      if (isAdmin() && filter.destination && task.destination !== filter.destination) return false;
      if (query) {
        const text = [task.title, task.display_title, task.bvid, task.key, task.group, task.error, task.progress_message, ownerLabel(task)].join(' ').toLowerCase();
        if (!text.includes(query)) return false;
      }
      return true;
    });
    const direction = filter.direction === 'asc' ? 1 : -1;
    const sort = TASK_SORTS.has(filter.sort) ? filter.sort : 'created_at';
    return items.sort((a, b) => {
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

  function taskStatusLabel(task) {
    if (isPausedTask(task)) return '已暂停';
    return ({ queued: '排队中', running: '下载中', success: '已完成', skipped: '已跳过', failed: '失败', cancelled: '已取消' })[task.status] || task.status || '未知';
  }

  function taskStatusClass(task) {
    if (task.status === 'success') return 'good';
    if (isPausedTask(task) || task.status === 'queued' || task.status === 'running') return 'warn';
    if (task.status === 'failed' || task.status === 'cancelled') return 'bad';
    return 'neutral';
  }

  function taskCard(task) {
    const admin = isAdmin();
    const selected = state.tasks.selected.has(task.id);
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

  function groupedMarkup(tasks) {
    const groups = new Map();
    for (const task of tasks) {
      const key = String(task.owner_user_id || 'unknown');
      if (!groups.has(key)) groups.set(key, { label: ownerLabel(task), items: [] });
      groups.get(key).items.push(task);
    }
    return [...groups.values()].map(group => `<section class="enh-task-user-group"><div class="enh-task-user-group-head"><h3>${esc(group.label)}</h3><span class="badge neutral">${group.items.length} 个任务</span></div><div class="task-list">${group.items.map(taskCard).join('')}</div></section>`).join('');
  }

  function renderTaskResults() {
    const box = $('#enhTaskResults');
    if (!box) return;
    const tasks = filteredTasks();
    const validIds = new Set(state.tasks.data.map(task => task.id));
    for (const id of [...state.tasks.selected]) if (!validIds.has(id)) state.tasks.selected.delete(id);
    const summary = state.tasks.summary || {};
    const summaryNode = $('#enhTaskSummary');
    if (summaryNode) summaryNode.textContent = `共 ${summary.all ?? state.tasks.data.length} 个 · 排队 ${summary.queued || 0} · 下载 ${summary.running || 0} · 失败 ${summary.failed || 0} · 已选择 ${state.tasks.selected.size}`;
    box.innerHTML = tasks.length ? (isAdmin() && state.tasks.groupByUser ? groupedMarkup(tasks) : `<div class="task-list">${tasks.map(taskCard).join('')}</div>`) : '<div class="empty">没有符合条件的任务</div>';
    bindResultActions(box);
  }

  function bindResultActions(box) {
    $$('[data-task-select]', box).forEach(input => { input.onchange = () => { if (input.checked) state.tasks.selected.add(input.dataset.taskSelect); else state.tasks.selected.delete(input.dataset.taskSelect); renderTaskResults(); }; });
    $$('[data-task-log]', box).forEach(button => { button.onclick = () => actionApi().openTaskLog(button.dataset.taskLog); });
    $$('[data-task-action]', box).forEach(button => { button.onclick = () => actionApi().singleTaskAction(button.dataset.taskActionId, button.dataset.taskAction); });
    $$('[data-task-edit-retry]', box).forEach(button => { button.onclick = () => actionApi().openRetryEditor(button.dataset.taskEditRetry); });
    $$('[data-task-library]', box).forEach(button => { button.onclick = () => { state.library.q = button.dataset.taskLibrary || ''; state.library.page = 1; location.hash = '#/library'; }; });
    $$('[data-task-discard-export]', box).forEach(button => { button.onclick = async () => {
      if (!confirm('确定删除这个设备导出的临时文件吗？')) return;
      try { await api(`/api/exports/${encodeURIComponent(button.dataset.taskDiscardExport)}`, { method: 'DELETE' }); toast('临时文件已清理', 'good'); await loadTasks(); }
      catch (error) { toast(error.message, 'bad'); }
    }; });
  }

  E.taskPage = { loadTasks, renderTaskResults };
  register('tasks', renderTasks);
})();
