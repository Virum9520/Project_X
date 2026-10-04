import * as Sentry from "@sentry/nextjs";
import { registerOTel } from "@vercel/otel";
import { scrubEvent, sentryOptions } from "@/lib/observability";

// Server-side observability (C23). Both integrations are no-ops until configured:
// NEXT_PUBLIC_SENTRY_DSN for errors, OTEL_EXPORTER_OTLP_ENDPOINT for traces.
export function register() {
  const options = sentryOptions();
  if (options.enabled) {
    Sentry.init({ ...options, beforeSend: (event) => scrubEvent(event) });
  }
  if (process.env.OTEL_EXPORTER_OTLP_ENDPOINT) {
    registerOTel({ serviceName: process.env.OTEL_SERVICE_NAME ?? "sg-web" });
  }
}

export const onRequestError = Sentry.captureRequestError;
