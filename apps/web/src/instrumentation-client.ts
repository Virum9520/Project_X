import * as Sentry from "@sentry/nextjs";
import { scrubEvent, sentryOptions } from "@/lib/observability";

// Browser error reporting (C23). No-op without NEXT_PUBLIC_SENTRY_DSN. No session replay, and
// request bodies, cookies and user identity are stripped before an event leaves the browser.
const options = sentryOptions();
if (options.enabled) {
  Sentry.init({ ...options, beforeSend: (event) => scrubEvent(event) });
}

export const onRouterTransitionStart = Sentry.captureRouterTransitionStart;
