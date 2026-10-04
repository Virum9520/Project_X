"""Arjuna's tool and learner routes against the in-memory store and a local sandbox stand-in."""

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest
from arjuna_fixtures import (
    DEV_HEADERS,
    SESSION_ID,
    TOOL_HEADER,
    TWO_SUM_PY,
    USER,
    Rig,
    arjuna_token,
    rig,
)

from sg_api.arjuna.plan import MAX_TEXT_CHARS
from sg_api.arjuna.store import InMemoryArjunaStore, PlanSources, RunRecord
from sg_api.arjuna.tools import MAX_AGENT_RUNS


@pytest.fixture
async def r() -> AsyncIterator[Rig]:
    async for x in rig():
        yield x


def _tool(character: str = "arjuna", conversation_id: str | None = "conv_1") -> dict[str, str]:
    return {TOOL_HEADER: arjuna_token(character, conversation_id)}


async def _save(
    r: Rig, code: str = TWO_SUM_PY, language: str = "python", problem: str = "p_two_sum"
):
    response = await r.client.put(
        f"/v1/arjuna/sessions/{SESSION_ID}/code",
        json={"problem_id": problem, "language": language, "code": code},
        headers=DEV_HEADERS,
    )
    assert response.status_code == 200, response.text
    return response.json()


def _run(problem: str = "p_two_sum", conv: str = "conv_1") -> dict[str, str]:
    return {"conversation_id": conv, "problem_id": problem}


# ── run_tests ──


async def test_run_tests_needs_a_token_and_the_right_conversation(r: Rig) -> None:
    assert (await r.client.post("/v1/agent-tools/run_tests", json=_run())).status_code == 401
    wrong = await r.client.post(
        "/v1/agent-tools/run_tests", json=_run(conv="other"), headers=_tool()
    )
    assert wrong.status_code == 403


async def test_run_tests_is_only_for_arjuna(r: Rig) -> None:
    response = await r.client.post("/v1/agent-tools/run_tests", json=_run(), headers=_tool("drona"))
    assert response.status_code == 403


async def test_run_tests_with_no_code_asks_for_code(r: Rig) -> None:
    response = await r.client.post("/v1/agent-tools/run_tests", json=_run(), headers=_tool())
    assert response.status_code == 200
    assert response.json()["status"] == "no_code"
    assert r.backend is not None and r.backend.created == 0


async def test_run_tests_unknown_problem_is_a_correctable_error(r: Rig) -> None:
    response = await r.client.post(
        "/v1/agent-tools/run_tests", json=_run("p_nope"), headers=_tool()
    )
    assert response.status_code == 404
    assert "fetch_question" in response.json()["detail"]


async def test_a_passing_run_is_independent_evidence_citing_code_and_run(r: Rig) -> None:
    await _save(r)
    response = await r.client.post("/v1/agent-tools/run_tests", json=_run(), headers=_tool())
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "passed" and body["passed"] == body["total"] > 0
    assert body["assisted"] is False and body["first_failure"] is None
    # Never says anything about progress or the garden.
    assert "garden" not in body["summary"].lower()

    assert len(r.store.evidence) == 1
    item = r.store.evidence[0]
    assert item["kind"] == "code_run" and item["assistance"] == "independent"
    assert item["concept"] == "dsa.hash_tables" and item["dimension"] == "application"
    assert item["family"] == "complement_lookup"
    assert item["snapshot_id"] == r.store.snapshots[-1].id
    assert str(item["run_id"]) == body["run_id"]
    assert r.backend is not None and r.backend.created == r.backend.killed == 1


async def test_a_hint_makes_later_test_evidence_assisted(r: Rig) -> None:
    await _save(r)
    hint = await r.client.post(
        "/v1/agent-tools/give_hint",
        json={"conversation_id": "conv_1", "problem_id": "p_two_sum"},
        headers=_tool(),
    )
    assert hint.status_code == 200
    ran = await r.client.post("/v1/agent-tools/run_tests", json=_run(), headers=_tool())
    assert ran.json()["status"] == "passed" and ran.json()["assisted"] is True
    assert r.store.evidence[-1]["assistance"] == "assisted"


async def test_failed_hidden_case_is_reported_by_label_only(r: Rig) -> None:
    await _save(r, "def two_sum(nums, target):\n    return [0, 1]\n")
    body = (await r.client.post("/v1/agent-tools/run_tests", json=_run(), headers=_tool())).json()
    assert body["status"] == "failed" and 0 < body["passed"] < body["total"]
    failure = body["first_failure"]
    # The example [3, 2, 4] / 6 is the first public case this wrong code fails: shareable.
    assert failure["label"] == "example 2" and failure["shareable"] is True
    assert failure["input"] == {"nums": [3, 2, 4], "target": 6}

    await _save(
        r,
        "def two_sum(nums, target):\n"
        "    if len(nums) == 2:\n        return [0, 1]\n"
        "    seen = {}\n"
        "    for i, n in enumerate(nums):\n"
        "        if target - n in seen: return [seen[target - n], i]\n"
        "        seen[n] = i\n"
        "    return [0, 0]\n"
        "def _never(): pass\n"
        "_orig = two_sum\n"
        "def two_sum(nums, target):\n"
        "    if len(nums) > 1000: return [0, 0]\n"
        "    return _orig(nums, target)\n",
    )
    body = (await r.client.post("/v1/agent-tools/run_tests", json=_run(), headers=_tool())).json()
    hidden = body["first_failure"]
    assert hidden["shareable"] is False and hidden["label"].startswith("large input")
    assert hidden["input"] is None and hidden["expected"] is None and hidden["actual"] is None


async def test_unsupported_language_is_explained_not_run(r: Rig) -> None:
    await _save(r, "class Solution {}", language="java")
    body = (await r.client.post("/v1/agent-tools/run_tests", json=_run(), headers=_tool())).json()
    assert body["status"] == "unsupported_language"
    assert r.backend is not None and r.backend.created == 0 and not r.store.evidence


async def test_missing_sandbox_is_reported_without_evidence() -> None:
    async for x in rig(sandbox=None):
        await _save(x)
        body = (
            await x.client.post("/v1/agent-tools/run_tests", json=_run(), headers=_tool())
        ).json()
        assert body["status"] == "unavailable"
        assert "Do not guess" in body["note"]
        assert not x.store.evidence


async def test_a_sandbox_crash_is_reported_without_evidence() -> None:
    class Boom:
        async def run(self, *a: object, **k: object) -> object:
            raise RuntimeError("e2b down")

    async for x in rig(sandbox=Boom()):  # type: ignore[arg-type]
        await _save(x)
        body = (
            await x.client.post("/v1/agent-tools/run_tests", json=_run(), headers=_tool())
        ).json()
        assert body["status"] == "unavailable" and not x.store.evidence


async def test_the_run_limit_stops_runaway_loops(r: Rig) -> None:
    await _save(r)
    ctx = await r.store.resolve(USER, str(SESSION_ID))
    assert ctx is not None
    for _ in range(MAX_AGENT_RUNS):
        r.store.runs.append(
            (
                ctx.session_id,
                RunRecord(
                    id=uuid.uuid4(),
                    problem_id="p_two_sum",
                    kind="tests",
                    status="failed",
                    passed=0,
                    total=1,
                    summary="",
                    first_failure=None,
                    at=datetime.now(UTC),
                ),
            )
        )
    body = (await r.client.post("/v1/agent-tools/run_tests", json=_run(), headers=_tool())).json()
    assert body["status"] == "run_limit"
    assert r.backend is not None and r.backend.created == 0


# ── give_hint ──


async def test_hints_escalate_in_order_and_then_run_out(r: Rig) -> None:
    levels = []
    for _ in range(4):
        response = await r.client.post(
            "/v1/agent-tools/give_hint",
            json={"conversation_id": "conv_1", "problem_id": "p_meeting_rooms_2"},
            headers=_tool(),
        )
        assert response.status_code == 200
        levels.append(response.json())
    assert [h["level"] for h in levels] == [1, 2, 3, 0]
    assert [h["status"] for h in levels] == ["given", "given", "given", "exhausted"]
    assert levels[0]["hint"] != levels[1]["hint"] and levels[3]["hint"] == ""
    assert levels[2]["hints_remaining"] == 0
    assert len(r.store.hints) == 3  # an exhausted request records nothing


async def test_hint_requires_arjuna_and_a_known_problem(r: Rig) -> None:
    body = {"conversation_id": "conv_1", "problem_id": "p_two_sum"}
    assert (
        await r.client.post("/v1/agent-tools/give_hint", json=body, headers=_tool("bhima"))
    ).status_code == 403
    bad = {"conversation_id": "conv_1", "problem_id": "p_zzz"}
    assert (
        await r.client.post("/v1/agent-tools/give_hint", json=bad, headers=_tool())
    ).status_code == 404


async def test_panel_sessions_can_use_the_tools(r: Rig) -> None:
    await _save(r)
    response = await r.client.post("/v1/agent-tools/run_tests", json=_run(), headers=_tool("panel"))
    assert response.status_code == 200 and response.json()["status"] == "passed"


# ── fetch_question for coding problems ──


async def test_fetch_question_serves_a_problem_for_arjuna(r: Rig) -> None:
    response = await r.client.post(
        "/v1/agent-tools/fetch_question",
        json={"conversation_id": "conv_1", "kind": "coding_problem", "concept_id": "dsa.heaps"},
        headers=_tool(),
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["question_id"] == "p_meeting_rooms_2" and body["concept_id"] == "dsa.heaps"
    assert body["kind"] == "coding_problem" and body["hints"] == []
    assert "give_hint" in body["note"]
    again = await r.client.post(
        "/v1/agent-tools/fetch_question",
        json={
            "conversation_id": "conv_1",
            "kind": "coding_problem",
            "concept_id": "dsa.heaps",
            "exclude_question_ids": "p_meeting_rooms_2",
        },
        headers=_tool(),
    )
    assert "repeats" in again.json()["note"]


async def test_fetch_question_coding_problem_is_refused_for_other_characters(r: Rig) -> None:
    response = await r.client.post(
        "/v1/agent-tools/fetch_question",
        json={"conversation_id": "conv_1", "kind": "coding_problem"},
        headers=_tool("drona"),
    )
    assert response.status_code == 422


# ── learner routes ──


async def test_problem_view_never_includes_hidden_tests(r: Rig) -> None:
    response = await r.client.get("/v1/arjuna/problems/p_two_sum", headers=DEV_HEADERS)
    assert response.status_code == 200
    body = response.json()
    assert body["function"] == "two_sum" and "def two_sum(nums, target)" in body["starter_code"]
    assert len(body["examples"]) == 2 and body["tests_available"] is True
    text = response.text
    assert "duplicate values" not in text and "60 thousand" not in text
    js = (
        await r.client.get("/v1/arjuna/problems/p_two_sum?language=javascript", headers=DEV_HEADERS)
    ).json()
    assert js["function"] == "twoSum" and "function twoSum" in js["starter_code"]
    java = (
        await r.client.get("/v1/arjuna/problems/p_two_sum?language=java", headers=DEV_HEADERS)
    ).json()
    assert java["tests_available"] is False
    assert (
        await r.client.get("/v1/arjuna/problems/p_nope", headers=DEV_HEADERS)
    ).status_code == 404
    assert (await r.client.get("/v1/arjuna/problems/p_two_sum")).status_code == 401


async def test_code_snapshots_dedupe_and_are_owner_scoped(r: Rig) -> None:
    first = await _save(r)
    second = await _save(r)
    assert first["duplicate"] is False and second["duplicate"] is True
    assert len(r.store.snapshots) == 1
    other = await r.client.put(
        f"/v1/arjuna/sessions/{SESSION_ID}/code",
        json={"problem_id": "p_two_sum", "language": "python", "code": "x"},
        headers={"X-Dev-User-Id": "someone_else"},
    )
    assert other.status_code == 404
    huge = await r.client.put(
        f"/v1/arjuna/sessions/{SESSION_ID}/code",
        json={"problem_id": "p_two_sum", "language": "python", "code": "x" * 60_000},
        headers=DEV_HEADERS,
    )
    assert huge.status_code == 422
    bad = await r.client.put(
        f"/v1/arjuna/sessions/{SESSION_ID}/code",
        json={"problem_id": "p_nope", "language": "python", "code": "x"},
        headers=DEV_HEADERS,
    )
    assert bad.status_code in (404, 422)


async def test_run_examples_is_practice_and_never_evidence(r: Rig) -> None:
    response = await r.client.post(
        f"/v1/arjuna/sessions/{SESSION_ID}/run-examples",
        json={"problem_id": "p_two_sum", "language": "python", "code": TWO_SUM_PY},
        headers=DEV_HEADERS,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "passed" and body["total"] == 2
    assert all(x["passed"] for x in body["results"])
    assert not r.store.evidence and r.store.snapshots  # code saved, nothing credited
    # Practice runs do not show up as the agent's test runs.
    runs = await r.client.get(f"/v1/arjuna/sessions/{SESSION_ID}/runs", headers=DEV_HEADERS)
    assert runs.json() == []

    wrong = await r.client.post(
        f"/v1/arjuna/sessions/{SESSION_ID}/run-examples",
        json={
            "problem_id": "p_two_sum",
            "language": "python",
            "code": "def two_sum(nums, target):\n    return [0, 1]\n",
        },
        headers=DEV_HEADERS,
    )
    results = {x["label"]: x for x in wrong.json()["results"]}
    assert results["example 1"]["passed"] is True and results["example 2"]["passed"] is False
    assert results["example 2"]["actual"] == "[0, 1]"


async def test_run_examples_reports_an_unavailable_sandbox() -> None:
    async for x in rig(sandbox=None):
        response = await x.client.post(
            f"/v1/arjuna/sessions/{SESSION_ID}/run-examples",
            json={"problem_id": "p_two_sum", "language": "python", "code": TWO_SUM_PY},
            headers=DEV_HEADERS,
        )
        assert response.status_code == 503


async def test_runs_list_shows_the_agents_runs_in_order(r: Rig) -> None:
    await _save(r)
    await r.client.post("/v1/agent-tools/run_tests", json=_run(), headers=_tool())
    runs = (
        await r.client.get(f"/v1/arjuna/sessions/{SESSION_ID}/runs", headers=DEV_HEADERS)
    ).json()
    assert len(runs) == 1
    assert runs[0]["problem_id"] == "p_two_sum" and runs[0]["status"] == "passed"
    after = await r.client.get(
        f"/v1/arjuna/sessions/{SESSION_ID}/runs",
        params={"after": "2999-01-01T00:00:00Z"},
        headers=DEV_HEADERS,
    )
    assert after.json() == []


async def test_scribe_token_comes_from_the_provider_and_hides_the_key(r: Rig) -> None:
    response = await r.client.post("/v1/arjuna/scribe-token", headers=DEV_HEADERS)
    assert response.status_code == 200
    assert response.json()["token"] == "sutkn_1"
    assert "xi-test" not in response.text
    assert (await r.client.post("/v1/arjuna/scribe-token")).status_code == 401


async def test_scribe_token_provider_failure_is_a_clean_502() -> None:
    async for x in rig(scribe_status=500):
        response = await x.client.post("/v1/arjuna/scribe-token", headers=DEV_HEADERS)
        assert response.status_code == 502


# ── plan and session start ──


async def test_plan_is_built_from_the_learners_documents() -> None:
    store = InMemoryArjunaStore(
        sources=PlanSources(
            "- Built a service with a priority queue and BFS over a graph for routing",
            "Looking for strong heap knowledge",
            frozenset({"dsa.heaps", "dsa.bfs", "dsa.hash_tables", "dsa.two_pointers"}),
        )
    )
    async for x in rig(store=store):
        body = (await x.client.get("/v1/arjuna/plan", headers=DEV_HEADERS)).json()
        assert body["grounded"] is True and body["probes"][0] == "dsa.heaps"
        assert body["has_resume"] and body["has_job_description"]
        assert [c["concept_id"] for c in body["job_requirements"]] == ["dsa.heaps"]
        assert any(p["id"] == "p_meeting_rooms_2" for p in body["problems"])
        assert (await x.client.get("/v1/arjuna/plan")).status_code == 401


async def test_starting_an_interview_adds_the_plan_to_the_dynamic_variables() -> None:
    store = InMemoryArjunaStore(
        sources=PlanSources(
            "- Implemented BFS over a graph for a routing service in production",
            None,
            frozenset({"dsa.bfs", "dsa.hash_tables"}),
        )
    )
    async for x in rig(store=store):
        response = await x.client.post(
            "/v1/arjuna/sessions", json={"language": "javascript"}, headers=DEV_HEADERS
        )
        assert response.status_code == 201, response.text
        body = response.json()
        variables = body["dynamic_variables"]
        assert body["character"] == "arjuna" and body["language"] == "javascript"
        assert variables["preferred_language"] == "javascript"
        assert "dsa.bfs" in variables["interview_plan"]
        assert "self-reported" in variables["interview_plan"]
        assert variables["focus_concept"] == "dsa.bfs"  # the plan's first probe
        assert variables["secret__sg_tool_token"]
        assert body["plan"]["probes"][0] == "dsa.bfs"


async def test_oversized_documents_never_blow_up_the_plan_variable() -> None:
    store = InMemoryArjunaStore(
        sources=PlanSources("heap " * MAX_TEXT_CHARS, None, frozenset({"dsa.heaps"}))
    )
    async for x in rig(store=store):
        body = (await x.client.post("/v1/arjuna/sessions", json={}, headers=DEV_HEADERS)).json()
        assert len(body["dynamic_variables"]["interview_plan"]) <= 1800
