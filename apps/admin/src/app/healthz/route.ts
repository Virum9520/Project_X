import { connection } from "next/server";

// Liveness probe for deploy smoke tests. Listed as public in src/proxy.ts.
export async function GET() {
  await connection(); // always evaluate at request time, never prerender
  return Response.json(
    {
      status: "ok",
      service: "admin",
      environment: process.env.VERCEL_ENV ?? "local",
      commit: process.env.VERCEL_GIT_COMMIT_SHA ?? null,
      apiUrl: process.env.API_URL ?? null,
    },
    { headers: { "Cache-Control": "no-store" } },
  );
}
