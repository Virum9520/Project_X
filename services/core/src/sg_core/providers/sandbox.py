"""E2B code sandbox (`SandboxClient`).

Each run gets a fresh sandbox with no internet access, a hard wall-clock limit, and is always
killed afterwards. Learner code and test files are data; nothing here interprets them. Sandbox
seconds are measured on our side and ledgered.
"""

import time
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Protocol

from pydantic import SecretStr

from sg_core.economics.usage import NullUsageRecorder, UsageContext, UsageMeasure, UsageRecorder
from sg_core.providers.base import ProviderNotConfiguredError

PROVIDER = "e2b"
DEFAULT_TEMPLATE = "base"
MAX_OUTPUT_CHARS = 20_000


@dataclass(frozen=True, slots=True)
class SandboxFile:
    path: str  # relative to the sandbox working directory
    content: str | bytes


@dataclass(frozen=True, slots=True)
class SandboxResult:
    exit_code: int
    stdout: str
    stderr: str
    timed_out: bool
    duration_seconds: float

    @property
    def ok(self) -> bool:
        return self.exit_code == 0 and not self.timed_out


class SandboxBackend(Protocol):
    """The slice of E2B we use; lets tests (and a future provider) stand in for the SDK."""

    async def create(self, *, template: str, timeout_seconds: int, allow_internet: bool) -> Any: ...
    async def write_file(self, sandbox: Any, path: str, content: str | bytes) -> None: ...
    async def run(
        self, sandbox: Any, command: str, *, timeout_seconds: float, env: dict[str, str]
    ) -> tuple[int, str, str]: ...
    async def kill(self, sandbox: Any) -> None: ...
    def sandbox_id(self, sandbox: Any) -> str | None: ...


class E2BBackend:
    def __init__(self, api_key: SecretStr) -> None:
        self._api_key = api_key.get_secret_value()

    async def create(self, *, template: str, timeout_seconds: int, allow_internet: bool) -> Any:
        from e2b import AsyncSandbox

        return await AsyncSandbox.create(
            template=template,
            timeout=timeout_seconds,
            allow_internet_access=allow_internet,
            api_key=self._api_key,
        )

    async def write_file(self, sandbox: Any, path: str, content: str | bytes) -> None:
        await sandbox.files.write(path, content)

    async def run(
        self, sandbox: Any, command: str, *, timeout_seconds: float, env: dict[str, str]
    ) -> tuple[int, str, str]:
        from e2b import CommandExitException

        try:
            result = await sandbox.commands.run(command, timeout=timeout_seconds, envs=env)
        except CommandExitException as exc:  # non-zero exit is a result, not an error
            return exc.exit_code, exc.stdout, exc.stderr
        return result.exit_code, result.stdout, result.stderr

    async def kill(self, sandbox: Any) -> None:
        await sandbox.kill()

    def sandbox_id(self, sandbox: Any) -> str | None:
        value = getattr(sandbox, "sandbox_id", None)
        return str(value) if value else None


class SandboxClient:
    def __init__(
        self,
        backend: SandboxBackend,
        *,
        template: str = DEFAULT_TEMPLATE,
        recorder: UsageRecorder | None = None,
    ) -> None:
        self._backend = backend
        self._template = template
        self._recorder: UsageRecorder = recorder or NullUsageRecorder()

    async def run(
        self,
        command: str,
        *,
        files: list[SandboxFile] | None = None,
        timeout_seconds: float = 10.0,
        allow_internet: bool = False,
        env: dict[str, str] | None = None,
        usage: UsageContext | None = None,
    ) -> SandboxResult:
        """Write `files`, run `command`, return the result. Never raises on a failing command.

        A command that outlives `timeout_seconds` yields `timed_out=True`, exit code 124.
        """
        started = time.monotonic()
        # The sandbox outlives the command a little so cleanup is ours, not the platform's.
        sandbox = await self._backend.create(
            template=self._template,
            timeout_seconds=int(timeout_seconds) + 30,
            allow_internet=allow_internet,
        )
        timed_out = False
        try:
            for f in files or []:
                await self._backend.write_file(sandbox, f.path, f.content)
            try:
                exit_code, stdout, stderr = await self._backend.run(
                    sandbox, command, timeout_seconds=timeout_seconds, env=env or {}
                )
            except TimeoutError:
                exit_code, stdout, stderr, timed_out = 124, "", "execution timed out", True
            except Exception as exc:
                if type(exc).__name__ != "TimeoutException":  # e2b's own timeout type
                    raise
                exit_code, stdout, stderr, timed_out = 124, "", "execution timed out", True
        finally:
            duration = time.monotonic() - started
            sandbox_ref = self._backend.sandbox_id(sandbox)
            await self._backend.kill(sandbox)
            if usage is not None:
                await self._recorder.record(
                    usage,
                    UsageMeasure(
                        provider=PROVIDER,
                        model=self._template,
                        external_ref=sandbox_ref,
                        sandbox_seconds=Decimal(str(round(duration, 3))),
                    ),
                )
        return SandboxResult(
            exit_code=exit_code,
            stdout=stdout[:MAX_OUTPUT_CHARS],
            stderr=stderr[:MAX_OUTPUT_CHARS],
            timed_out=timed_out,
            duration_seconds=duration,
        )


def sandbox_client_from_settings(recorder: UsageRecorder | None = None) -> SandboxClient:
    from sg_core.economics.ledger import DbUsageRecorder
    from sg_core.settings import get_settings

    s = get_settings()
    if s.e2b_api_key is None:
        raise ProviderNotConfiguredError("E2B_API_KEY is not configured")
    return SandboxClient(E2BBackend(s.e2b_api_key), recorder=recorder or DbUsageRecorder())
