// Fetch wrapper: bearer access token in memory, silent refresh via the httpOnly cookie, typed errors.
import type { AuthResponse } from "./types";

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

let accessToken: string | null = null;
let onSessionLost: (() => void) | null = null;
let refreshInFlight: Promise<AuthResponse | null> | null = null;
const listeners = new Set<(a: AuthResponse | null) => void>();

export const getAccessToken = () => accessToken;
export const setAccessToken = (t: string | null) => {
  accessToken = t;
};
/** Called when a refresh fails after a 401: the session is gone and the UI must go to sign-in. */
export const setSessionLostHandler = (fn: (() => void) | null) => {
  onSessionLost = fn;
};
/** Subscribe to token refreshes (the WebSocket reconnects with the new token). */
export const onTokenRefreshed = (fn: (a: AuthResponse | null) => void) => {
  listeners.add(fn);
  return () => {
    listeners.delete(fn);
  };
};

/** Turn FastAPI's error payloads (string or validation list) into one readable sentence. */
function messageFrom(payload: unknown, status: number): string {
  const detail = (payload as { detail?: unknown } | null)?.detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail) && detail.length) {
    return detail
      .map((d: { msg?: string; loc?: (string | number)[] }) => {
        const field = d.loc?.filter((p) => p !== "body" && p !== "query").join(".");
        const msg = (d.msg ?? "Invalid value").replace(/^Value error, /, "");
        return field ? `${field}: ${msg}` : msg;
      })
      .join("; ");
  }
  if (status === 0) return "Cannot reach the server. Check your connection.";
  if (status >= 500) return "The server had a problem. Please try again.";
  return `Request failed (${status})`;
}

async function send(path: string, init: RequestInit & { json?: unknown }): Promise<Response> {
  const headers = new Headers(init.headers);
  if (init.json !== undefined) headers.set("Content-Type", "application/json");
  if (accessToken) headers.set("Authorization", `Bearer ${accessToken}`);
  try {
    return await fetch(path, {
      ...init,
      headers,
      body: init.json !== undefined ? JSON.stringify(init.json) : init.body,
      credentials: "same-origin",
    });
  } catch {
    throw new ApiError(0, messageFrom(null, 0));
  }
}

/** Exchange the refresh cookie for a new access token. Single-flight, with one retry (another tab may have rotated). */
export function refreshSession(): Promise<AuthResponse | null> {
  if (refreshInFlight) return refreshInFlight;
  refreshInFlight = (async () => {
    for (let attempt = 0; attempt < 2; attempt++) {
      try {
        const res = await fetch("/api/auth/refresh", { method: "POST", credentials: "same-origin" });
        if (res.ok) {
          const data = (await res.json()) as AuthResponse;
          accessToken = data.access_token;
          listeners.forEach((fn) => fn(data));
          return data;
        }
        if (res.status !== 401) break;
      } catch {
        break;
      }
      await new Promise((r) => setTimeout(r, 350));
    }
    accessToken = null;
    listeners.forEach((fn) => fn(null));
    return null;
  })().finally(() => {
    refreshInFlight = null;
  });
  return refreshInFlight;
}

export interface RequestOptions {
  method?: "GET" | "POST" | "PATCH" | "DELETE";
  json?: unknown;
  signal?: AbortSignal;
  /** Skip the bearer token and the refresh-on-401 logic (sign in / sign up). */
  anonymous?: boolean;
}

export async function api<T>(path: string, opts: RequestOptions = {}): Promise<T> {
  const { method = opts.json !== undefined ? "POST" : "GET", json, signal, anonymous } = opts;
  const doFetch = () => send(path, { method, json, signal, ...(anonymous ? { headers: {} } : {}) });

  let res: Response;
  if (anonymous) {
    const saved = accessToken;
    accessToken = null;
    try {
      res = await doFetch();
    } finally {
      accessToken = saved;
    }
  } else {
    res = await doFetch();
    if (res.status === 401 && accessToken !== null) {
      const renewed = await refreshSession();
      if (renewed) {
        res = await doFetch();
      } else {
        onSessionLost?.();
      }
    }
  }

  let payload: unknown = null;
  const text = await res.text();
  if (text) {
    try {
      payload = JSON.parse(text);
    } catch {
      payload = null;
    }
  }
  if (!res.ok) throw new ApiError(res.status, messageFrom(payload, res.status));
  return payload as T;
}
