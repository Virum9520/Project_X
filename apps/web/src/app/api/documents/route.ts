import { auth } from "@clerk/nextjs/server";

import { isInterviewKind, validateUpload } from "@/lib/documents/upload";

const API_URL = process.env.API_URL ?? "http://localhost:8000";
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

// Browser -> this handler -> `POST /v1/documents`, with the learner's Clerk token added
// server-side. Only résumés and job descriptions are accepted here (study material has its own
// flow). The file is forwarded as an opaque blob: its text is data and is never interpreted.
export const dynamic = "force-dynamic";

export async function POST(request: Request) {
  const token = await (await auth()).getToken();
  if (!token) return Response.json({ detail: "not signed in" }, { status: 401 });

  let form: FormData;
  try {
    form = await request.formData();
  } catch {
    return Response.json({ detail: "expected a multipart upload" }, { status: 400 });
  }
  const file = form.get("file");
  const kind = form.get("kind");
  const documentId = form.get("document_id");
  if (!(file instanceof File) || !isInterviewKind(kind))
    return Response.json({ detail: "choose a file and a document type" }, { status: 400 });
  const problem = validateUpload(file);
  if (problem) return Response.json({ detail: problem }, { status: 415 });
  if (documentId !== null && (typeof documentId !== "string" || !UUID.test(documentId)))
    return Response.json({ detail: "unknown document" }, { status: 400 });

  const out = new FormData();
  out.set("file", file, file.name);
  out.set("kind", kind);
  if (typeof documentId === "string") out.set("document_id", documentId);

  try {
    const upstream = await fetch(`${API_URL}/v1/documents`, {
      method: "POST",
      headers: { Authorization: `Bearer ${token}` },
      body: out,
      cache: "no-store",
    });
    return new Response(upstream.body, {
      status: upstream.status,
      headers: {
        "Content-Type": upstream.headers.get("content-type") ?? "application/json",
        "Cache-Control": "no-store",
      },
    });
  } catch {
    return Response.json({ detail: "The upload service is unreachable." }, { status: 502 });
  }
}
