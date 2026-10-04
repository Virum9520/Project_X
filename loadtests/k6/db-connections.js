// Database connection pressure. Every /readyz does a real `SELECT 1` through the API's SQLAlchemy
// pool (pool_size=5, max_overflow=10 per process, see sg_core/db.py), so hammering it shows how
// the pool and Tiger Cloud's connection limit behave. Run `db-connections.sql` in another
// terminal while this runs and watch the connection count.
//
//   k6 run -e API_URL=http://localhost:8000 loadtests/k6/db-connections.js
//
// Pass criteria: no 5xx, p95 under 1 s, no "QueuePool limit" timeouts in the API log, and the
// peak connection count in db-connections.sql stays below TIGER_MAX_CONNECTIONS minus headroom
// for the worker, admin and migrations (see README for the arithmetic).
import http from "k6/http";

import { API, assertNotProduction, ok } from "./lib.js";

export const options = {
  scenarios: {
    // Constant arrival rate rather than VUs, so slow responses do not hide pressure.
    readyz_burst: {
      executor: "ramping-arrival-rate",
      startRate: 5,
      timeUnit: "1s",
      preAllocatedVUs: 50,
      maxVUs: 300,
      stages: [
        { target: 25, duration: "1m" },
        { target: 100, duration: "2m" },
        { target: 200, duration: "1m" },
        { target: 0, duration: "30s" },
      ],
    },
  },
  thresholds: {
    http_req_failed: ["rate<0.01"],
    http_req_duration: ["p(95)<1000"],
  },
};

export function setup() {
  assertNotProduction();
}

export default function () {
  ok(http.get(`${API}/readyz`), "readyz");
}
