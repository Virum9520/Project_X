import json

from drona_fixtures import make_client

from sg_api.drona.growth import GrowthEvent, MemoryGrowthFeed, format_sse, sse_stream


def _event(kind: str = "provisional") -> GrowthEvent:
    return GrowthEvent(
        kind=kind,  # type: ignore[arg-type]
        session_id="s1",
        concept_id="dsa.bfs",
        dimension="application",
        part="stem",
        outcome="demonstrated",
    )


async def test_stream_emits_events_after_the_cursor_and_heartbeats() -> None:
    feed = MemoryGrowthFeed()
    cursor = await feed.latest_cursor("u1")
    await feed.append("u1", _event())
    await feed.append("other", _event())
    chunks = [
        c
        async for c in sse_stream(
            feed, "u1", cursor, poll_seconds=0, heartbeat_seconds=0, max_polls=2
        )
    ]
    assert chunks[0].startswith("retry:")
    growth = [c for c in chunks if c.startswith("id:")]
    assert len(growth) == 1  # the other learner's event never leaks
    payload = json.loads(growth[0].split("data: ", 1)[1])
    assert payload["conceptId"] == "dsa.bfs"
    assert payload["part"] == "stem"
    assert any(c.startswith(": keep-alive") for c in chunks)


async def test_resume_from_last_event_id_replays_missed_events() -> None:
    feed = MemoryGrowthFeed()
    start = await feed.latest_cursor("u1")
    await feed.append("u1", _event())
    ((first_cursor, _),) = await feed.after("u1", start)
    await feed.append("u1", _event("confirmed"))
    replay = await feed.after("u1", first_cursor)
    assert [e.kind for _, e in replay] == ["confirmed"]


async def test_stream_stops_when_the_client_disconnects() -> None:
    feed = MemoryGrowthFeed()

    async def gone() -> bool:
        return True

    chunks = [c async for c in sse_stream(feed, "u1", "0", is_disconnected=gone, poll_seconds=0)]
    assert len(chunks) == 1


def test_wire_format_is_camel_case_sse() -> None:
    text = format_sse("123", _event())
    assert text.startswith("id: 123\nevent: growth\ndata: {")
    assert text.endswith("\n\n")
    assert '"conceptId"' in text and '"sessionId"' in text


async def test_route_requires_identity() -> None:
    async for client in make_client():
        assert (await client.get("/v1/live/growth")).status_code == 401


async def test_end_and_bind_routes() -> None:
    async for client in make_client():
        h = {"X-Dev-User-Id": "u1"}
        assert (await client.post("/v1/sessions/abc/end", json={}, headers=h)).status_code == 204
        assert (
            await client.post("/v1/sessions/missing/end", json={}, headers=h)
        ).status_code == 404
        r = await client.put(
            "/v1/sessions/abc/conversation", json={"conversation_id": "c"}, headers=h
        )
        assert r.status_code == 204
        bad = await client.post("/v1/sessions/abc/end", json={"status": "bogus"}, headers=h)
        assert bad.status_code == 422
