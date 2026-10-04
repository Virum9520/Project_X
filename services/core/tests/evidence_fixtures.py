"""Shared helpers for the evidence pipeline tests: a scripted LLM, catalog and transcripts."""

import json
import uuid
from datetime import UTC, datetime
from functools import lru_cache
from typing import Any

from sg_core.curriculum import curriculum_path, load_curriculum
from sg_core.economics.usage import UsageContext
from sg_core.evidence import ConceptInfo, InMemoryEvidenceStore, RubricInfo
from sg_core.models.enums import Character
from sg_core.providers.llm import ChatMessage, LLMResponse

T0 = datetime(2026, 10, 4, 12, 0, tzinfo=UTC)
START = int(T0.timestamp())
BS = "dsa.binary_search"
HEAP = "dsa.heaps"
CONV = "conv_abc123"


@lru_cache(maxsize=1)
def _catalog() -> dict[str, ConceptInfo]:
    spec = load_curriculum(curriculum_path("cs-core", "v1"))
    out: dict[str, ConceptInfo] = {}
    for c in spec.concepts:
        out[c.key] = ConceptInfo(
            id=uuid.uuid5(uuid.NAMESPACE_DNS, c.key),
            key=c.key,
            title=c.title,
            domain=c.key.split(".")[0],
            summary=c.summary,
            rubric=RubricInfo(
                id=uuid.uuid5(uuid.NAMESPACE_URL, c.key),
                version=spec.rubric_version,
                criteria=c.rubric.model_dump(mode="json"),
            ),
        )
    return out


def catalog() -> dict[str, ConceptInfo]:
    return dict(_catalog())


class ScriptedLLM:
    """Returns queued JSON bodies (or raises), and records every request."""

    def __init__(self, *bodies: Any) -> None:
        self.bodies = list(bodies)
        self.calls: list[dict[str, Any]] = []

    async def complete(
        self,
        messages: list[ChatMessage],
        *,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | dict[str, Any] | None = None,
        response_format: dict[str, Any] | None = None,
        usage: UsageContext | None = None,
    ) -> LLMResponse:
        self.calls.append({"messages": messages, "model": model, "usage": usage})
        body = self.bodies.pop(0) if len(self.bodies) > 1 else self.bodies[0]
        if isinstance(body, Exception):
            raise body
        return LLMResponse(
            model=model or "fake", content=body if isinstance(body, str) else json.dumps(body)
        )


def verdict(
    concept: str = BS,
    dimension: str = "explanation",
    outcome: str = "demonstrated",
    assistance: str = "independent",
    turn: int = 1,
    quote: str = "it halves the search range each step",
    uncertainty: float = 0.2,
    family: str | None = None,
    **extra: Any,
) -> dict[str, Any]:
    return {
        "concept": concept,
        "dimension": dimension,
        "outcome": outcome,
        "assistance": assistance,
        "uncertainty": uncertainty,
        "problem_family": family,
        "citations": [{"turn": turn, "quote": quote}],
        "rationale": "Explained the halving invariant correctly.",
        **extra,
    }


def judge_body(*verdicts: dict[str, Any]) -> dict[str, Any]:
    return {"version": "judge@1", "assessments": list(verdicts)}


def turn(role: str, text: str, t: int, **extra: Any) -> dict[str, Any]:
    return {"role": role, "message": text, "time_in_call_secs": t, **extra}


def observation_call(
    concept: str = BS,
    dimension: str = "explanation",
    assistance: str = "independent",
    outcome: str = "correct",
) -> dict[str, Any]:
    params = {
        "concept_id": concept,
        "dimension": dimension,
        "outcome": outcome,
        "assistance": assistance,
        "evidence_quote": "it halves the range",
    }
    return {
        "role": "agent",
        "message": "",
        "time_in_call_secs": 20,
        "tool_calls": [
            {
                "tool_name": "record_observation",
                "request_id": "r1",
                "params_as_json": json.dumps(params),
            }
        ],
    }


def transcript_turns() -> list[dict[str, Any]]:
    return [
        turn("agent", "Explain how binary search works.", 0),
        turn(
            "user", "Sure, it halves the search range each step, comparing the middle element.", 10
        ),
        turn("agent", "Good. What is the complexity?", 15),
        observation_call(),
        turn("user", "O of log n because the range halves every comparison.", 30),
    ]


def payload(
    turns: list[dict[str, Any]] | None = None,
    *,
    conversation_id: str = CONV,
    status: str = "done",
    focus: str | None = BS,
    duration: int = 120,
) -> dict[str, Any]:
    data: dict[str, Any] = {
        "agent_id": "agent_1",
        "conversation_id": conversation_id,
        "status": status,
        "transcript": turns if turns is not None else transcript_turns(),
        "metadata": {"start_time_unix_secs": START, "call_duration_secs": duration},
        "conversation_initiation_client_data": {
            "dynamic_variables": {"focus_concept": focus, "secret__sg_tool_token": "tok"}
            if focus
            else {"secret__sg_tool_token": "tok"}
        },
    }
    return data


class World:
    def __init__(self, character: Character = Character.DRONA, mode: str = "concept_exam") -> None:
        self.user_id = uuid.uuid4()
        self.store = InMemoryEvidenceStore(
            catalog(),
            users={"clerk_1": self.user_id},
            dimension_rubrics={
                "explanation": {"levels": {"demonstrated": "x"}, "guardrails": ["g"]}
            },
        )
        self.character = character
        self.mode = mode
        self.session_id: uuid.UUID | None = None

    async def start_session(self, conversation_id: str = CONV) -> uuid.UUID:
        ref = await self.store.ensure_session(
            user_id=self.user_id,
            character=self.character,
            mode=self.mode,
            conversation_id=conversation_id,
            public_session_id="ses_1",
            now=T0,
        )
        self.session_id = ref.id
        return ref.id
