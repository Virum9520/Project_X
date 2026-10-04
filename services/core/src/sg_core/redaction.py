"""PII and secret redaction for logs and error reports.

Used by the structlog pipeline (`sg_core.logging`) and by Sentry's `before_send`
(`sg_core.observability`). Two layers: values under sensitive keys are always replaced, and
free text is scrubbed for emails, phone numbers, bearer tokens, JWTs and provider API keys.
Learner transcripts, document text and answers are never logged on purpose; the key list is the
backstop if someone logs them anyway.
"""

import re
from collections.abc import Mapping
from typing import Any

REDACTED = "[redacted]"
MAX_DEPTH = 8

# Substrings of a (lower-cased) key that mark its value as sensitive.
SENSITIVE_KEY_PARTS: tuple[str, ...] = (
    "authorization",
    "cookie",
    "password",
    "passwd",
    "secret",
    "token",
    "api_key",
    "apikey",
    "api-key",
    "private_key",
    "signature",
    "dsn",
    "email",
    "phone",
    "transcript",
    "answer",
    "document_text",
    "quote",
    "ssn",
)
# Keys that look sensitive by substring but are only counters.
SAFE_KEYS: frozenset[str] = frozenset(
    {"tokens", "input_tokens", "output_tokens", "max_tokens", "total_tokens", "token_count"}
)

_EMAIL = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
_BEARER = re.compile(r"\b(Bearer|Basic)\s+[A-Za-z0-9._~+/=\-]{8,}", re.IGNORECASE)
_JWT = re.compile(r"\beyJ[A-Za-z0-9_\-]{5,}\.[A-Za-z0-9_\-]{5,}\.[A-Za-z0-9_\-]*")
_API_KEY = re.compile(
    r"\b(?:sk|pk|rk|xi|whsec|ghp|gho|xox[abp])(?:_(?:live|test))?[-_][A-Za-z0-9_\-]{12,}"
)
# NANP-style (+1 555 555 0123, (555) 555-0123) or E.164 (+<8-14 digits>); ISO dates don't match.
_PHONE = re.compile(
    r"(?<![\w.\-])(?:"
    r"\+\d{8,14}"
    r"|(?:\+?1[\s.\-]?)?\(?\d{3}\)?[\s.\-]\d{3}[\s.\-]\d{4}"
    r"|(?:\+?1[\s.\-]?)?\(\d{3}\)\d{3}[\s.\-]?\d{4}"
    r")(?![\w\-])"
)
_URL_CREDS = re.compile(r"(\w+(?:\+\w+)?://)[^/\s:@]+:[^@\s/]+@")


def is_sensitive_key(key: object) -> bool:
    lowered = str(key).lower()
    return lowered not in SAFE_KEYS and any(part in lowered for part in SENSITIVE_KEY_PARTS)


def redact_text(text: str) -> str:
    """Scrub emails, phone numbers, tokens and credentials out of free text."""
    text = _URL_CREDS.sub(r"\1[redacted]@", text)
    text = _BEARER.sub(lambda m: f"{m.group(1)} {REDACTED}", text)
    text = _JWT.sub(REDACTED, text)
    text = _API_KEY.sub(REDACTED, text)
    text = _EMAIL.sub("[email]", text)
    return _PHONE.sub("[phone]", text)


def redact_value(value: Any, *, _depth: int = 0) -> Any:
    """Recursively redact `value`: mappings by key, strings by pattern."""
    if _depth > MAX_DEPTH:
        return REDACTED
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, Mapping):
        return {
            k: (REDACTED if is_sensitive_key(k) else redact_value(v, _depth=_depth + 1))
            for k, v in value.items()
        }
    if isinstance(value, list | tuple | set | frozenset):
        return [redact_value(v, _depth=_depth + 1) for v in value]
    if isinstance(value, bytes | bytearray):
        return REDACTED
    return value


def redact_event_dict(
    _logger: object, _method: str, event_dict: dict[str, Any]
) -> dict[str, Any]:
    """structlog processor: redact every field except the event name, timestamp and level."""
    out: dict[str, Any] = {}
    for key, value in event_dict.items():
        if key in {"event", "level", "timestamp"}:
            out[key] = value
        elif is_sensitive_key(key):
            out[key] = REDACTED
        else:
            out[key] = redact_value(value)
    return out
