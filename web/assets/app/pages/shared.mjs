import { formatBytes, toEpochMilliseconds } from '../core/format.mjs';

export const QUALITY_OPTIONS = Object.freeze([
  [0, '不限制'], [360, '至少 360P'], [480, '至少 480P'], [720, '至少 720P'],
  [1080, '至少 1080P'], [1440, '至少 2K / 1440P'], [2160, '至少 4K'], [4320, '至少 8K'],
]);

export function esc(value) {
  return String(value ?? '').replace(/[&<>'"]/g, char => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;',
  }[char]));
}

export function formatDate(value, onlyDate = false) {
  const milliseconds = toEpochMilliseconds(value);
  if (milliseconds === null) return '-';
  const date = new Date(milliseconds);
  if (Number.isNaN(date.getTime())) return '-';
  return onlyDate ? date.toLocaleDateString() : date.toLocaleString();
}

export function qualityOptions(selected = 1080) {
  return QUALITY_OPTIONS.map(([value, label]) => (
    `<option value="${value}" ${Number(selected) === value ? 'selected' : ''}>${esc(label)}</option>`
  )).join('');
}

export function groupOptions(groups, selected = '', includeAll = false) {
  const prefix = includeAll ? '<option value="">全部分组</option>' : '';
  return prefix + (groups || []).map(group => (
    `<option value="${esc(group.id)}" ${String(group.id) === String(selected) ? 'selected' : ''}>${esc(group.display_name)}</option>`
  )).join('');
}

export function coverUrl(value) {
  const text = String(value || '');
  if (text.startsWith('https://')) return `/api/cover?url=${encodeURIComponent(text)}`;
  const svg = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 640 360"><rect width="640" height="360" fill="#e8edf5"/><path d="M275 125l115 55-115 55z" fill="#94a3b8"/><text x="320" y="290" text-anchor="middle" font-family="sans-serif" font-size="23" fill="#64748b">暂无封面</text></svg>';
  return `data:image/svg+xml,${encodeURIComponent(svg)}`;
}

export function bindCoverFallback(root, signal) {
  for (const image of root.querySelectorAll('img[data-cover-img]')) {
    image.addEventListener('error', () => {
      image.src = coverUrl('');
    }, { once: true, signal });
  }
}

export function statusClass(status) {
  if (status === 'success' || status === 'valid') return 'good';
  if (status === 'failed' || status === 'cancelled' || status === 'invalid') return 'bad';
  if (status === 'running' || status === 'queued' || status === 'unknown') return 'warn';
  return 'neutral';
}

export function statusLabel(status) {
  return ({
    queued: '排队中', running: '下载中', success: '已完成', skipped: '已跳过',
    failed: '失败', cancelled: '已取消', valid: '登录有效', unknown: '状态未知', invalid: '未登录',
  })[status] || status || '未知';
}

export function metric(label, value, foot = '') {
  return `<section class="card metric-card"><span class="metric-label">${esc(label)}</span><strong class="metric-value">${esc(value)}</strong><span class="metric-foot">${esc(foot)}</span></section>`;
}

export function mediaCard(item) {
  return `<article class="media-card"><div class="cover-wrap"><img data-cover-img src="${esc(coverUrl(item.cover))}" alt="${esc(item.title || '')}" loading="lazy" referrerpolicy="no-referrer"><div class="cover-badges"><span class="badge brand">${esc(item.selected_quality || item.selected_resolution || '媒体')}</span></div></div><div class="media-body"><div class="media-title">${esc(item.title || item.bvid || item.source_key)}</div><div class="media-meta"><span>${esc(item.author || '-')}</span><span>${esc(item.bvid || item.source_key || '')}</span></div><div class="media-meta"><span>${esc(item.group_name || '未分组')}</span><span>${formatBytes(item.total_size)}</span></div></div></article>`;
}

export function modalActions(label) {
  return `<div class="v062-modal-actions"><button type="button" class="btn" data-dialog-cancel data-v062-cancel>取消</button><button type="submit" class="btn primary">${esc(label)}</button></div>`;
}

export function bindDialogCancel(modal) {
  modal.body.querySelector('[data-dialog-cancel]')?.addEventListener('click', () => modal.close('cancel'), { once: true });
}

export function isAbort(error) {
  return error?.name === 'AbortError';
}

export { formatBytes };
