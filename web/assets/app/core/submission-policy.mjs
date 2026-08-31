import { filterSearchItems } from './search-policy.mjs';

export const DISCOVERY_SCAN_LIMIT = 10;
export const DEFAULT_HIDDEN_SUBMISSION_STATUSES = Object.freeze([
  'downloaded',
  'deleted',
]);

const DEFAULT_HIDDEN = new Set(DEFAULT_HIDDEN_SUBMISSION_STATUSES);

export function submissionPageKey({ uid = '', order = 'pubdate', page = 1, destination = 'device' } = {}) {
  return JSON.stringify([
    String(uid || ''),
    order === 'click' ? 'click' : 'pubdate',
    Math.max(1, Number.parseInt(page, 10) || 1),
    destination === 'library' ? 'library' : 'device',
  ]);
}

export function visibleSubmissionItems(
  items,
  {
    filterText = '',
    filterMode = 'raw',
    hideDownloaded = true,
  } = {},
) {
  const filtered = filterSearchItems(items, filterText, filterMode);
  if (!hideDownloaded) return filtered;
  return filtered.filter(item => !DEFAULT_HIDDEN.has(String(item?.local_status || '')));
}

export function selectableSubmissionItems(items, options = {}) {
  return visibleSubmissionItems(items, options).filter(item => item?.selectable !== false);
}

export function submissionScanDecision({
  page = 1,
  pages = 0,
  candidateCount = 0,
  scanned = 1,
  limit = DISCOVERY_SCAN_LIMIT,
} = {}) {
  const current = Math.max(1, Number.parseInt(page, 10) || 1);
  const total = Math.max(0, Number.parseInt(pages, 10) || 0);
  const count = Math.max(0, Number.parseInt(candidateCount, 10) || 0);
  const used = Math.max(1, Number.parseInt(scanned, 10) || 1);
  const cap = Math.max(1, Number.parseInt(limit, 10) || DISCOVERY_SCAN_LIMIT);
  if (count > 0) return Object.freeze({ action: 'candidate', page: current });
  if (total === 0 || current >= total) return Object.freeze({ action: 'end', page: current });
  if (used >= cap) return Object.freeze({ action: 'limit', page: current, nextPage: current + 1 });
  return Object.freeze({ action: 'next', page: current, nextPage: current + 1 });
}

export function canSelectSubmission({ selectedCount = 0, limit = 0, alreadySelected = false } = {}) {
  if (alreadySelected) return true;
  return Math.max(0, Number(selectedCount || 0)) < Math.max(0, Number(limit || 0));
}
