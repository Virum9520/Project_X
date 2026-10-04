"""Weekly Sanjaya recap: script, keyframe timing, storage, sharing and routes (no database)."""

import base64
import itertools
import json
import uuid
from datetime import timedelta
from decimal import Decimal

import pytest
from garden_fixtures import (
    EV_GRAPH_ASSISTED,
    EV_STAR,
    NOW,
    make_data,
    uid,
)
from httpx import ASGITransport, AsyncClient

from sg_api.garden.data import GardenData, RevisionRec
from sg_api.main import create_app
from sg_api.recap.router import get_recap_service
from sg_api.recap.script import build_script, iso_week, week_window
from sg_api.recap.service import (
    InvalidShareToken,
    RecapNotFound,
    RecapService,
    estimate_speech_usd,
)
from sg_api.recap.timing import keyframes
from sg_core.economics.budget import BudgetExceededError
from sg_core.providers.elevenlabs import CharacterAlignment, TimedAudioResult
from sg_core.providers.storage import InMemoryObjectStore
from sg_core.settings import Environment, Settings, get_settings

USER = uid(900)
DEV = {"X-Dev-User-Id": "learner_1"}
DAY = timedelta(days=1)


def busy_week() -> GardenData:
    """The fixture garden plus two changes this week: STAR grew (independent), Graphs (assisted)."""
    data = make_data()
    data.revisions += [
        RevisionRec(
            4, "rules@1+normal.1", "assessment", NOW - 3 * DAY, [uid(403)],
            [
                {
                    "concept": "behavioral.star",
                    "status": {"before": "unassessed", "after": "independent"},
                    "events": [{"evidence_ids": [str(EV_STAR)], "dimension": "explanation"}],
                }
            ],
        ),
        RevisionRec(
            5, "rules@1+normal.1", "assessment", NOW - 1 * DAY, [uid(402)],
            [
                {
                    "concept": "dsa.graphs",
                    "status": {"before": "unassessed", "after": "sprouting"},
                    "events": [
                        {"evidence_ids": [str(EV_GRAPH_ASSISTED)], "dimension": "explanation"}
                    ],
                }
            ],
        ),
    ]  # fmt: skip
    return data


def test_week_window_and_iso_week() -> None:
    start, end = week_window(NOW)
    assert (end - start).days == 6 and end == NOW.date()
    assert iso_week(end) == "2026-W40"


def test_script_covers_growth_practice_and_next_steps_with_real_citations() -> None:
    data = busy_week()
    script = build_script(data, NOW)
    ids = [s.id for s in script.segments]
    assert ids[0] == "intro" and ids[-1] == "outro"
    assert "growth-behavioral.star" in ids and "growth-dsa.graphs" in ids
    assert "practice" in ids and "next" in ids
    assert not script.quiet
    star = next(s for s in script.segments if s.id == "growth-behavioral.star")
    assert star.focus == "plant:behavioral.star" and star.evidence_ids == [str(EV_STAR)]
    graphs = next(s for s in script.segments if s.id == "growth-dsa.graphs")
    assert "not as mastery" in graphs.text  # assisted evidence is never described as mastery
    real = {str(e.id) for e in data.evidence}
    assert set(script.citations) <= real and script.citations
    assert all(s.kind != "growth" or s.evidence_ids for s in script.segments)


def test_offsets_index_the_narration() -> None:
    script = build_script(busy_week(), NOW)
    for s in script.segments:
        assert script.narration[s.start_char : s.end_char] == s.text


def test_quiet_week_says_so_and_cites_nothing_it_did_not_see() -> None:
    script = build_script(make_data(), NOW)
    assert script.quiet
    assert "Nothing new grew" in script.segments[0].text
    assert not any(s.kind == "growth" for s in script.segments)


def test_stored_text_is_flattened() -> None:
    data = busy_week()
    data.view.plants[1].title = "Graphs"
    script = build_script(data, NOW)
    assert all("\n" not in s.text for s in script.segments)


def test_keyframes_follow_character_timing() -> None:
    script = build_script(busy_week(), NOW)
    n = len(script.narration)
    # 50 ms per character.
    alignment = CharacterAlignment(
        characters=list(script.narration),
        start_times=[i * 0.05 for i in range(n)],
        end_times=[(i + 1) * 0.05 for i in range(n)],
    )
    frames, duration, source = keyframes(script, alignment)
    assert source == "aligned"
    star_seg = next(s for s in script.segments if s.id == "growth-behavioral.star")
    star = next(f for f in frames if f.segment_id == star_seg.id)
    assert star.start_ms == round(star_seg.start_char * 50)
    assert star.focus == "plant:behavioral.star"
    assert all(a.end_ms <= b.start_ms for a, b in itertools.pairwise(frames))
    assert duration >= n * 50 - 50


def test_keyframes_fall_back_when_alignment_does_not_match_or_is_missing() -> None:
    script = build_script(busy_week(), NOW)
    short = CharacterAlignment(characters=["a"], start_times=[0.0], end_times=[9.0])
    frames, duration, source = keyframes(script, short)
    assert source == "proportional" and duration >= 9000 - 10
    assert frames == sorted(frames, key=lambda f: f.start_ms)
    _, _, source = keyframes(script, None, duration_seconds=30)
    assert source == "proportional"
    frames, duration, source = keyframes(script)
    assert source == "estimated" and duration > 0 and frames[0].start_ms == 0


# ── service ──
class FakeSpeech:
    def __init__(self, *, fail: bool = False, align: bool = True) -> None:
        self.calls = 0
        self.fail = fail
        self.align = align
        self.usage = None

    async def text_to_speech_with_timestamps(self, voice_id, text, *, usage=None):  # type: ignore[no-untyped-def]
        self.calls += 1
        self.usage = usage
        if self.fail:
            raise RuntimeError("down")
        n = len(text)
        alignment = CharacterAlignment(
            characters=list(text),
            start_times=[i * 0.06 for i in range(n)],
            end_times=[(i + 1) * 0.06 for i in range(n)],
        )
        return TimedAudioResult(audio=b"mp3", alignment=alignment if self.align else None)


class Holds:
    def __init__(self, exceeded: bool = False) -> None:
        self.exceeded = exceeded
        self.amounts: list[Decimal] = []

    def __call__(self, user_id: uuid.UUID, amount: Decimal):  # type: ignore[no-untyped-def]
        holds = self

        class Ctx:
            async def __aenter__(self) -> None:
                if holds.exceeded:
                    raise BudgetExceededError("user:x", Decimal(1), Decimal(1), amount)
                holds.amounts.append(amount)

            async def __aexit__(self, *exc: object) -> None:
                return None

        return Ctx()


def make_service(
    *,
    speech: FakeSpeech | None = None,
    voice: str | None = "voice_1",
    holds: Holds | None = None,
    data: GardenData | None = None,
    secret: bytes | None = b"s" * 32,
    store: InMemoryObjectStore | None = None,
) -> RecapService:
    garden = data or busy_week()

    async def resolve(learner: str) -> uuid.UUID | None:
        return USER if learner == "learner_1" else None

    async def load(user_id: uuid.UUID, now):  # type: ignore[no-untyped-def]
        assert user_id == USER
        return garden

    return RecapService(
        resolve_user=resolve,
        load_data=load,
        store=store or InMemoryObjectStore(),
        speech=speech,
        voice_id=voice,
        secret=secret,
        hold=holds or Holds(),  # type: ignore[arg-type]
    )


async def test_generate_with_voice_is_aligned_budgeted_and_idempotent() -> None:
    speech, holds = FakeSpeech(), Holds()
    svc = make_service(speech=speech, holds=holds)
    recap = await svc.generate("learner_1", now=NOW)
    assert recap.timing == "aligned" and recap.audio_url and recap.week == "2026-W40"
    assert holds.amounts == [estimate_speech_usd(recap.narration)] and holds.amounts[0] > 0
    assert speech.usage is not None and speech.usage.cost_center.value == "learner"
    assert speech.usage.user_id == USER
    assert [s.start_ms for s in recap.segments] == sorted(s.start_ms for s in recap.segments)
    again = await svc.generate("learner_1", now=NOW)
    assert speech.calls == 1 and again.narration == recap.narration  # stored, not re-spoken
    await svc.generate("learner_1", now=NOW, force=True)
    assert speech.calls == 2
    assert (await svc.get("learner_1")).week == "2026-W40"
    assert (await svc.get("learner_1", "2026-W40")).audio_url


@pytest.mark.parametrize(
    "case",
    ["no_voice", "no_client", "provider_error", "budget"],
)
async def test_text_only_recap_when_audio_is_unavailable(case: str) -> None:
    if case == "no_voice":
        svc = make_service(speech=FakeSpeech(), voice=None)
    elif case == "no_client":
        svc = make_service(speech=None)
    elif case == "provider_error":
        svc = make_service(speech=FakeSpeech(fail=True))
    else:
        svc = make_service(speech=FakeSpeech(), holds=Holds(exceeded=True))
    recap = await svc.generate("learner_1", now=NOW)
    assert recap.audio_url is None and recap.timing == "estimated" and recap.segments


async def test_unknown_learner_and_bad_week() -> None:
    svc = make_service()
    with pytest.raises(RecapNotFound):
        await svc.generate("stranger", now=NOW)
    with pytest.raises(RecapNotFound):
        await svc.get("learner_1")  # nothing generated yet
    await svc.generate("learner_1", now=NOW)
    with pytest.raises(RecapNotFound):
        await svc.get("learner_1", "../other/2026-W40")


async def test_recaps_are_scoped_to_the_learner_prefix() -> None:
    store = InMemoryObjectStore()
    svc = make_service(store=store, speech=FakeSpeech())
    await svc.generate("learner_1", now=NOW)
    keys = await store.list_keys()
    assert keys and all(k.startswith(f"recaps/{USER}/2026-W40/") for k in keys)


async def test_share_link_opens_expires_and_revokes() -> None:
    svc = make_service(speech=FakeSpeech())
    await svc.generate("learner_1", now=NOW)
    token, expires = await svc.share("learner_1", "2026-W40", now=NOW)
    assert (await svc.get("learner_1")).shared
    opened = await svc.open_shared(token, now=NOW + DAY)
    assert opened.week == "2026-W40"
    with pytest.raises(InvalidShareToken):
        await svc.open_shared(token, now=expires + DAY)
    with pytest.raises(InvalidShareToken):
        await svc.open_shared(token[:-3] + "abc", now=NOW)
    with pytest.raises(InvalidShareToken):
        await svc.open_shared("garbage", now=NOW)
    raw = token.split(".")[0]
    forged = base64.urlsafe_b64encode(
        base64.urlsafe_b64decode(raw + "==").replace(b"2026-W40", b"2026-W39")
    ).decode()
    with pytest.raises(InvalidShareToken):
        await svc.open_shared(f"{forged}.{token.split('.')[1]}", now=NOW)
    token2, _ = await svc.share("learner_1", "2026-W40", now=NOW)
    assert (await svc.open_shared(token2, now=NOW)).week == "2026-W40"
    await svc.unshare("learner_1", "2026-W40")
    for t in (token, token2):
        with pytest.raises(InvalidShareToken):
            await svc.open_shared(t, now=NOW)
    assert not (await svc.get("learner_1")).shared


async def test_sharing_needs_a_secret() -> None:
    svc = make_service(secret=None)
    await svc.generate("learner_1", now=NOW)
    with pytest.raises(InvalidShareToken):
        await svc.share("learner_1", "2026-W40", now=NOW)


# ── routes ──
SETTINGS = Settings(_env_file=None, environment=Environment.TEST)  # type: ignore[call-arg]


@pytest.fixture
async def client():  # type: ignore[no-untyped-def]
    svc = make_service(speech=FakeSpeech())
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: SETTINGS
    app.dependency_overrides[get_recap_service] = lambda: svc
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        yield c


async def test_routes_generate_read_share_and_open(client: AsyncClient) -> None:
    assert (await client.get("/v1/recap/latest")).status_code == 401
    assert (await client.get("/v1/recap/latest", headers=DEV)).status_code == 404
    made = await client.post("/v1/recap/generate", headers=DEV, json={})
    assert made.status_code == 200
    body = made.json()
    assert body["week"] == "2026-W40" and body["audioUrl"].startswith("memory://")
    assert body["segments"][0]["startMs"] == 0 and "evidenceIds" in body["segments"][1]
    assert (await client.get("/v1/recap/latest", headers=DEV)).json()["week"] == "2026-W40"
    assert (await client.get("/v1/recap/2026-W39", headers=DEV)).status_code == 404
    shared = await client.post("/v1/recap/2026-W40/share", headers=DEV)
    token = shared.json()["token"]
    opened = await client.get(f"/v1/recap/shared/{token}")  # no auth: the link is the credential
    assert opened.status_code == 200 and opened.headers["cache-control"] == "private, no-store"
    assert (await client.delete("/v1/recap/2026-W40/share", headers=DEV)).status_code == 204
    assert (await client.get(f"/v1/recap/shared/{token}")).status_code == 404
    assert json.dumps(opened.json())  # serialisable
