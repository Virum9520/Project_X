"""Export the practice content that the static (GitHub Pages) build runs in the browser.

The full app gets questions, problems and interview plans from the API. The static build has no
server, so it ships the same content as JSON, produced here from the API's own pure modules so it
cannot drift from what the app asks:

- Drona's questions, built from each concept's curriculum rubric (`sg_api.drona.questions`)
- Vidura's STAR prompts, probes and competency rotation (`sg_api.vidura.behavioral`)
- Arjuna's problem bank: the public view in `bank.json`, and every case with its expected value
  (computed from the trusted reference solution) in `problems/<id>.json`, fetched only when the
  learner runs the full tests
- the résumé and job-description lexicon behind the interview plan (`sg_api.arjuna.plan`)

Run from the repository root (CI does this before the Pages build):

    uv run --no-project --with pyyaml python apps/web/scripts/export-practice-data.py
"""

import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "services/api/src"))

import yaml  # noqa: E402

from sg_api.arjuna import plan as arjuna_plan  # noqa: E402
from sg_api.arjuna.problems import (  # noqa: E402
    ALL_PROBLEMS,
    MAX_HINT_LEVEL,
    cases_for,
    public_examples,
    starter_code,
)
from sg_api.drona.questions import ConceptRubric, select_question  # noqa: E402
from sg_api.vidura import behavioral  # noqa: E402

CURRICULUM = ROOT / "curriculum/cs-core/v1"
DEFAULT_OUT = ROOT / "apps/web/public/practice"
QUESTION_KINDS = ("concept_check", "cross_question", "teach_back")


def dump(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, separators=(",", ":"), ensure_ascii=False), encoding="utf-8")


def questions_for(concept: ConceptRubric, kind: str) -> list[dict[str, Any]]:
    """Every variant of one question kind, in the order Drona serves them."""
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    while True:
        q = select_question(concept, kind, exclude=seen)
        if q.repeat:
            return out
        seen.add(q.question_id)
        out.append({"id": q.question_id, "prompt": q.prompt, "hints": q.hints})


def load_concepts() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for path in sorted((CURRICULUM / "concepts").glob("*.yaml")):
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
        for c in doc["concepts"]:
            rubric = {k: [s for s in v if isinstance(s, str)] for k, v in c["rubric"].items()}
            concept = ConceptRubric(c["key"], c["title"], c.get("summary", ""), rubric)
            kinds = ("behavioral",) if doc["domain"] == "behavioral" else QUESTION_KINDS
            out.append(
                {
                    "key": c["key"],
                    "title": c["title"],
                    "grove": doc["domain"],
                    "summary": c.get("summary", ""),
                    "difficulty": c["difficulty"],
                    "rubric": rubric,
                    "questions": {kind: questions_for(concept, kind) for kind in kinds},
                }
            )
    return out


def export(out_dir: Path) -> None:
    concepts = load_concepts()
    problems = []
    for p in ALL_PROBLEMS:
        cases = cases_for(p.id)
        problems.append(
            {
                "id": p.id,
                "family": p.family,
                "concept_id": p.concept_key,
                "secondary_concepts": list(p.secondary_concepts),
                "title": p.title,
                "difficulty": p.difficulty,
                "statement": p.statement,
                "function": p.function,
                "js_function": p.js_function,
                "params": list(p.params),
                "examples": public_examples(p),
                "hidden_count": sum(1 for c in cases if not c.shareable),
                "hints": list(p.hints)[:MAX_HINT_LEVEL],
                "time_limit_s": p.time_limit_s,
                "starter": {
                    lang: starter_code(p, lang) for lang in ("python", "javascript", "typescript")
                },
            }
        )
        dump(
            out_dir / "problems" / f"{p.id}.json",
            [
                {"label": c.label, "args": c.args, "expected": c.expected, "public": c.shareable}
                for c in cases
            ],
        )
    dump(
        out_dir / "bank.json",
        {
            "curriculum": "cs-core@v1",
            "concepts": concepts,
            "behavioral": {
                "rotation": list(behavioral.ROTATION),
                "probes": behavioral.PROBES,
                "bank": {k: list(v) for k, v in behavioral.BANK.items()},
            },
            "problems": problems,
            "plan": {
                "lexicon": {k: list(v) for k, v in arjuna_plan.LEXICON.items()},
                "fallback_probes": list(arjuna_plan.FALLBACK_PROBES),
                "max_probes": arjuna_plan.MAX_PROBES,
                "max_projects": arjuna_plan.MAX_PROJECTS,
                "max_problems": arjuna_plan.MAX_PROBLEMS,
            },
        },
    )
    print(f"Exported {len(concepts)} concepts and {len(problems)} problems to {out_dir}")


if __name__ == "__main__":
    export(Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_OUT)
