import { describe, expect, it } from "vitest";

import { REDACTED, redactText, scrubEvent } from "./observability";

describe("web error-report scrubbing", () => {
  it("redacts emails, bearer tokens, JWTs, API keys and share-link tokens", () => {
    const out = redactText(
      "mail a@b.co Bearer abcdefgh12345 eyJhbGciOi.eyJzdWIiOi.sig sk-abcdefghijklmnop /recap/shared/SIGNED.TOKEN?x=1",
    );
    expect(out).not.toMatch(/a@b\.co|abcdefgh12345|eyJhbGciOi|sk-abcdef|SIGNED\.TOKEN/);
    expect(out).toContain("/recap/shared/" + REDACTED);
  });

  it("drops request bodies, headers, cookies and user identity", () => {
    const event = scrubEvent({
      user: { email: "x@y.com" },
      request: { url: "/a", data: "secret", cookies: "c", headers: { a: "b" } },
      extra: { transcript: "I said hello", count: 3 },
    }) as { user?: unknown; request: { data?: unknown; headers?: unknown }; extra: unknown };
    expect(event.user).toBeUndefined();
    expect(event.request.data).toBeUndefined();
    expect(event.request.headers).toBeUndefined();
    expect(event.extra).toEqual({ transcript: REDACTED, count: 3 });
  });
});
