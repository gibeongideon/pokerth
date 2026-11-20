/**
 * Typed client for the platform API, shared by the web app and the
 * Capacitor apps (D-011). Types come from the FastAPI OpenAPI schema:
 *   npm run api:types   (after exporting packages/api-client/openapi.json)
 *
 * Web uses httpOnly cookies; native apps pass a bearer token via getToken.
 * A 401 triggers one refresh attempt, then the request is retried.
 */
import createFetchClient, { type Middleware } from "openapi-fetch";
import type { paths } from "./schema";

export type { paths };

export interface ApiError {
  status: number;
  code: string;
  message: string;
}

export interface ClientOptions {
  baseUrl: string;
  getToken?: () => string | null;
  onRefresh?: () => Promise<boolean>;
}

export function createApi({ baseUrl, getToken, onRefresh }: ClientOptions) {
  const client = createFetchClient<paths>({ baseUrl, credentials: "include" });
  const auth: Middleware = {
    onRequest({ request }) {
      const token = getToken?.();
      if (token) request.headers.set("Authorization", `Bearer ${token}`);
      return request;
    },
  };
  client.use(auth);

  const retrying = new WeakSet<Request>();
  const refresh: Middleware = {
    async onResponse({ request, response }) {
      if (response.status !== 401 || !onRefresh || retrying.has(request)) return response;
      if (new URL(request.url).pathname.endsWith("/auth/refresh")) return response;
      if (!(await onRefresh())) return response;
      const retry = new Request(request);
      retrying.add(retry);
      const token = getToken?.();
      if (token) retry.headers.set("Authorization", `Bearer ${token}`);
      return fetch(retry);
    },
  };
  client.use(refresh);
  return client;
}

/** Turn an error body from the API into a readable error. */
export function toApiError(status: number, body: unknown): ApiError {
  const detail = (body as { detail?: unknown } | undefined)?.detail;
  if (detail && typeof detail === "object" && "code" in detail) {
    const d = detail as { code: string; message?: string };
    return { status, code: d.code, message: d.message ?? d.code };
  }
  if (Array.isArray(detail)) {
    return { status, code: "invalid", message: "Please check the form and try again." };
  }
  return { status, code: "error", message: "Something went wrong. Try again." };
}
