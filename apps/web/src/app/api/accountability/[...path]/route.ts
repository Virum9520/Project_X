import { auth } from "@clerk/nextjs/server";

import { isAllowedRoute } from "@/lib/accountability/helpers";

const API_URL = process.env.API_URL ?? "http://localhost:8000";

// Browser -> this handler -> `services/api`, with the learner's Clerk token added server-side.
// Only the learner accountability routes are reachable (see `isAllowedRoute`).
async function forward(request: Request, ctx: RouteContext<"/api/accountability/[...path]">) {
  const { path } = await ctx.params;
  const route = path.join("/");
  if (!isAllowedRoute(route, request.method)) {
    return Response.json({ detail: "not found" }, { status: 404 });
  }
  const token = await (await auth()).getToken();
  if (!token) return Response.json({ detail: "not signed in" }, { status: 401 });

  const headers = new Headers({ Authorization: `Bearer ${token}` });
  const hasBody = request.method === "POST" || request.method === "PUT";
  if (hasBody) headers.set("Content-Type", "application/json");
  const userAgent = request.headers.get("user-agent");
  if (userAgent) headers.set("User-Agent", userAgent);
  try {
    const upstream = await fetch(`${API_URL}/v1/accountability/${route}`, {
      method: request.method,
      headers,
      body: hasBody ? await request.text() : undefined,
      cache: "no-store",
    });
    return new Response(upstream.status === 204 ? null : upstream.body, {
      status: upstream.status,
      headers: {
        "Content-Type": upstream.headers.get("content-type") ?? "application/json",
        "Cache-Control": "no-store",
      },
    });
  } catch {
    return Response.json({ detail: "call service unreachable" }, { status: 502 });
  }
}

export { forward as GET, forward as POST, forward as PUT, forward as DELETE };
