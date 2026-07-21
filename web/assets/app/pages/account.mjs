import { bindDialogCancel, esc, formatDate, modalActions, statusClass, statusLabel } from './shared.mjs';

function accountUser(session) {
  const value = session.get();
  return value.user || {
    username: value.username,
    display_name: value.displayName,
    role: value.role,
  };
}

export async function mount(root, context) {
  const statusResponse = await context.api('/api/status?refresh_login=true', { signal: context.signal });
  const status = statusResponse.data || {};
  context.shared.patch({ status });
  context.syncLegacy();
  const user = accountUser(context.session);
  const host = document.createElement('div');
  host.innerHTML = `<div id="v062AccountTabs" class="v062-account-tabs" role="tablist"><button type="button" class="active" data-v062-account-tab="bilibili" role="tab" aria-selected="true">Bilibili 登录</button><button type="button" data-v062-account-tab="website" role="tab" aria-selected="false">网站账号与设备</button></div>
    <div class="v062-account-grid">
      <section class="card" data-v062-account-panel="bilibili"><div class="card-head"><div><h2>Bilibili 账号</h2><p>用于会员画质与登录搜索。完整 Cookie 只保存在服务器 BBDown.data，不返回浏览器。</p></div><span class="badge ${statusClass(status.login_state)}">${statusLabel(status.login_state)}</span></div><div class="notice">${esc(status.message || '')}</div><div class="toolbar" style="margin-top:15px"><button type="button" id="qrLoginButton" class="btn primary">网页扫码登录</button><button type="button" id="refreshBiliButton" class="btn">重新验证</button><button type="button" id="biliLogoutButton" class="btn danger">退出 B站登录</button></div></section>
      <section class="card hidden" data-v062-account-panel="website"><div class="card-head"><div><h2>网站账号</h2><p>管理当前网站账号、密码和登录设备；与 Bilibili 登录完全独立。</p></div></div><div class="v062-account-summary"><div><span class="metric-foot">当前网站账号</span><strong>${esc(user.display_name || user.username || '用户')}</strong><small>${esc(user.username || '')}</small></div><button type="button" class="btn" id="v062EditOwnDisplayName">修改显示名</button></div><form id="passwordForm" class="form-grid"><div class="field full"><label>当前密码</label><input id="currentPassword" class="input" type="password" autocomplete="current-password" required></div><div class="field"><label>新密码</label><input id="newPassword" class="input" type="password" autocomplete="new-password" minlength="10" maxlength="64" required></div><div class="field"><label>确认新密码</label><input id="confirmPassword" class="input" type="password" autocomplete="new-password" minlength="10" maxlength="64" required></div><div class="field full"><button class="btn primary" type="submit">更换密码并撤销其他会话</button></div></form><button type="button" id="accountLogout" class="btn" style="margin-top:15px">退出网站</button><div id="v062SessionPanel" class="v062-session-panel"><div class="loading-card">切换到此页签后读取登录设备…</div></div></section>
    </div>`;
  context.commit(() => root.replaceChildren(host));

  let sessionsLoaded = false;
  const sessionsPanel = host.querySelector('#v062SessionPanel');
  const renderSessions = async () => {
    if (sessionsPanel.dataset.loading === '1') return;
    sessionsPanel.dataset.loading = '1';
    sessionsPanel.innerHTML = '<div class="loading-card">正在读取登录设备…</div>';
    try {
      const response = await context.api('/api/auth/sessions', { signal: context.signal });
      const data = response.data || {};
      const sessions = data.items || [];
      const others = sessions.filter(session => !session.current);
      sessionsPanel.innerHTML = `<div class="v062-session-head"><div><h3>登录设备</h3><p>当前 ${sessions.length}/${Number(data.limit || 10)} 个有效 Token；超过上限时最久未连接的会话自动失效。</p></div><button type="button" class="btn" id="v062RevokeOtherSessions" ${others.length ? '' : 'disabled'}>退出其他设备</button></div><div class="v062-session-list">${sessions.map(session => `<article class="v062-session-row"><div><strong>${esc(session.user_agent || '未知设备')}</strong><p>${esc(session.remote_addr || '未知地址')} · 最近活动 ${esc(formatDate(session.last_seen_at))}<br>登录 ${esc(formatDate(session.created_at))} · 过期 ${esc(formatDate(session.expires_at))}</p></div>${session.current ? '<span class="badge good">当前设备</span>' : `<button type="button" class="btn danger small" data-v062-revoke-session="${esc(session.id)}">退出</button>`}</article>`).join('')}</div>`;
      sessionsLoaded = true;
    } catch (error) {
      if (error?.name !== 'AbortError') sessionsPanel.innerHTML = `<div class="notice bad">${esc(error.message)}</div>`;
    } finally {
      sessionsPanel.dataset.loading = '0';
    }
  };

  const activateTab = tab => {
    const value = tab === 'website' ? 'website' : 'bilibili';
    try { sessionStorage.setItem('bili-v062-account-tab', value); } catch {}
    for (const button of host.querySelectorAll('[data-v062-account-tab]')) {
      const active = button.dataset.v062AccountTab === value;
      button.classList.toggle('active', active);
      button.setAttribute('aria-selected', active ? 'true' : 'false');
    }
    for (const panel of host.querySelectorAll('[data-v062-account-panel]')) {
      panel.classList.toggle('hidden', panel.dataset.v062AccountPanel !== value);
    }
    if (value === 'website' && !sessionsLoaded) void renderSessions();
  };

  host.querySelector('#v062AccountTabs').addEventListener('click', event => {
    const button = event.target.closest('[data-v062-account-tab]');
    if (button) activateTab(button.dataset.v062AccountTab);
  }, { signal: context.signal });

  let initial = 'bilibili';
  try { initial = sessionStorage.getItem('bili-v062-account-tab') || 'bilibili'; } catch {}
  activateTab(initial);

  sessionsPanel.addEventListener('click', async event => {
    const button = event.target.closest('button');
    if (!button) return;
    if (button.id === 'v062RevokeOtherSessions') {
      button.disabled = true;
      try {
        const result = await context.api('/api/auth/sessions/revoke-others', { method: 'POST' });
        context.toast.show(`已退出 ${result.data?.revoked || 0} 个其他设备`, 'good');
        sessionsLoaded = false;
        await renderSessions();
      } catch (error) {
        context.toast.show(error.message, 'bad');
        button.disabled = false;
      }
    } else if (button.dataset.v062RevokeSession) {
      button.disabled = true;
      try {
        await context.api(`/api/auth/sessions/${encodeURIComponent(button.dataset.v062RevokeSession)}`, { method: 'DELETE' });
        context.toast.show('设备已退出', 'good');
        sessionsLoaded = false;
        await renderSessions();
      } catch (error) {
        context.toast.show(error.message, 'bad');
        button.disabled = false;
      }
    }
  }, { signal: context.signal });

  host.querySelector('#v062EditOwnDisplayName').addEventListener('click', () => {
    const current = accountUser(context.session);
    const modal = context.modal.open({
      title: '修改我的显示名', narrow: true,
      body: `<form id="v062OwnProfileForm" class="form-grid"><div class="notice full">登录账号：<strong>${esc(current.username || '')}</strong></div><div class="field full"><label for="v062OwnDisplayName">中文显示名</label><input id="v062OwnDisplayName" class="input" value="${esc(current.display_name || '')}" minlength="2" maxlength="12" required></div><div class="field full">${modalActions('保存')}</div></form>`,
    });
    bindDialogCancel(modal);
    modal.body.querySelector('#v062OwnProfileForm').addEventListener('submit', async event => {
      event.preventDefault();
      try {
        const result = await context.api('/api/auth/profile', { method: 'PATCH', body: { display_name: modal.body.querySelector('#v062OwnDisplayName').value.trim() } });
        context.session.patch(result.data || { display_name: modal.body.querySelector('#v062OwnDisplayName').value.trim() });
        modal.close('saved');
        context.toast.show('显示名已更新', 'good');
        context.renderChrome();
        void context.remount();
      } catch (error) {
        context.toast.show(error.message, 'bad');
      }
    });
  }, { signal: context.signal });

  host.querySelector('#passwordForm').addEventListener('submit', async event => {
    event.preventDefault();
    const next = host.querySelector('#newPassword').value;
    if (next !== host.querySelector('#confirmPassword').value) {
      context.toast.show('两次输入的新密码不一致', 'bad');
      return;
    }
    const button = event.currentTarget.querySelector('button[type="submit"]');
    button.disabled = true;
    try {
      const result = await context.api('/api/auth/password', { method: 'POST', body: { current_password: host.querySelector('#currentPassword').value, new_password: next } });
      context.session.patch({ csrf_token: result.data?.csrf_token || context.session.get().csrfToken });
      event.currentTarget.reset();
      context.toast.show(`密码已更新，已撤销 ${result.data?.other_sessions_revoked || 0} 个其他会话`, 'good');
      sessionsLoaded = false;
      await renderSessions();
    } catch (error) {
      context.toast.show(error.message, 'bad');
    } finally {
      button.disabled = false;
    }
  }, { signal: context.signal });

  host.querySelector('#accountLogout').addEventListener('click', () => void context.logout(), { signal: context.signal });
  host.querySelector('#refreshBiliButton').addEventListener('click', () => void context.remount(), { signal: context.signal });
  host.querySelector('#biliLogoutButton').addEventListener('click', async () => {
    const accepted = await context.confirm({ title: '退出 Bilibili 登录', message: '确定删除服务器上的 Bilibili 登录会话吗？', confirmLabel: '退出', danger: true });
    if (!accepted) return;
    try {
      await context.api('/api/account/bilibili', { method: 'DELETE' });
      context.toast.show('已退出 Bilibili 登录', 'good');
      void context.remount();
    } catch (error) {
      context.toast.show(error.message, 'bad');
    }
  }, { signal: context.signal });

  host.querySelector('#qrLoginButton').addEventListener('click', async () => {
    const modal = context.modal.open({ title: 'Bilibili 扫码登录', narrow: true, body: '<div class="loading-card">正在生成二维码…</div>' });
    let timer = 0;
    const stop = () => { if (timer) clearInterval(timer); timer = 0; };
    try {
      const result = await context.api('/api/account/bilibili/qr', { method: 'POST' });
      const qrSession = result.data || {};
      modal.body.innerHTML = '<div id="qrBox" class="qr-box"></div><div id="qrStatus" class="notice" style="text-align:center">等待使用 Bilibili App 扫码</div><div class="metric-foot" style="text-align:center;margin-top:10px">二维码只包含一次性登录 URL；Cookie 不会发送到当前浏览器。</div>';
      if (globalThis.QRCode) new globalThis.QRCode(modal.body.querySelector('#qrBox'), { text: qrSession.login_url, width: 212, height: 212, correctLevel: globalThis.QRCode.CorrectLevel.M });
      const poll = async () => {
        try {
          const value = (await context.api(`/api/account/bilibili/qr/${encodeURIComponent(qrSession.id)}`, { method: 'POST' })).data || {};
          const node = modal.body.querySelector('#qrStatus');
          if (!node) { stop(); return; }
          node.textContent = value.status_label || value.message || '';
          if (value.status === 'success') {
            stop();
            context.toast.show('Bilibili 登录成功', 'good');
            modal.close('success');
            void context.remount();
          } else if (value.status === 'expired') {
            stop();
            node.className = 'notice bad';
          }
        } catch (error) {
          stop();
          const node = modal.body.querySelector('#qrStatus');
          if (node) { node.className = 'notice bad'; node.textContent = error.message; }
        }
      };
      timer = setInterval(poll, 1800);
      void poll();
    } catch (error) {
      modal.body.innerHTML = `<div class="notice bad">${esc(error.message)}</div>`;
    }
    context.signal.addEventListener('abort', stop, { once: true });
  }, { signal: context.signal });

  return Object.freeze({ dispose() {} });
}
