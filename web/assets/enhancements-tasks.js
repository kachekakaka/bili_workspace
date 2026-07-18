(() => {
  'use strict';
  const E = window.BiliEnhancements;
  if (!E) return;
  const { VERSION, state, $, $$, esc, currentPage, formatBytes, toast, api, register } = E;
  const actionApi = () => E.taskActions;

  async function renderTasks(root) {
    const tasks = state.tasks;
    root.innerHTML = `<div data-enhanced-view="tasks" data-version="${VERSION}">
      <section class="card"><div class="card-head"><div><h2>任务中心</h2><p>通过服务端事件实时更新进度；仅在 BBDown 输出可用数据时显示百分比、大小、速度与剩余时间。</p></div><span class="badge brand">实时任务</span></div><div class="toolbar"><select id="enhTaskStatus" class="select enh-inline-select"><option value="">全部状态</option><option value="running">下载中</option><option value="queued">排队中</option><option value="paused">已暂停</option><option value="success">已完成</option><option value="failed">失败</option><option value="cancelled">已取消</option></select><select id="enhTaskDestination" class="select enh-inline-select"><option value="">全部目标</option><option value="library">媒体库</option><option value="device">设备导出</option></select><input id="enhTaskQuery" class="input" style="width:min(320px,100%)" value="${esc(tasks.q)}" placeholder="标题 / BV / 分组 / 错误"></div><div class="enh-batch-bar" style="margin-top:14px"><span id="enhTaskSummary" class="metric-foot">正在读取任务…</span><span class="enh-spacer"></span><button type="button" id="enhTaskSelectVisible" class="btn small">全选当前列表</button><button type="button" id="enhTaskSelectFailed" class="btn small">选择失败/取消</button><button type="button" id="enhTaskClearSelection" class="btn small">清空选择</button><button type="button" data-enh-task-batch="retry" class="btn small">批量重试</button><button type="button" id="enhTaskRetryAllFailed" class="btn small">全部重试失败</button><button type="button" data-enh-task-batch="pause" class="btn small">批量暂停</button><button type="button" data-enh-task-batch="resume" class="btn small">批量继续</button><button type="button" data-enh-task-batch="cancel" class="btn danger small">批量取消</button><button type="button" data-enh-task-batch="delete" class="btn danger small">删除选中</button><button type="button" id="enhTaskClearFailed" class="btn danger small">清理失败/取消</button></div></section>
      <section id="enhTaskResults" style="margin-top:16px"><div class="loading-card">正在读取任务…</div></section>
    </div>`;
    $('#enhTaskStatus').value = tasks.status;
    $('#enhTaskDestination').value = tasks.destination;
    $('#enhTaskStatus').onchange = () => { tasks.status = $('#enhTaskStatus').value; renderTaskResults(); };
    $('#enhTaskDestination').onchange = () => { tasks.destination = $('#enhTaskDestination').value; renderTaskResults(); };
    $('#enhTaskQuery').oninput = () => { tasks.q = $('#enhTaskQuery').value; renderTaskResults(); };
    $('#enhTaskSelectVisible').onclick = () => { for (const task of filteredTasks()) tasks.selected.add(task.id); renderTaskResults(); };
    $('#enhTaskSelectFailed').onclick = () => {
      for (const task of tasks.data) if (task.status === 'failed' || task.status === 'cancelled') tasks.selected.add(task.id);
      renderTaskResults();
    };
    $('#enhTaskClearSelection').onclick = () => { tasks.selected.clear(); renderTaskResults(); };
    $$('[data-enh-task-batch]').forEach(button => { button.onclick = () => actionApi().batchTaskAction(button.dataset.enhTaskBatch); });
    $('#enhTaskRetryAllFailed').onclick = () => actionApi().retryAllFailedTasks();
    $('#enhTaskClearFailed').onclick = () => actionApi().clearFailedTasks();
    await loadTasks();
    ensureTaskEvents();
  }

  async function loadTasks() {
    try {
      const response = await api('/api/tasks');
      state.tasks.data = response.data || [];
      state.tasks.summary = response.summary || {};
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
    return filter.data.filter(task => {
      const effectiveStatus = isPausedTask(task) ? 'paused' : task.status;
      if (filter.status && effectiveStatus !== filter.status) return false;
      if (filter.destination && task.destination !== filter.destination) return false;
      if (query && ![task.title, task.display_title, task.bvid, task.key, task.group, task.error, task.progress_message].join(' ').toLowerCase().includes(query)) return false;
      return true;
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
    const selected = state.tasks.selected.has(task.id);
    const active = ['queued', 'running'].includes(task.status);
    const paused = isPausedTask(task);
    const terminal = ['success', 'skipped', 'failed', 'cancelled'].includes(task.status);
    const percent = task.progress_percent == null ? null : Math.max(0, Math.min(100, Number(task.progress_percent)));
    const size = task.downloaded_bytes != null
      ? `${formatBytes(task.downloaded_bytes)}${task.total_bytes ? ` / ${formatBytes(task.total_bytes)}` : ''}`
      : '';
    const part = task.part_total ? `分 P ${task.current_part || '?'} / ${task.part_total}` : '';
    const quality = [task.selected_quality, task.selected_resolution, task.selected_codec, task.selected_fps].filter(Boolean).join(' · ');
    const exportReady = task.destination === 'device' && task.status === 'success' && task.export_state !== 'downloaded';
    return `<article class="task-card" data-task-id="${esc(task.id)}"><div class="task-main"><div class="toolbar"><label class="enh-task-selector"><input type="checkbox" data-task-select="${esc(task.id)}" ${selected ? 'checked' : ''}> 选择</label><span class="badge ${taskStatusClass(task)}">${esc(taskStatusLabel(task))}</span><span class="badge ${task.destination === 'device' ? 'warn' : 'brand'}">${esc(task.destination_label || (task.destination === 'device' ? '设备导出' : '媒体库'))}</span>${task.selected_quality ? `<span class="badge neutral">${esc(task.selected_quality)}</span>` : ''}</div><div class="task-title" style="margin-top:9px">${esc(task.display_title || task.title || task.bvid || task.key)}</div><div class="task-sub"><span>${esc(task.bvid || task.key)}</span>${task.destination === 'library' ? `<span>分组：${esc(task.group || '未分组')}</span>` : ''}<span>最低：${esc(task.min_height_label || task.min_height || '不限制')}</span><span>${task.preferred_quality ? `指定：${esc(task.preferred_quality)}` : '自动最高'}</span>${task.duration ? `<span>时长：${esc(task.duration)}</span>` : ''}${part ? `<span>${esc(part)}</span>` : ''}<span>${esc(task.phase_label || '')}</span></div><div class="enh-task-meta">${size ? `<span>当前大小 <strong>${esc(size)}</strong></span>` : ''}${task.speed_text ? `<span>速度 <strong>${esc(task.speed_text)}</strong></span>` : ''}${task.eta_text ? `<span>剩余 <strong>${esc(task.eta_text)}</strong></span>` : ''}${percent != null ? `<span>进度 <strong>${percent.toFixed(percent >= 10 ? 0 : 1)}%</strong></span>` : ''}${task.queue_position ? `<span>队列位置 <strong>${task.queue_position}</strong></span>` : ''}${task.elapsed_sec ? `<span>耗时 <strong>${Math.round(task.elapsed_sec)} 秒</strong></span>` : ''}</div>${quality ? `<div class="metric-foot" style="margin-top:7px">实际：${esc(quality)}</div>` : ''}${active ? `<div class="progress ${percent == null ? 'indeterminate' : ''}" title="${esc(task.progress_message || task.phase_label || '')}"><span style="width:${percent == null ? 38 : percent}%"></span></div>` : ''}${paused && size ? `<div class="progress"><span style="width:${percent == null ? 0 : percent}%"></span></div>` : ''}${task.progress_message && active ? `<div class="metric-foot enh-progress-message">${esc(task.progress_message)}</div>` : ''}${task.error && ['failed', 'cancelled'].includes(task.status) ? `<div class="notice ${paused ? 'warn' : 'bad'}" style="margin-top:10px">${esc(task.error)}</div>` : ''}</div><div class="task-side"><button type="button" class="btn small" data-task-log="${esc(task.id)}">日志</button>${active ? `<button type="button" class="btn small" data-task-action="pause" data-task-action-id="${esc(task.id)}">暂停</button><button type="button" class="btn danger small" data-task-action="cancel" data-task-action-id="${esc(task.id)}">取消</button>` : ''}${paused ? `<button type="button" class="btn primary small" data-task-action="resume" data-task-action-id="${esc(task.id)}">继续</button><button type="button" class="btn small" data-task-edit-retry="${esc(task.id)}">编辑后重试</button>` : ''}${task.status === 'failed' || (task.status === 'cancelled' && !paused) ? `<button type="button" class="btn primary small" data-task-action="retry" data-task-action-id="${esc(task.id)}">重试</button><button type="button" class="btn small" data-task-edit-retry="${esc(task.id)}">编辑画质</button>` : ''}${terminal && !active ? `<button type="button" class="btn danger small" data-task-action="delete" data-task-action-id="${esc(task.id)}">删除记录</button>` : ''}${task.destination === 'library' && task.status === 'success' ? `<button type="button" class="btn small" data-task-library="${esc(task.bvid || task.key)}">作品库</button>` : ''}${exportReady ? `<a class="btn primary small" href="/api/exports/${encodeURIComponent(task.id)}/download">下载到设备</a><button type="button" class="btn danger small" data-task-discard-export="${esc(task.id)}">删除临时文件</button>` : ''}</div></article>`;
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
    box.innerHTML = tasks.length ? `<div class="task-list">${tasks.map(taskCard).join('')}</div>` : '<div class="empty">没有符合条件的任务</div>';
    $$('[data-task-select]', box).forEach(input => {
      input.onchange = () => {
        if (input.checked) state.tasks.selected.add(input.dataset.taskSelect);
        else state.tasks.selected.delete(input.dataset.taskSelect);
        renderTaskResults();
      };
    });
    $$('[data-task-log]', box).forEach(button => { button.onclick = () => actionApi().openTaskLog(button.dataset.taskLog); });
    $$('[data-task-action]', box).forEach(button => { button.onclick = () => actionApi().singleTaskAction(button.dataset.taskActionId, button.dataset.taskAction); });
    $$('[data-task-edit-retry]', box).forEach(button => { button.onclick = () => actionApi().openRetryEditor(button.dataset.taskEditRetry); });
    $$('[data-task-library]', box).forEach(button => {
      button.onclick = () => {
        state.library.q = button.dataset.taskLibrary || '';
        state.library.page = 1;
        location.hash = '#/library';
      };
    });
    $$('[data-task-discard-export]', box).forEach(button => {
      button.onclick = async () => {
        if (!confirm('确定删除这个设备导出的临时文件吗？')) return;
        try {
          await api(`/api/exports/${encodeURIComponent(button.dataset.taskDiscardExport)}`, { method: 'DELETE' });
          toast('临时文件已清理', 'good');
          await loadTasks();
        } catch (error) { toast(error.message, 'bad'); }
      };
    });
  }

  E.taskPage = { loadTasks, renderTaskResults };
  register('tasks', renderTasks);
})();
