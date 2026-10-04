// Shared, dependency-free pieces of web observability (C23): PII scrubbing for error
// reports and the env-driven config. Everything is a no-op without a DSN / OTLP endpoint.

export const REDACTED = "[redacted]";

const SENSITIVE_KEY = /authorization|cookie|password|secret|token|api[_-]?key|email|phone|transcript|answer|quote/i;
const EMAIL = /[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}/g;
const BEARER = /\b(Bearer|Basic)\s+[A-Za-z0-9._~+/=-]{8,}/gi;
const JWT = /\beyJ[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]*/g;
const API_KEY = /\b(?:sk|pk|rk|xi|whsec|ghp)(?:_(?:live|test))?[-_][A-Za-z0-9_-]{12,}/g;
// Signed share links carry their credential in the path.
const SHARED_PATH = /(\/recap\/shared\/)[^/?#\s]+/g;

export function redactText(text: string): string {
  return text
    .replace(SHARED_PATH, `$1${REDACTED}`)
    .replace(BEARER, (_m, scheme: string) => `${scheme} ${REDACTED}`)
    .replace(JWT, REDACTED)
    .replace(API_KEY, REDACTED)
    .replace(EMAIL, "[email]");
}

export function redactValue(value: unknown, depth = 0): unknown {
  if (depth > 8) return REDACTED;
  if (typeof value === "string") return redactText(value);
  if (Array.isArray(value)) return value.map((v) => redactValue(v, depth + 1));
  if (value && typeof value === "object") {
    return Object.fromEntries(
      Object.entries(value as Record<string, unknown>).map(([k, v]) => [
        k,
        SENSITIVE_KEY.test(k) ? REDACTED : redactValue(v, depth + 1),
      ]),
    );
  }
  return value;
}

/** Sentry `beforeSend`: no request bodies, cookies, headers or user identity leave the app. */
export function scrubEvent<T extends object>(event: T): T {
  const e = event as Record<string, unknown>;
  const request = e.request as Record<string, unknown> | undefined;
  if (request) {
    delete request.data;
    delete request.cookies;
    delete request.headers;
    delete request.query_string;
  }
  delete e.user;
  for (const key of ["message", "exception", "breadcrumbs", "extra", "contexts", "tags", "request"]) {
    if (key in e) e[key] = redactValue(e[key]);
  }
  return event;
}

export function sentryOptions() {
  const dsn = process.env.NEXT_PUBLIC_SENTRY_DSN;
  return {
    dsn: dsn || undefined,
    enabled: Boolean(dsn),
    environment: process.env.SENTRY_ENVIRONMENT ?? process.env.VERCEL_ENV ?? "local",
    release: process.env.VERCEL_GIT_COMMIT_SHA,
    tracesSampleRate: Number(process.env.SENTRY_TRACES_SAMPLE_RATE ?? 0),
    sendDefaultPii: false,
  };
}
