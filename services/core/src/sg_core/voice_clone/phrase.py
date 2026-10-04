"""Consent phrase: signed one-time challenge and tolerant matching of the Scribe transcript.

The learner reads a scripted sentence that contains challenge words picked by the server. The
challenge is a stateless HMAC token bound to the learner and an expiry, so a recording of someone
else (or an old recording) cannot pass: the words differ each time and must be heard in the
transcript. The matching is tolerant to Scribe's punctuation, casing and small slips, but the
challenge words must match exactly and in order.
"""

import base64
import hashlib
import hmac
import json
import re
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from difflib import SequenceMatcher

CONSENT_VERSION = "future-self-v1"
CHALLENGE_TTL = timedelta(minutes=10)
CHALLENGE_WORDS = 3
MIN_SIMILARITY = 0.85

CONSENT_STATEMENTS: tuple[str, ...] = (
    "Skill Garden will create an AI copy of my voice from the recording I make now.",
    "The copy is used only to speak daily messages from my future self to me.",
    "My recording is kept only as proof of consent, and it is never used to train models.",
    "I can revoke at any time. Revoking deletes the voice at ElevenLabs and my recording here.",
)

PHRASE_TEMPLATE = (
    "I consent to Skill Garden making an AI copy of my own voice. My code words are {words}."
)

# Short, common, phonetically distinct words that Scribe transcribes reliably.
WORDLIST: tuple[str, ...] = (
    "maple",
    "river",
    "lantern",
    "orbit",
    "copper",
    "meadow",
    "violet",
    "harbor",
    "falcon",
    "granite",
    "willow",
    "ember",
    "compass",
    "thunder",
    "velvet",
    "anchor",
    "pebble",
    "cactus",
    "saffron",
    "juniper",
    "glacier",
    "marble",
    "tundra",
    "walnut",
    "zephyr",
    "bamboo",
    "cinder",
    "dolphin",
    "echo",
    "fjord",
)


class ChallengeError(ValueError):
    """The challenge token is malformed, forged, expired or belongs to someone else."""


@dataclass(frozen=True, slots=True)
class Challenge:
    phrase: str
    words: tuple[str, ...]
    token: str
    expires_at: datetime
    consent_version: str


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _sign(secret: bytes, payload: str) -> str:
    # Domain-separated so the shared secret cannot be replayed as another token type.
    mac = hmac.new(secret, b"future-self-consent:" + payload.encode(), hashlib.sha256)
    return _b64(mac.digest())


def issue_challenge(user_id: uuid.UUID, secret: bytes, *, now: datetime | None = None) -> Challenge:
    moment = now or datetime.now(UTC)
    words = tuple(secrets.SystemRandom().sample(WORDLIST, CHALLENGE_WORDS))
    expires_at = moment + CHALLENGE_TTL
    body = {
        "u": str(user_id),
        "w": list(words),
        "v": CONSENT_VERSION,
        "e": int(expires_at.timestamp()),
        "n": secrets.token_hex(6),
    }
    payload = _b64(json.dumps(body, separators=(",", ":")).encode())
    return Challenge(
        phrase=PHRASE_TEMPLATE.format(words=", ".join(words)),
        words=words,
        token=f"{payload}.{_sign(secret, payload)}",
        expires_at=expires_at,
        consent_version=CONSENT_VERSION,
    )


def open_challenge(
    token: str, user_id: uuid.UUID, secret: bytes, *, now: datetime | None = None
) -> Challenge:
    """Verify `token` for this learner and return the challenge it encodes."""
    payload, _, signature = token.partition(".")
    if not payload or not signature:
        raise ChallengeError("malformed challenge")
    if not hmac.compare_digest(signature, _sign(secret, payload)):
        raise ChallengeError("invalid challenge")
    try:
        body = json.loads(_unb64(payload))
        words = tuple(str(w) for w in body["w"])
        expires_at = datetime.fromtimestamp(int(body["e"]), tz=UTC)
        owner = str(body["u"])
        version = str(body["v"])
    except (ValueError, KeyError, TypeError) as exc:
        raise ChallengeError("malformed challenge") from exc
    if owner != str(user_id):
        raise ChallengeError("challenge belongs to another learner")
    if expires_at < (now or datetime.now(UTC)):
        raise ChallengeError("challenge expired; request a new phrase")
    return Challenge(
        phrase=PHRASE_TEMPLATE.format(words=", ".join(words)),
        words=words,
        token=token,
        expires_at=expires_at,
        consent_version=version,
    )


_NON_WORD = re.compile(r"[^a-z0-9\s]")


def normalize(text: str) -> list[str]:
    return _NON_WORD.sub(" ", text.lower().replace("'", "")).split()


@dataclass(frozen=True, slots=True)
class PhraseMatch:
    matched: bool
    similarity: float
    words_heard: bool


def match_phrase(expected: str, words: tuple[str, ...], transcript: str) -> PhraseMatch:
    """The transcript must contain the challenge words in order and resemble the phrase."""
    heard = normalize(transcript)
    want = normalize(expected)
    similarity = SequenceMatcher(a=want, b=heard, autojunk=False).ratio() if heard else 0.0
    # Challenge words must appear in order (other words may sit between them).
    position = 0
    words_heard = True
    for word in words:
        try:
            position = heard.index(word, position) + 1
        except ValueError:
            words_heard = False
            break
    return PhraseMatch(
        matched=words_heard and similarity >= MIN_SIMILARITY,
        similarity=round(similarity, 3),
        words_heard=words_heard,
    )
