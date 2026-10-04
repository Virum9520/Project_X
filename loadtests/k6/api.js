// API load: liveness, readiness (touches Postgres + Redis) and, with a learner token, the
// learner read paths the app hits on every page (me, garden snapshot, analytics).
//
//   k6 run loadtests/k6/api.js                                   # smoke profile
//   k6 run -e PROFILE=load -e K6_LEARNER_TOKEN=... loadtests/k6/api.js
//
// Profiles: smoke (1 VU, 30 s), load (ramp to 50 VUs), stress (ramp to 200 VUs).
import http from "k6/http";
import { sleep } from "k6";

import { API, assertNotProduction, authHeaders, ok } from "./lib.js";

const PROFILES = {
  smoke: [{ duration: "30s", target: 1 }],
  load: [
    { duration: "1m", target: 20 },
    { duration: "3m", target: 50 },
    { duration: "1m", target: 0 },
  ],
  stress: [
    { duration: "2m", target: 100 },
    { duration: "3m", target: 200 },
    { duration: "1m", target: 0 },
  ],
};

export const options = {
  stages: PROFILES[__ENV.PROFILE || "smoke"],
  // Targets for a hackathon-scale cohort on Railway; tune with the real cohort size (build-plan
  // open question "initial cohort/concurrency").
  thresholds: {
    http_req_failed: ["rate<0.01"],
    "http_req_duration{route:healthz}": ["p(95)<200"],
    "http_req_duration{route:readyz}": ["p(95)<800"],
    "http_req_duration{route:garden}": ["p(95)<1200"],
    "http_req_duration{route:me}": ["p(95)<600"],
  },
};

const learner = __ENV.K6_LEARNER_TOKEN;

export function setup() {
  assertNotProduction();
}

export default function () {
  ok(http.get(`${API}/healthz`, { tags: { route: "healthz" } }), "healthz");
  ok(http.get(`${API}/readyz`, { tags: { route: "readyz" } }), "readyz");

  if (learner) {
    const h = authHeaders(learner);
    ok(http.get(`${API}/v1/me`, { ...h, tags: { route: "me" } }), "me");
    ok(
      http.get(`${API}/v1/garden/snapshot`, { ...h, tags: { route: "garden" } }),
      "garden snapshot",
    );
    ok(
      http.get(`${API}/v1/garden/analytics`, { ...h, tags: { route: "garden" } }),
      "garden analytics",
    );
  }
  sleep(1);
}
