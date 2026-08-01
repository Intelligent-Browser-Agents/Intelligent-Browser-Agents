/**
 * Shared API client.
 *
 * Every authenticated call goes through here so the bearer token is attached in
 * one place and a 401 has a single, predictable consequence: clear the stored
 * token and send the user back to the login page. Previously each call site
 * hand-rolled its header and ignored the response status, so an expired token
 * left the user on a dashboard whose every request silently failed.
 */

const TOKEN_KEY = 'token';

export function getToken() {
  const token = localStorage.getItem(TOKEN_KEY);
  if (!token || token === 'undefined' || token === 'null') return '';
  return token;
}

export function setToken(token) {
  localStorage.setItem(TOKEN_KEY, token);
}

export function clearToken() {
  localStorage.removeItem(TOKEN_KEY);
}

/** Thrown for any non-2xx response so callers can branch on `status`. */
export class ApiError extends Error {
  constructor(status, detail) {
    super(detail || `Request failed with status ${status}`);
    this.name = 'ApiError';
    this.status = status;
    this.detail = detail;
  }
}

function onUnauthorized() {
  clearToken();
  // Full reload rather than a router navigate: this is reachable from outside a
  // Router context, and a hard reset avoids rendering stale authenticated state.
  if (window.location.pathname !== '/') {
    window.location.assign('/');
  }
}

async function parseBody(response) {
  const text = await response.text();
  if (!text) return null;
  try {
    return JSON.parse(text);
  } catch {
    return { detail: text };
  }
}

/**
 * @param {string} path
 * @param {{method?: string, body?: unknown, auth?: boolean}} options
 */
export async function apiFetch(path, { method = 'GET', body, auth = true } = {}) {
  const headers = {};
  if (body !== undefined) headers['Content-Type'] = 'application/json';

  if (auth) {
    const token = getToken();
    if (!token) {
      onUnauthorized();
      throw new ApiError(401, 'Not signed in.');
    }
    headers.Authorization = `Bearer ${token}`;
  }

  let response;
  try {
    response = await fetch(path, {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch {
    // Network-level failure: no response at all.
    throw new ApiError(0, 'Could not reach the server. Is the backend running?');
  }

  const payload = await parseBody(response);

  if (response.status === 401) {
    onUnauthorized();
    throw new ApiError(401, payload?.detail || 'Your session has expired.');
  }

  if (!response.ok) {
    throw new ApiError(response.status, payload?.detail || `Request failed (${response.status}).`);
  }

  return payload;
}

/** Build a same-origin WebSocket URL. Tokens are sent in the first frame, never here. */
export function buildWebSocketUrl(path) {
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  return `${protocol}//${window.location.host}${path}`;
}

// ---------------------------------------------------------------------------
// Endpoint wrappers
// ---------------------------------------------------------------------------

export const api = {
  login: (username, password) =>
    apiFetch('/api/users/login/', { method: 'POST', body: { username, password }, auth: false }),

  register: (fields) =>
    apiFetch('/api/users/insert/', { method: 'POST', body: fields, auth: false }),

  forgotPassword: (identifier) =>
    apiFetch('/api/users/forgot-password', {
      method: 'POST',
      body: identifier.includes('@') ? { email: identifier } : { username: identifier },
      auth: false,
    }),

  /** Uses the scoped reset token rather than the normal access token. */
  changePassword: async (resetToken, password) => {
    const response = await fetch('/api/users/change-password', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${resetToken}` },
      body: JSON.stringify({ password }),
    });
    const payload = await parseBody(response);
    if (!response.ok) {
      throw new ApiError(response.status, payload?.detail || 'Could not change the password.');
    }
    return payload;
  },

  me: () => apiFetch('/api/users/'),

  verifyPassword: (password) =>
    apiFetch('/api/users/verify/', { method: 'POST', body: { password } }),

  readCredentials: () => apiFetch('/api/users/credentials'),

  storeCredentials: (credentials) =>
    apiFetch('/api/users/store-credentials', { method: 'POST', body: { credentials } }),

  deleteCredentials: () => apiFetch('/api/users/credentials', { method: 'DELETE' }),

  deleteAccount: () => apiFetch('/api/users/delete/', { method: 'DELETE' }),

  hitlReply: (content) =>
    apiFetch('/api/hitl_reply', { method: 'POST', body: { content } }),
};
