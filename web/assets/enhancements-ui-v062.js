(() => {
  'use strict';

  const E = window.BiliEnhancements;
  if (!E) return;
  const { $, $$, esc, api, ensureContext, formatDate, showModal, toast, currentPage } = E;
  const SEARCHABLE_OPTION_THRESHOLD = 8;
  const SEARCHABLE_SELECT_ID = /(group|user|owner)/i;
  let applying = false;

  function refreshCurrentPage() {
    const refresh = $('#refreshButton');
    if (refresh instanceof HTMLButtonElement) {
      refresh.click();
      return;
    }
    window.location.reload();
  }

  function modalActions(submitLabel) {
    return `<div class="v062-modal-actions"><button type="button" class="btn" data-v062-cancel>取消</button><button type="submit" class="btn primary">${esc(submitLabel)}</button></div>`;
  }

  function bindCancel(modal) {
    const cancel = $('[data-v062-cancel]', modal.root);
    if (cancel) cancel.onclick = modal.close;
  }

  async function adminUsers() {
    await ensureContext(true);
    const result = await api('/api/admin/users');
    return result.data?.items || [];
  }

  async function openUserDisplayNameDialog(userId) {
    try {
      const users = await adminUsers();
      const user = users.find(item => String(item.id) === String(userId));
      if (!user) throw new Error('用户不存在或已被删除');
      const label = user.display_name || user.username;
      const modal = showModal('修改显示名', `<form id="v062UserDisplayNameForm" class="form-grid"><div class="notice full"><strong>${esc(label)}</strong><br>登录账号：${esc(user.username)}</div><div class="field full"><label for="v062UserDisplayName">中文显示名</label><input id="v062UserDisplayName" class="input" value="${esc(user.display_name || '')}" minlength="2" maxlength="12" required autofocus><small>允许与其他用户重复；登录账号不会改变。</small></div><div class="field full">${modalActions('保存')}</div></form>`, { narrow: true });
      bindCancel(modal);
      const form = $('#v062UserDisplayNameForm', modal.root);
      form.onsubmit = async event => {
        event.preventDefault();
        const button = $('button[type="submit"]', form);
        button.disabled = true;
        try {
          const displayName = $('#v062UserDisplayName', modal.root).value.trim();
          if (displayName === String(user.display_name || '')) {
            modal.close();
            return;
          }
          await api(`/api/admin/users/${encodeURIComponent(user.id)}`, {
            method: 'PATCH',
            body: { display_name: displayName },
          });
          modal.close();
          toast('显示名已更新', 'good');
          refreshCurrentPage();
        } catch (error) {
          toast(error.message, 'bad');
        } finally {
          button.disabled = false;
        }
      };
      requestAnimationFrame(() => $('#v062UserDisplayName', modal.root)?.focus());
    } catch (error) {
      toast(error.message, 'bad');
    }
  }

  async function openUserPasswordResetDialog(userId) {
    try {
      const users = await adminUsers();
      const user = users.find(item => String(item.id) === String(userId));
      if (!user) throw new Error('用户不存在或已被删除');
      const modal = showModal('设置临时密码', `<form id="v062UserPasswordForm" class="form-grid"><div class="notice warn full"><strong>${esc(user.display_name || user.username)}</strong>（${esc(user.username)}）<br>保存后该用户现有会话会立即失效，下次登录必须修改密码。</div><div class="field full"><label for="v062TemporaryPassword">临时密码</label><input id="v062TemporaryPassword" class="input" type="password" minlength="10" maxlength="64" autocomplete="new-password" required><small>10–64 位可见 ASCII，至少包含一个英文字母和一个数字。</small></div><div class="field full"><label for="v062TemporaryPasswordConfirm">再次输入</label><input id="v062TemporaryPasswordConfirm" class="input" type="password" minlength="10" maxlength="64" autocomplete="new-password" required></div><div class="field full">${modalActions('重置密码')}</div></form>`, { narrow: true });
      bindCancel(modal);
      const form = $('#v062UserPasswordForm', modal.root);
      form.onsubmit = async event => {
        event.preventDefault();
        const password = $('#v062TemporaryPassword', modal.root).value;
        const confirmPassword = $('#v062TemporaryPasswordConfirm', modal.root).value;
        if (password !== confirmPassword) {
          toast('两次输入的临时密码不一致', 'bad');
          return;
        }
        const button = $('button[type="submit"]', form);
        button.disabled = true;
        try {
          const result = await api(`/api/admin/users/${encodeURIComponent(user.id)}/reset-password`, {
            method: 'POST',
            body: { temporary_password: password },
          });
          modal.close();
          toast(`临时密码已重置，撤销 ${result.data?.sessions_revoked || 0} 个会话`, 'good');
          refreshCurrentPage();
        } catch (error) {
          toast(error.message, 'bad');
        } finally {
          button.disabled = false;
        }
      };
    } catch (error) {
      toast(error.message, 'bad');
    }
  }

  async function openGroupRenameDialog(groupId) {
    try {
      await ensureContext(true);
      const response = await api('/api/groups');
      const groups = response.data?.records || [];
      const group = groups.find(item => String(item.id) === String(groupId));
      if (!group) throw new Error('分组不存在或已被删除');
      const modal = showModal('重命名分组', `<form id="v062GroupRenameForm" class="form-grid"><div class="notice full">目录标识保持不变，只修改页面显示名称。</div><div class="field full"><label for="v062GroupName">分组名称</label><input id="v062GroupName" class="input" value="${esc(group.display_name || '')}" maxlength="60" required autofocus></div><div class="field full">${modalActions('保存')}</div></form>`, { narrow: true });
      bindCancel(modal);
      const form = $('#v062GroupRenameForm', modal.root);
      form.onsubmit = async event => {
        event.preventDefault();
        const name = $('#v062GroupName', modal.root).value.trim();
        if (name === String(group.display_name || '')) {
          modal.close();
          return;
        }
        const button = $('button[type="submit"]', form);
        button.disabled = true;
        try {
          await api(`/api/groups/${encodeURIComponent(group.id)}`, {
            method: 'PATCH',
            body: { name },
          });
          modal.close();
          E.state.contextLoadedAt = 0;
          toast('分组已重命名', 'good');
          refreshCurrentPage();
        } catch (error) {
          toast(error.message, 'bad');
        } finally {
          button.disabled = false;
        }
      };
      requestAnimationFrame(() => $('#v062GroupName', modal.root)?.select());
    } catch (error) {
      toast(error.message, 'bad');
    }
  }

  function interceptLegacyPromptActions(event) {
    const target = event.target instanceof Element ? event.target : null;
    if (!target) return;
    const userEdit = target.closest('[data-user-edit]');
    const userReset = target.closest('[data-user-reset]');
    const groupRename = target.closest('[data-rename-group]');
    const action = userEdit || userReset || groupRename;
    if (!action) return;
    event.preventDefault();
    event.stopImmediatePropagation();
    if (userEdit) void openUserDisplayNameDialog(userEdit.dataset.userEdit || '');
    else if (userReset) void openUserPasswordResetDialog(userReset.dataset.userReset || '');
    else void openGroupRenameDialog(groupRename.dataset.renameGroup || '');
  }

  function selectLabel(select) {
    return select.selectedOptions[0]?.textContent?.trim() || '请选择';
  }

  function syncSearchableSelect(select) {
    const wrapper = select.closest('.v062-search-select');
    const label = wrapper?.querySelector('.v062-select-trigger-label');
    if (label) label.textContent = selectLabel(select);
  }

  function openSearchableSelect(select) {
    const options = [...select.options].filter(option => !option.disabled);
    const modal = showModal(select.closest('.field')?.querySelector('label')?.textContent?.trim() || '选择项目', `<div class="field"><label for="v062SelectSearch">搜索</label><input id="v062SelectSearch" class="input" type="search" placeholder="输入关键词筛选"></div><div id="v062SelectOptions" class="v062-select-option-grid" role="listbox"></div>`, { narrow: true });
    const list = $('#v062SelectOptions', modal.root);
    const render = query => {
      const keyword = String(query || '').trim().toLocaleLowerCase();
      const filtered = options.filter(option => !keyword || option.textContent.toLocaleLowerCase().includes(keyword));
      list.innerHTML = filtered.length ? filtered.map(option => `<button type="button" class="v062-select-option ${option.selected ? 'active' : ''}" data-v062-option="${esc(option.value)}" role="option" aria-selected="${option.selected ? 'true' : 'false'}"><span>${esc(option.textContent.trim())}</span>${option.selected ? '<small>当前选择</small>' : ''}</button>`).join('') : '<div class="empty">没有匹配的选项</div>';
      $$('[data-v062-option]', list).forEach(button => {
        button.onclick = () => {
          select.value = button.dataset.v062Option || '';
          select.dispatchEvent(new Event('input', { bubbles: true }));
          select.dispatchEvent(new Event('change', { bubbles: true }));
          syncSearchableSelect(select);
          modal.close();
        };
      });
    };
    const search = $('#v062SelectSearch', modal.root);
    search.oninput = () => render(search.value);
    render('');
    requestAnimationFrame(() => search.focus());
  }

  function enhanceSearchableSelect(select) {
    if (!(select instanceof HTMLSelectElement) || select.dataset.v062Searchable === '1') return;
    if (!SEARCHABLE_SELECT_ID.test(select.id || select.name || '')) return;
    if (select.options.length <= SEARCHABLE_OPTION_THRESHOLD) return;
    const wrapper = document.createElement('div');
    wrapper.className = 'v062-search-select';
    select.parentNode.insertBefore(wrapper, select);
    wrapper.appendChild(select);
    select.classList.add('v062-native-select');
    select.dataset.v062Searchable = '1';
    const trigger = document.createElement('button');
    trigger.type = 'button';
    trigger.className = 'v062-select-trigger';
    trigger.setAttribute('aria-haspopup', 'dialog');
    trigger.innerHTML = '<span class="v062-select-trigger-label"></span><span aria-hidden="true">⌄</span>';
    wrapper.appendChild(trigger);
    trigger.onclick = () => openSearchableSelect(select);
    select.addEventListener('change', () => syncSearchableSelect(select));
    syncSearchableSelect(select);
  }

  function accountUser() {
    const auth = E.state.auth || {};
    return auth.user || auth;
  }

  async function renderSessions(panel) {
    if (!panel || panel.dataset.loading === '1') return;
    panel.dataset.loading = '1';
    panel.innerHTML = '<div class="loading-card">正在读取登录设备…</div>';
    try {
      await ensureContext(true);
      const response = await api('/api/auth/sessions');
      const data = response.data || {};
      const sessions = data.items || [];
      const others = sessions.filter(session => !session.current);
      panel.innerHTML = `<div class="v062-session-head"><div><h3>登录设备</h3><p>当前 ${sessions.length}/${Number(data.limit || 10)} 个有效 Token；超过上限时最久未连接的会话自动失效。</p></div><button type="button" class="btn" id="v062RevokeOtherSessions" ${others.length ? '' : 'disabled'}>退出其他设备</button></div><div class="v062-session-list">${sessions.map(session => `<article class="v062-session-row"><div><strong>${esc(session.user_agent || '未知设备')}</strong><p>${esc(session.remote_addr || '未知地址')} · 最近活动 ${esc(formatDate(session.last_seen_at))}<br>登录 ${esc(formatDate(session.created_at))} · 过期 ${esc(formatDate(session.expires_at))}</p></div>${session.current ? '<span class="badge good">当前设备</span>' : `<button type="button" class="btn danger small" data-v062-revoke-session="${esc(session.id)}">退出</button>`}</article>`).join('')}</div>`;
      const revokeOthers = $('#v062RevokeOtherSessions', panel);
      if (revokeOthers) revokeOthers.onclick = async () => {
        revokeOthers.disabled = true;
        try {
          const result = await api('/api/auth/sessions/revoke-others', { method: 'POST' });
          toast(`已退出 ${result.data?.revoked || 0} 个其他设备`, 'good');
          panel.dataset.loading = '0';
          await renderSessions(panel);
        } catch (error) {
          toast(error.message, 'bad');
          revokeOthers.disabled = false;
        }
      };
      $$('[data-v062-revoke-session]', panel).forEach(button => {
        button.onclick = async () => {
          button.disabled = true;
          try {
            await api(`/api/auth/sessions/${encodeURIComponent(button.dataset.v062RevokeSession || '')}`, { method: 'DELETE' });
            toast('设备已退出', 'good');
            panel.dataset.loading = '0';
            await renderSessions(panel);
          } catch (error) {
            toast(error.message, 'bad');
            button.disabled = false;
          }
        };
      });
    } catch (error) {
      panel.innerHTML = `<div class="notice bad">${esc(error.message)}</div>`;
    } finally {
      panel.dataset.loading = '0';
    }
  }

  async function openOwnDisplayNameDialog() {
    try {
      await ensureContext(true);
      const user = accountUser();
      const modal = showModal('修改我的显示名', `<form id="v062OwnProfileForm" class="form-grid"><div class="notice full">登录账号：<strong>${esc(user.username || '')}</strong></div><div class="field full"><label for="v062OwnDisplayName">中文显示名</label><input id="v062OwnDisplayName" class="input" value="${esc(user.display_name || '')}" minlength="2" maxlength="12" required></div><div class="field full">${modalActions('保存')}</div></form>`, { narrow: true });
      bindCancel(modal);
      const form = $('#v062OwnProfileForm', modal.root);
      form.onsubmit = async event => {
        event.preventDefault();
        const button = $('button[type="submit"]', form);
        button.disabled = true;
        try {
          await api('/api/auth/profile', { method: 'PATCH', body: { display_name: $('#v062OwnDisplayName', modal.root).value.trim() } });
          E.state.contextLoadedAt = 0;
          modal.close();
          toast('显示名已更新', 'good');
          refreshCurrentPage();
        } catch (error) {
          toast(error.message, 'bad');
        } finally {
          button.disabled = false;
        }
      };
    } catch (error) {
      toast(error.message, 'bad');
    }
  }

  function activateAccountTab(root, tab) {
    const value = tab === 'website' ? 'website' : 'bilibili';
    try { sessionStorage.setItem('bili-v062-account-tab', value); } catch (_) {}
    $$('[data-v062-account-tab]', root).forEach(button => {
      const active = button.dataset.v062AccountTab === value;
      button.classList.toggle('active', active);
      button.setAttribute('aria-selected', active ? 'true' : 'false');
    });
    $$('[data-v062-account-panel]', root).forEach(panel => {
      panel.classList.toggle('hidden', panel.dataset.v062AccountPanel !== value);
    });
    if (value === 'website') void renderSessions($('#v062SessionPanel', root));
  }

  function applyAccountLayout() {
    if (currentPage() !== 'account') return;
    const root = $('#pageRoot');
    if (!root || root.dataset.v062AccountLayout === '1') return;
    const cards = $$(':scope > .grid > section.card', root);
    const bilibili = cards.find(card => card.querySelector('h2')?.textContent.includes('Bilibili'));
    const website = cards.find(card => /网站管理员|网站账号/.test(card.querySelector('h2')?.textContent || ''));
    if (!bilibili || !website) return;
    root.dataset.v062AccountLayout = '1';
    const grid = bilibili.parentElement;
    grid.classList.remove('cols-2');
    grid.classList.add('v062-account-grid');
    bilibili.dataset.v062AccountPanel = 'bilibili';
    website.dataset.v062AccountPanel = 'website';
    const heading = website.querySelector('h2');
    const description = website.querySelector('.card-head p');
    if (heading) heading.textContent = '网站账号';
    if (description) description.textContent = '管理当前网站账号、密码和登录设备；与 Bilibili 登录完全独立。';
    const user = accountUser();
    const summary = document.createElement('div');
    summary.className = 'v062-account-summary';
    summary.innerHTML = `<div><span class="metric-foot">当前网站账号</span><strong>${esc(user.display_name || user.username || '用户')}</strong><small>${esc(user.username || '')}</small></div><button type="button" class="btn" id="v062EditOwnDisplayName">修改显示名</button>`;
    website.insertBefore(summary, website.querySelector('form, button#accountLogout'));
    const sessions = document.createElement('div');
    sessions.id = 'v062SessionPanel';
    sessions.className = 'v062-session-panel';
    website.appendChild(sessions);
    const editOwn = $('#v062EditOwnDisplayName', website);
    if (editOwn) editOwn.onclick = () => void openOwnDisplayNameDialog();
    const tabs = document.createElement('div');
    tabs.id = 'v062AccountTabs';
    tabs.className = 'v062-account-tabs';
    tabs.setAttribute('role', 'tablist');
    tabs.innerHTML = '<button type="button" class="active" data-v062-account-tab="bilibili" role="tab" aria-selected="true">Bilibili 登录</button><button type="button" data-v062-account-tab="website" role="tab" aria-selected="false">网站账号与设备</button>';
    root.insertBefore(tabs, grid);
    $$('[data-v062-account-tab]', tabs).forEach(button => {
      button.onclick = () => activateAccountTab(root, button.dataset.v062AccountTab || 'bilibili');
    });
    let initial = 'bilibili';
    try { initial = sessionStorage.getItem('bili-v062-account-tab') || 'bilibili'; } catch (_) {}
    activateAccountTab(root, initial);
  }

  function applyEnhancements() {
    if (applying) return;
    applying = true;
    try {
      $$('select').forEach(enhanceSearchableSelect);
      applyAccountLayout();
      $$('select[data-v062-searchable="1"]').forEach(syncSearchableSelect);
    } finally {
      applying = false;
    }
  }

  function scheduleApply() {
    requestAnimationFrame(applyEnhancements);
  }

  document.addEventListener('click', interceptLegacyPromptActions, true);
  document.addEventListener('change', event => {
    if (event.target instanceof HTMLSelectElement) syncSearchableSelect(event.target);
  });

  const start = () => {
    const root = $('#pageRoot');
    if (root) new MutationObserver(scheduleApply).observe(root, { childList: true, subtree: true });
    const modalRoot = $('#modalRoot');
    if (modalRoot) new MutationObserver(scheduleApply).observe(modalRoot, { childList: true, subtree: true });
    window.addEventListener('hashchange', scheduleApply);
    scheduleApply();
  };
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start, { once: true });
  else start();
})();
