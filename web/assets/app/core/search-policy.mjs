export const SEARCH_FILTER_MODES = Object.freeze(['raw', 'exact', 'fuzzy']);

export function splitTitleTerms(value) {
  return [...new Set(
    String(value || '')
      .trim()
      .toLocaleLowerCase()
      .split(/\s+/u)
      .filter(Boolean),
  )];
}

export function titleMatches(title, filterText, mode = 'raw') {
  if (mode === 'raw') return true;
  if (!SEARCH_FILTER_MODES.includes(mode)) return false;
  const terms = splitTitleTerms(filterText);
  if (!terms.length) return true;
  const normalizedTitle = String(title || '').toLocaleLowerCase();
  return mode === 'exact'
    ? terms.every(term => normalizedTitle.includes(term))
    : terms.some(term => normalizedTitle.includes(term));
}

export function filterSearchItems(items, filterText, mode = 'raw') {
  return (Array.isArray(items) ? items : []).filter(item => (
    titleMatches(item?.title, filterText, mode)
  ));
}

export function searchPageKey({ keyword = '', order = 'totalrank', page = 1 } = {}) {
  return JSON.stringify([
    String(keyword).trim(),
    String(order || 'totalrank'),
    Math.max(1, Number.parseInt(page, 10) || 1),
  ]);
}

export function shouldPrefetchNextPage({
  page = 1,
  pages = 0,
  saveData = false,
  currentPageSucceeded = false,
  queryIsCurrent = false,
} = {}) {
  const current = Math.max(1, Number.parseInt(page, 10) || 1);
  const total = Math.max(0, Number.parseInt(pages, 10) || 0);
  return Boolean(
    currentPageSucceeded
      && queryIsCurrent
      && !saveData
      && total > current,
  );
}
