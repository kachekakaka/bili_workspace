import { esc, qualityOptions } from './shared.mjs';

export async function mount(root, context) {
  const configResponse = await context.api('/api/config', { signal: context.signal });
  const cfg = configResponse.data || {};
  const status = context.shared.get().status || {};
  const server = Boolean(status.server_mode);
  const protectedFields = new Set(configResponse.protected_fields || []);
  const portProtected = protectedFields.has('port');
  const downloadProtected = protectedFields.has('download_dir');
  const managedFields = portProtected || downloadProtected;
  const groups = context.shared.get().groups || [];
  const host = document.createElement('div');
  host.innerHTML = `<section class="card"><div class="card-head"><div><h2>运行与目录</h2><p>${managedFields ? '端口和媒体目录由当前启动入口管理。' : 'Windows 本地源码入口可以在这里调整下载目录和端口。'}</p></div><span class="badge ${managedFields || server ? 'brand' : 'neutral'}">${managedFields ? '入口托管' : (server ? 'NAS / Docker' : 'Windows 本地')}</span></div><form id="settingsForm" class="form-grid"><div class="field"><label>监听地址</label><input class="input" value="${esc(cfg.host)}" disabled></div><div class="field"><label>端口</label><input id="cfgPort" class="input" type="number" value="${esc(cfg.port)}" ${portProtected ? 'disabled' : ''}></div><div class="field full"><label>媒体目录</label><input id="cfgDownload" class="input" value="${esc(cfg.download_dir)}" ${downloadProtected ? 'disabled' : ''}></div><div class="field"><label>默认分组</label><select id="cfgGroup" class="select">${groups.map(group => `<option value="${esc(group.display_name)}" ${group.display_name === cfg.default_group ? 'selected' : ''}>${esc(group.display_name)}</option>`).join('')}</select></div><div class="field"><label>默认最低清晰度</label><select id="cfgQuality" class="select">${qualityOptions(cfg.default_min_height)}</select></div><details class="v062-settings-advanced field full"><summary><span><strong>高级设置</strong><small>任务超时、轮询和下载策略；不熟悉时保持默认即可。</small></span><span class="v062-details-caret" aria-hidden="true">⌄</span></summary><div class="form-grid v062-settings-advanced-grid hidden"><div class="field"><label>任务超时（秒）</label><input id="cfgTimeout" class="input" type="number" min="30" max="86400" value="${esc(cfg.download_timeout_sec)}"></div><div class="field"><label>页面轮询后备间隔（毫秒）</label><input id="cfgPoll" class="input" type="number" min="200" max="60000" value="${esc(cfg.poll_hint_ms)}"></div><div class="field"><label>画质优先级（高级）</label><input id="cfgDfn" class="input" value="${esc(cfg.dfn_priority || '')}"></div><div class="field"><label>编码优先级</label><input id="cfgEncoding" class="input" value="${esc(cfg.encoding_priority || '')}" placeholder="网页兼容优先可填 avc,hevc,av1"></div></div></details><div class="field full"><button type="submit" class="btn primary">保存设置</button></div></form></section><section class="card" style="margin-top:18px"><div class="card-head"><div><h2>服务器路径</h2><p>临时导出、兼容副本与媒体库使用独立根目录。</p></div></div><div class="grid cols-3"><div class="notice"><strong>媒体</strong><br>${esc(cfg.download_dir)}</div><div class="notice"><strong>临时</strong><br>${esc(cfg.temp_dir || status.temp_dir)}</div><div class="notice"><strong>缓存</strong><br>${esc(cfg.cache_dir || status.cache_dir)}</div></div></section>`;
  context.commit(() => root.replaceChildren(host));
  const advanced = host.querySelector('.v062-settings-advanced');
  const advancedGrid = host.querySelector('.v062-settings-advanced-grid');
  const syncAdvancedVisibility = () => {
    advancedGrid.classList.toggle('hidden', !advanced.open);
  };
  advanced.addEventListener('toggle', syncAdvancedVisibility, { signal: context.signal });
  syncAdvancedVisibility();
  host.querySelector('#settingsForm').addEventListener('submit', async event => {
    event.preventDefault();
    const button = event.currentTarget.querySelector('button[type="submit"]');
    button.disabled = true;
    const body = {
      default_group: host.querySelector('#cfgGroup').value,
      default_min_height: Number(host.querySelector('#cfgQuality').value),
      download_timeout_sec: Number(host.querySelector('#cfgTimeout').value),
      poll_hint_ms: Number(host.querySelector('#cfgPoll').value),
      dfn_priority: host.querySelector('#cfgDfn').value.trim(),
      encoding_priority: host.querySelector('#cfgEncoding').value.trim(),
    };
    if (!portProtected) {
      body.port = Number(host.querySelector('#cfgPort').value);
    }
    if (!downloadProtected) {
      body.download_dir = host.querySelector('#cfgDownload').value.trim();
    }
    try {
      const result = await context.api('/api/config', { method: 'PUT', body, signal: context.signal });
      context.toast.show(result.restart_required ? '已保存，端口变更需重启' : '设置已保存', 'good');
      await context.refreshShared({ force: true });
    } catch (error) {
      if (error?.name !== 'AbortError') context.toast.show(error.message, 'bad');
    } finally {
      button.disabled = false;
    }
  }, { signal: context.signal });
  return Object.freeze({ dispose() {} });
}
