import { createApi, toApiError, type ApiError } from "@poker/api-client";
import { API_BASE, isNative, loadRefreshToken, saveRefreshToken } from "./native";

/**
 * Web: the API sets httpOnly cookies, so no token is kept here.
 * Dev demo players and (later) the Capacitor apps use a bearer token, kept
 * for this tab only. Storage can be unavailable (private mode), so every
 * access is guarded.
 */
const TOKEN_KEY = "fk.token";

export function getToken(): string | null {
  try {
    return sessionStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

export function setToken(token: string | null): void {
  try {
    if (token) sessionStorage.setItem(TOKEN_KEY, token);
    else sessionStorage.removeItem(TOKEN_KEY);
  } catch {
    /* ignore */
  }
}

/** Store what a sign-in returned. App: access token for this run + refresh
 * token on the device. Web: nothing (the API set httpOnly cookies). */
export async function storeSession(s: { access_token?: string | null; refresh_token?: string | null } | null): Promise<void> {
  if (!isNative) return;
  setToken(s?.access_token ?? null);
  await saveRefreshToken(s?.refresh_token ?? null);
}

async function refreshApp(): Promise<boolean> {
  const refreshToken = await loadRefreshToken();
  if (!refreshToken) return false;
  const res = await fetch(`${API_BASE}/auth/refresh`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ client: "app", refresh_token: refreshToken }),
  });
  if (!res.ok) {
    if (res.status === 401) await storeSession(null); // revoked or expired: sign in again
    return false;
  }
  await storeSession(await res.json());
  return true;
}

async function refreshWeb(): Promise<boolean> {
  if (getToken()) return false; // bearer tokens from dev sign-in are not refreshable
  const res = await fetch(`${API_BASE}/auth/refresh`, {
    method: "POST",
    credentials: "include",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ client: "web" }),
  });
  return res.ok;
}

// One refresh at a time: refresh tokens rotate, and presenting the same one
// twice (parallel 401s at start-up) would look like theft and end the session.
let inFlight: Promise<boolean> | null = null;
function refresh(): Promise<boolean> {
  inFlight ??= (isNative ? refreshApp() : refreshWeb()).finally(() => {
    inFlight = null;
  });
  return inFlight;
}

/** Sign out on this device. */
export async function signOut(): Promise<void> {
  const refreshToken = isNative ? await loadRefreshToken() : null;
  await fetch(`${API_BASE}/auth/logout`, {
    method: "POST",
    credentials: "include",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(refreshToken ? { refresh_token: refreshToken } : {}),
  }).catch(() => undefined);
  setToken(null);
  await storeSession(null);
}

export const api = createApi({ baseUrl: API_BASE, getToken, onRefresh: refresh });

/** Unwrap an openapi-fetch result: return data or throw an ApiError. */
export async function call<T = unknown>(
  request: Promise<{ data?: unknown; error?: unknown; response: Response }>,
): Promise<T> {
  const { data, error, response } = await request;
  if (!response.ok || error !== undefined) throw toApiError(response.status, error);
  return data as T;
}

export function isApiError(e: unknown): e is ApiError {
  return typeof e === "object" && e !== null && "code" in e && "message" in e;
}

export function errorMessage(e: unknown): string {
  return isApiError(e) ? e.message : "Something went wrong. Try again.";
}
