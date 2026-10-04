"""PII redaction and the env-driven, no-op-by-default observability setup (C23)."""

import json
from typing import Any

import pytest
from pydantic import SecretStr

from sg_core import observability
from sg_core.logging import configure_logging
from sg_core.redaction import REDACTED, redact_text, redact_value
from sg_core.settings import Environment, Settings


def settings(**kw: Any) -> Settings:
    return Settings(_env_file=None, environment=Environment.TEST, **kw)  # type: ignore[call-arg]


@pytest.mark.parametrize(
    ("raw", "gone"),
    [
        ("contact jane.doe@umich.edu please", "jane.doe@umich.edu"),
        ("call +15555550123 now", "+15555550123"),
        ("call (555) 555-0123 now", "555-0123"),
        ("Authorization: Bearer abcdef0123456789", "abcdef0123456789"),
        ("jwt eyJhbGciOiJSUzI1NiJ9.eyJzdWIiOiJ1In0.c2lnbmF0dXJl x", "eyJhbGci"),
        ("key sk-live-abcdefghijklmnop12", "abcdefghijklmnop12"),
        ("whsec_abcdefghijklmnopqrst", "abcdefghijklmnopqrst"),
        ("postgres://user:hunter2secret@host:5432/db", "hunter2secret"),
    ],
)
def test_free_text_is_scrubbed(raw: str, gone: str) -> None:
    assert gone not in redact_text(raw)


def test_innocent_text_is_left_alone() -> None:
    text = "2026-10-04 12:30:00 session 3f2a9c1e-1111-4444-8888-123456789abc took 12.5s"
    assert redact_text(text) == text


def test_sensitive_keys_are_masked_at_any_depth_but_counters_survive() -> None:
    out = redact_value(
        {
            "user_id": "u1",
            "authorization": "Bearer x",
            "nested": [{"password": "p", "transcript": "learner said things", "n": 1}],
            "input_tokens": 120,
            "answer": "my secret answer",
        }
    )
    assert out["authorization"] == REDACTED
    assert out["nested"][0] == {"password": REDACTED, "transcript": REDACTED, "n": 1}
    assert out["input_tokens"] == 120 and out["answer"] == REDACTED and out["user_id"] == "u1"


def test_logging_pipeline_redacts_before_rendering(monkeypatch: pytest.MonkeyPatch) -> None:
    import io

    import structlog

    from sg_core.redaction import redact_event_dict

    seen: dict[str, Any] = {}
    monkeypatch.setattr(structlog, "configure", lambda **kw: seen.update(kw))
    configure_logging("INFO", json=True)
    processors = seen["processors"]
    assert redact_event_dict in processors
    assert processors.index(redact_event_dict) < len(processors) - 1  # runs before the renderer

    out = io.StringIO()
    logger = structlog.wrap_logger(structlog.PrintLogger(file=out), processors=processors)
    logger.info("upload.failed", error="bad file from sam@example.com", email="sam@x.io", n=2)
    line = json.loads(out.getvalue())
    assert line["event"] == "upload.failed"
    assert line["email"] == REDACTED and "sam@example.com" not in line["error"]
    assert line["n"] == 2


def test_sentry_event_scrub_drops_bodies_and_identity() -> None:
    event = {
        "user": {"email": "a@b.co"},
        "request": {"url": "/v1/x", "data": "body", "headers": {"authorization": "x"}},
        "message": "failed for a@b.co",
        "extra": {"quote": "learner words"},
    }
    out = observability.scrub_sentry_event(event)
    assert out is not None
    assert "user" not in out and "data" not in out["request"] and "headers" not in out["request"]
    assert "a@b.co" not in out["message"] and out["extra"]["quote"] == REDACTED


def test_everything_is_a_noop_without_configuration() -> None:
    cfg = settings()
    assert observability.init_sentry(cfg, "sg-test") is False
    assert observability.init_tracing(cfg, "sg-test") is False
    observability._initialised.discard("sg-noop")
    assert observability.init_observability("sg-noop", cfg) == {"sentry": False, "tracing": False}


def test_sentry_initialises_with_pii_off(monkeypatch: pytest.MonkeyPatch) -> None:
    import sentry_sdk

    seen: dict[str, Any] = {}
    monkeypatch.setattr(sentry_sdk, "init", lambda **kw: seen.update(kw))
    monkeypatch.setattr(sentry_sdk, "set_tag", lambda *a: None)
    cfg = settings(sentry_dsn=SecretStr("https://k@o0.ingest.sentry.io/1"))
    assert observability.init_sentry(cfg, "sg-test") is True
    assert seen["send_default_pii"] is False and seen["max_request_body_size"] == "never"
    assert seen["before_send"] is observability.scrub_sentry_event


def test_tracing_header_parsing() -> None:
    assert observability._parse_headers("a=b, c=d=e,bad") == {"a": "b", "c": "d=e"}


def test_init_failure_never_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*a: Any) -> bool:
        raise RuntimeError("nope")

    monkeypatch.setattr(observability, "init_sentry", boom)
    observability._initialised.discard("sg-boom")
    assert observability.init_observability("sg-boom", settings()) == {
        "sentry": False,
        "tracing": False,
    }
