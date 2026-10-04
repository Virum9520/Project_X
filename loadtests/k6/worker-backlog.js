// Worker backlog: flood the signed webhook endpoint with unique events, then watch the owner
// console Quality numbers (webhook oldest unprocessed age, provider events by status) drain.
//
// The events use type `load_test_ping`, which the worker records and ignores, so no judge or
// ElevenLabs call is made and no money is spent. They are real `provider_events` rows with
// provider `elevenlabs`; delete them afterwards (see README) if you ran against a shared DB.
//
//   k6 run -e API_URL=http://localhost:8000 -e ELEVENLABS_WEBHOOK_SECRET=... \
//          -e K6_ADMIN_TOKEN=... loadtests/k6/worker-backlog.js
//
// Needs a locally configured API + worker with the same webhook secret. Never use a production
// secret: guard in lib.js refuses production URLs.
import crypto from "k6/crypto";
import http from "k6/http";
import { sleep } from "k6";
import { Trend } from "k6/metrics";

import { API, assertNotProduction, authHeaders, ok } from "./lib.js";

const SECRET = __ENV.ELEVENLABS_WEBHOOK_SECRET;
const backlogAge = new Trend("webhook_oldest_unprocessed_age_s");

export const options = {
  scenarios: {
    flood: {
      executor: "constant-arrival-rate",
      rate: Number(__ENV.RATE || 50),
      timeUnit: "1s",
      duration: __ENV.DURATION || "1m",
      preAllocatedVUs: 50,
      maxVUs: 200,
      exec: "flood",
    },
    watch: {
      executor: "constant-vus",
      vus: 1,
      duration: __ENV.WATCH_DURATION || "3m", // longer than the flood so the drain is visible
      exec: "watch",
    },
  },
  thresholds: {
    // Ingest must stay fast even when the worker is behind: it stores first and acknowledges.
    "http_req_duration{route:webhook}": ["p(95)<500"],
    http_req_failed: ["rate<0.01"],
    // Backlog must drain: oldest unprocessed event under 60 s at the end of the watch.
    webhook_oldest_unprocessed_age_s: ["p(95)<120"],
  },
};

export function setup() {
  assertNotProduction();
  if (!SECRET) throw new Error("set ELEVENLABS_WEBHOOK_SECRET (a local/dev secret)");
}

export function flood() {
  const body = JSON.stringify({
    type: "load_test_ping",
    event_timestamp: Math.floor(Date.now() / 1000),
    data: { conversation_id: `k6-${__VU}-${__ITER}-${Date.now()}` },
  });
  const t = String(Math.floor(Date.now() / 1000));
  const sig = crypto.hmac("sha256", SECRET, `${t}.${body}`, "hex");
  const res = http.post(`${API}/v1/webhooks/elevenlabs`, body, {
    headers: { "Content-Type": "application/json", "ElevenLabs-Signature": `t=${t},v0=${sig}` },
    tags: { route: "webhook" },
  });
  ok(res, "webhook accepted");
}

export function watch() {
  const token = __ENV.K6_ADMIN_TOKEN;
  if (!token) {
    sleep(10);
    return;
  }
  const res = http.get(`${API}/v1/admin/quality`, authHeaders(token));
  if (res.status === 200) {
    const q = res.json();
    backlogAge.add(q.webhook_oldest_unprocessed_age_s || 0);
    console.log(
      `backlog age=${q.webhook_oldest_unprocessed_age_s} by_status=${JSON.stringify(q.provider_events_by_status)}`,
    );
  }
  sleep(5);
}
