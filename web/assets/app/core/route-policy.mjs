export const ADMIN_ROUTES = Object.freeze([
  'dashboard',
  'download',
  'search',
  'library',
  'groups',
  'tasks',
  'users',
  'account',
  'settings',
  'more',
]);

export const USER_ROUTES = Object.freeze(['download', 'tasks']);

export function normalizeRole(role) {
  return String(role || '').toLowerCase() === 'admin' ? 'admin' : 'user';
}

export function defaultRouteForRole(role) {
  return normalizeRole(role) === 'admin' ? 'dashboard' : 'download';
}

export function allowedRoutesForRole(role) {
  return normalizeRole(role) === 'admin' ? ADMIN_ROUTES : USER_ROUTES;
}

export function parseHashRoute(hashValue) {
  const raw = String(hashValue || '').trim().replace(/^#\/?/, '');
  const encodedRoute = raw.split('?', 1)[0].split('/', 1)[0];
  if (!encodedRoute) return '';
  try {
    return decodeURIComponent(encodedRoute).trim().toLowerCase();
  } catch {
    return '';
  }
}

export function resolveRoute(hashValue, role) {
  const requested = parseHashRoute(hashValue);
  const allowed = allowedRoutesForRole(role);
  const fallback = defaultRouteForRole(role);
  const route = allowed.includes(requested) ? requested : fallback;
  return Object.freeze({
    requested,
    route,
    fallback,
    redirected: route !== requested,
    hash: `#/${route}`,
  });
}
