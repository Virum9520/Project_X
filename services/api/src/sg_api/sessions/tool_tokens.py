"""Session-scoped tokens that ElevenLabs agents present to `/v1/agent-tools/*` (server tools).

POST /v1/sessions mints one per conversation and hands it to the browser, which passes it to
ElevenLabs as the `secret__sg_tool_token` dynamic variable. Agents send it in the
`X-SG-Tool-Token` header (see agents/tool_configs). `secret__` variables are never shown to the
LLM.

Client-supplied dynamic variables are not an authorization boundary, so the token is: it is
HMAC-signed, short-lived, and binds the learner, session, character and the ElevenLabs
conversation ID returned with the conversation token. Tool endpoints must also check that the
body's `conversation_id` (filled by ElevenLabs from `system__conversation_id`) matches `cid`.
"""

import time
import uuid
from typing import Annotated

import jwt
from fastapi import Depends, Header, HTTPException, status
from pydantic import BaseModel

from sg_core.settings import Settings, get_settings

AUDIENCE = "sg-agent-tools"
ISSUER = "sg-api"
HEADER = "X-SG-Tool-Token"


class ToolTokenClaims(BaseModel):
    user_id: str
    session_id: str
    character: str
    conversation_id: str | None
    expires_at: int


def _secret(settings: Settings) -> str:
    if settings.agent_tool_token_secret is None:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "agent tool signing is not configured"
        )
    return settings.agent_tool_token_secret.get_secret_value()


def mint_tool_token(
    *,
    user_id: str,
    session_id: str,
    character: str,
    conversation_id: str | None,
    settings: Settings,
    now: int | None = None,
) -> tuple[str, int]:
    """Return `(token, expires_at)`."""
    issued = int(time.time()) if now is None else now
    expires_at = issued + settings.agent_tool_token_ttl_seconds
    claims = {
        "iss": ISSUER,
        "aud": AUDIENCE,
        "sub": user_id,
        "sid": session_id,
        "chr": character,
        "cid": conversation_id,
        "iat": issued,
        "exp": expires_at,
        "jti": uuid.uuid4().hex,
    }
    return jwt.encode(claims, _secret(settings), algorithm="HS256"), expires_at


def verify_tool_token(token: str, settings: Settings) -> ToolTokenClaims:
    try:
        claims = jwt.decode(
            token,
            _secret(settings),
            algorithms=["HS256"],
            audience=AUDIENCE,
            issuer=ISSUER,
            options={"require": ["exp", "iat", "sub", "aud", "iss"]},
        )
    except jwt.PyJWTError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid agent tool token") from exc
    return ToolTokenClaims(
        user_id=claims["sub"],
        session_id=claims["sid"],
        character=claims["chr"],
        conversation_id=claims.get("cid"),
        expires_at=claims["exp"],
    )


async def require_tool_token(
    settings: Annotated[Settings, Depends(get_settings)],
    token: Annotated[str | None, Header(alias=HEADER)] = None,
) -> ToolTokenClaims:
    """FastAPI dependency for server-tool endpoints."""
    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "missing agent tool token")
    return verify_tool_token(token, settings)


def check_conversation(claims: ToolTokenClaims, conversation_id: str) -> None:
    """Reject a tool call whose body `conversation_id` is not the one the token was minted for."""
    if claims.conversation_id is not None and claims.conversation_id != conversation_id:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "tool token is bound to another conversation"
        )
