(() => {
  'use strict';

  const $ = (selector, root = document) => root.querySelector(selector);
  const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
  const esc = value => String(value ?? '').replace(/[&<>'"]/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[ch]));
  const state = {
    auth: null, csrf: '', status: null, groups: [], tasks: [], taskSummary: {},
    events: null, page: '',
    library: { q: '', groupId: '', sort: 'newest', codec: '', minHeight: 0, watched: '', page: 1, data: null },
  };
  const NAV = [
    ['dashboard','⌂','概览'], ['download','↓','下载'], ['search','⌕','搜索'],
    ['library','▶','作品库'], ['groups','▣','分组'], ['tasks','≡','任务'],
    ['account','◎','账号'], ['settings','⚙','设置'],
  ];
  const MOBILE_NAV = [NAV[1], NAV[2], NAV[3], NAV[5], ['more','•••','更多']];
  const TITLES = {
    dashboard:['PRIVATE MEDIA WORKSPACE','概览'], download:['DOWNLOAD & EXPORT','创建下载'],
    search:['SEARCH BILIBILI','搜索作品'], library:['MEDIA LIBRARY','作品库'],
    groups:['COLLECTION MANAGEMENT','分组管理'], tasks:['DOWNLOAD QUEUE','任务中心'],
    account:['ACCOUNT & QR LOGIN','账号'], settings:['SERVER SETTINGS','设置'], more:['MORE','更多'],
  };
  const QUALITY_OPTIONS = [[0,'不限制'],[360,'至少 360P'],[480,'至少 480P'],[720,'至少 720P'],[1080,'至少 1080P'],[1440,'至少 2K / 1440P'],[2160,'至少 4K'],[4320,'至少 8K']];

  function formatBytes(value) {
    const n = Number(value);
    if (!Number.isFinite(n) || n < 0) return '-';
    if (n === 0) return '0 B';
    const units = ['B','KB','MB','GB','TB','PB'];
    const i = Math.min(units.length - 1, Math.floor(Math.log(n) / Math.log(1024)));
    const v = n / Math.pow(1024, i);
    return `${v.toFixed(i === 0 || v >= 100 ? 0 : v >= 10 ? 1 : 2)} ${units[i]}`;
  }
  function formatDate(value, onlyDate = false) {
    if (!value) return '-';
    const n = Number(value); const d = new Date(n * (n < 1e12 ? 1000 : 1));
    if (Number.isNaN(d.getTime())) return '-';
    return onlyDate ? d.toLocaleDateString() : d.toLocaleString();
  }
  function formatPlay(value) {
    const n = Number(value); if (!Number.isFinite(n)) return '-';
    if (n >= 1e8) return `${(n/1e8).toFixed(n>=1e9?0:1)}亿`;
    if (n >= 1e4) return `${(n/1e4).toFixed(n>=1e5?0:1)}万`;
    return String(Math.round(n));
  }
  function statusLabel(status) {
    return ({queued:'排队中',running:'下载中',success:'已完成',skipped:'已跳过',failed:'失败',cancelled:'已取消'})[status] || status || '未知';
  }
  function statusClass(status) {
    if (status === 'success') return 'good';
    if (status === 'failed' || status === 'cancelled') return 'bad';
    if (status === 'running' || status === 'queued') return 'warn';
    return 'neutral';
  }
  function cover(value) {
    return String(value || '').startsWith('https://') ? `/api/cover?url=${encodeURIComponent(String(value))}` : `data:image/svg+xml,${encodeURIComponent('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 640 360"><rect width="640" height="360" fill="#e8edf5"/><path d="M275 125l115 55-115 55z" fill="#94a3b8"/><text x="320" y="290" text-anchor="middle" font-family="sans-serif" font-size="23" fill="#64748b">暂无封面</text></svg>')}`;
  }
  function bindCoverFallback(root = document) {
    $$('img[data-cover-img]', root).forEach(image => {
      image.onerror = () => { image.onerror = null; image.src = cover(''); };
    });
  }
  function qualityOptions(selected = 1080) {
    return QUALITY_OPTIONS.map(([value,label]) => `<option value="${value}" ${Number(selected)===value?'selected':''}>${label}</option>`).join('');
  }
  function groupOptions(selected = '', includeAll = false) {
    const prefix = includeAll ? '<option value="">全部分组</option>' : '';
    return prefix + state.groups.map(group => `<option value="${esc(group.id)}" ${group.id===selected?'selected':''}>${esc(group.display_name)}</option>`).join('');
  }
  function toast(message, type = '') {
    const node = document.createElement('div');
    node.className = `toast ${type}`; node.textContent = message;
    $('#toastRoot').appendChild(node);
    setTimeout(() => node.remove(), 3800);
  }
  function showModal(title, body, { narrow = false, onClose = null } = {}) {
    const root = $('#modalRoot');
    root.classList.remove('hidden');
    root.innerHTML = `<section class="modal ${narrow?'narrow':''}"><header class="modal-head"><h2>${esc(title)}</h2><button class="close-button" aria-label="关闭">×</button></header><div class="modal-body">${body}</div></section>`;
    const close = () => { root.dispatchEvent(new Event('modalclose')); root.classList.add('hidden'); root.innerHTML = ''; if (onClose) onClose(); };
    $('.close-button', root).onclick = close;
    root.onclick = event => { if (event.target === root) close(); };
    return { root, close };
  }

  async function api(path, { method = 'GET', body, raw = false } = {}) {
    const headers = { 'Accept': 'application/json' };
    if (body !== undefined) headers['Content-Type'] = 'application/json';
    if (method !== 'GET' && method !== 'HEAD' && state.csrf) headers['X-CSRF-Token'] = state.csrf;
    let response;
    try {
      response = await fetch(path, { method, headers, body: body === undefined ? undefined : JSON.stringify(body), cache: 'no-store', credentials: 'same-origin' });
    } catch (error) {
      throw new Error(`无法连接服务：${error.message || '网络错误'}`);
    }
    if (raw) return response;
    let payload;
    try { payload = await response.json(); } catch (_) { throw new Error(`服务返回无效响应（HTTP ${response.status}）`); }
    if (response.status === 401 && !path.startsWith('/api/auth/')) {
      await bootAuth();
      throw new Error('登录已失效，请重新登录');
    }
    if (!response.ok || !payload.ok) {
      const detail = Array.isArray(payload.detail) ? payload.detail.map(item => item.msg).join('；') : '';
      throw new Error(payload.error || detail || `请求失败（HTTP ${response.status}）`);
    }
    return payload;
  }

  async function bootAuth() {
    if (state.events) { state.events.close(); state.events = null; }
    const result = await api('/api/auth/status');
    state.auth = result.data;
    state.csrf = result.data.csrf_token || '';
    if (result.data.authenticated) {
      $('#authRoot').classList.add('hidden');
      $('#appRoot').classList.remove('hidden');
      await bootApp();
      return;
    }
    $('#appRoot').classList.add('hidden');
    const root = $('#authRoot'); root.classList.remove('hidden');
    const setup = result.data.setup_required;
    root.innerHTML = `<section class="auth-card">
      <div class="auth-brand"><span class="brand-mark">b</span><div><h1>bili workspace</h1><p>${setup?'首次初始化 NAS 管理员':'登录私人媒体库'}</p></div></div>
      ${setup?`<div class="notice">${esc(result.data.bootstrap_hint || '请读取 bootstrap-token.txt')}。初始化成功后令牌立即作废。</div>`:''}
      <form id="authForm" class="form-grid" style="margin-top:18px">
        <div class="field full"><label>管理员用户名</label><input class="input" id="authUser" autocomplete="username" required minlength="3"></div>
        <div class="field full"><label>密码</label><input class="input" id="authPassword" type="password" autocomplete="${setup?'new-password':'current-password'}" required minlength="${setup?10:1}"></div>
        ${setup?'<div class="field full"><label>一次性初始化令牌</label><input class="input" id="authToken" type="password" required></div>':''}
        <div class="field full"><button class="btn primary" type="submit">${setup?'创建管理员并登录':'登录'}</button></div>
      </form></section>`;
    $('#authForm').onsubmit = async event => {
      event.preventDefault();
      const button = $('button', event.currentTarget); button.disabled = true;
      try {
        const payload = setup
          ? await api('/api/auth/setup', { method:'POST', body:{ username:$('#authUser').value, password:$('#authPassword').value, bootstrap_token:$('#authToken').value } })
          : await api('/api/auth/login', { method:'POST', body:{ username:$('#authUser').value, password:$('#authPassword').value } });
        state.csrf = payload.data.csrf_token || '';
        toast('登录成功', 'good');
        await bootAuth();
      } catch (error) { toast(error.message, 'bad'); }
      finally { button.disabled = false; }
    };
  }

  function renderNav() {
    $('#desktopNav').innerHTML = NAV.map(([id,icon,label]) => `<a class="nav-item" data-page="${id}" href="#/${id}"><span class="nav-icon">${icon}</span><span>${label}</span></a>`).join('');
    $('#mobileNav').innerHTML = MOBILE_NAV.map(([id,icon,label]) => `<a class="nav-item" data-page="${id}" href="#/${id}"><span class="nav-icon">${icon}</span><span>${label}</span></a>`).join('');
  }
  function setActiveNav(page) {
    $$('.nav-item').forEach(node => node.classList.toggle('active', node.dataset.page === page));
    const [kicker,title] = TITLES[page] || TITLES.dashboard;
    $('#pageKicker').textContent = kicker; $('#pageTitle').textContent = title;
  }

  async function refreshGlobals() {
    const [statusRes, groupsRes, tasksRes] = await Promise.all([
      api('/api/status'), api('/api/groups'), api('/api/tasks'),
    ]);
    state.status = statusRes.data;
    state.groups = groupsRes.data.records || [];
    state.tasks = tasksRes.data || [];
    state.taskSummary = tasksRes.summary || {};
    $('#brandMode').textContent = `V${statusRes.data.version} · ${statusRes.data.server_mode ? 'NAS' : '本地'}`;
    $('#biliBadge').className = `badge ${statusRes.data.login_state === 'valid' ? 'good' : statusRes.data.login_state === 'unknown' ? 'warn' : 'neutral'}`;
    $('#biliBadge').textContent = statusRes.data.login_state === 'valid' ? 'B站已登录' : statusRes.data.login_state === 'unknown' ? '登录状态未知' : 'B站未登录';
    $('#connectionDot').className = 'dot good'; $('#connectionText').textContent = '服务已连接';
    $('#logoutButton').classList.toggle('hidden', !state.auth?.required);
  }

  function startEvents() {
    if (state.events) state.events.close();
    const events = new EventSource('/api/events'); state.events = events;
    events.addEventListener('tasks', event => {
      try {
        const payload = JSON.parse(event.data); state.tasks = payload.tasks || []; state.taskSummary = payload.summary || {};
        $('#connectionDot').className = 'dot good'; $('#connectionText').textContent = '实时连接';
        if (state.page === 'tasks') renderTaskListOnly();
        if (state.page === 'dashboard') updateDashboardMetrics();
      } catch (_) {}
    });
    events.onerror = () => { $('#connectionDot').className = 'dot'; $('#connectionText').textContent = '正在重连'; };
  }

  async function bootApp() {
    renderNav();
    $('#logoutButton').onclick = async () => {
      try { await api('/api/auth/logout', { method:'POST' }); state.csrf=''; await bootAuth(); }
      catch (error) { toast(error.message,'bad'); }
    };
    $('#refreshButton').onclick = async () => {
      try { await refreshGlobals(); await route(true); toast('已刷新','good'); }
      catch (error) { toast(error.message,'bad'); }
    };
    try { await refreshGlobals(); } catch (error) { toast(error.message,'bad'); }
    startEvents();
    if (!location.hash) location.hash = '#/dashboard';
    await route(true);
  }

  async function renderEnhancedPage(page, root) {
    const enhancements = window.BiliEnhancements;
    if (!enhancements?.renderPage) throw new Error(`增强页面未加载：${page}`);
    await enhancements.renderPage(page, root);
  }

  async function route(force = false) {
    const page = (location.hash.replace(/^#\//,'').split('?')[0] || 'dashboard');
    if (!force && page === state.page) return;
    state.page = page; setActiveNav(page);
    const root = $('#pageRoot'); root.innerHTML = '<div class="loading-card">正在载入…</div>';
    try {
      const renderer = ({dashboard:renderDashboard,download:renderDownload,search:root=>renderEnhancedPage('search',root),library:renderLibrary,groups:renderGroups,tasks:renderTasks,account:renderAccount,settings:renderSettings,more:renderMore})[page] || renderDashboard;
      await renderer(root);
    } catch (error) {
      root.innerHTML = `<div class="notice bad">${esc(error.message)}</div>`;
      toast(error.message,'bad');
    }
  }

  function metric(label, value, foot = '') {
    return `<section class="card metric-card"><span class="metric-label">${esc(label)}</span><strong class="metric-value">${esc(value)}</strong><span class="metric-foot">${esc(foot)}</span></section>`;
  }
  async function renderDashboard(root) {
    const [summaryRes, recentRes] = await Promise.all([api('/api/library/summary'), api('/api/library?page=1&page_size=6&sort=recent')]);
    const summary = summaryRes.data; const recent = recentRes.data.items || [];
    root.innerHTML = `<div id="dashboardMetrics" class="grid cols-4"></div>
      <div class="grid cols-2" style="margin-top:18px">
        <section class="card"><div class="card-head"><div><h2>最近观看与下载</h2><p>点击作品可直接在浏览器或手机上继续播放。</p></div><button class="btn small" data-go="library">查看全部</button></div><div class="media-grid">${recent.length?recent.map(libraryCard).join(''):'<div class="empty">作品库还是空的</div>'}</div></section>
        <section class="card"><div class="card-head"><div><h2>运行状态</h2><p>原始文件优先直放；兼容副本只在需要时手动生成。</p></div></div>
          <div class="grid cols-2">
            <div class="notice"><strong>运行模式</strong><br>${esc(state.status.server_mode?'QNAP / Docker 服务器':'Windows 本地')}</div>
            <div class="notice"><strong>Bilibili</strong><br>${esc(state.status.message || '未检测')}</div>
            <div class="notice"><strong>媒体目录</strong><br>${esc(state.status.download_dir || '-')}</div>
            <div class="notice"><strong>临时导出</strong><br>完整传输后立即删除；中断保留至 TTL</div>
          </div>
        </section>
      </div>`;
    root.dataset.mediaCount = summary.media_count || 0; root.dataset.mediaSize = summary.total_size || 0;
    updateDashboardMetrics(); bindLibraryCards(root);
    $('[data-go="library"]', root).onclick = () => { location.hash='#/library'; };
  }
  function updateDashboardMetrics() {
    const box = $('#dashboardMetrics'); if (!box) return;
    const root = $('#pageRoot');
    const mediaCount = Number(root.dataset.mediaCount || state.status?.library?.media_count || 0);
    const mediaSize = Number(root.dataset.mediaSize || state.status?.library?.total_size || 0);
    const s = state.taskSummary || {};
    box.innerHTML = metric('作品数量', mediaCount, '已进入私人媒体库') + metric('媒体占用', formatBytes(mediaSize), '不包含临时导出与缓存') + metric('活动任务', Number(s.active || 0), `排队 ${Number(s.queued||0)} · 运行 ${Number(s.running||0)}`) + metric('下载失败', Number(s.failed || 0), '可在任务中心查看日志并重试');
  }

  async function createGroupDialog(onCreated) {
    const modal = showModal('新建分组', `<form id="newGroupForm" class="form-grid"><div class="field full"><label>分组名称</label><input id="newGroupName" class="input" maxlength="60" placeholder="例如：摄影教程" required><small>显示名称可随时修改，磁盘目录标识保持稳定。</small></div><div class="field full"><button class="btn primary" type="submit">创建并选中</button></div></form>`, {narrow:true});
    $('#newGroupForm', modal.root).onsubmit = async event => {
      event.preventDefault(); const button = $('button',event.currentTarget); button.disabled=true;
      try {
        const result = await api('/api/groups',{method:'POST',body:{name:$('#newGroupName').value}});
        await refreshGroups(); modal.close(); toast('分组已创建','good'); if(onCreated)onCreated(result.data);
      } catch(error){toast(error.message,'bad');} finally{button.disabled=false;}
    };
  }
  async function refreshGroups() {
    const result = await api('/api/groups'); state.groups = result.data.records || [];
  }

  async function renderDownload(root) {
    const defaultGroup = state.groups.find(item => item.display_name === state.status.default_group) || state.groups[0];
    root.innerHTML = `<section class="card"><div class="card-head"><div><h2>创建下载</h2><p>保存到 NAS 会进入媒体库；导出到当前设备只使用专用临时目录。</p></div></div>
      <form id="downloadForm" class="form-grid">
        <div class="field full"><label>作品链接或 BV / av / ep / ss 编号</label><textarea id="downloadTargets" class="textarea" placeholder="每行一个，例如：&#10;BV1xxxxxxxxx&#10;https://www.bilibili.com/video/BV1xxxxxxxxx" required></textarea></div>
        <div class="field full"><label>下载目标</label><div class="segmented" id="destinationSegment"><button type="button" data-value="library" class="active">保存到 NAS 媒体库</button><button type="button" data-value="device">导出到当前设备</button></div><input type="hidden" id="downloadDestination" value="library"></div>
        <div class="field" id="downloadGroupField"><label>保存分组</label><div class="toolbar"><select id="downloadGroup" class="select" style="flex:1">${groupOptions(defaultGroup?.id||'')}</select><button type="button" class="btn" id="newGroupButton">＋ 新建</button></div><small>分组显示名可重命名，不会移动已有大文件。</small></div>
        <div class="field"><label>最低清晰度</label><select id="downloadQuality" class="select">${qualityOptions(state.status.default_min_height)}</select><small>预检或实际码流低于门槛时会失败，不会保存低清文件。</small></div>
        <div class="field"><label>重新下载策略</label><label style="font-weight:500"><input id="downloadForce" type="checkbox"> 强制重新下载并事务替换旧文件</label></div>
        <div class="field full"><div id="destinationNotice" class="notice">成品长期保存在 NAS，可在作品库中播放、下载到手机或移动分组。</div></div>
        <div class="field full"><button class="btn primary" type="submit">加入下载队列</button></div>
      </form></section>`;
    $$('#destinationSegment button',root).forEach(button => button.onclick = () => {
      $$('#destinationSegment button',root).forEach(item=>item.classList.toggle('active',item===button));
      $('#downloadDestination').value=button.dataset.value;
      const device=button.dataset.value==='device';
      $('#downloadGroupField').classList.toggle('hidden',device);
      $('#downloadForce').closest('.field').classList.toggle('hidden',device);
      $('#destinationNotice').className=`notice ${device?'warn':''}`;
      $('#destinationNotice').textContent=device?'NAS 完成下载与混流后提供一次性浏览器下载；服务器完整发送后立即删除临时文件，中断则保留到过期时间。':'成品长期保存在 NAS，可在作品库中播放、下载到手机或移动分组。';
    });
    $('#newGroupButton').onclick=()=>createGroupDialog(group=>{ $('#downloadGroup').innerHTML=groupOptions(group.id); });
    $('#downloadForm').onsubmit=async event=>{
      event.preventDefault(); const button=$('button[type="submit"]',event.currentTarget);button.disabled=true;
      const lines=$('#downloadTargets').value.split(/\r?\n/).map(v=>v.trim()).filter(Boolean);
      const bvids=lines.filter(v=>/^BV[0-9A-Za-z]+$/i.test(v)); const urls=lines.filter(v=>!/^BV[0-9A-Za-z]+$/i.test(v));
      try{
        const result=await api('/api/download',{method:'POST',body:{urls,bvids,items:[],force:$('#downloadForce').checked,group_id:$('#downloadGroup').value,group:'',destination:$('#downloadDestination').value,min_height:Number($('#downloadQuality').value)}});
        toast(`已创建 ${result.total} 个任务`,'good');location.hash='#/tasks';
      }catch(error){toast(error.message,'bad');}finally{button.disabled=false;}
    };
  }

  function libraryCard(item){
    const progress=Number(item.watch_duration)>0?Math.min(100,Number(item.watch_position)/Number(item.watch_duration)*100):0;
    return `<article class="media-card" data-media="${esc(item.id)}"><div class="cover-wrap"><img data-cover-img src="${esc(cover(item.cover))}" alt="" loading="lazy" referrerpolicy="no-referrer"><div class="cover-badges"><span class="badge brand">${esc(item.selected_quality||item.selected_resolution||'媒体')}</span>${item.watch_completed?'<span class="badge good">已看完</span>':''}</div></div><div class="media-body"><button class="media-title" data-open-media="${esc(item.id)}" style="border:0;background:none;padding:0;text-align:left;cursor:pointer">${esc(item.title||item.bvid||item.source_key)}</button><div class="media-meta"><span>${esc(item.author||'-')}</span><span>${esc(item.bvid||item.source_key)}</span></div><div class="media-meta"><span>${esc(item.group_name||'未分组')}</span><span>${formatBytes(item.total_size)}</span><span>${esc(item.selected_codec||'')}</span></div>${progress?`<div class="progress" title="观看进度"><span style="width:${progress}%"></span></div>`:''}<div class="media-actions"><button class="btn primary small" data-open-media="${esc(item.id)}">播放</button>${item.primary_file_id?`<a class="btn small" href="/api/media/${encodeURIComponent(item.primary_file_id)}/download">下载到设备</a>`:''}</div></div></article>`;
  }
  async function renderLibrary(root){
    root.innerHTML=`<section class="card"><div class="form-grid">
      <div class="field full"><label>作品关键词</label><input id="libraryQuery" class="input" value="${esc(state.library.q)}" placeholder="搜索标题、BV号或UP主"></div>
      <div class="field"><label>分组</label><select id="libraryGroup" class="select">${groupOptions(state.library.groupId,true)}</select></div>
      <div class="field"><label>排序</label><select id="librarySort" class="select"><option value="newest">最新下载</option><option value="recent">最近观看</option><option value="title">标题</option><option value="size">文件大小</option><option value="oldest">最早下载</option></select></div>
      <div class="field"><label>视频编码</label><select id="libraryCodec" class="select"><option value="">全部编码</option><option value="AVC">AVC / H.264</option><option value="HEVC">HEVC / H.265</option><option value="AV1">AV1</option></select></div>
      <div class="field"><label>最低实际清晰度</label><select id="libraryMinHeight" class="select">${qualityOptions(state.library.minHeight)}</select></div>
      <div class="field"><label>观看状态</label><select id="libraryWatched" class="select"><option value="">全部</option><option value="unwatched">未观看</option><option value="watching">观看中</option><option value="completed">已看完</option></select></div>
      <div class="field" style="align-self:end"><button id="librarySearch" class="btn primary">应用筛选</button></div>
    </div></section><section id="libraryResults" style="margin-top:18px"><div class="loading-card">正在读取作品库…</div></section>`;
    $('#librarySort').value=state.library.sort;$('#libraryCodec').value=state.library.codec;$('#libraryMinHeight').value=String(state.library.minHeight||0);$('#libraryWatched').value=state.library.watched;
    $('#librarySearch').onclick=()=>{state.library.q=$('#libraryQuery').value.trim();state.library.groupId=$('#libraryGroup').value;state.library.sort=$('#librarySort').value;state.library.codec=$('#libraryCodec').value;state.library.minHeight=Number($('#libraryMinHeight').value);state.library.watched=$('#libraryWatched').value;state.library.page=1;loadLibrary()};
    $('#libraryQuery').onkeydown=e=>{if(e.key==='Enter')$('#librarySearch').click()};
    await loadLibrary();
  }

  async function loadLibrary(){
    const box=$('#libraryResults');if(!box)return;box.innerHTML='<div class="loading-card">正在读取作品库…</div>';
    const params=new URLSearchParams({page:String(state.library.page),page_size:'36',q:state.library.q,group_id:state.library.groupId,sort:state.library.sort,codec:state.library.codec,min_height:String(state.library.minHeight||0),watched:state.library.watched});
    try{const result=await api(`/api/library?${params}`);state.library.data=result.data;const data=result.data;box.innerHTML=data.items.length?`<div class="toolbar spread" style="margin-bottom:12px"><span class="metric-foot">共 ${data.total} 个作品</span><span class="metric-foot">第 ${data.page} / ${data.pages} 页</span></div><div class="media-grid">${data.items.map(libraryCard).join('')}</div><div class="pagination"><button class="btn" id="libraryPrev" ${data.page<=1?'disabled':''}>上一页</button><span>${data.page}</span><button class="btn" id="libraryNext" ${data.page>=data.pages?'disabled':''}>下一页</button></div>`:'<div class="empty">没有符合条件的作品</div>';bindLibraryCards(box);const prev=$('#libraryPrev'),next=$('#libraryNext');if(prev)prev.onclick=()=>{state.library.page--;loadLibrary()};if(next)next.onclick=()=>{state.library.page++;loadLibrary()};}catch(error){box.innerHTML=`<div class="notice bad">${esc(error.message)}</div>`}
  }

  function bindLibraryCards(root){$$('[data-open-media]',root).forEach(button=>button.onclick=()=>openMedia(button.dataset.openMedia))}
  async function openMedia(mediaId){
    let save=()=>{};let saveTimer=0;let current=null;let player=null;
    const modal=showModal('作品详情','<div class="loading-card">正在载入播放器…</div>',{onClose:()=>save()});
    const setResume=(file)=>{const position=Number(file?.watch_position||0);if(!player||position<=1)return;const apply=()=>{try{if(Number.isFinite(player.duration)&&position<player.duration-2)player.currentTime=position}catch(_){}};if(player.readyState>=1)apply();else player.addEventListener('loadedmetadata',apply,{once:true})};
    try{
      const result=await api(`/api/library/${encodeURIComponent(mediaId)}`);const media=result.data;const files=media.files||[];current=files.find(f=>f.is_primary)||files.find(f=>f.kind==='media')||files[0];
      if(!current){$('.modal-body',modal.root).innerHTML='<div class="empty">作品没有可播放文件</div>';return}
      $('.modal-head h2',modal.root).textContent=media.title||media.bvid||'作品详情';
      $('.modal-body',modal.root).innerHTML=`<div class="player-shell"><video id="mediaPlayer" controls playsinline preload="metadata" poster="${esc(cover(media.cover))}" src="/api/media/${encodeURIComponent(current.id)}/stream"></video></div><div class="card flat" style="margin-top:14px;padding:0"><div class="card-head"><div><h3>${esc(media.title||media.bvid)}</h3><p>${esc(media.bvid||media.source_key)} · ${esc(media.author||'-')} · ${esc(media.selected_quality||media.selected_resolution||'-')} · ${esc(media.selected_codec||'-')}</p></div><span class="badge brand">${esc(media.group_name||'未分组')}</span></div><div id="playbackNotice" class="notice hidden"></div><div class="toolbar"><a id="downloadCurrent" class="btn primary" href="/api/media/${encodeURIComponent(current.id)}/download">下载到当前设备</a>${media.source_url?`<a class="btn" href="${esc(media.source_url)}" target="_blank" rel="noopener noreferrer">B站原页面</a>`:''}<button id="compatibleButton" class="btn">生成兼容播放版</button><button id="moveMediaButton" class="btn">移动分组</button><button id="deleteMediaButton" class="btn danger">删除作品</button></div></div><h3 style="margin:20px 0 10px">文件与分 P</h3><div class="file-list">${files.map(file=>`<div class="file-row"><div><strong>${esc(file.filename)}</strong><div class="metric-foot">${esc(file.kind==='compatible'?'兼容副本':'原始文件')} · ${formatBytes(file.size)}${file.watch_position>1?` · 已看 ${Math.round(file.watch_position)} 秒`:''}</div></div><button class="btn small ${file.id===current.id?'primary':''}" data-play-file="${esc(file.id)}">播放</button></div>`).join('')}</div>`;
      player=$('#mediaPlayer',modal.root);
      save=()=>{if(!current||!player||!Number.isFinite(player.duration)||player.duration<=0||player.currentTime<0)return;api(`/api/library/${encodeURIComponent(mediaId)}/progress`,{method:'PUT',body:{file_id:current.id,position_sec:player.currentTime,duration_sec:player.duration}}).catch(()=>{})};
      setResume(current);
      player.addEventListener('timeupdate',()=>{const now=Date.now();if(now-saveTimer>8000){saveTimer=now;save()}});player.addEventListener('pause',save);player.addEventListener('ended',save);
      player.addEventListener('error',()=>{const notice=$('#playbackNotice',modal.root);if(notice){notice.className='notice warn';notice.textContent='当前浏览器可能不支持这个原始文件的容器或编码。可先下载到设备，或点击“生成兼容播放版”。'}});
      $$('[data-play-file]',modal.root).forEach(button=>button.onclick=()=>{const file=files.find(v=>v.id===button.dataset.playFile);if(!file)return;save();current=file;player.pause();player.src=`/api/media/${encodeURIComponent(file.id)}/stream`;setResume(file);$('#downloadCurrent').href=`/api/media/${encodeURIComponent(file.id)}/download`;$$('[data-play-file]',modal.root).forEach(v=>v.classList.toggle('primary',v===button));player.play().catch(()=>{})});
      $('#compatibleButton',modal.root).onclick=async()=>{if(current.kind==='compatible'){toast('当前已经是兼容播放副本','warn');return}if(!confirm('将使用 FFmpeg 在后台生成 H.264/AAC MP4 兼容副本。原始文件会保留，继续吗？'))return;try{const job=(await api(`/api/library/${encodeURIComponent(mediaId)}/compatible`,{method:'POST',body:{file_id:current.id}})).data;toast('兼容副本任务已开始','good');pollTranscode(job.id,modal,mediaId)}catch(error){toast(error.message,'bad')}};
      $('#moveMediaButton',modal.root).onclick=()=>moveMediaDialog(mediaId,media.group_id,async()=>{modal.close();await loadLibrary()});
      $('#deleteMediaButton',modal.root).onclick=async()=>{const deleteRecord=confirm('确定从作品库移除这个作品吗？\n\n下一步会询问是否同时永久删除 NAS 中的媒体文件。');if(!deleteRecord)return;const filesToo=confirm('是否同时永久删除 NAS 中的原始媒体文件？\n取消：只移除作品库记录；确定：文件也删除。');try{await api(`/api/library/${encodeURIComponent(mediaId)}?delete_files=${filesToo?'true':'false'}`,{method:'DELETE'});toast('作品已删除','good');modal.close();await loadLibrary()}catch(error){toast(error.message,'bad')}};
    }catch(error){$('.modal-body',modal.root).innerHTML=`<div class="notice bad">${esc(error.message)}</div>`}
  }

  async function pollTranscode(jobId,modal,mediaId){
    for(let i=0;i<720;i++){await new Promise(r=>setTimeout(r,2000));try{const job=(await api(`/api/transcodes/${encodeURIComponent(jobId)}`)).data;if(job.status==='success'){toast('兼容副本已生成','good');modal.close();openMedia(mediaId);return}if(job.status==='failed'){toast(job.error||'转码失败','bad');return}}catch(error){toast(error.message,'bad');return}}
  }
  function moveMediaDialog(mediaId,currentGroup,onMoved){
    const modal=showModal('移动到分组',`<form id="moveForm" class="form-grid"><div class="field full"><label>目标分组</label><select id="moveGroup" class="select">${groupOptions(currentGroup)}</select></div><div class="field full"><button class="btn primary">移动</button></div></form>`,{narrow:true});
    $('#moveForm',modal.root).onsubmit=async e=>{e.preventDefault();try{await api(`/api/library/${encodeURIComponent(mediaId)}/move`,{method:'POST',body:{group_id:$('#moveGroup').value}});toast('已移动分组','good');modal.close();if(onMoved)onMoved()}catch(error){toast(error.message,'bad')}};
  }

  async function renderGroups(root){
    await refreshGroups();root.innerHTML=`<section class="card"><div class="toolbar spread"><div><h2>分组管理</h2><p class="metric-foot">重命名只修改显示名称，不搬移大型媒体文件。</p></div><button id="createGroupTop" class="btn primary">＋ 新建分组</button></div></section><section id="groupResults" class="group-grid" style="margin-top:18px">${state.groups.map(groupCard).join('')}</section>`;
    $('#createGroupTop').onclick=()=>createGroupDialog(()=>renderGroups(root));bindGroupActions(root);bindCoverFallback(root);
  }
  function groupCard(group){return `<article class="group-card"><div class="group-cover"><img data-cover-img src="${esc(cover(group.cover))}" alt="" loading="lazy" referrerpolicy="no-referrer"><span>${esc(group.display_name.slice(0,1)||'▣')}</span></div><div class="group-name">${esc(group.display_name)}</div><div class="group-stats">${group.media_count} 个作品 · ${formatBytes(group.total_size)}<br>进行中：${Number(group.active_count||0)} · 失败：${Number(group.failed_count||0)}<br>最近更新：${formatDate(group.latest_download)}<br>目录标识：${esc(group.folder_key)}</div><div class="toolbar"><button class="btn small" data-browse-group="${esc(group.id)}">查看</button><button class="btn small" data-rename-group="${esc(group.id)}">重命名</button><button class="btn small" data-merge-group="${esc(group.id)}">合并</button><button class="btn danger small" data-delete-group="${esc(group.id)}" ${group.display_name==='未分组'?'disabled':''}>删除</button></div></article>`}
  function bindGroupActions(root){
    $$('[data-browse-group]',root).forEach(b=>b.onclick=()=>{state.library.groupId=b.dataset.browseGroup;state.library.page=1;location.hash='#/library'});
    $$('[data-rename-group]',root).forEach(b=>b.onclick=async()=>{const group=state.groups.find(v=>v.id===b.dataset.renameGroup);const name=prompt('新的显示名称：',group.display_name);if(!name)return;try{await api(`/api/groups/${encodeURIComponent(group.id)}`,{method:'PATCH',body:{name}});toast('分组已重命名','good');renderGroups(root)}catch(error){toast(error.message,'bad')}});
    $$('[data-merge-group]',root).forEach(b=>b.onclick=()=>{const group=state.groups.find(v=>v.id===b.dataset.mergeGroup);const targets=state.groups.filter(v=>v.id!==group.id);if(!targets.length){toast('没有其他可合并分组','warn');return}const modal=showModal(`合并“${group.display_name}”`, `<form id="mergeForm" class="form-grid"><div class="notice full">作品记录会归入目标分组；现有文件不做大规模搬移。</div><div class="field full"><label>目标分组</label><select id="mergeTarget" class="select">${targets.map(v=>`<option value="${esc(v.id)}">${esc(v.display_name)}</option>`).join('')}</select></div><div class="field full"><button class="btn primary">确认合并</button></div></form>`,{narrow:true});$('#mergeForm',modal.root).onsubmit=async e=>{e.preventDefault();try{await api(`/api/groups/${encodeURIComponent(group.id)}/merge`,{method:'POST',body:{target_id:$('#mergeTarget').value}});toast('分组已合并','good');modal.close();renderGroups(root)}catch(error){toast(error.message,'bad')}}});
    $$('[data-delete-group]',root).forEach(b=>b.onclick=async()=>{if(!confirm('只允许删除空分组。继续吗？'))return;try{await api(`/api/groups/${encodeURIComponent(b.dataset.deleteGroup)}`,{method:'DELETE'});toast('分组已删除','good');renderGroups(root)}catch(error){toast(error.message,'bad')}});
  }

  async function renderTasks(root){
    root.innerHTML=`<section class="card"><div class="toolbar spread"><div><h2>任务中心</h2><p class="metric-foot">NAS 媒体库任务与一次性设备导出任务统一展示。</p></div><div class="toolbar"><select id="taskStatus" class="select" style="width:auto"><option value="">全部状态</option><option value="running">下载中</option><option value="queued">排队中</option><option value="success">已完成</option><option value="failed">失败</option><option value="cancelled">已取消</option></select><select id="taskDestination" class="select" style="width:auto"><option value="">全部目标</option><option value="library">NAS 媒体库</option><option value="device">设备导出</option></select><input id="taskQuery" class="input" style="width:220px" placeholder="标题 / BV / 分组"></div></div></section><section id="taskListRoot" style="margin-top:16px"></section>`;
    ['taskStatus','taskDestination','taskQuery'].forEach(id=>$('#'+id).oninput=renderTaskListOnly);renderTaskListOnly();
  }
  function renderTaskListOnly(){
    const box=$('#taskListRoot');if(!box)return;const status=$('#taskStatus')?.value||'',destination=$('#taskDestination')?.value||'',q=($('#taskQuery')?.value||'').toLowerCase();const tasks=state.tasks.filter(t=>(!status||t.status===status)&&(!destination||t.destination===destination)&&(!q||[t.title,t.bvid,t.key,t.group,t.error].join(' ').toLowerCase().includes(q)));
    box.innerHTML=tasks.length?`<div class="task-list">${tasks.map(taskCard).join('')}</div>`:'<div class="empty">没有符合条件的任务</div>';bindTaskActions(box);
  }
  function taskCard(task){
    const percent=task.progress_percent==null?null:Math.max(0,Math.min(100,Number(task.progress_percent)));const running=['queued','running'].includes(task.status);const exportReady=task.destination==='device'&&task.status==='success'&&task.export_state!=='downloaded';
    const quality=[task.selected_quality,task.selected_resolution,task.selected_codec,task.selected_fps].filter(Boolean).join(' · ');
    const verified=task.quality_expected_parts?`核对 ${Number(task.quality_verified_parts||0)}/${Number(task.quality_expected_parts||0)} 分段`:'';
    const exportMeta=task.destination==='device'&&task.export_expires_at?`<span>过期：${esc(formatDate(task.export_expires_at))}</span>`:'';
    return `<article class="task-card"><div class="task-main"><div class="toolbar"><span class="badge ${statusClass(task.status)}">${esc(statusLabel(task.status))}</span><span class="badge ${task.destination==='device'?'warn':'brand'}">${esc(task.destination_label)}</span>${task.selected_quality?`<span class="badge neutral">${esc(task.selected_quality)}</span>`:''}</div><div class="task-title" style="margin-top:9px">${esc(task.display_title||task.title||task.bvid||task.key)}</div><div class="task-sub"><span>${esc(task.bvid||task.key)}</span>${task.destination==='library'?`<span>分组：${esc(task.group||'未分组')}</span>`:''}<span>最低：${esc(task.min_height_label||task.min_height||'不限制')}</span>${task.preferred_quality?`<span>指定：${esc(task.preferred_quality)}</span>`:'<span>自动最高</span>'}<span>${esc(task.phase_label||'')}</span>${task.speed_text?`<span>${esc(task.speed_text)}</span>`:''}${task.eta_text?`<span>剩余 ${esc(task.eta_text)}</span>`:''}${exportMeta}</div>${quality?`<div class="metric-foot" style="margin-top:7px">实际：${esc(quality)}${verified?` · ${esc(verified)}`:''}</div>`:''}${running?`<div class="progress ${percent==null?'indeterminate':''}"><span style="width:${percent==null?38:percent}%"></span></div>`:''}${task.error&&task.status==='failed'?`<div class="notice bad" style="margin-top:10px">${esc(task.error)}</div>`:''}</div><div class="task-side"><button class="btn small" data-log-task="${esc(task.id)}">日志</button>${running?`<button class="btn danger small" data-cancel-task="${esc(task.id)}">取消</button>`:''}${['failed','cancelled'].includes(task.status)?`<button class="btn small" data-retry-task="${esc(task.id)}">重试</button>`:''}${task.destination==='library'&&task.status==='success'?`<button class="btn small" data-library-task="${esc(task.bvid||task.key)}">作品库</button>`:''}${exportReady?`<button class="btn primary small" data-export-task="${esc(task.id)}">下载到当前设备</button><button class="btn danger small" data-discard-export="${esc(task.id)}">删除临时文件</button>`:''}${task.destination==='device'&&task.export_state==='downloaded'?'<span class="badge good">临时文件已清理</span>':''}</div></article>`;
  }

  function bindTaskActions(root){
    $$('[data-log-task]',root).forEach(b=>b.onclick=()=>openTaskLog(b.dataset.logTask));
    $$('[data-cancel-task]',root).forEach(b=>b.onclick=async()=>{try{await api(`/api/tasks/${encodeURIComponent(b.dataset.cancelTask)}/cancel`,{method:'POST'});toast('已提交取消请求','good')}catch(error){toast(error.message,'bad')}});
    $$('[data-retry-task]',root).forEach(b=>b.onclick=async()=>{try{const result=await api(`/api/tasks/${encodeURIComponent(b.dataset.retryTask)}/retry`,{method:'POST',body:{force:false}});toast(`已创建 ${result.total} 个重试任务`,'good')}catch(error){toast(error.message,'bad')}});
    $$('[data-library-task]',root).forEach(b=>b.onclick=()=>{state.library.q=b.dataset.libraryTask;state.library.page=1;location.hash='#/library'});
    $$('[data-export-task]',root).forEach(b=>b.onclick=()=>{const a=document.createElement('a');a.href=`/api/exports/${encodeURIComponent(b.dataset.exportTask)}/download`;a.download='';document.body.appendChild(a);a.click();a.remove();toast('浏览器已开始接收文件；服务器完整发送后 NAS 临时文件会立即清理','good')});
    $$('[data-discard-export]',root).forEach(b=>b.onclick=async()=>{if(!confirm('确定删除这个设备导出的 NAS 临时文件吗？删除后不能继续下载。'))return;try{await api(`/api/exports/${encodeURIComponent(b.dataset.discardExport)}`,{method:'DELETE'});toast('临时文件已清理','good');await refreshGlobals();renderTaskListOnly()}catch(error){toast(error.message,'bad')}});
  }
  async function openTaskLog(taskId){const modal=showModal('任务日志','<div class="loading-card">正在读取日志…</div>');try{const result=await api(`/api/tasks/${encodeURIComponent(taskId)}/log?tail=200000`);$('.modal-body',modal.root).innerHTML=`<div class="toolbar" style="margin-bottom:10px"><a class="btn small" href="/api/tasks/${encodeURIComponent(taskId)}/log/download">下载完整日志</a><button id="copyLog" class="btn small">复制</button></div><pre class="log-box">${esc(result.data.text||'暂无日志')}</pre>`;$('#copyLog',modal.root).onclick=async()=>{try{await navigator.clipboard.writeText(result.data.text||'');toast('日志已复制','good')}catch(_){toast('浏览器不允许复制','bad')}}}catch(error){$('.modal-body',modal.root).innerHTML=`<div class="notice bad">${esc(error.message)}</div>`}}

  async function renderAccount(root){
    const result=await api('/api/status?refresh_login=true');state.status=result.data;
    const passwordPanel=state.auth?.required?`<form id="passwordForm" class="form-grid" style="margin-top:16px"><div class="field full"><label>当前密码</label><input id="currentPassword" class="input" type="password" autocomplete="current-password" required></div><div class="field"><label>新密码</label><input id="newPassword" class="input" type="password" autocomplete="new-password" minlength="10" required></div><div class="field"><label>确认新密码</label><input id="confirmPassword" class="input" type="password" autocomplete="new-password" minlength="10" required></div><div class="field full"><button class="btn primary" type="submit">更换密码并撤销其他会话</button></div></form>`:'';
    root.innerHTML=`<div class="grid cols-2"><section class="card"><div class="card-head"><div><h2>Bilibili 账号</h2><p>用于会员画质与登录搜索。完整 Cookie 只保存在服务器 BBDown.data，不返回浏览器。</p></div><span class="badge ${state.status.login_state==='valid'?'good':state.status.login_state==='unknown'?'warn':'neutral'}">${state.status.login_state==='valid'?'登录有效':state.status.login_state==='unknown'?'状态未知':'未登录'}</span></div><div class="notice">${esc(state.status.message||'')}</div><div class="toolbar" style="margin-top:15px"><button id="qrLoginButton" class="btn primary">网页扫码登录</button><button id="refreshBiliButton" class="btn">重新验证</button><button id="biliLogoutButton" class="btn danger">退出 B站登录</button></div></section><section class="card"><div class="card-head"><div><h2>网站管理员</h2><p>网站登录与 Bilibili 登录是两套独立凭据。</p></div></div><div class="notice"><strong>${esc(state.auth?.username||'本地用户')}</strong><br>${state.auth?.required?'NAS / 服务器访问已启用管理员认证。更换密码后，除当前浏览器外的其他会话会立即失效。':'本地模式默认不要求网站登录。'}</div>${passwordPanel}${state.auth?.required?'<button id="accountLogout" class="btn" style="margin-top:15px">退出网站</button>':''}</section></div>`;
    $('#qrLoginButton').onclick=startQrLogin;$('#refreshBiliButton').onclick=()=>renderAccount(root);$('#biliLogoutButton').onclick=async()=>{if(!confirm('确定删除服务器上的 Bilibili 登录会话吗？'))return;try{await api('/api/account/bilibili',{method:'DELETE'});toast('已退出 Bilibili 登录','good');renderAccount(root)}catch(error){toast(error.message,'bad')}};
    if($('#accountLogout'))$('#accountLogout').onclick=$('#logoutButton').onclick;
    if($('#passwordForm'))$('#passwordForm').onsubmit=async event=>{event.preventDefault();const current=$('#currentPassword').value;const next=$('#newPassword').value;const confirmValue=$('#confirmPassword').value;if(next!==confirmValue){toast('两次输入的新密码不一致','bad');return}const button=$('button[type="submit"]',event.currentTarget);button.disabled=true;try{const changed=(await api('/api/auth/password',{method:'POST',body:{current_password:current,new_password:next}})).data;state.csrf=changed.csrf_token||state.csrf;state.auth.csrf_token=state.csrf;event.currentTarget.reset();toast(`密码已更新，已撤销 ${changed.other_sessions_revoked||0} 个其他会话`,'good')}catch(error){toast(error.message,'bad')}finally{button.disabled=false}};
  }
  async function startQrLogin(){
    const modal=showModal('Bilibili 扫码登录','<div class="loading-card">正在生成二维码…</div>',{narrow:true});let timer=null;const stop=()=>{if(timer)clearInterval(timer)};const originalClose=modal.close;modal.close=()=>{stop();originalClose()};$('.close-button',modal.root).onclick=modal.close;
    try{const result=await api('/api/account/bilibili/qr',{method:'POST'});const session=result.data;$('.modal-body',modal.root).innerHTML='<div id="qrBox" class="qr-box"></div><div id="qrStatus" class="notice" style="text-align:center">等待使用 Bilibili App 扫码</div><div class="metric-foot" style="text-align:center;margin-top:10px">二维码只包含一次性登录 URL；Cookie 不会发送到当前浏览器。</div>';new QRCode($('#qrBox',modal.root),{text:session.login_url,width:212,height:212,correctLevel:QRCode.CorrectLevel.M});const poll=async()=>{try{const value=(await api(`/api/account/bilibili/qr/${encodeURIComponent(session.id)}`,{method:'POST'})).data;$('#qrStatus',modal.root).textContent=value.status_label||value.message;if(value.status==='success'){stop();toast('Bilibili 登录成功','good');setTimeout(()=>{modal.close();if(state.page==='account')renderAccount($('#pageRoot'))},900)}else if(value.status==='expired'){stop();$('#qrStatus',modal.root).className='notice bad'}}catch(error){stop();$('#qrStatus',modal.root).className='notice bad';$('#qrStatus',modal.root).textContent=error.message}};timer=setInterval(poll,1800);poll();}catch(error){$('.modal-body',modal.root).innerHTML=`<div class="notice bad">${esc(error.message)}</div>`}
  }

  async function renderMore(root){
    root.innerHTML=`<div class="grid cols-2"><button class="card menu-card" data-more-go="groups"><strong>分组管理</strong><span>新建、查看、重命名、合并和删除空分组</span></button><button class="card menu-card" data-more-go="account"><strong>账号与扫码</strong><span>网站管理员状态与 Bilibili 网页二维码登录</span></button><button class="card menu-card" data-more-go="settings"><strong>设置</strong><span>默认清晰度、目录、端口和服务器信息</span></button><button class="card menu-card" data-more-go="dashboard"><strong>概览</strong><span>作品数量、磁盘占用与运行状态</span></button></div>`;
    $$('[data-more-go]',root).forEach(button=>button.onclick=()=>{location.hash=`#/${button.dataset.moreGo}`});
  }

  async function renderSettings(root){
    const [configRes,statusRes]=await Promise.all([api('/api/config'),api('/api/status')]);const cfg=configRes.data;const server=!!statusRes.data.server_mode;
    root.innerHTML=`<section class="card"><div class="card-head"><div><h2>运行与目录</h2><p>${server?'NAS 目录和端口由 Docker Compose 的环境变量及目录映射管理。':'Windows 本地版可以在这里调整下载目录和端口。'}</p></div><span class="badge ${server?'brand':'neutral'}">${server?'NAS / Docker':'Windows 本地'}</span></div><form id="settingsForm" class="form-grid"><div class="field"><label>监听地址</label><input class="input" value="${esc(cfg.host)}" disabled></div><div class="field"><label>端口</label><input id="cfgPort" class="input" type="number" value="${esc(cfg.port)}" ${server?'disabled':''}></div><div class="field full"><label>媒体目录</label><input id="cfgDownload" class="input" value="${esc(cfg.download_dir)}" ${server?'disabled':''}></div><div class="field"><label>默认分组</label><select id="cfgGroup" class="select">${state.groups.map(g=>`<option value="${esc(g.display_name)}" ${g.display_name===cfg.default_group?'selected':''}>${esc(g.display_name)}</option>`).join('')}</select></div><div class="field"><label>默认最低清晰度</label><select id="cfgQuality" class="select">${qualityOptions(cfg.default_min_height)}</select></div><div class="field"><label>任务超时（秒）</label><input id="cfgTimeout" class="input" type="number" min="30" max="86400" value="${esc(cfg.download_timeout_sec)}"></div><div class="field"><label>页面轮询后备间隔（毫秒）</label><input id="cfgPoll" class="input" type="number" min="200" max="60000" value="${esc(cfg.poll_hint_ms)}"></div><div class="field"><label>画质优先级（高级）</label><input id="cfgDfn" class="input" value="${esc(cfg.dfn_priority||'')}"></div><div class="field"><label>编码优先级</label><input id="cfgEncoding" class="input" value="${esc(cfg.encoding_priority||'')}" placeholder="网页兼容优先可填 avc,hevc,av1"></div><div class="field full"><button class="btn primary">保存设置</button></div></form></section><section class="card" style="margin-top:18px"><div class="card-head"><div><h2>服务器路径</h2><p>临时导出、兼容副本与媒体库使用独立根目录。</p></div></div><div class="grid cols-3"><div class="notice"><strong>媒体</strong><br>${esc(cfg.download_dir)}</div><div class="notice"><strong>临时</strong><br>${esc(cfg.temp_dir||statusRes.data.temp_dir)}</div><div class="notice"><strong>缓存</strong><br>${esc(cfg.cache_dir||statusRes.data.cache_dir)}</div></div></section>`;
    $('#settingsForm').onsubmit=async e=>{e.preventDefault();const body={default_group:$('#cfgGroup').value,default_min_height:Number($('#cfgQuality').value),download_timeout_sec:Number($('#cfgTimeout').value),poll_hint_ms:Number($('#cfgPoll').value),dfn_priority:$('#cfgDfn').value.trim(),encoding_priority:$('#cfgEncoding').value.trim()};if(!server){body.port=Number($('#cfgPort').value);body.download_dir=$('#cfgDownload').value.trim()}try{const result=await api('/api/config',{method:'PUT',body});toast(result.restart_required?'已保存，端口变更需重启':'设置已保存','good');await refreshGlobals()}catch(error){toast(error.message,'bad')}};
  }

  window.addEventListener('hashchange',()=>route());
  document.addEventListener('DOMContentLoaded',()=>bootAuth().catch(error=>{toast(error.message,'bad');$('#authRoot').classList.remove('hidden');$('#authRoot').innerHTML=`<section class="auth-card"><div class="notice bad">${esc(error.message)}</div></section>`}));
})();
