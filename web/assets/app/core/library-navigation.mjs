export const LIBRARY_OPEN_REQUEST_KEY = 'bili-v070-library-open';

export function storeLibraryOpenRequest(storage, mediaId) {
  const value = String(mediaId || '').trim();
  if (!value) return false;
  storage.setItem(LIBRARY_OPEN_REQUEST_KEY, value);
  return true;
}

export function takeLibraryOpenRequest(storage) {
  const value = String(storage.getItem(LIBRARY_OPEN_REQUEST_KEY) || '').trim();
  if (value) storage.removeItem(LIBRARY_OPEN_REQUEST_KEY);
  return value;
}
