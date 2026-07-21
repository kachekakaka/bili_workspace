import {
  bindCoverFallback,
  bindDialogCancel,
  coverUrl,
  esc,
  formatBytes,
  formatDate,
  modalActions,
} from './shared.mjs';

function groupCard(group) {
  return `<article class="group-card"><div class="group-cover"><img data-cover-img src="${esc(coverUrl(group.cover))}" alt="" loading="lazy" referrerpolicy="no-referrer"><span>${esc(group.display_name?.slice(0, 1) || '▣')}</span></div><div class="group-name">${esc(group.display_name)}</div><div class="group-stats">${Number(group.media_count || 0)} 个作品 · ${formatBytes(group.total_size)}<br>进行中：${Number(group.active_count || 0)} · 失败：${Number(group.failed_count || 0)}<br>最近更新：${formatDate(group.latest_download)}<br>目录标识：${esc(group.folder_key)}</div><div class="toolbar"><button type="button" class="btn small" data-browse-group="${esc(group.id)}">查看</button><button type="button" class="btn small" data-rename-group="${esc(group.id)}">重命名</button><button type="button" class="btn small" data-merge-group="${esc(group.id)}">合并</button><button type="button" class="btn danger small" data-delete-group="${esc(group.id)}" ${group.display_name === '未分组' ? 'disabled' : ''}>删除</button></div></article>`;
}

export async function mount(root, context) {
  const host = document.createElement('div');
  let groups = [];

  const render = () => {
    host.innerHTML = `<section class="card"><div class="toolbar spread"><div><h2>分组管理</h2><p class="metric-foot">重命名只修改显示名称，不搬移大型媒体文件。</p></div><button type="button" id="createGroupTop" class="btn primary">＋ 新建分组</button></div></section><section id="groupResults" class="group-grid" style="margin-top:18px">${groups.map(groupCard).join('')}</section>`;
    bindCoverFallback(host, context.signal);
  };

  const reload = async () => {
    const response = await context.api('/api/groups', { signal: context.signal });
    groups = response.data?.records || [];
    context.shared.patch({ groups });
    if (context.isCurrent()) render();
  };

  context.commit(() => root.replaceChildren(host));
  await reload();

  const openCreate = () => {
    const modal = context.modal.open({
      title: '新建分组', narrow: true,
      body: `<form id="newGroupForm" class="form-grid"><div class="field full"><label>分组名称</label><input id="newGroupName" class="input" maxlength="60" required></div><div class="field full">${modalActions('创建分组')}</div></form>`,
    });
    bindDialogCancel(modal);
    modal.body.querySelector('#newGroupForm').addEventListener('submit', async event => {
      event.preventDefault();
      const button = event.currentTarget.querySelector('button[type="submit"]');
      button.disabled = true;
      try {
        await context.api('/api/groups', { method: 'POST', body: { name: modal.body.querySelector('#newGroupName').value.trim() } });
        modal.close('created');
        context.toast.show('分组已创建', 'good');
        await reload();
      } catch (error) {
        context.toast.show(error.message, 'bad');
      } finally {
        button.disabled = false;
      }
    });
  };

  const openRename = group => {
    const modal = context.modal.open({
      title: '重命名分组', narrow: true,
      body: `<form id="v062GroupRenameForm" class="form-grid"><div class="notice full">目录标识保持不变，只修改页面显示名称。</div><div class="field full"><label for="v062GroupName">分组名称</label><input id="v062GroupName" class="input" value="${esc(group.display_name || '')}" maxlength="60" required autofocus></div><div class="field full">${modalActions('保存')}</div></form>`,
    });
    bindDialogCancel(modal);
    modal.body.querySelector('#v062GroupRenameForm').addEventListener('submit', async event => {
      event.preventDefault();
      const name = modal.body.querySelector('#v062GroupName').value.trim();
      if (!name || name === group.display_name) {
        modal.close('unchanged');
        return;
      }
      const button = event.currentTarget.querySelector('button[type="submit"]');
      button.disabled = true;
      try {
        await context.api(`/api/groups/${encodeURIComponent(group.id)}`, { method: 'PATCH', body: { name } });
        modal.close('saved');
        context.toast.show('分组已重命名', 'good');
        await reload();
      } catch (error) {
        context.toast.show(error.message, 'bad');
      } finally {
        button.disabled = false;
      }
    });
  };

  const openMerge = group => {
    const targets = groups.filter(item => item.id !== group.id);
    if (!targets.length) {
      context.toast.show('没有其他可合并分组', 'warn');
      return;
    }
    const modal = context.modal.open({
      title: `合并“${group.display_name}”`, narrow: true,
      body: `<form id="mergeForm" class="form-grid"><div class="notice full">作品记录会归入目标分组；现有文件不做大规模搬移。</div><div class="field full"><label>目标分组</label><select id="mergeTarget" class="select">${targets.map(item => `<option value="${esc(item.id)}">${esc(item.display_name)}</option>`).join('')}</select></div><div class="field full">${modalActions('确认合并')}</div></form>`,
    });
    bindDialogCancel(modal);
    modal.body.querySelector('#mergeForm').addEventListener('submit', async event => {
      event.preventDefault();
      try {
        await context.api(`/api/groups/${encodeURIComponent(group.id)}/merge`, {
          method: 'POST', body: { target_id: modal.body.querySelector('#mergeTarget').value },
        });
        modal.close('merged');
        context.toast.show('分组已合并', 'good');
        await reload();
      } catch (error) {
        context.toast.show(error.message, 'bad');
      }
    });
  };

  host.addEventListener('click', async event => {
    const target = event.target.closest('button');
    if (!target) return;
    if (target.id === 'createGroupTop') {
      openCreate();
      return;
    }
    const groupId = target.dataset.browseGroup || target.dataset.renameGroup || target.dataset.mergeGroup || target.dataset.deleteGroup;
    const group = groups.find(item => String(item.id) === String(groupId));
    if (!group) return;
    if (target.dataset.browseGroup !== undefined) {
      try {
        sessionStorage.setItem('bili-v070-library-group', String(group.id || ''));
      } catch {}
      context.navigate('library');
    } else if (target.dataset.renameGroup !== undefined) {
      openRename(group);
    } else if (target.dataset.mergeGroup !== undefined) {
      openMerge(group);
    } else if (target.dataset.deleteGroup !== undefined) {
      const accepted = await context.confirm({
        title: '删除空分组',
        message: `只允许删除空分组“${group.display_name}”。继续吗？`,
        confirmLabel: '删除',
        danger: true,
      });
      if (!accepted) return;
      try {
        await context.api(`/api/groups/${encodeURIComponent(group.id)}`, { method: 'DELETE' });
        context.toast.show('分组已删除', 'good');
        await reload();
      } catch (error) {
        context.toast.show(error.message, 'bad');
      }
    }
  }, { signal: context.signal });

  return Object.freeze({ dispose() {} });
}
