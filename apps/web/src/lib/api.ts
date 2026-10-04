import { auth } from "@clerk/nextjs/server";

const API_URL = process.env.API_URL ?? "http://localhost:8000";

export type ApiResult<T> = { ok: true; data: T } | { ok: false; status: number; detail: string };

/** Server-side call to `services/api` with the caller's Clerk session token. */
export async function apiGet<T>(path: string): Promise<ApiResult<T>> {
  const token = await (await auth()).getToken();
  if (!token) return { ok: false, status: 401, detail: "not signed in" };
  try {
    const response = await fetch(`${API_URL}${path}`, {
      headers: { Authorization: `Bearer ${token}` },
      cache: "no-store",
    });
    if (!response.ok) {
      const body = (await response.json().catch(() => ({}))) as { detail?: string };
      return { ok: false, status: response.status, detail: body.detail ?? response.statusText };
    }
    return { ok: true, data: (await response.json()) as T };
  } catch {
    return { ok: false, status: 0, detail: `API unreachable at ${API_URL}` };
  }
}

/** Server-side mutation (POST, DELETE, ...) with the caller's Clerk session token. */
export async function apiSend<T>(
  method: "POST" | "PUT" | "PATCH" | "DELETE",
  path: string,
  body?: unknown,
): Promise<ApiResult<T>> {
  const token = await (await auth()).getToken();
  if (!token) return { ok: false, status: 401, detail: "not signed in" };
  try {
    const response = await fetch(`${API_URL}${path}`, {
      method,
      headers: {
        Authorization: `Bearer ${token}`,
        ...(body === undefined ? {} : { "Content-Type": "application/json" }),
      },
      body: body === undefined ? undefined : JSON.stringify(body),
      cache: "no-store",
    });
    if (!response.ok) {
      const payload = (await response.json().catch(() => ({}))) as { detail?: unknown };
      const detail = typeof payload.detail === "string" ? payload.detail : response.statusText;
      return { ok: false, status: response.status, detail };
    }
    if (response.status === 204) return { ok: true, data: undefined as T };
    return { ok: true, data: (await response.json()) as T };
  } catch {
    return { ok: false, status: 0, detail: `API unreachable at ${API_URL}` };
  }
}
