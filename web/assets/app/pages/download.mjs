import { bindDialogCancel, esc, groupOptions, modalActions, qualityOptions } from './shared.mjs';
import { once } from '../core/lifecycle.mjs';
import {
  clearSubmissionSessionState,
  mountSubmissionBrowser,
} from './submission-browser.mjs';

const downloadStates = new Map();

export function clearDownloadSessionState() {
  downloadStates.clear();
  clearSubmissionSessionState();
}

function sessionKey(context) {
  const session = context.session.get();
  return String(session.user?.id || session.username || 'anonymous');
}

function parseTargets(value) {
  const lines = String(value || '').split(/\r?\n/).map(item => item.trim()).filter(Boolean);
  return {
    lines,
    bvids: lines.filter(item => /^BV[0-9A-Za-z]+$/i.test(item)),
    urls: lines.filter(item => !/^BV[0-9A-Za-z]+$/i.test(item)),
  };
}

async function renderClaimableNotice(host, context) {
  const root = host.querySelector('[data-claimable-exports]');
  if (!root) return;
  try {
    const response = await context.api('/api/tasks?destination=device&status=success', {
      signal: context.signal,
    });
    const claimable = (response.data || []).filter(task => task.export_available);
    if (!claimable.length || !context.isCurrent()) {
      root.innerHTML = '';
      return;
    }
    const links = claimable.slice(0, 3).map(task => (
      `<a class="btn primary small" href="/api/exports/${encodeURIComponent(task.id)}/download">领取：${esc(task.display_title || task.title || task.bvid || task.id)}</a>`
    )).join('');
    root.innerHTML = `<div class="notice warn"><strong>你有 ${claimable.length} 个已完成、尚未领取的设备导出。</strong><div class="toolbar" style="margin-top:8px">${links}<button type="button" class="btn small" data-open-tasks>查看全部</button></div></div>`;
    root.querySelector('[data-open-tasks]').addEventListener('click', () => context.navigate('tasks'), {
      signal: context.signal,
    });
  } catch (error) {
    if (error?.name !== 'AbortError') root.innerHTML = '';
  }
}

export async function mount(root, context) {
  const snapshot = context.shared.get();
  const status = snapshot.status || {};
  const groups = snapshot.groups || [];
  const normalUser = !context.session.isAdmin();
  const defaultGroup = groups.find(item => item.display_name === status.default_group) || groups[0];
  const identity = sessionKey(context);
  const downloadState = downloadStates.get(identity) || { mode: 'direct', directDraft: '' };
  downloadStates.set(identity, downloadState);
  const normalMode = downloadState.mode;
  const host = document.createElement('div');
  const normalDirect = `<section class="card normal-user-download" data-user-download="1"><div class="card-head"><div><h2>直接创建下载</h2><p>提交作品链接或编号，服务器完成下载后提供给当前浏览器设备。</p></div></div><form id="downloadForm" class="form-grid"><div class="field full"><label>作品链接或 BV / av / ep / ss 编号</label><textarea id="downloadTargets" class="textarea" placeholder="每行一个，例如：&#10;BV1xxxxxxxxx&#10;https://www.bilibili.com/video/BV1xxxxxxxxx" required>${esc(downloadState.directDraft)}</textarea></div><div class="field full"><div class="notice">自动选择最高可用画质；最低清晰度门槛固定为管理员全局设置的 ${Number(status.default_min_height || 0)}P，低于门槛时任务失败。</div></div><div class="field full"><div id="destinationNotice" class="notice warn">下载完成后导出到当前设备，不会进入管理员媒体库。</div></div><div class="field full"><button class="btn primary" type="submit">加入下载队列</button></div></form></section>`;
  const adminDirect = `<section class="card"><div class="card-head"><div><h2>创建下载</h2><p>保存到 NAS 会进入媒体库；导出到当前设备只使用专用临时目录。</p></div></div><form id="downloadForm" class="form-grid"><div class="field full"><label>作品链接或 BV / av / ep / ss 编号</label><textarea id="downloadTargets" class="textarea" placeholder="每行一个，例如：&#10;BV1xxxxxxxxx&#10;https://www.bilibili.com/video/BV1xxxxxxxxx" required></textarea></div><div class="field full"><label>下载目标</label><div class="segmented" id="destinationSegment"><button type="button" data-value="library" class="active">保存到 NAS 媒体库</button><button type="button" data-value="device">导出到当前设备</button></div><input type="hidden" id="downloadDestination" value="library"></div><div class="field" id="downloadGroupField"><label>保存分组</label><div class="toolbar"><select id="downloadGroup" class="select" style="flex:1">${groupOptions(groups, defaultGroup?.id || '')}</select><button type="button" class="btn" id="newGroupButton">＋ 新建</button></div><small>分组显示名可重命名，不会移动已有大文件。</small></div><div class="field"><label>最低清晰度</label><select id="downloadQuality" class="select">${qualityOptions(status.default_min_height || 1080)}</select><small>预检或实际码流低于门槛时会失败，不会保存低清文件。</small></div><div class="field"><label>重新下载策略</label><label style="font-weight:500"><input id="downloadForce" type="checkbox"> 强制重新下载并事务替换旧文件</label></div><div class="field full"><div id="destinationNotice" class="notice">成品长期保存在 NAS，可在作品库中播放、下载到手机或移动分组。</div></div><div class="field full"><button class="btn primary" type="submit">加入下载队列</button></div></form></section>`;
  host.innerHTML = `<div data-claimable-exports></div>${normalUser ? `<section class="card download-mode-card"><div class="card-head"><div><h2>选择创建方式</h2><p>可直接提交作品，也可按指定 UP 主的唯一 UID 浏览公开投稿后选择。</p></div></div><div class="segmented"><button type="button" data-download-mode="direct">作品链接 / 编号</button><button type="button" data-download-mode="creator">指定 UP 主</button></div></section><div data-download-direct>${normalDirect}</div><div data-download-creator></div>` : adminDirect}`;
  context.commit(() => root.replaceChildren(host));
  const disposers = [];

  void renderClaimableNotice(host, context);

  if (normalUser) {
    const creatorRoot = host.querySelector('[data-download-creator]');
    const creatorMount = await mountSubmissionBrowser(creatorRoot, context, {
      surface: 'normal-download-creator',
      allowNameSearch: false,
      normalUser: true,
      defaultDestination: 'device',
      defaultMinHeight: Number(status.default_min_height || 1080),
    });
    disposers.push(creatorMount.dispose);
    const applyMode = mode => {
      const current = mode === 'creator' ? 'creator' : 'direct';
      downloadState.mode = current;
      host.querySelector('[data-download-direct]').classList.toggle('hidden', current !== 'direct');
      creatorRoot.classList.toggle('hidden', current !== 'creator');
      for (const button of host.querySelectorAll('[data-download-mode]')) {
        button.classList.toggle('active', button.dataset.downloadMode === current);
      }
    };
    applyMode(normalMode);
    host.querySelector('.download-mode-card').addEventListener('click', async event => {
      const button = event.target.closest('[data-download-mode]');
      if (!button) return;
      const next = button.dataset.downloadMode === 'creator' ? 'creator' : 'direct';
      if (
        downloadState.mode === 'creator'
        && next !== 'creator'
        && creatorMount.selectionCount() > 0
      ) {
        const accepted = await context.confirm({
          title: '切换创建方式',
          message: '切换后会清空当前 UP 主投稿选择，是否继续？',
          confirmLabel: '切换并清空',
        });
        if (!accepted) return;
        creatorMount.clearSelection();
      }
      applyMode(next);
    }, { signal: context.signal });
    host.querySelector('#downloadTargets').addEventListener('input', event => {
      downloadState.directDraft = event.currentTarget.value;
    }, { signal: context.signal });
  } else {
    const segment = host.querySelector('#destinationSegment');
    segment.addEventListener('click', event => {
      const button = event.target.closest('button[data-value]');
      if (!button) return;
      for (const item of segment.querySelectorAll('button')) item.classList.toggle('active', item === button);
      host.querySelector('#downloadDestination').value = button.dataset.value;
      const device = button.dataset.value === 'device';
      host.querySelector('#downloadGroupField').classList.toggle('hidden', device);
      host.querySelector('#downloadForce').closest('.field').classList.toggle('hidden', device);
      const notice = host.querySelector('#destinationNotice');
      notice.className = `notice ${device ? 'warn' : ''}`;
      notice.textContent = device
        ? 'NAS 完成下载与混流后提供一次性浏览器下载；服务器完整发送后立即删除临时文件，中断则保留到过期时间。'
        : '成品长期保存在 NAS，可在作品库中播放、下载到手机或移动分组。';
    }, { signal: context.signal });

    const select = host.querySelector('#downloadGroup');
    const searchable = context.mountSearchableSelect(select, {
      modal: context.modal,
      threshold: 8,
    });
    disposers.push(searchable.dispose);

    host.querySelector('#newGroupButton').addEventListener('click', () => {
      const modal = context.modal.open({
        title: '新建分组',
        narrow: true,
        body: `<form id="newGroupForm" class="form-grid"><div class="field full"><label>分组名称</label><input id="newGroupName" class="input" maxlength="60" placeholder="例如：摄影教程" required><small>显示名称可随时修改，磁盘目录标识保持稳定。</small></div><div class="field full">${modalActions('创建并选中')}</div></form>`,
      });
      bindDialogCancel(modal);
      modal.body.querySelector('#newGroupForm').addEventListener('submit', async event => {
        event.preventDefault();
        const button = event.currentTarget.querySelector('button[type="submit"]');
        button.disabled = true;
        try {
          const result = await context.api('/api/groups', {
            method: 'POST',
            body: { name: modal.body.querySelector('#newGroupName').value.trim() },
          });
          await context.refreshShared();
          const nextGroups = context.shared.get().groups || [];
          select.innerHTML = groupOptions(nextGroups, result.data?.id || '');
          modal.close('created');
          context.toast.show('分组已创建', 'good');
        } catch (error) {
          context.toast.show(error.message, 'bad');
        } finally {
          button.disabled = false;
        }
      });
    }, { signal: context.signal });
  }

  host.querySelector('#downloadForm').addEventListener('submit', async event => {
    event.preventDefault();
    const button = event.currentTarget.querySelector('button[type="submit"]');
    if (button.disabled) return;
    button.disabled = true;
    const targets = parseTargets(host.querySelector('#downloadTargets').value);
    if (!targets.lines.length) {
      context.toast.show('请输入作品链接或编号', 'warn');
      button.disabled = false;
      return;
    }
    const destination = normalUser ? 'device' : host.querySelector('#downloadDestination').value;
    const body = {
      urls: targets.urls,
      bvids: targets.bvids,
      items: [],
      force: normalUser ? false : Boolean(host.querySelector('#downloadForce').checked),
      group_id: destination === 'library' ? (host.querySelector('#downloadGroup')?.value || '') : '',
      group: '',
      destination,
      min_height: normalUser
        ? Number(status.default_min_height || 0)
        : Number(host.querySelector('#downloadQuality').value || 0),
    };
    try {
      const result = await context.api('/api/download', { method: 'POST', body, signal: context.signal });
      host.querySelector('#downloadTargets').value = '';
      if (normalUser) downloadState.directDraft = '';
      context.toast.show(`已创建 ${result.total || targets.lines.length} 个任务，可继续浏览当前页面`, 'good');
      void renderClaimableNotice(host, context);
    } catch (error) {
      if (error?.name !== 'AbortError') context.toast.show(error.message, 'bad');
    } finally {
      button.disabled = false;
    }
  }, { signal: context.signal });

  return Object.freeze({
    dispose: once(() => {
      for (const dispose of disposers) dispose?.();
    }),
  });
}
