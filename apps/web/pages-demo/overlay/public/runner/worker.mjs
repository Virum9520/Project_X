// Runs a learner's solution for the coding workbench, one test case per message, off the main
// thread: the page enforces each case's time limit and terminates this worker when it is exceeded.
// Mirrors the sandbox harness (services/api/src/sg_api/arjuna/harness.py): the function is called
// with the case's arguments in a fresh namespace and its return value is compared as JSON.

let pyodide = null;
let pyRun = null;

const PY_RUN = `
import io, json, sys

def __sg_run(src, fn, args_json):
    ns = {"__name__": "solution"}
    real_stdout = sys.stdout
    sys.stdout = io.StringIO()  # learner prints must not reach the result
    try:
        exec(compile(src, "solution.py", "exec"), ns)
        f = ns.get(fn)
        if not callable(f):
            return json.dumps({"status": "error", "detail": "function " + fn + " is not defined"})
        value = f(*json.loads(args_json))
        try:
            return json.dumps({"status": "ok", "value": json.loads(json.dumps(value))})
        except (TypeError, ValueError):
            return json.dumps({"status": "error", "detail": "the return value is not JSON-serializable"})
    except BaseException as exc:
        return json.dumps({"status": "error", "detail": type(exc).__name__ + ": " + str(exc)})
    finally:
        sys.stdout = real_stdout
`;

async function python(base) {
  if (!pyodide) {
    const { loadPyodide } = await import(`${base}pyodide.mjs`);
    pyodide = await loadPyodide({ indexURL: base });
    pyodide.runPython(PY_RUN);
    pyRun = pyodide.globals.get("__sg_run");
  }
  return pyRun;
}

const errorText = (e) => `${(e && e.name) || "Error"}: ${(e && e.message) || String(e)}`;

function runJavaScript(code, fn, args) {
  let f;
  try {
    // `require`, `module` and `exports` exist so compiled TypeScript with exports still loads.
    const load = new Function(
      "require",
      "module",
      "exports",
      `${code}\n;return typeof ${fn} === "function" ? ${fn} : undefined;`,
    );
    f = load(
      () => {
        throw new Error("require is not available here");
      },
      { exports: {} },
      {},
    );
  } catch (e) {
    return { status: "error", detail: errorText(e) };
  }
  if (typeof f !== "function") return { status: "error", detail: `function ${fn} is not defined` };
  try {
    const value = f(...args);
    if (value === undefined) return { status: "ok", value: null, undef: true };
    return { status: "ok", value: JSON.parse(JSON.stringify(value)) };
  } catch (e) {
    return { status: "error", detail: errorText(e) };
  }
}

self.onmessage = async (event) => {
  const msg = event.data;
  try {
    if (msg.kind === "warm") {
      if (msg.language === "python") await python(msg.pyodideBase);
      self.postMessage({ id: msg.id, ready: true });
      return;
    }
    if (msg.language === "python") {
      const run = await python(msg.pyodideBase);
      const result = JSON.parse(run(msg.code, msg.fn, JSON.stringify(msg.args)));
      self.postMessage({ id: msg.id, result });
      return;
    }
    self.postMessage({ id: msg.id, result: runJavaScript(msg.code, msg.fn, msg.args) });
  } catch (e) {
    self.postMessage({ id: msg.id, result: { status: "error", detail: errorText(e) } });
  }
};
