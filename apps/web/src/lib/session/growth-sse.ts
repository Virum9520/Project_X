import type { LiveGrowthEvent } from "@sg/contracts";

const KINDS = new Set(["provisional", "confirmed", "retracted", "noted"]);
const PARTS = new Set(["roots", "stem", "branches", "blossoms"]);

/** Validate one SSE `data` payload. The stream is trusted, but a bad frame must not crash the UI. */
export function parseGrowthEvent(data: string): LiveGrowthEvent | null {
  let raw: unknown;
  try {
    raw = JSON.parse(data);
  } catch {
    return null;
  }
  if (typeof raw !== "object" || raw === null) return null;
  const e = raw as Record<string, unknown>;
  if (typeof e.id !== "string" || typeof e.conceptId !== "string") return null;
  if (typeof e.kind !== "string" || !KINDS.has(e.kind)) return null;
  const part = typeof e.part === "string" && PARTS.has(e.part) ? e.part : null;
  const str = (v: unknown) => (typeof v === "string" ? v : "");
  return {
    id: e.id,
    kind: e.kind as LiveGrowthEvent["kind"],
    sessionId: str(e.sessionId),
    conceptId: e.conceptId,
    questionId: typeof e.questionId === "string" ? e.questionId : null,
    dimension: str(e.dimension),
    part: part as LiveGrowthEvent["part"],
    outcome: (str(e.outcome) || "unassessable") as LiveGrowthEvent["outcome"],
    assisted: e.assisted === true,
    quote: str(e.quote),
    note: str(e.note),
    judge: str(e.judge),
    reason: str(e.reason),
    occurredAt: str(e.occurredAt),
  };
}

/** Only growth that actually changes a plant makes it glow; `noted` observations do not. */
export const pulses = (e: LiveGrowthEvent) => e.kind !== "noted";

/** Concept ids that glow at `now`, given each concept's last pulse time. */
export function activePulses(
  lastPulse: ReadonlyMap<string, number>,
  now: number,
  ttlMs: number,
): Set<string> {
  const out = new Set<string>();
  for (const [id, at] of lastPulse) if (now - at < ttlMs) out.add(id);
  return out;
}
