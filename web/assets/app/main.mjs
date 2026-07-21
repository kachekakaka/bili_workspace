import { AuthExpiredError, createApiClient } from './core/api.mjs';
import { createSessionStore } from './core/auth-session.mjs';
import { createContextStore } from './core/context-store.mjs';
import { resolveRoute } from './core/route-policy.mjs';
import { createRouter } from './core/router.mjs';
import { createTaskStream } from './core/task-stream.mjs';
import { createModalService } from './components/modal.mjs';
import { createToastService } from './components/toast.mjs';
import { createConfirmDialog } from './components/confirm-dialog.mjs';
import { mountSearchableSelect } from './components/searchable-select.mjs';
import { legacyBridge } from './legacy/bridge.mjs';
import * as dashboardPage from './pages/dashboard.mjs';
import * as downloadPage from './pages/download.mjs';
import * as searchPage from './pages/search.mjs';
import * as libraryPage from './pages/library.mjs';
import * as groupsPage from './pages/groups.mjs';
import * as tasksPage from './pages/tasks.mjs';
import * as usersPage from './pages/users.mjs';
import * as accountPage from './pages/account.mjs';
import * as settingsPage from './pages/settings.mjs';
import * as morePage from './pages/more.mjs';

const ADMIN_NAV = Object.freeze([
  ['dashboard', '⌂', '概览'], ['download', '↓', '下载'], ['search', '⌕', '搜索'],
  ['library', '▶', '作品库'], ['groups', '▣', '分组'], ['tasks', '≡', '任务'],
  ['users', '♙', '用户管理'], ['account', '◎', '账号'], ['settings', '⚙', '设置'],
]);
const USER_NAV = Object.freeze([['download', '↓', '下载'], ['tasks', '≡', '任务']]);
const ADMIN_MOBILE_NAV = Object.freeze([ADMIN_NAV[1], ADMIN_NAV[2], ADMIN_NAV[3], ADMIN_NAV[5], ['more', '•••', '更多']]);
const TITLES = Object.freeze({
  dashboard: ['PRIVATE MEDIA WORKSPACE', '概览'], download: ['DOWNLOAD & EXPORT', '创建下载'],
  search: ['SEARCH BILIBILI', '搜索作品'], library: ['MEDIA LIBRARY', '作品库'],
  groups: ['COLLECTION MANAGEMENT', '分组管理'], tasks: ['DOWNLOAD QUEUE', '任务中心'],
  users: ['USER MANAGEMENT', '用户管理'], account: ['ACCOUNT & QR LOGIN', '账号'],
  settings: ['SERVER SETTINGS', '设置'], more: ['MORE', '更多'],
});
const PAGE_MODULES = Object.freeze({
  dashboard: dashboardPage, download: downloadPage, search: searchPage, library: libraryPage,
  groups: groupsPage, tasks: tasksPage, users: usersPage, account: accountPage,
  settings: settingsPage, more: morePage,
});

const authRoot = document.querySelector('#authRoot');
const appRoot = document.querySelector('#appRoot');
const pageRoot = document.querySelector('#pageRoot');
const modal = createModalService(document.querySelector('#modalRoot'));
const toast = createToastService(document.querySelector('#toastRoot'));
const confirmDialog = createConfirmDialog(modal);
const session = createSessionStore();
const shared = createContextStore();
const taskStream = createTaskStream();
let router = null;
let authController = null;
let chromeController = null;
let expiring = false;

const api = createApiClient({
  getCsrfToken: () => session.get().csrfToken,
  onAuthExpired: error => expireSession(error),
});

function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>'"]/g, character => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;',
  }[character]));
}

function syncLegacy() {
  const legacy = legacyBridge.state();
  if (!legacy) return;
  const snapshot = shared.get();
  legacy.auth = {
    ...session.get(),
    csrf_token: session.get().csrfToken,
    display_name: session.get().displayName,
    must_change_password: session.get().mustChangePassword,
  };
  legacy.csrf = session.get().csrfToken;
  legacy.status = snapshot.status || null;
  legacy.groups = [...(snapshot.groups || [])];
  legacy.tags = [...(snapshot.tags || [])];
  legacy.contextLoadedAt = Date.now();
}

async function refreshShared({ signal } = {}) {
  const statusResponse = await api('/api/status', { signal });
  let groups = [];
  let tags = [];
  if (session.isAdmin()) {
    const [groupsResponse, tagsResponse] = await Promise.all([
      api('/api/groups', { signal }),
      api('/api/enhancements/tags', { signal }),
    ]);
    groups = groupsResponse.data?.records || [];
    tags = tagsResponse.data?.items || [];
  }
  shared.replace({ status: statusResponse.data || {}, groups, tags });
  syncLegacy();
  renderStatusBadges();
  return shared.get();
}

function closeLegacyStream() {
  const source = legacyBridge.state()?.tasks?.eventSource;
  if (source) source.close();
  if (legacyBridge.state()?.tasks) legacyBridge.state().tasks.eventSource = null;
}

function stopApp({ clear = false } = {}) {
  router?.stop();
  router = null;
  chromeController?.abort();
  chromeController = null;
  taskStream.stop({ clear });
  closeLegacyStream();
  modal.dispose();
  if (clear) {
    shared.clear();
    pageRoot.replaceChildren();
  }
}

async function expireSession(error) {
  if (expiring) return;
  expiring = true;
  stopApp({ clear: true });
  session.clear();
  appRoot.classList.add('hidden');
  showLogin({ authenticated: false, setup_required: false }, error?.message || '登录已失效，请重新登录');
  expiring = false;
}

function userValue() {
  const value = session.get();
  return value.user || {
    username: value.username,
    display_name: value.displayName,
    role: value.role,
  };
}

function setActiveRoute(page) {
  for (const item of document.querySelectorAll('[data-page]')) {
    item.classList.toggle('active', item.dataset.page === page);
  }
  const [kicker, title] = TITLES[page] || ['', page];
  document.querySelector('#pageKicker').textContent = kicker;
  document.querySelector('#pageTitle').textContent = title;
}

function renderStatusBadges() {
  const status = shared.get().status || {};
  const badge = document.querySelector('#biliBadge');
  if (!badge) return;
  const state = status.login_state || 'unknown';
  badge.className = `badge ${state === 'valid' ? 'good' : state === 'invalid' ? 'bad' : 'warn'}`;
  badge.textContent = state === 'valid' ? 'B站已登录' : state === 'invalid' ? 'B站未登录' : 'B站状态未知';
}

function closeUserMenu() {
  document.querySelector('#userMenuPanel')?.classList.add('hidden');
  document.querySelector('#userMenuButton')?.setAttribute('aria-expanded', 'false');
}

function renderChrome() {
  chromeController?.abort();
  chromeController = new AbortController();
  const signal = chromeController.signal;
  const admin = session.isAdmin();
  const desktop = admin ? ADMIN_NAV : USER_NAV;
  const mobile = admin ? ADMIN_MOBILE_NAV : USER_NAV;
  document.querySelector('#desktopNav').innerHTML = desktop.map(([id, icon, label]) => `<a class="nav-item" data-page="${id}" href="#/${id}"><span>${icon}</span><span>${label}</span></a>`).join('');
  document.querySelector('#mobileNav').innerHTML = mobile.map(([id, icon, label]) => `<a class="nav-item mobile-nav-item" data-page="${id}" href="#/${id}"><span>${icon}</span><small>${label}</small></a>`).join('');
  const user = userValue();
  const name = user.display_name || user.username || '用户';
  document.querySelector('#userMenuRoot').classList.remove('hidden');
  document.querySelector('#userMenuName').textContent = name;
  document.querySelector('#userMenuRole').textContent = admin ? '管理员' : '普通用户';
  document.querySelector('#userMenuAvatar').textContent = name.slice(0, 1) || '用';
  document.querySelector('#userMenuPanel').innerHTML = `<div class="user-menu-summary"><strong>${escapeHtml(name)}</strong><small>${escapeHtml(user.username || '')} · ${admin ? '管理员' : '普通用户'}</small></div><button type="button" role="menuitem" data-menu-account>网站账号与设备</button><button type="button" role="menuitem" data-menu-bilibili>Bilibili 登录</button><button type="button" role="menuitem" data-menu-logout>退出网站</button>`;

  document.querySelector('#userMenuButton').addEventListener('click', () => {
    const panel = document.querySelector('#userMenuPanel');
    const expanded = panel.classList.toggle('hidden') === false;
    document.querySelector('#userMenuButton').setAttribute('aria-expanded', expanded ? 'true' : 'false');
  }, { signal });
  document.querySelector('#userMenuPanel').addEventListener('click', event => {
    const button = event.target.closest('button');
    if (!button) return;
    closeUserMenu();
    if (button.dataset.menuLogout !== undefined) void logout();
    else {
      try { sessionStorage.setItem('bili-v062-account-tab', button.dataset.menuAccount !== undefined ? 'website' : 'bilibili'); } catch {}
      navigate('account');
    }
  }, { signal });
  document.querySelector('#pageTitle').addEventListener('click', closeUserMenu, { signal });
  pageRoot.addEventListener('click', closeUserMenu, { signal });
  document.querySelector('#refreshButton').addEventListener('click', async () => {
    const button = document.querySelector('#refreshButton');
    button.disabled = true;
    try {
      await refreshShared({ signal });
      await remount();
      toast.show('已刷新', 'good');
    } catch (error) {
      if (error?.name !== 'AbortError' && !(error instanceof AuthExpiredError)) toast.show(error.message, 'bad');
    } finally {
      button.disabled = false;
    }
  }, { signal });
  document.querySelector('#logoutButton').classList.remove('hidden');
  document.querySelector('#logoutButton').addEventListener('click', () => void logout(), { signal });
  document.querySelector('#connectionDot').className = 'dot online';
  document.querySelector('#connectionText').textContent = '已连接';
  setActiveRoute(router?.current()?.route || resolveRoute(location.hash, session.get().role).route);
  renderStatusBadges();
}

function appContext(routeContext) {
  return Object.freeze({
    ...routeContext,
    api,
    session,
    shared,
    taskStream,
    modal,
    toast,
    confirm: confirmDialog,
    mountSearchableSelect,
    legacy: legacyBridge,
    syncLegacy,
    refreshShared,
    renderChrome,
    logout,
    navigate,
    remount,
  });
}

function routeMount(page) {
  return async (root, routeContext) => {
    setActiveRoute(page);
    const module = PAGE_MODULES[page];
    return module.mount(root, appContext(routeContext));
  };
}

function createAppRouter() {
  const routes = Object.fromEntries(Object.keys(PAGE_MODULES).map(page => [page, routeMount(page)]));
  return createRouter({
    root: pageRoot,
    routes,
    resolve: hash => resolveRoute(hash, session.get().role),
    onError(error) {
      if (error instanceof AuthExpiredError || error?.name === 'AbortError') return;
      pageRoot.innerHTML = `<div class="notice bad">${escapeHtml(error.message)}</div>`;
      toast.show(error.message, 'bad');
    },
  });
}

function navigate(page, options = {}) {
  if (router) return router.navigate(page, options);
  location.hash = `#/${page}`;
  return location.hash;
}

async function remount() {
  if (!router) return null;
  return router.transition(location.hash);
}

async function bootAuthenticated() {
  authController?.abort();
  authRoot.classList.add('hidden');
  appRoot.classList.remove('hidden');
  await refreshShared();
  renderChrome();
  router = createAppRouter();
  router.start();
}

function showForcedPassword(auth) {
  stopApp({ clear: true });
  authController?.abort();
  authController = new AbortController();
  const signal = authController.signal;
  appRoot.classList.add('hidden');
  authRoot.classList.remove('hidden');
  authRoot.innerHTML = `<section class="auth-card"><div class="auth-brand"><span class="brand-mark">b</span><div><h1>首次修改密码</h1><p>${escapeHtml(auth.display_name || auth.username)}（${escapeHtml(auth.username)}）</p></div></div><div class="notice warn">临时密码只能用于首次登录。修改完成前不能访问下载、搜索、任务或设置。</div><form id="passwordChangeForm" class="form-grid" style="margin-top:18px"><div class="field full"><label>当前临时密码</label><input class="input" id="currentPassword" type="password" autocomplete="current-password" required></div><div class="field full"><label>新密码</label><input class="input" id="newPassword" type="password" autocomplete="new-password" minlength="10" maxlength="64" required></div><div class="field full"><label>再次输入新密码</label><input class="input" id="confirmPassword" type="password" autocomplete="new-password" minlength="10" maxlength="64" required></div><div class="field full"><button class="btn primary" type="submit">修改密码并继续</button></div><div class="field full"><button class="btn" id="forcedLogout" type="button">退出登录</button></div></form></section>`;
  authRoot.querySelector('#passwordChangeForm').addEventListener('submit', async event => {
    event.preventDefault();
    const button = event.currentTarget.querySelector('button[type="submit"]');
    button.disabled = true;
    try {
      if (authRoot.querySelector('#newPassword').value !== authRoot.querySelector('#confirmPassword').value) throw new Error('两次输入的新密码不一致');
      const payload = await api('/api/auth/password', { method: 'POST', body: { current_password: authRoot.querySelector('#currentPassword').value, new_password: authRoot.querySelector('#newPassword').value } });
      session.patch({ csrf_token: payload.data?.csrf_token || session.get().csrfToken, must_change_password: false });
      toast.show('密码已修改', 'good');
      await bootAuth();
    } catch (error) {
      toast.show(error.message, 'bad');
    } finally {
      button.disabled = false;
    }
  }, { signal });
  authRoot.querySelector('#forcedLogout').addEventListener('click', () => void logout(), { signal });
}

function showLogin(auth, message = '') {
  stopApp({ clear: true });
  authController?.abort();
  authController = new AbortController();
  const signal = authController.signal;
  appRoot.classList.add('hidden');
  authRoot.classList.remove('hidden');
  const setup = Boolean(auth.setup_required ?? auth.setupRequired);
  authRoot.innerHTML = `<section class="auth-card"><div class="auth-brand"><span class="brand-mark">b</span><div><h1>bili workspace</h1><p>${setup ? '首次初始化 NAS 管理员' : '登录私人媒体库'}</p></div></div>${message ? `<div class="notice warn">${escapeHtml(message)}</div>` : ''}${setup ? `<div class="notice">${escapeHtml(auth.bootstrap_hint || '请读取 bootstrap-token.txt')}。初始化成功后令牌立即作废。</div>` : ''}<form id="authForm" class="form-grid" style="margin-top:18px"><div class="field full"><label>登录账号</label><input class="input" id="authUser" autocomplete="username" required minlength="3"></div><div class="field full"><label>密码</label><input class="input" id="authPassword" type="password" autocomplete="${setup ? 'new-password' : 'current-password'}" required minlength="${setup ? 10 : 1}"></div>${setup ? '<div class="field full"><label>中文显示名</label><input class="input" id="authDisplayName" value="管理员" minlength="2" maxlength="12" required></div><div class="field full"><label>一次性初始化令牌</label><input class="input" id="authToken" type="password" required></div>' : ''}<div class="field full"><button class="btn primary" type="submit">${setup ? '创建管理员并登录' : '登录'}</button></div></form></section>`;
  authRoot.querySelector('#authForm').addEventListener('submit', async event => {
    event.preventDefault();
    const button = event.currentTarget.querySelector('button');
    button.disabled = true;
    try {
      const payload = setup
        ? await api('/api/auth/setup', { method: 'POST', body: { username: authRoot.querySelector('#authUser').value, display_name: authRoot.querySelector('#authDisplayName').value, password: authRoot.querySelector('#authPassword').value, bootstrap_token: authRoot.querySelector('#authToken').value } })
        : await api('/api/auth/login', { method: 'POST', body: { username: authRoot.querySelector('#authUser').value, password: authRoot.querySelector('#authPassword').value } });
      session.patch({ csrf_token: payload.data?.csrf_token || '' });
      toast.show('登录成功', 'good');
      await bootAuth();
    } catch (error) {
      toast.show(error.message, 'bad');
    } finally {
      button.disabled = false;
    }
  }, { signal });
}

async function logout() {
  try {
    if (session.get().authenticated) await api('/api/auth/logout', { method: 'POST' });
  } catch (error) {
    if (!(error instanceof AuthExpiredError)) toast.show(error.message, 'bad');
  } finally {
    stopApp({ clear: true });
    session.clear();
    await bootAuth();
  }
}

async function bootAuth() {
  expiring = false;
  const response = await api('/api/auth/status');
  const auth = response.data || {};
  session.set(auth);
  syncLegacy();
  if (auth.authenticated && (auth.must_change_password || auth.mustChangePassword)) {
    showForcedPassword(auth);
  } else if (auth.authenticated) {
    await bootAuthenticated();
  } else {
    showLogin(auth);
  }
}

async function boot() {
  try {
    await bootAuth();
  } catch (error) {
    authRoot.classList.remove('hidden');
    authRoot.innerHTML = `<section class="auth-card"><div class="notice bad">${escapeHtml(error.message)}</div><button type="button" id="retryBoot" class="btn primary" style="margin-top:14px">重试</button></section>`;
    authRoot.querySelector('#retryBoot').addEventListener('click', () => void boot());
  }
}

if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', () => void boot(), { once: true });
else void boot();
