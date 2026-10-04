"""Question selection for `fetch_question`: deterministic prompts built from the concept rubric.

There is no stored question bank yet (C07 ships rubrics, not questions), so a question is derived
from the curriculum rubric of the target concept. The ID is `kind:concept_key:variant`, so the
post-call pipeline (C11) can reconcile transcript turns with the rubric criterion that was asked
without a lookup table, and the browser can tell a Teach-back question from the ID alone.

Everything here is pure; the database lookup that feeds it lives in `sg_api.drona.store`.
"""

import re
from dataclasses import dataclass, field
from typing import Literal

QuestionKind = Literal[
    "concept_check", "cross_question", "teach_back", "coding_problem", "behavioral"
]
Difficulty = Literal["easier", "same", "harder"]

# Kinds Drona serves. Coding problems belong to Arjuna (C16).
SERVED_KINDS: tuple[str, ...] = ("concept_check", "cross_question", "teach_back", "behavioral")

# Cap what reaches the learner's screen and the agent's context.
MAX_PROMPT_CHARS = 400
MAX_HINTS = 4

_LEADING_VERB = re.compile(
    r"^(?P<verb>Explains|States|Describes|Identifies|Gives|Names|Compares|Traces|Recognises|"
    r"Recognizes|Justifies|Distinguishes|Predicts|Chooses|Shows|Tells)\s+(?P<rest>.+)$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class ConceptRubric:
    """What the question builder needs from a concept and its rubric (`cs-core@v1/<key>`)."""

    key: str
    title: str
    summary: str = ""
    criteria: dict[str, list[str]] = field(default_factory=dict)

    def listed(self, name: str) -> list[str]:
        return [c for c in self.criteria.get(name, []) if isinstance(c, str) and c.strip()]


@dataclass(frozen=True)
class Question:
    question_id: str
    kind: str
    concept_id: str
    title: str
    prompt: str
    # For the agent only: what a good answer covers, and (Teach-back) confusions to voice.
    hints: list[str]
    repeat: bool = False


def question_id(kind: str, concept_key: str, variant: int) -> str:
    return f"{kind}:{concept_key}:{variant}"


def parse_question_id(value: str) -> tuple[str, str, int] | None:
    """`(kind, concept_key, variant)` or None for anything not produced by `question_id`."""
    parts = value.split(":")
    if len(parts) != 3 or not parts[2].isdigit():
        return None
    return parts[0], parts[1], int(parts[2])


def _clip(text: str, limit: int) -> str:
    flat = " ".join(text.split())
    return flat if len(flat) <= limit else flat[: limit - 1].rstrip() + "…"


def _as_question(criterion: str) -> str | None:
    """Turn a rubric criterion ("Explains why the input must be sorted") into a spoken ask."""
    match = _LEADING_VERB.match(criterion.strip().rstrip("."))
    if not match:
        return None
    verb = match["verb"].lower()
    verb = verb[:-1] if verb.endswith("s") else verb
    return f"Can you {verb} {match['rest'][0].lower()}{match['rest'][1:]}?"


def _variants(concept: ConceptRubric, kind: str) -> list[tuple[str, list[str]]]:
    """`(prompt, hints)` per variant, easiest first."""
    title = concept.title
    explanation = concept.listed("explanation")
    application = concept.listed("application")
    transfer = concept.listed("transfer")
    misconceptions = concept.listed("misconceptions")

    if kind == "teach_back":
        base = (
            f"Pretend I'm a first-year student who has never seen {title}. Teach it to me in "
            "your own words, and tell me when to use it."
        )
        return [(base, misconceptions[:MAX_HINTS] or explanation[:MAX_HINTS])]
    if kind == "cross_question":
        out: list[tuple[str, list[str]]] = []
        for criterion in transfer + application:
            asked = _as_question(criterion)
            out.append(
                (
                    asked or f"What changes about {title} if the situation is different? Why?",
                    [criterion],
                )
            )
        for wrong in misconceptions:
            out.append(
                (
                    f'A classmate says: "{wrong}" Is that right? Why or why not?',
                    [f"Common misconception: {wrong}"],
                )
            )
        return out or [(f"What could go wrong when using {title}, and why?", [])]
    # concept_check and behavioral
    generic = f"In your own words, what is {title}, and why does it work?"
    if kind == "behavioral":
        generic = (
            f"Tell me about a time that shows {title.lower()}. What did you do and what happened?"
        )
    out = [(generic, explanation[:MAX_HINTS])]
    for criterion in explanation:
        asked = _as_question(criterion)
        if asked:
            out.append((asked, [criterion]))
    return out


def select_question(
    concept: ConceptRubric,
    kind: str,
    *,
    difficulty: str = "same",
    exclude: set[str] | frozenset[str] = frozenset(),
) -> Question:
    """Pick the next unused variant for `kind`; `difficulty` nudges the starting point."""
    variants = _variants(concept, kind)
    start = len(variants) // 2 if difficulty == "harder" and len(variants) > 1 else 0
    order = list(range(start, len(variants))) + list(range(0, start))
    for index in order:
        qid = question_id(kind, concept.key, index)
        if qid not in exclude:
            prompt, hints = variants[index]
            return Question(
                qid,
                kind,
                concept.key,
                concept.title,
                _clip(prompt, MAX_PROMPT_CHARS),
                [_clip(h, 200) for h in hints[:MAX_HINTS]],
            )
    prompt, hints = variants[order[0]]
    return Question(
        question_id(kind, concept.key, order[0]),
        kind,
        concept.key,
        concept.title,
        _clip(prompt, MAX_PROMPT_CHARS),
        [_clip(h, 200) for h in hints[:MAX_HINTS]],
        repeat=True,
    )


def parse_exclusions(raw: str | None) -> set[str]:
    return {part.strip() for part in (raw or "").split(",") if part.strip()}
