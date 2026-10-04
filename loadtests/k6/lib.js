// Shared helpers for the Skill Garden k6 scripts. See ../README.md.
import { check } from "k6";

export const API = (__ENV.API_URL || "http://localhost:8000").replace(/\/$/, "");

// Bearer token of a normal learner (K6_LEARNER_TOKEN) or the owner (K6_ADMIN_TOKEN). Both are
// short-lived Clerk session JWTs you paste in; scripts never create accounts or log in.
export function authHeaders(token) {
  return token ? { headers: { Authorization: `Bearer ${token}` } } : {};
}

export function ok(res, name) {
  return check(res, { [`${name} 2xx`]: (r) => r.status >= 200 && r.status < 300 });
}

// Guardrail so a typo cannot point a load test at production by accident.
export function assertNotProduction() {
  if (
    /skillgarden\.(app|com)|railway\.app$/i.test(API) &&
    __ENV.I_KNOW_THIS_IS_PRODUCTION !== "yes"
  ) {
    throw new Error(
      `Refusing to load test ${API}. Use dev or local, or set I_KNOW_THIS_IS_PRODUCTION=yes.`,
    );
  }
}
