export class ApiError extends Error {
  constructor(message, { status = 0, code = '', detail = null, payload = null } = {}) {
    super(message);
    this.name = 'ApiError';
    this.status = Number(status || 0);
    this.code = String(code || '');
    this.detail = detail;
    this.payload = payload;
  }
}

export class AuthExpiredError extends ApiError {
  constructor(message = '登录已失效，请重新登录', options = {}) {
    super(message, { ...options, status: options.status || 401, code: options.code || 'auth_expired' });
    this.name = 'AuthExpiredError';
  }
}

function detailMessage(detail) {
  if (!Array.isArray(detail)) return '';
  return detail.map(item => String(item?.msg || '')).filter(Boolean).join('；');
}

async function readPayload(response) {
  try {
    return await response.json();
  } catch {
    throw new ApiError(`服务返回无效响应（HTTP ${response.status}）`, {
      status: response.status,
      code: 'invalid_response',
    });
  }
}

export function createApiClient({
  fetchImpl = globalThis.fetch,
  getCsrfToken = () => '',
  onAuthExpired = null,
} = {}) {
  if (typeof fetchImpl !== 'function') throw new TypeError('fetchImpl must be a function');

  return async function api(path, {
    method = 'GET',
    body,
    raw = false,
    signal,
    headers: extraHeaders = {},
  } = {}) {
    const verb = String(method || 'GET').toUpperCase();
    const headers = { Accept: 'application/json', ...extraHeaders };
    if (body !== undefined && !Object.keys(headers).some(key => key.toLowerCase() === 'content-type')) {
      headers['Content-Type'] = 'application/json';
    }
    const csrf = String(getCsrfToken() || '');
    if (!['GET', 'HEAD', 'OPTIONS'].includes(verb) && csrf) headers['X-CSRF-Token'] = csrf;

    let response;
    try {
      response = await fetchImpl(path, {
        method: verb,
        headers,
        body: body === undefined ? undefined : JSON.stringify(body),
        cache: 'no-store',
        credentials: 'same-origin',
        signal,
      });
    } catch (error) {
      if (error?.name === 'AbortError') throw error;
      throw new ApiError(`无法连接服务：${error?.message || '网络错误'}`, { code: 'network_error' });
    }

    if (raw) return response;
    const payload = await readPayload(response);
    if (response.status === 401) {
      const error = new AuthExpiredError(payload?.error || '登录已失效，请重新登录', {
        status: response.status,
        code: payload?.code || 'auth_expired',
        detail: payload?.detail,
        payload,
      });
      if (typeof onAuthExpired === 'function') await onAuthExpired(error);
      throw error;
    }
    if (!response.ok || payload?.ok === false) {
      throw new ApiError(
        payload?.error || detailMessage(payload?.detail) || `请求失败（HTTP ${response.status}）`,
        {
          status: response.status,
          code: payload?.code || 'request_failed',
          detail: payload?.detail,
          payload,
        },
      );
    }
    return payload;
  };
}
