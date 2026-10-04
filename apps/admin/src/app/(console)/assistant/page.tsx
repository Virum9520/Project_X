import { Card, PageHeader } from "@/components/ui";
import { requireOwner } from "@/lib/owner";

/**
 * Placeholder. The owner assistant (OpenRouter tool use through `mcp_gateway`, ElevenLabs hosted
 * MCP and a read-only Tiger MCP role) is component C22. This page keeps the destination and
 * states the guarantees the assistant will have to meet.
 */
export default async function AssistantPage() {
  await requireOwner();
  return (
    <>
      <PageHeader
        title="Ask the owner assistant"
        subtitle="Natural-language questions over usage, cost and quality data."
      />
      <Card title="Not connected yet">
        <p className="text-sm text-foreground/70">
          The assistant arrives with the MCP gateway (component C22). Until then, the Overview,
          Usage and costs, Calls and Quality pages answer the same questions from the ledger
          directly.
        </p>
        <h3 className="mb-2 mt-5 text-xs uppercase tracking-wider text-foreground/50">
          What it will guarantee
        </h3>
        <ul className="list-inside list-disc space-y-1 text-sm text-foreground/70">
          <li>Read-only: it cannot place calls. Call now stays a separate, audited action.</li>
          <li>Every answer states its date range, metric definitions and freshness.</li>
          <li>It says whether figures are estimated or reconciled.</li>
          <li>Questions and tool calls are audited by the gateway.</li>
        </ul>
      </Card>
    </>
  );
}
