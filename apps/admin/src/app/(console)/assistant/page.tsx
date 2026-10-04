import type { AssistantStatus } from "@sg/contracts";

import { Badge, Card, PageHeader, Stat } from "@/components/ui";
import { apiGet } from "@/lib/api";
import { usd } from "@/lib/format";
import { requireOwner } from "@/lib/owner";

import { AskBox } from "./ask-box";

/**
 * Ask the owner assistant (C22). Owner-only and read-only: questions go to the API, which runs an
 * OpenRouter model over the MCP gateway (ElevenLabs hosted MCP and a read-only Tiger MCP role).
 * Every question and tool call is audited; spend is held against the owner-assistant budget.
 */
export default async function AssistantPage() {
  await requireOwner();
  const status = await apiGet<AssistantStatus>("/v1/admin/assistant/status");
  const s = status.ok ? status.data : null;
  const disabled = !status.ok || !s?.model_configured;
  const reason = !status.ok
    ? `The assistant API is not reachable: ${status.detail}`
    : !s?.model_configured
      ? "No model key is configured (OPENROUTER_API_KEY), so the assistant cannot answer yet."
      : null;
  const budget = s?.budget;

  return (
    <>
      <PageHeader
        title="Ask the owner assistant"
        subtitle="Natural-language questions over usage, cost, calls and quality. Read-only: it cannot place calls or change anything."
      />

      <div className="grid gap-3 sm:grid-cols-3">
        <Stat
          label="Assistant budget, this month"
          value={budget ? usd(budget.committed_usd) : "n/a"}
          hint={budget ? `of ${usd(budget.limit_usd)} (holds included)` : "budget unavailable"}
          tone={budget && budget.committed_usd >= budget.limit_usd ? "bad" : "default"}
        />
        <Stat label="Model" value={<span className="text-base">{s?.model ?? "unknown"}</span>} />
        <div className="rounded-xl border border-white/10 bg-dusk/60 p-4">
          <p className="text-xs uppercase tracking-wider text-foreground/50">Data sources</p>
          <div className="mt-2 flex flex-wrap gap-2">
            {Object.entries(s?.providers ?? {}).map(([name, connected]) => (
              <Badge key={name} tone={connected ? "good" : "neutral"}>
                {name === "tiger" ? "Tiger MCP (analytics views)" : "ElevenLabs hosted MCP"}:{" "}
                {connected ? "configured" : "not configured"}
              </Badge>
            ))}
          </div>
        </div>
      </div>

      <Card title="Conversation">
        <AskBox disabled={disabled} reason={reason} />
      </Card>

      <Card title="What it guarantees">
        <ul className="list-inside list-disc space-y-1 text-sm text-foreground/70">
          <li>Owner-only with MFA. The API checks it again; this page is not the boundary.</li>
          <li>
            Read-only: SELECTs over the analytics views, and ElevenLabs inspection tools only.
          </li>
          <li>
            Cost figures count only live ledger entries, so a reconciled amount replaces the
            estimate it superseded.
          </li>
          <li>Answers state their date range, metric definitions, freshness and amount basis.</li>
          <li>
            A disconnected data source gives an explicit partial answer. Tool output is treated as
            data, never as instructions.
          </li>
          <li>Every question and every tool call is in the audit log. Spend is budget-held.</li>
        </ul>
        {s && (
          <p className="mt-3 text-xs text-foreground/50">
            Limits per question: {s.limits.max_steps} model turns, {s.limits.max_tool_calls} tool
            calls, {s.limits.max_rows} rows and {Math.round(s.limits.max_tool_bytes / 1000)} KB per
            result.
          </p>
        )}
      </Card>
    </>
  );
}
