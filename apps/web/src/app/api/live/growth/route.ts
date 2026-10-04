import { auth } from "@clerk/nextjs/server";

const API_URL = process.env.API_URL ?? "http://localhost:8000";

// Browser EventSource cannot send an Authorization header, so it connects here and this handler
// opens the stream on `services/api` with the learner's Clerk token, then pipes it through.
// The stream is per learner on the API side; nothing in the URL selects whose events to read.
export const dynamic = "force-dynamic";

export async function GET(request: Request) {
  const token = await (await auth()).getToken();
  if (!token) return Response.json({ detail: "not signed in" }, { status: 401 });

  const headers = new Headers({ Authorization: `Bearer ${token}`, Accept: "text/event-stream" });
  const resume = request.headers.get("last-event-id");
  if (resume && /^\d+$/.test(resume)) headers.set("Last-Event-ID", resume);

  try {
    const upstream = await fetch(`${API_URL}/v1/live/growth`, {
      headers,
      cache: "no-store",
      signal: request.signal,
    });
    if (!upstream.ok || !upstream.body) {
      return Response.json(
        { detail: "live updates unavailable" },
        { status: upstream.status || 502 },
      );
    }
    return new Response(upstream.body, {
      status: 200,
      headers: {
        "Content-Type": "text/event-stream; charset=utf-8",
        "Cache-Control": "no-store, no-transform",
        "X-Accel-Buffering": "no",
        Connection: "keep-alive",
      },
    });
  } catch {
    return Response.json({ detail: "live updates unreachable" }, { status: 502 });
  }
}
