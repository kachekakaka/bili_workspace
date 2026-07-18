(() => {
  'use strict';
  const E = window.BiliEnhancements;
  if (!E) return;
  const {
    COMMON_QUALITY_LABELS, state, $, $$, esc, qualityOptions, toast, showModal, api,
  } = E;
  const taskPage = () => E.taskPage;

  async function singleTaskAction(taskId, action, body = {}) {
    try {
      await api(`/api/enhancements/tasks/${encodeURIComponent(taskId)}/${encodeURIComponent(action)}`, {
        method: 'POST', body: { force: false, min_height: null, preferred_quality: null, ...body },
      });
      toast(({ retry: '任务已原地重试', pause: '已提交暂停', resume: '任务已继续', cancel: '已提交取消', delete: '任务记录已删除' })[action] || '操作完成', 'good');
      if (action === 'delete') state.tasks.selected.delete(taskId);
      await taskPage().loadTasks();
    } catch (error) {
      toast(error.message, 'bad');
    }
  }

  async function batchTaskAction(action, ids = [...state.tasks.selected]) {
    const unique = [...new Set(ids)].filter(Boolean);
    if (!unique.length) {
      toast('请先勾选任务', 'warn');
      return;
    }
    if ((action === 'delete' || action === 'cancel') && !confirm(`确定对选中的 ${unique.length} 个任务执行“${action === 'delete' ? '删除记录' : '取消'}”吗？`)) return;
    try {
      const response = await api('/api/enhancements/tasks/batch', {
        method: 'POST',
        body: { task_ids: unique, action, force: false, min_height: null, preferred_quality: null },
      });
      const done = response.data?.items?.length || 0;
      const errors = Object.keys(response.data?.errors || {}).length;
      if (action === 'delete') for (const id of unique) state.tasks.selected.delete(id);
      toast(`已处理 ${done} 个任务${errors ? `，${errors} 个失败` : ''}`, errors ? 'warn' : 'good');
      await taskPage().loadTasks();
    } catch (error) {
      toast(error.message, 'bad');
    }
  }

  async function retryAllFailedTasks() {
    const ids = state.tasks.data.filter(task => task.status === 'failed').map(task => task.id);
    if (!ids.length) {
      toast('当前没有失败任务', 'warn');
      return;
    }
    if (!confirm(`确定原地重试全部 ${ids.length} 个失败任务吗？`)) return;
    await batchTaskAction('retry', ids);
  }

  async function clearFailedTasks() {
    if (!confirm('确定清理所有失败和已取消任务记录吗？媒体库中的已完成文件不会删除。')) return;
    try {
      const response = await api('/api/enhancements/tasks/clear', {
        method: 'POST', body: { statuses: ['failed', 'cancelled'], destination: 'all' },
      });
      toast(`已清理 ${response.data?.removed || 0} 个任务记录`, 'good');
      state.tasks.selected.clear();
      await taskPage().loadTasks();
    } catch (error) {
      toast(error.message, 'bad');
    }
  }

  async function openTaskLog(taskId) {
    const modal = showModal('任务日志', '<div class="loading-card">正在读取日志…</div>');
    try {
      const response = await api(`/api/tasks/${encodeURIComponent(taskId)}/log?tail=250000`);
      $('.modal-body', modal.root).innerHTML = `<div class="toolbar" style="margin-bottom:10px"><a class="btn small" href="/api/tasks/${encodeURIComponent(taskId)}/log/download">下载完整日志</a><button type="button" id="enhCopyTaskLog" class="btn small">复制</button></div><pre class="log-box">${esc(response.data?.text || '暂无日志')}</pre>`;
      $('#enhCopyTaskLog', modal.root).onclick = async () => {
        try { await navigator.clipboard.writeText(response.data?.text || ''); toast('日志已复制', 'good'); }
        catch (_) { toast('浏览器不允许复制', 'bad'); }
      };
    } catch (error) {
      $('.modal-body', modal.root).innerHTML = `<div class="notice bad">${esc(error.message)}</div>`;
    }
  }

  async function openRetryEditor(taskId) {
    const modal = showModal('编辑画质并重试', '<div class="loading-card">正在读取任务…</div>', { narrow: true });
    try {
      const response = await api(`/api/tasks/${encodeURIComponent(taskId)}`);
      const task = response.data || {};
      $('.modal-body', modal.root).innerHTML = `<form id="enhRetryForm" class="form-grid"><div class="notice full"><strong>${esc(task.display_title || task.title || task.bvid || task.key)}</strong><br>${esc(task.bvid || task.key)} · 当前最低 ${esc(task.min_height_label || task.min_height || '不限制')}</div><div class="field full"><label>最低清晰度</label><select id="enhRetryHeight" class="select">${qualityOptions(task.min_height || 0)}</select></div><div class="field full"><label>指定画质档位</label><select id="enhRetryPreferred" class="select"><option value="">自动最高</option>${COMMON_QUALITY_LABELS.map(label => `<option value="${esc(label)}" ${task.preferred_quality === label ? 'selected' : ''}>${esc(label)}</option>`).join('')}</select><small>可先读取该作品实际可用的共同画质，再选择严格档位。</small></div><div class="field full"><button type="button" id="enhRetryLoadQuality" class="btn">读取实际可用画质</button></div><div class="field full"><button type="submit" class="btn primary">保存并使用原任务 ID 重试</button></div></form>`;
      $('#enhRetryLoadQuality', modal.root).onclick = async () => {
        const button = $('#enhRetryLoadQuality', modal.root);
        button.disabled = true;
        button.textContent = '正在读取…';
        try {
          const preview = await api('/api/preview', {
            method: 'POST',
            body: {
              item: {
                bvid: task.bvid, url: task.url, title: task.title, cover: task.cover,
                author: task.author, pubdate: task.pubdate, duration: task.duration,
                play: task.play, preferred_quality: '',
              },
              min_height: Number($('#enhRetryHeight', modal.root).value || 0),
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
          const select = $('#enhRetryPreferred', modal.root);
          const current = select.value;
          select.innerHTML = `<option value="">自动最高</option>${choices.map(label => `<option value="${esc(label)}">${esc(label)}</option>`).join('')}`;
          if (choices.includes(current)) select.value = current;
          toast(`读取到 ${choices.length} 个所有分 P 共同可用档位`, 'good');
        } catch (error) {
          toast(error.message, 'bad');
        } finally {
          button.disabled = false;
          button.textContent = '重新读取实际可用画质';
        }
      };
      $('#enhRetryForm', modal.root).onsubmit = async event => {
        event.preventDefault();
        const submit = $('button[type="submit"]', event.currentTarget);
        submit.disabled = true;
        try {
          await api(`/api/enhancements/tasks/${encodeURIComponent(taskId)}/retry`, {
            method: 'POST',
            body: {
              force: false,
              min_height: Number($('#enhRetryHeight', modal.root).value || 0),
              preferred_quality: $('#enhRetryPreferred', modal.root).value,
            },
          });
          modal.close();
          toast('画质已更新，任务已使用原 ID 重新排队', 'good');
          await taskPage().loadTasks();
        } catch (error) {
          toast(error.message, 'bad');
        } finally {
          submit.disabled = false;
        }
      };
    } catch (error) {
      $('.modal-body', modal.root).innerHTML = `<div class="notice bad">${esc(error.message)}</div>`;
    }
  }

  E.taskActions = {
    singleTaskAction, batchTaskAction, retryAllFailedTasks, clearFailedTasks,
    openTaskLog, openRetryEditor,
  };
})();
