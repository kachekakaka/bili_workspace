export function formatBytes(value) {
  const number = Number(value);
  if (!Number.isFinite(number) || number < 0) return '-';
  if (number === 0) return '0 B';
  const units = ['B', 'KB', 'MB', 'GB', 'TB', 'PB'];
  const index = Math.min(units.length - 1, Math.floor(Math.log(number) / Math.log(1024)));
  const scaled = number / Math.pow(1024, index);
  const digits = index === 0 || scaled >= 100 ? 0 : scaled >= 10 ? 1 : 2;
  return `${scaled.toFixed(digits)} ${units[index]}`;
}

export function formatPlayCount(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) return '-';
  if (number >= 1e8) return `${(number / 1e8).toFixed(number >= 1e9 ? 0 : 1)}亿`;
  if (number >= 1e4) return `${(number / 1e4).toFixed(number >= 1e5 ? 0 : 1)}万`;
  return String(Math.round(number));
}

export function toEpochMilliseconds(value) {
  if (value === null || value === undefined || value === '') return null;
  const number = Number(value);
  if (!Number.isFinite(number)) return null;
  return number < 1e12 ? number * 1000 : number;
}
