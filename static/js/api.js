import { getLang, t } from "./i18n.js";

// Har darkhwast same-origin hai; session cookie browser khud bhejta hai (JavaScript usay nahi dekh sakta).
export async function api(method, path, body, extra = {}) {
  try {
    const res = await fetch(path, {
      method,
      credentials: "same-origin",
      headers: { "X-Lang": getLang(), ...(body ? { "Content-Type": "application/json" } : {}), ...extra },
      body: body ? JSON.stringify(body) : undefined,
    });
    let data = null;
    try { data = await res.json(); } catch { /* khali jawab */ }
    return { ok: res.ok, status: res.status, data };
  } catch {
    return { ok: false, status: 0, data: null };
  }
}

export function errorText(r) {
  if (r.status === 0) return t("err_network");
  const d = r.data && r.data.detail;
  if (d && d.message) return d.message;  // server ne pehle se user ki zaban mein likha hai
  if (Array.isArray(d)) return t("err_form");
  return t("err_generic");
}

// File upload: FormData; Content-Type browser khud lagata hai (boundary ke saath).
export async function apiUpload(path, file, extra = {}) {
  const fd = new FormData();
  fd.append("file", file);
  for (const [k, v] of Object.entries(extra)) fd.append(k, v);
  try {
    const res = await fetch(path, { method: "POST", credentials: "same-origin", headers: { "X-Lang": getLang() }, body: fd });
    let data = null;
    try { data = await res.json(); } catch { /* khali */ }
    return { ok: res.ok, status: res.status, data };
  } catch {
    return { ok: false, status: 0, data: null };
  }
}

export const idemKey = () => (globalThis.crypto && crypto.randomUUID ? crypto.randomUUID() : `k-${Date.now()}-${Math.random().toString(16).slice(2)}`);
