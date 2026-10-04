"""Test doubles for the Arjuna (C16) API tests.

`LocalBackend` stands in for E2B: it runs the real harness in a temp directory with a local
subprocess, so the harness, the child-process isolation and the result parsing are exercised for
real. It is a test double only; production runs always go through E2B.
"""

import os
import shutil
import subprocess
import sys
import tempfile
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
from drona_fixtures import SETTINGS, FakeStore
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr

from sg_api.arjuna.store import InMemoryArjunaStore, get_arjuna_store
from sg_api.arjuna.tools import get_sandbox
from sg_api.drona.store import get_session_store
from sg_api.main import create_app
from sg_api.sessions.briefing import StubBriefingProvider, get_briefing_provider
from sg_api.sessions.router import get_elevenlabs
from sg_api.sessions.tool_tokens import HEADER, mint_tool_token
from sg_core.providers.elevenlabs import ElevenLabsClient
from sg_core.providers.sandbox import SandboxClient
from sg_core.settings import get_settings

SRC = str(Path(__file__).resolve().parents[1] / "src")
CORE_SRC = str(Path(__file__).resolve().parents[2] / "core" / "src")


class LocalBackend:
    def __init__(self) -> None:
        self.created = 0
        self.killed = 0
        self.commands: list[str] = []

    async def create(self, *, template: str, timeout_seconds: int, allow_internet: bool) -> Any:
        assert allow_internet is False, "learner code must never get the network"
        self.created += 1
        return tempfile.mkdtemp(prefix="sg-arjuna-")

    async def write_file(self, sandbox: Any, path: str, content: str | bytes) -> None:
        data = content.encode() if isinstance(content, str) else content
        (Path(sandbox) / path).write_bytes(data)

    async def run(
        self, sandbox: Any, command: str, *, timeout_seconds: float, env: dict[str, str]
    ) -> tuple[int, str, str]:
        self.commands.append(command)
        argv = command.split()
        if argv[0] == "python3":
            argv[0] = sys.executable
        environment = {**os.environ, "PYTHONPATH": os.pathsep.join([SRC, CORE_SRC]), **env}
        try:
            proc = subprocess.run(  # noqa: ASYNC221 - a test double, blocking is fine
                argv,
                cwd=sandbox,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
                env=environment,
            )
        except subprocess.TimeoutExpired as exc:
            raise TimeoutError from exc
        return proc.returncode, proc.stdout, proc.stderr

    async def kill(self, sandbox: Any) -> None:
        self.killed += 1
        shutil.rmtree(sandbox, ignore_errors=True)

    def sandbox_id(self, sandbox: Any) -> str | None:
        return Path(sandbox).name


def local_sandbox() -> tuple[SandboxClient, LocalBackend]:
    backend = LocalBackend()
    return SandboxClient(backend), backend  # type: ignore[arg-type]


def node_available() -> bool:
    return shutil.which("node") is not None


def reference_solution(problem_id: str) -> str:
    """Learner-style Python source that defers to the bank's reference (plumbing check only)."""
    from sg_api.arjuna.problems import BY_ID

    p = BY_ID[problem_id]
    args = ", ".join(p.params)
    return (
        "from sg_api.arjuna import problems as _p\n"
        f"def {p.function}({args}):\n"
        f"    return _p.BY_ID[{problem_id!r}].reference({args})\n"
    )


# ── API client wiring ──

SESSION_ID = uuid.UUID(int=77)
USER = "user_clerk_1"
DEV_HEADERS = {"X-Dev-User-Id": USER, "X-Dev-User-Name": "Asha"}
TOOL_HEADER = HEADER

TWO_SUM_PY = """
def two_sum(nums, target):
    seen = {}
    for i, n in enumerate(nums):
        if target - n in seen:
            return [seen[target - n], i]
        seen[n] = i
"""


def arjuna_token(character: str = "arjuna", conversation_id: str | None = "conv_1") -> str:
    value, _ = mint_tool_token(
        user_id=USER,
        session_id=str(SESSION_ID),
        character=character,
        conversation_id=conversation_id,
        settings=SETTINGS,
    )
    return value


@dataclass
class Rig:
    client: AsyncClient
    store: InMemoryArjunaStore
    backend: LocalBackend | None
    requests: list[httpx.Request]


async def rig(
    *,
    sandbox: SandboxClient | str | None = "local",
    store: InMemoryArjunaStore | None = None,
    scribe_status: int = 200,
) -> AsyncIterator[Rig]:
    app = create_app()
    arjuna_store = store or InMemoryArjunaStore()
    if not any(k.endswith(str(SESSION_ID)) for k in arjuna_store.sessions):
        arjuna_store.add_session(SESSION_ID)
    backend: LocalBackend | None = None
    if sandbox == "local":
        client_sandbox, backend = local_sandbox()
    else:
        client_sandbox = sandbox  # type: ignore[assignment]
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.path == "/v1/single-use-token/realtime_scribe":
            if scribe_status != 200:
                return httpx.Response(scribe_status, text="nope")
            return httpx.Response(200, json={"token": "sutkn_1"})
        return httpx.Response(200, json={"token": "lk_token", "conversation_id": "conv_new"})

    async def fake_elevenlabs() -> AsyncIterator[ElevenLabsClient]:
        async with ElevenLabsClient(
            SecretStr("xi-test"), transport=httpx.MockTransport(handler)
        ) as c:
            yield c

    settings = SETTINGS.model_copy(update={"elevenlabs_agent_ids": {"arjuna": "agent_arjuna"}})
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_arjuna_store] = lambda: arjuna_store
    app.dependency_overrides[get_sandbox] = lambda: client_sandbox
    app.dependency_overrides[get_session_store] = lambda: FakeStore()
    app.dependency_overrides[get_briefing_provider] = StubBriefingProvider
    app.dependency_overrides[get_elevenlabs] = fake_elevenlabs
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield Rig(client, arjuna_store, backend, seen)
