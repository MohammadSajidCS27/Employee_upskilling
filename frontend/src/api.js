const API_BASE = (import.meta?.env?.VITE_API_BASE || '').replace(/\/$/, '');

function buildUrl(path) {
  if (!API_BASE) return path;
  return `${API_BASE}${path}`;
}

async function request(path, options = {}) {
  const response = await fetch(buildUrl(path), {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      ...(options.headers || {}),
    },
    credentials: 'include',
  });
  const text = await response.text();
  let data = null;
  try {
    data = text ? JSON.parse(text) : null;
  } catch {
    data = text;
  }
  if (!response.ok) {
    const message = typeof data === 'string' ? data : (data?.detail || data?.message || `Request failed: ${response.status}`);
    throw new Error(message);
  }
  return data;
}

export async function postJson(path, payload) {
  return request(path, {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export async function getJson(path) {
  return request(path);
}

export async function putJson(path, payload) {
  return request(path, {
    method: 'PUT',
    body: JSON.stringify(payload),
  });
}

export async function deleteJson(path) {
  return request(path, {
    method: 'DELETE',
  });
}
