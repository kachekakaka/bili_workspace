import { bindDialogCancel, esc, formatDate, modalActions } from './shared.mjs';

function label(user) {
  return `${user.display_name || user.username}（${user.username}）`;
}

function statusBadge(user) {
  if (user.role === 'admin') return '<span class="badge brand">管理员</span>';
  if (user.disabled) return '<span class="badge bad">已禁用</span>';
  if (user.must_change_password) return '<span class="badge warn">待改密</span>';
  return '<span class="badge good">已启用</span>';
}

function actions(user) {
  const admin = user.role === 'admin';
  return `<div class="user-actions"><button type="button" class="btn small" data-user-edit="${esc(user.id)}">改显示名</button>${admin ? '' : `<button type="button" class="btn small" data-user-toggle="${esc(user.id)}">${user.disabled ? '启用' : '禁用'}</button><button type="button" class="btn small" data-user-reset="${esc(user.id)}">重置密码</button><button type="button" class="btn small" data-user-revoke="${esc(user.id)}">撤销会话</button><button type="button" class="btn primary small" data-user-tasks="${esc(user.id)}">查看任务</button>`}</div>`;
}

function tableRows(users) {
  return users.map(user => `<tr><td><strong>${esc(user.display_name || user.username)}</strong><small>${esc(user.username)}</small></td><td>${statusBadge(user)}</td><td>${Number(user.active_session_count || 0)}</td><td>${esc(formatDate(user.last_login_at))}</td><td>${esc(formatDate(user.created_at, true))}</td><td>${actions(user)}</td></tr>`).join('');
}

function cards(users) {
  return users.map(user => `<article class="user-card"><div class="user-card-head"><div><strong>${esc(user.display_name || user.username)}</strong><small>${esc(user.username)}</small></div>${statusBadge(user)}</div><div class="user-card-meta"><span>有效会话：${Number(user.active_session_count || 0)}</span><span>最后登录：${esc(formatDate(user.last_login_at))}</span><span>创建时间：${esc(formatDate(user.created_at, true))}</span></div>${actions(user)}</article>`).join('');
}

export async function mount(root, context) {
  if (!context.session.isAdmin()) {
    context.navigate('download', { replace: true });
    return Object.freeze({ dispose() {} });
  }
  const host = document.createElement('div');
  let users = [];
  const render = () => {
    host.innerHTML = `<section class="card"><div class="card-head"><div><h2>用户管理</h2><p>创建普通用户、管理登录设备和查看用户任务。只允许一个启用的管理员。</p></div><button type="button" id="createUserButton" class="btn primary">＋ 创建用户</button></div><div class="notice">登录账号创建后不可修改；中文显示名允许重复。禁用用户会立即撤销其全部网站会话，已有运行任务不会被自动取消。</div></section><section class="card user-table-shell" style="margin-top:18px"><div class="user-table-scroll"><table class="user-table"><thead><tr><th>用户</th><th>状态</th><th>有效会话</th><th>最后登录</th><th>创建时间</th><th>操作</th></tr></thead><tbody>${tableRows(users)}</tbody></table></div></section><section class="user-card-list">${cards(users)}</section>`;
  };
  const reload = async () => {
    const result = await context.api('/api/admin/users', { signal: context.signal });
    users = result.data?.items || [];
    if (context.isCurrent()) render();
  };
  context.commit(() => root.replaceChildren(host));
  await reload();

  const createUser = () => {
    const modal = context.modal.open({
      title: '创建普通用户', narrow: true,
      body: `<form id="createUserForm" class="form-grid"><div class="field full"><label>登录账号</label><input id="createUsername" class="input" minlength="3" maxlength="32" autocomplete="off" required><small>以英文字母开头，只允许字母、数字、点、下划线和短横线。</small></div><div class="field full"><label>中文显示名</label><input id="createDisplayName" class="input" minlength="2" maxlength="12" required></div><div class="field full"><label>临时密码</label><input id="createTemporaryPassword" class="input" type="password" minlength="10" maxlength="64" autocomplete="new-password" required><small>用户首次登录后必须修改；至少包含英文字母和数字。</small></div><div class="field full">${modalActions('创建用户')}</div></form>`,
    });
    bindDialogCancel(modal);
    modal.body.querySelector('#createUserForm').addEventListener('submit', async event => {
      event.preventDefault();
      const button = event.currentTarget.querySelector('button[type="submit"]');
      button.disabled = true;
      try {
        await context.api('/api/admin/users', {
          method: 'POST',
          body: {
            username: modal.body.querySelector('#createUsername').value.trim(),
            display_name: modal.body.querySelector('#createDisplayName').value.trim(),
            temporary_password: modal.body.querySelector('#createTemporaryPassword').value,
          },
        });
        modal.close('created');
        context.toast.show('普通用户已创建', 'good');
        await reload();
      } catch (error) {
        context.toast.show(error.message, 'bad');
      } finally {
        button.disabled = false;
      }
    });
  };

  const editDisplayName = user => {
    const modal = context.modal.open({
      title: '修改显示名', narrow: true,
      body: `<form id="v062UserDisplayNameForm" class="form-grid"><div class="notice full"><strong>${esc(label(user))}</strong></div><div class="field full"><label for="v062UserDisplayName">中文显示名</label><input id="v062UserDisplayName" class="input" value="${esc(user.display_name || '')}" minlength="2" maxlength="12" required></div><div class="field full">${modalActions('保存')}</div></form>`,
    });
    bindDialogCancel(modal);
    modal.body.querySelector('#v062UserDisplayNameForm').addEventListener('submit', async event => {
      event.preventDefault();
      const value = modal.body.querySelector('#v062UserDisplayName').value.trim();
      if (!value || value === user.display_name) {
        modal.close('unchanged');
        return;
      }
      try {
        await context.api(`/api/admin/users/${encodeURIComponent(user.id)}`, { method: 'PATCH', body: { display_name: value } });
        modal.close('saved');
        context.toast.show('显示名已更新', 'good');
        await reload();
      } catch (error) {
        context.toast.show(error.message, 'bad');
      }
    });
  };

  const resetPassword = user => {
    const modal = context.modal.open({
      title: '设置临时密码', narrow: true,
      body: `<form id="v062UserPasswordForm" class="form-grid"><div class="notice warn full"><strong>${esc(label(user))}</strong><br>保存后现有会话立即失效，下次登录必须修改密码。</div><div class="field full"><label for="v062TemporaryPassword">临时密码</label><input id="v062TemporaryPassword" class="input" type="password" minlength="10" maxlength="64" required></div><div class="field full"><label for="v062TemporaryPasswordConfirm">再次输入</label><input id="v062TemporaryPasswordConfirm" class="input" type="password" minlength="10" maxlength="64" required></div><div class="field full">${modalActions('重置密码')}</div></form>`,
    });
    bindDialogCancel(modal);
    modal.body.querySelector('#v062UserPasswordForm').addEventListener('submit', async event => {
      event.preventDefault();
      const password = modal.body.querySelector('#v062TemporaryPassword').value;
      const confirmation = modal.body.querySelector('#v062TemporaryPasswordConfirm').value;
      if (password !== confirmation) {
        context.toast.show('两次输入的临时密码不一致', 'bad');
        return;
      }
      try {
        const result = await context.api(`/api/admin/users/${encodeURIComponent(user.id)}/reset-password`, { method: 'POST', body: { temporary_password: password } });
        modal.close('reset');
        context.toast.show(`临时密码已重置，撤销 ${result.data?.sessions_revoked || 0} 个会话`, 'good');
        await reload();
      } catch (error) {
        context.toast.show(error.message, 'bad');
      }
    });
  };

  host.addEventListener('click', async event => {
    const button = event.target.closest('button');
    if (!button) return;
    if (button.id === 'createUserButton') {
      createUser();
      return;
    }
    const id = button.dataset.userEdit || button.dataset.userToggle || button.dataset.userReset || button.dataset.userRevoke || button.dataset.userTasks;
    const user = users.find(item => String(item.id) === String(id));
    if (!user) return;
    if (button.dataset.userEdit !== undefined) {
      editDisplayName(user);
    } else if (button.dataset.userReset !== undefined) {
      resetPassword(user);
    } else if (button.dataset.userToggle !== undefined) {
      const disabled = !user.disabled;
      const accepted = await context.confirm({ title: disabled ? '禁用用户' : '启用用户', message: `${disabled ? '禁用' : '启用'} ${label(user)}？${disabled ? ' 该用户全部会话会立即失效。' : ''}`, confirmLabel: disabled ? '禁用' : '启用', danger: disabled });
      if (!accepted) return;
      try {
        await context.api(`/api/admin/users/${encodeURIComponent(user.id)}`, { method: 'PATCH', body: { disabled } });
        context.toast.show(disabled ? '用户已禁用' : '用户已启用', 'good');
        await reload();
      } catch (error) {
        context.toast.show(error.message, 'bad');
      }
    } else if (button.dataset.userRevoke !== undefined) {
      const accepted = await context.confirm({ title: '撤销登录会话', message: `撤销 ${label(user)} 的全部登录会话吗？`, confirmLabel: '撤销', danger: true });
      if (!accepted) return;
      try {
        const result = await context.api(`/api/admin/users/${encodeURIComponent(user.id)}/revoke-sessions`, { method: 'POST' });
        context.toast.show(`已撤销 ${result.data?.revoked || 0} 个会话`, 'good');
        await reload();
      } catch (error) {
        context.toast.show(error.message, 'bad');
      }
    } else if (button.dataset.userTasks !== undefined) {
      const state = context.legacy.state();
      if (state?.tasks) state.tasks.ownerUserId = user.id;
      context.navigate('tasks');
    }
  }, { signal: context.signal });

  return Object.freeze({ dispose() {} });
}
