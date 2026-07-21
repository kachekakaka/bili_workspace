export const SEARCH_FILTER_MODES = Object.freeze(['raw', 'exact', 'fuzzy']);

export function normalizeSearchText(value) {
  return String(value || '').normalize('NFKC').toLocaleLowerCase();
}

export function splitTitleTerms(value) {
  const terms = [];
  const seen = new Set();
  for (const raw of String(value || '').split(/[\s,，;；|/\\()（）\[\]{}<>《》]+/u)) {
    const term = raw.trim();
    const folded = normalizeSearchText(term);
    if (!term || seen.has(folded)) continue;
    seen.add(folded);
    terms.push(term.slice(0, 50));
    if (terms.length >= 6) break;
  }
  return terms;
}

export function titleMatches(title, filterText, mode = 'raw') {
  if (mode === 'raw') return true;
  if (!SEARCH_FILTER_MODES.includes(mode)) return false;
  const terms = splitTitleTerms(filterText);
  if (!terms.length) return true;
  const normalizedTitle = normalizeSearchText(title);
  const matches = terms.map(term => normalizedTitle.includes(normalizeSearchText(term)));
  return mode === 'exact' ? matches.every(Boolean) : matches.some(Boolean);
}

export function filterSearchItems(items, filterText, mode = 'raw') {
  return (Array.isArray(items) ? items : []).filter(item => (
    titleMatches(item?.title, filterText, mode)
  ));
}

export function searchPageKey({ keyword = '', order = 'totalrank', page = 1 } = {}) {
  return JSON.stringify([
    normalizeSearchText(String(keyword).trim()),
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
