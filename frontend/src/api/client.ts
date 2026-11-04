import { useCallback, useEffect, useState } from "react";

const TOKEN_KEY = "rc.token";
const API_BASE_KEY = "rc.apiBase";

// The web app is served next to the API ("/api"). The Android app bundles the web files, so it
// needs an absolute server address: set at build time (VITE_API_BASE) or changed on the login screen.
export const apiBase = {
  get: (): string => {
    try {
      const saved = localStorage.getItem(API_BASE_KEY);
      if (saved) return saved;
    } catch {
      /* storage unavailable */
    }
    return import.meta.env.VITE_API_BASE || "/api";
  },
  set: (url: string | null) => {
    try {
      if (url) localStorage.setItem(API_BASE_KEY, url.replace(/\/+$/, ""));
      else localStorage.removeItem(API_BASE_KEY);
    } catch {
      /* storage unavailable */
    }
  },
};

// True inside the Android (Capacitor) app.
export const isNativeApp = () =>
  typeof window !== "undefined" && !!(window as unknown as { Capacitor?: { isNativePlatform?: () => boolean } }).Capacitor?.isNativePlatform?.();

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

// Token kept in sessionStorage (cleared when the tab closes). Production: short-lived
// tokens + refresh via httpOnly cookie at the edge (see docs/SECURITY.md).
export const tokenStore = {
  get: () => {
    try {
      return sessionStorage.getItem(TOKEN_KEY);
    } catch {
      return null;
    }
  },
  set: (t: string | null) => {
    try {
      if (t) sessionStorage.setItem(TOKEN_KEY, t);
      else sessionStorage.removeItem(TOKEN_KEY);
    } catch {
      /* storage unavailable */
    }
  },
};

let onUnauthorized: (() => void) | null = null;
export const setUnauthorizedHandler = (fn: () => void) => (onUnauthorized = fn);

function detailMessage(body: unknown, status: number): string {
  if (body && typeof body === "object" && "detail" in body) {
    const d = (body as { detail: unknown }).detail;
    if (typeof d === "string") return d;
    if (Array.isArray(d)) return d.map((e) => (e as { msg?: string }).msg ?? "Invalid input").join("; ");
    if (d && typeof d === "object" && "errors" in d) return ((d as { errors: string[] }).errors ?? []).join("; ");
  }
  return `Request failed (${status})`;
}

export async function api<T = unknown>(path: string, opts: { method?: string; body?: unknown; form?: FormData } = {}): Promise<T> {
  const headers: Record<string, string> = {};
  const token = tokenStore.get();
  if (token) headers.Authorization = `Bearer ${token}`;
  let body: BodyInit | undefined;
  if (opts.form) body = opts.form;
  else if (opts.body !== undefined) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(opts.body);
  }
  const res = await fetch(apiBase.get() + path, { method: opts.method ?? (body ? "POST" : "GET"), headers, body });
  const text = await res.text();
  const data = text ? (() => { try { return JSON.parse(text); } catch { return text; } })() : null;
  if (res.status === 401 && onUnauthorized && !path.startsWith("/auth/login")) onUnauthorized();
  if (!res.ok) throw new ApiError(res.status, detailMessage(data, res.status));
  return data as T;
}

export function useApi<T>(path: string | null, deps: unknown[] = []) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState<boolean>(!!path);

  const load = useCallback(async () => {
    if (!path) return;
    setLoading(true);
    try {
      setData(await api<T>(path));
      setError(null);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [path, ...deps]);

  useEffect(() => {
    load();
  }, [load]);

  return { data, error, loading, reload: load, setData };
}
