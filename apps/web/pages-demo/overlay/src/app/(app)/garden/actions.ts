import type { AskSanjayaAnswer, MemoryItem } from "@sg/contracts";

/** Static demo: there is no API, so memory edits and questions are declined politely. */
export type ActionResult<T> = { ok: true; data: T } | { ok: false; message: string };

const OFFLINE = {
  ok: false,
  message: "This is a static demo. Sign in to the full app to do that.",
} as const;

export async function correctMemory(
  _id: string,
  _content: string,
): Promise<ActionResult<MemoryItem>> {
  return OFFLINE;
}
export async function deleteMemory(_id: string): Promise<ActionResult<null>> {
  return OFFLINE;
}
export async function askSanjaya(_question: string): Promise<ActionResult<AskSanjayaAnswer>> {
  return OFFLINE;
}
