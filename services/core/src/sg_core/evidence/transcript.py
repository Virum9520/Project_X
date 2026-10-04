"""Normalise an ElevenLabs conversation into a `Transcript`, and read the agent's tool calls.

Accepts both the `post_call_transcription` webhook body and `GET /v1/convai/conversations/{id}`
(they share the `transcript` / `metadata` shapes). Parsing is defensive: ElevenLabs may add or
drop fields, and none of the text is trusted. Text is length-capped and stripped of control
characters; it is wrapped as data wherever it reaches a model (see `judge.py`).
"""

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

from sg_core.evidence.types import AgentObservation, ToolEvent, Transcript, Turn

MAX_TURNS = 400
MAX_TURN_CHARS = 4000
RECORD_OBSERVATION = "record_observation"

_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
# Phrases that address the model rather than the interviewer. A learner's answer legitimately
# rarely contains these; if a cited quote does, the verdict is made ambiguous (see validation).
INJECTION_PATTERN = re.compile(
    r"(ignore|disregard|forget)\b[^.\n]{0,40}\b(previous|prior|above|earlier|all)\b[^.\n]{0,40}"
    r"\b(instruction|prompt|rule|message)s?"
    r"|\b(system|developer)\s*(prompt|message|instruction)"
    r"|\bmark\b[^.\n]{0,30}\b(demonstrated|correct|mastered|full)\b"
    r"|\b(you are|act as)\s+(now\s+)?(a|an|the)\s+(judge|grader|assistant|evaluator)"
    r"|\bgive (me|this) (full|top|maximum|a perfect)\b"
    r"|</?\s*(transcript|rubric|assessments?)\s*>",
    re.IGNORECASE,
)


def clean_text(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    text = _CONTROL.sub("", value).strip()
    return text[:MAX_TURN_CHARS]


def looks_like_injection(text: str) -> bool:
    return INJECTION_PATTERN.search(text) is not None


def normalize(value: str) -> str:
    """Case- and whitespace-insensitive form used to check that a quote is really in a turn."""
    return " ".join(value.lower().split())


def _role(value: Any) -> str | None:
    if value in ("user", "learner"):
        return "learner"
    if value in ("agent", "assistant"):
        return "agent"
    return None


def _tool_events(item: Mapping[str, Any]) -> tuple[ToolEvent, ...]:
    results: dict[str, str | None] = {}
    for r in item.get("tool_results") or []:
        if isinstance(r, Mapping):
            key = str(r.get("request_id") or r.get("tool_call_id") or r.get("tool_name") or "")
            results[key] = clean_text(r.get("result_value")) or None
    events: list[ToolEvent] = []
    for call in item.get("tool_calls") or []:
        if not isinstance(call, Mapping):
            continue
        params = call.get("params_as_json", call.get("params"))
        if isinstance(params, str):
            try:
                params = json.loads(params)
            except ValueError:
                params = {}
        name = str(call.get("tool_name") or call.get("name") or "")
        key = str(call.get("request_id") or call.get("tool_call_id") or name)
        events.append(
            ToolEvent(
                name=name,
                params=dict(params) if isinstance(params, Mapping) else {},
                result=results.get(key) or results.get(name),
            )
        )
    return tuple(events)


def _dynamic_variables(data: Mapping[str, Any]) -> dict[str, str]:
    init = data.get("conversation_initiation_client_data") or {}
    raw = init.get("dynamic_variables") if isinstance(init, Mapping) else None
    if not isinstance(raw, Mapping):
        return {}
    # Tokens and anything secret are never kept.
    return {
        str(k): str(v)[:300]
        for k, v in raw.items()
        if not str(k).startswith("secret__") and isinstance(v, str | int | float)
    }


def parse_conversation(
    data: Mapping[str, Any], *, conversation_id: str | None = None
) -> Transcript:
    """Build a `Transcript` from a webhook `data` object or a conversation-details body."""
    raw: Sequence[Any] = data.get("transcript") or []
    turns: list[Turn] = []
    for i, item in enumerate(raw[:MAX_TURNS]):
        if not isinstance(item, Mapping):
            continue
        role = _role(item.get("role"))
        tools = _tool_events(item)
        text = clean_text(item.get("message"))
        if role is None or (not text and not tools):
            continue
        time_raw = item.get("time_in_call_secs")
        time_s = float(time_raw) if isinstance(time_raw, int | float) else None
        turns.append(Turn(index=i, role=role, text=text, time_s=time_s, tools=tools))  # type: ignore[arg-type]
    meta = data.get("metadata") or {}
    started = meta.get("start_time_unix_secs") if isinstance(meta, Mapping) else None
    duration = meta.get("call_duration_secs") if isinstance(meta, Mapping) else None
    return Transcript(
        conversation_id=str(data.get("conversation_id") or conversation_id or ""),
        turns=tuple(turns),
        started_at=datetime.fromtimestamp(started, UTC)
        if isinstance(started, int | float)
        else None,
        duration_s=float(duration) if isinstance(duration, int | float) else None,
        status=str(data["status"]) if data.get("status") else None,
        dynamic_variables=_dynamic_variables(data),
    )


def observations_in(transcript: Transcript) -> list[AgentObservation]:
    """The agent's own `record_observation` calls. Claims about the learner, not evidence."""
    found: list[AgentObservation] = []
    for turn in transcript.turns:
        for tool in turn.tools:
            if tool.name != RECORD_OBSERVATION:
                continue
            p = tool.params
            concept = p.get("concept_id")
            dimension = p.get("dimension")
            if not isinstance(concept, str) or not isinstance(dimension, str):
                continue
            found.append(
                AgentObservation(
                    concept_key=concept,
                    dimension=dimension,
                    assistance=str(p.get("assistance") or "independent"),
                    outcome=str(p.get("outcome") or ""),
                    question_id=str(p["question_id"]) if p.get("question_id") else None,
                    evidence_quote=clean_text(p.get("evidence_quote")) or None,
                )
            )
    return found


def occurred_at(transcript: Transcript, turn: int, fallback: datetime) -> datetime:
    """Wall-clock time of a turn: call start plus its offset; the fallback when unknown."""
    t = transcript.turn(turn)
    if transcript.started_at is None or t is None or t.time_s is None:
        return fallback
    return transcript.started_at + timedelta(seconds=t.time_s)


def transcript_hash(transcript: Transcript) -> str:
    payload = json.dumps([(t.index, t.role, t.text) for t in transcript.turns], ensure_ascii=False)
    return hashlib.sha256(payload.encode()).hexdigest()[:16]
