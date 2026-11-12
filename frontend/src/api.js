// Tiny API client. The token lives in localStorage; every call sends it.
// Render passes the API's host without https://, so add it when missing.
const RAW_BASE = (import.meta.env.VITE_API_URL || "").replace(/\/+$/, "");
const BASE = RAW_BASE && !RAW_BASE.includes("://") ? `https://${RAW_BASE}` : RAW_BASE;
const TOKEN_KEY = "khataz_token";

export const token = {
  get: () => { try { return localStorage.getItem(TOKEN_KEY); } catch { return null; } },
  set: (t) => { try { localStorage.setItem(TOKEN_KEY, t); } catch { /* private mode */ } },
  clear: () => { try { localStorage.removeItem(TOKEN_KEY); } catch { /* ignore */ } },
};

export class ApiError extends Error {
  constructor(status, message) { super(message); this.status = status; }
}

function errorText(body, status) {
  const d = body?.detail;
  if (typeof d === "string") return d;
  if (Array.isArray(d)) {
    // FastAPI validation errors -> "field: message"
    return d.map((e) => `${(e.loc || []).slice(1).join(".") || "input"}: ${e.msg}`).join("; ");
  }
  return `Request failed (${status})`;
}

export async function api(path, { method = "GET", body, form } = {}) {
  const headers = {};
  const t = token.get();
  if (t) headers.Authorization = `Bearer ${t}`;
  let payload;
  if (form) payload = form;
  else if (body !== undefined) { headers["Content-Type"] = "application/json"; payload = JSON.stringify(body); }

  let res;
  try {
    res = await fetch(`${BASE}${path}`, { method, headers, body: payload });
  } catch {
    throw new ApiError(0, "Can't reach the server. Is the backend running on port 8000?");
  }
  const isJson = res.headers.get("content-type")?.includes("application/json");
  const data = isJson ? await res.json() : null;
  if (res.status === 401 && path !== "/api/auth/login") {
    token.clear();
    window.dispatchEvent(new Event("khataz:logout"));
  }
  if (!res.ok) throw new ApiError(res.status, errorText(data, res.status));
  if (method !== "GET") window.dispatchEvent(new Event("khataz:changed")); // refresh header counts
  return data;
}

export async function apiBlobUrl(path) {
  const t = token.get();
  const res = await fetch(`${BASE}${path}`, { headers: t ? { Authorization: `Bearer ${t}` } : {} });
  if (!res.ok) throw new ApiError(res.status, "Image not available");
  return URL.createObjectURL(await res.blob());
}
