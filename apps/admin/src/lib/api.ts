import { auth } from "@clerk/nextjs/server";

const API_URL = process.env.API_URL ?? "http://localhost:8000";

export type ApiResult<T> = { ok: true; data: T } | { ok: false; status: number; detail: string };

async function call<T>(path: string, init: RequestInit): Promise<ApiResult<T>> {
  const token = await (await auth()).getToken();
  if (!token) return { ok: false, status: 401, detail: "not signed in" };
  try {
    const response = await fetch(`${API_URL}${path}`, {
      ...init,
      headers: {
        ...init.headers,
        Authorization: `Bearer ${token}`,
        ...(init.body ? { "Content-Type": "application/json" } : {}),
      },
      cache: "no-store",
    });
    if (!response.ok) {
      const body = (await response.json().catch(() => ({}))) as { detail?: unknown };
      const detail =
        typeof body.detail === "string"
          ? body.detail
          : Array.isArray(body.detail)
            ? "the request was not valid"
            : response.statusText;
      return { ok: false, status: response.status, detail };
    }
    return { ok: true, data: (await response.json()) as T };
  } catch {
    return { ok: false, status: 0, detail: `API unreachable at ${API_URL}` };
  }
}

/** Server-side call to `services/api` with the caller's Clerk session token. */
export function apiGet<T>(path: string): Promise<ApiResult<T>> {
  return call<T>(path, { method: "GET" });
}

/** Server-side mutation. The API re-checks the capability, applies the CSRF guard and audits it. */
export function apiPost<T>(path: string, body: unknown): Promise<ApiResult<T>> {
  return call<T>(path, { method: "POST", body: JSON.stringify(body) });
}

/** Query string from defined, non-empty values only. */
export function query(params: Record<string, string | number | undefined | null>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null && value !== "") search.set(key, String(value));
  }
  const text = search.toString();
  return text ? `?${text}` : "";
}
