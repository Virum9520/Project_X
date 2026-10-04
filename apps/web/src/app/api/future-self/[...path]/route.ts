import { auth } from "@clerk/nextjs/server";

const API_URL = process.env.API_URL ?? "http://localhost:8000";

// Browser -> this handler -> `services/api`, with the learner's Clerk token added server-side.
// Only the Future-Self routes are reachable, and only with the methods each one allows.
const ALLOWED: Record<string, readonly string[]> = {
  consent: ["GET", "DELETE"],
  "consent/challenge": ["POST"],
  "consent/recording": ["POST"],
  message: ["POST"],
};
const FORWARDED_HEADERS = ["content-type", "x-consent-challenge", "x-consent-accepted"];

async function forward(request: Request, ctx: RouteContext<"/api/future-self/[...path]">) {
  const { path } = await ctx.params;
  const route = path.join("/");
  if (!ALLOWED[route]?.includes(request.method)) {
    return Response.json({ detail: "not found" }, { status: 404 });
  }
  const token = await (await auth()).getToken();
  if (!token) return Response.json({ detail: "not signed in" }, { status: 401 });

  const headers = new Headers({ Authorization: `Bearer ${token}` });
  for (const name of FORWARDED_HEADERS) {
    const value = request.headers.get(name);
    if (value) headers.set(name, value);
  }
  const hasBody = request.method === "POST" && route === "consent/recording";
  try {
    const upstream = await fetch(`${API_URL}/v1/future-self/${route}`, {
      method: request.method,
      headers,
      body: hasBody ? await request.arrayBuffer() : undefined,
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
    return Response.json({ detail: "voice service unreachable" }, { status: 502 });
  }
}

export { forward as GET, forward as POST, forward as DELETE };
