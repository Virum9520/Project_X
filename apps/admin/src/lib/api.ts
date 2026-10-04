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
