# ruff: noqa: E501, UP031
"""The test harness that runs inside the E2B sandbox, and the parsing of what it prints.

Layout inside the sandbox working directory:

    solution.py | solution.js    the learner's code (data: never imported by our code)
    harness.py  | harness.js     ours; reads `payload.json`, deletes it, then runs each case

The harness (parent) holds the expected values; the learner's code runs in a child process per
case with only that case's arguments, so a test cannot be passed by printing the expected text
and a case cannot read the answers from the learner's process. The harness prints one line,
`SG_RESULT <nonce> <json>`, where the nonce comes from the payload. Anything else on stdout
(including the learner's prints) is ignored. Each case runs under a time limit and a memory cap.
The network is off for the whole sandbox (see `SandboxClient`).
"""

import json
import secrets
from dataclasses import dataclass
from typing import Any

from sg_api.arjuna.problems import Problem, TestCase, cases_for
from sg_core.providers.sandbox import SandboxFile

MARKER = "SG_RESULT"
MEMORY_LIMIT_MB = 512
MAX_CODE_BYTES = 50_000
MAX_DETAIL_CHARS = 240

PY_HARNESS = r'''
import json, os, resource, subprocess, sys, tempfile

CHILD = r"""
import json, sys
real_stdout = sys.stdout
try:
    sys.setrecursionlimit(5000)
    payload = json.loads(sys.stdin.read())
    src = open("solution.py", encoding="utf-8").read()
    ns = {"__name__": "solution"}
    sys.stdout = sys.stderr  # learner prints must not reach the result channel
    exec(compile(src, "solution.py", "exec"), ns)
    fn = ns.get(payload["function"])
    if not callable(fn):
        out = {"status": "error", "detail": "function " + payload["function"] + " is not defined"}
    else:
        value = fn(*payload["args"])
        try:
            out = {"status": "ok", "value": json.loads(json.dumps(value))}
        except (TypeError, ValueError):
            out = {"status": "error", "detail": "the return value is not JSON-serializable"}
except BaseException as exc:  # noqa
    out = {"status": "error", "detail": type(exc).__name__ + ": " + str(exc)}
sys.stdout = real_stdout
sys.stdout.write("\n@@SG@@" + json.dumps(out))
"""

def limits():
    cap = %(mem)d * 1024 * 1024
    for which, value in ((resource.RLIMIT_AS, (cap, cap)), (resource.RLIMIT_CORE, (0, 0))):
        try:
            resource.setrlimit(which, value)
        except (ValueError, OSError):
            pass  # not every OS supports every limit; the sandbox is Linux

def main():
    with open("payload.json", encoding="utf-8") as fh:
        payload = json.load(fh)
    os.remove("payload.json")
    results = []
    for case in payload["cases"]:
        entry = {"i": case["i"]}
        try:
            proc = subprocess.run(
                [sys.executable, "-c", CHILD],
                input=json.dumps({"function": payload["function"], "args": case["args"]}),
                capture_output=True, text=True, timeout=payload["time_limit"],
                preexec_fn=limits,
            )
            marker = proc.stdout.rfind("@@SG@@")
            if marker < 0:
                tail = (proc.stderr or "").strip().splitlines()
                detail = tail[-1] if tail else "the program exited without a result"
                if proc.returncode in (-9, -11):
                    detail = "out of memory or crashed"
                entry.update(status="error", detail=detail[:%(detail)d])
            else:
                out = json.loads(proc.stdout[marker + 6:])
                if out["status"] == "ok":
                    ok = out["value"] == case["expected"]
                    entry["status"] = "pass" if ok else "fail"
                    if not ok:
                        entry["actual"] = json.dumps(out["value"])[:%(detail)d]
                else:
                    entry.update(status="error", detail=out["detail"][:%(detail)d])
        except subprocess.TimeoutExpired:
            entry["status"] = "timeout"
        results.append(entry)
    sys.stdout.write("\n%(marker)s " + payload["nonce"] + " " + json.dumps({"cases": results}) + "\n")

main()
''' % {"mem": MEMORY_LIMIT_MB, "detail": MAX_DETAIL_CHARS, "marker": MARKER}

JS_HARNESS = r"""
const fs = require("fs");
const { spawnSync } = require("child_process");

const CHILD = `
const fs = require("fs");
let out;
const realWrite = process.stdout.write.bind(process.stdout);
try {
  const payload = JSON.parse(fs.readFileSync(0, "utf8"));
  console.log = console.error;
  const src = fs.readFileSync("solution.js", "utf8");
  const fn = new Function("require", "module", "exports", src + "\\n;return typeof " + payload.function +
    " === 'function' ? " + payload.function + " : undefined;")(require, { exports: {} }, {});
  if (typeof fn !== "function") {
    out = { status: "error", detail: "function " + payload.function + " is not defined" };
  } else {
    const value = fn(...payload.args);
    if (value === undefined) out = { status: "ok", value: null, undef: true };
    else out = { status: "ok", value: JSON.parse(JSON.stringify(value)) };
  }
} catch (e) {
  out = { status: "error", detail: String(e && e.name || "Error") + ": " + String(e && e.message || e) };
}
realWrite("\\n@@SG@@" + JSON.stringify(out));
`;

function deepEqual(a, b) {
  if (a === b) return true;
  if (typeof a !== typeof b || a === null || b === null) return false;
  if (Array.isArray(a)) {
    return Array.isArray(b) && a.length === b.length && a.every((x, i) => deepEqual(x, b[i]));
  }
  if (typeof a === "object") {
    const ka = Object.keys(a), kb = Object.keys(b);
    return ka.length === kb.length && ka.every((k) => deepEqual(a[k], b[k]));
  }
  return false;
}

const payload = JSON.parse(fs.readFileSync("payload.json", "utf8"));
fs.unlinkSync("payload.json");
const results = [];
for (const c of payload.cases) {
  const entry = { i: c.i };
  const proc = spawnSync(process.execPath, ["--max-old-space-size=%(mem)d", "-e", CHILD], {
    input: JSON.stringify({ function: payload.function, args: c.args }),
    timeout: payload.time_limit * 1000,
    maxBuffer: 20 * 1024 * 1024,
    encoding: "utf8",
  });
  if (proc.error && proc.error.code === "ETIMEDOUT") {
    entry.status = "timeout";
  } else {
    const stdout = proc.stdout || "";
    const at = stdout.lastIndexOf("@@SG@@");
    if (at < 0) {
      const tail = (proc.stderr || "").trim().split("\n");
      entry.status = "error";
      entry.detail = (tail[tail.length - 1] || "the program exited without a result").slice(0, %(detail)d);
    } else {
      const out = JSON.parse(stdout.slice(at + 6));
      if (out.status === "ok") {
        const ok = !out.undef && deepEqual(out.value, c.expected);
        entry.status = ok ? "pass" : "fail";
        if (!ok) entry.actual = (out.undef ? "undefined" : JSON.stringify(out.value)).slice(0, %(detail)d);
      } else {
        entry.status = "error";
        entry.detail = String(out.detail).slice(0, %(detail)d);
      }
    }
  }
  results.push(entry);
}
process.stdout.write("\n%(marker)s " + payload.nonce + " " + JSON.stringify({ cases: results }) + "\n");
""" % {"mem": MEMORY_LIMIT_MB, "detail": MAX_DETAIL_CHARS, "marker": MARKER}

_LANGUAGES: dict[str, dict[str, str]] = {
    "python": {"solution": "solution.py", "harness": "harness.py", "command": "python3 harness.py"},
    "javascript": {
        "solution": "solution.js",
        "harness": "harness.js",
        "command": "node harness.js",
    },
}


@dataclass(frozen=True)
class HarnessRun:
    files: list[SandboxFile]
    command: str
    nonce: str
    cases: tuple[TestCase, ...]


def build_run(
    problem: Problem, language: str, code: str, *, visible_only: bool = False
) -> HarnessRun:
    """Files and command for one run. Raises `ValueError` for an unsupported language or code
    that is too large."""
    spec = _LANGUAGES.get(language)
    if spec is None:
        raise ValueError(f"tests are not available for {language}")
    if len(code.encode("utf-8")) > MAX_CODE_BYTES:
        raise ValueError("code is too large to run")
    cases = tuple(c for c in cases_for(problem.id) if c.shareable or not visible_only)
    nonce = secrets.token_hex(12)
    payload: dict[str, Any] = {
        "nonce": nonce,
        "function": problem.function if language == "python" else problem.js_function,
        "time_limit": problem.time_limit_s,
        "cases": [{"i": c.index, "args": c.args, "expected": c.expected} for c in cases],
    }
    harness = PY_HARNESS if language == "python" else JS_HARNESS
    return HarnessRun(
        files=[
            SandboxFile(spec["solution"], code),
            SandboxFile(spec["harness"], harness),
            SandboxFile("payload.json", json.dumps(payload)),
        ],
        command=spec["command"],
        nonce=nonce,
        cases=cases,
    )


def total_timeout_s(problem: Problem, case_count: int) -> float:
    """Wall-clock for the whole sandbox command: per-case limits plus start-up per process."""
    return min(60.0, case_count * (problem.time_limit_s + 0.5) + 5.0)


@dataclass(frozen=True)
class CaseResult:
    index: int
    status: str  # pass | fail | error | timeout
    detail: str = ""
    actual: str = ""


def parse_output(stdout: str, nonce: str) -> list[CaseResult] | None:
    """Per-case results, or None when the harness never printed a result for this nonce."""
    prefix = f"{MARKER} {nonce} "
    for line in reversed(stdout.splitlines()):
        if not line.startswith(prefix):
            continue
        try:
            data = json.loads(line[len(prefix) :])
            return [
                CaseResult(
                    index=int(c["i"]),
                    status=str(c["status"]),
                    detail=str(c.get("detail", ""))[:MAX_DETAIL_CHARS],
                    actual=str(c.get("actual", ""))[:MAX_DETAIL_CHARS],
                )
                for c in data["cases"]
            ]
        except (ValueError, KeyError, TypeError):
            return None
    return None
