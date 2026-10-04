"""Error reporting (Sentry) and tracing (OpenTelemetry), env-driven and safe to skip.

`init_observability(service)` is called once at process start by the API and the worker. With no
`SENTRY_DSN` / `OTEL_EXPORTER_OTLP_ENDPOINT` it does nothing and imports nothing heavy. All
events pass through `sg_core.redaction` before leaving the process, and Sentry never receives
request bodies, cookies, headers or user PII (`send_default_pii=False`).
"""

from typing import Any

from sg_core.logging import get_logger
from sg_core.redaction import redact_value
from sg_core.settings import Settings, get_settings

log = get_logger(__name__)

_initialised: set[str] = set()


def scrub_sentry_event(event: dict[str, Any], _hint: object = None) -> dict[str, Any] | None:
    """Sentry `before_send`/`before_send_transaction`: drop bodies and redact the rest."""
    request = event.get("request")
    if isinstance(request, dict):
        for key in ("data", "cookies", "headers", "query_string", "env"):
            request.pop(key, None)
    event.pop("user", None)
    for key in ("message", "logentry", "exception", "breadcrumbs", "extra", "contexts", "tags"):
        if key in event:
            event[key] = redact_value(event[key])
    return event


def init_sentry(settings: Settings, service: str) -> bool:
    if settings.sentry_dsn is None:
        return False
    import sentry_sdk

    sentry_sdk.init(
        dsn=settings.sentry_dsn.get_secret_value(),
        environment=settings.environment.value,
        release=settings.git_sha,
        server_name=service,
        traces_sample_rate=settings.sentry_traces_sample_rate,
        send_default_pii=False,
        max_request_body_size="never",
        before_send=scrub_sentry_event,  # type: ignore[arg-type]
        before_send_transaction=scrub_sentry_event,  # type: ignore[arg-type]
    )
    sentry_sdk.set_tag("service", service)
    return True


def _parse_headers(raw: str | None) -> dict[str, str]:
    out: dict[str, str] = {}
    for part in (raw or "").split(","):
        key, sep, value = part.partition("=")
        if sep and key.strip():
            out[key.strip()] = value.strip()
    return out


def init_tracing(settings: Settings, service: str) -> bool:
    endpoint = settings.otel_exporter_otlp_endpoint
    if not endpoint:
        return False
    from opentelemetry import trace
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor
    from opentelemetry.sdk.trace.sampling import ParentBased, TraceIdRatioBased

    headers = settings.otel_exporter_otlp_headers
    provider = TracerProvider(
        resource=Resource.create(
            {
                "service.name": service,
                "deployment.environment": settings.environment.value,
                "service.version": settings.git_sha or "unknown",
            }
        ),
        sampler=ParentBased(TraceIdRatioBased(settings.otel_traces_sample_ratio)),
    )
    exporter = OTLPSpanExporter(
        endpoint=endpoint.rstrip("/") + "/v1/traces",
        headers=_parse_headers(headers.get_secret_value() if headers else None),
    )
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    HTTPXClientInstrumentor().instrument()
    return True


def instrument_fastapi(app: Any, settings: Settings | None = None) -> None:
    """Trace inbound requests when an OTLP endpoint is configured; otherwise a no-op."""
    settings = settings or get_settings()
    if settings.otel_exporter_otlp_endpoint:
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

        FastAPIInstrumentor.instrument_app(app, excluded_urls="healthz,readyz")


def init_observability(service: str, settings: Settings | None = None) -> dict[str, bool]:
    """Start Sentry and tracing once per process. Returns which backends are active."""
    settings = settings or get_settings()
    if service in _initialised:
        return {"sentry": False, "tracing": False}
    _initialised.add(service)
    active = {"sentry": False, "tracing": False}
    try:
        active["sentry"] = init_sentry(settings, service)
        active["tracing"] = init_tracing(settings, service)
    except Exception as exc:  # observability must never stop the service from starting
        log.warning("observability.init_failed", error=str(exc))
    log.info("observability.ready", service=service, **active)
    return active
