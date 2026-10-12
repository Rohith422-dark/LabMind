import type { components } from "./schema";

export type Schemas = components["schemas"];

const TOKEN_KEY = "sla_token";

export const tokenStore = {
  get: () => {
    try { return localStorage.getItem(TOKEN_KEY); } catch { return null; }
  },
  set: (t: string) => { try { localStorage.setItem(TOKEN_KEY, t); } catch { /* ignore */ } },
  clear: () => { try { localStorage.removeItem(TOKEN_KEY); } catch { /* ignore */ } },
};

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

let onUnauthorized: () => void = () => {};
export const setUnauthorizedHandler = (fn: () => void) => { onUnauthorized = fn; };

function headers(extra?: HeadersInit, json = true): Headers {
  const h = new Headers(extra);
  const t = tokenStore.get();
  if (t) h.set("Authorization", `Bearer ${t}`);
  if (json && !h.has("Content-Type")) h.set("Content-Type", "application/json");
  return h;
}

async function fail(res: Response): Promise<never> {
  let msg = res.statusText;
  try {
    const body = await res.json();
    if (typeof body.detail === "string") msg = body.detail;
  } catch { /* non-JSON body */ }
  if (res.status === 401 && tokenStore.get()) onUnauthorized();
  throw new ApiError(res.status, msg);
}

export async function api<T>(path: string, init: RequestInit & { json?: unknown } = {}): Promise<T> {
  const isForm = init.body instanceof FormData;
  const res = await fetch(`/api${path}`, {
    ...init,
    headers: headers(init.headers, !isForm),
    body: init.json !== undefined ? JSON.stringify(init.json) : init.body,
  });
  if (!res.ok) await fail(res);
  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

export async function apiBlob(path: string): Promise<Blob> {
  const res = await fetch(`/api${path}`, { headers: headers(undefined, false) });
  if (!res.ok) await fail(res);
  return res.blob();
}

/** POST and read an NDJSON stream, calling onEvent for each parsed line. */
export async function streamNdjson<E>(path: string, json: unknown, onEvent: (e: E) => void,
                                      signal?: AbortSignal): Promise<void> {
  const res = await fetch(`/api${path}`, { method: "POST", headers: headers(), body: JSON.stringify(json), signal });
  if (!res.ok || !res.body) await fail(res);
  const reader = res.body!.getReader();
  const dec = new TextDecoder();
  let buf = "";
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buf += dec.decode(value, { stream: true });
    let i: number;
    while ((i = buf.indexOf("\n")) >= 0) {
      const line = buf.slice(0, i).trim();
      buf = buf.slice(i + 1);
      if (line) onEvent(JSON.parse(line) as E);
    }
  }
  if (buf.trim()) onEvent(JSON.parse(buf) as E);
}
