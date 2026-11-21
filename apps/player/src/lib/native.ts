/**
 * Web vs. phone app (Capacitor). The same React app runs in both; this file
 * holds the few differences: where the API lives, the public site URL for
 * shared links, and where the app keeps its refresh token.
 */
import { Capacitor } from "@capacitor/core";
import { Preferences } from "@capacitor/preferences";

export const isNative = Capacitor.isNativePlatform();
export const nativePlatform = Capacitor.getPlatform(); // "android" | "ios" | "web"

const env = import.meta.env as Record<string, string | undefined>;

/** Web: same-origin "/api" (proxied). App: absolute API URL baked in at build time. */
// `||`, not `??`: CI passes unset variables as empty strings.
export const API_BASE = (env.VITE_API_BASE_URL || "/api").replace(/\/$/, "");

/** Links people share must point at the public site, never at the app's own origin. */
export const PUBLIC_URL = (env.VITE_PUBLIC_URL || (isNative ? "" : location.origin)).replace(/\/$/, "");

/**
 * Test builds only: sign in automatically as this seeded demo player
 * (VITE_DEMO_PLAYER=alice). Uses the API's /dev/token endpoint, which exists
 * only when the API runs with PLATFORM_ENV=local - so it can't work against a
 * real server.
 */
export const DEMO_PLAYER = env.VITE_DEMO_PLAYER || null;
export const DEV_TOOLS = import.meta.env.DEV || !!DEMO_PLAYER;

const REFRESH_KEY = "fk.refresh";

// TODO(security): move to Android Keystore / iOS Keychain storage before launch;
// Preferences is app-private storage, not encrypted.
export async function loadRefreshToken(): Promise<string | null> {
  return (await Preferences.get({ key: REFRESH_KEY })).value;
}

export async function saveRefreshToken(token: string | null): Promise<void> {
  if (token) await Preferences.set({ key: REFRESH_KEY, value: token });
  else await Preferences.remove({ key: REFRESH_KEY });
}
