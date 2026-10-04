"""Typed models for the human-edited agent sources under `agents/`.

Sources are small YAML files plus markdown prompts. `compiler.py` turns them into the raw
ElevenLabs configs that the `elevenlabs` CLI pushes. Unknown keys are rejected everywhere so a
typo fails loudly instead of being silently ignored.
"""

import re
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

TurnEagerness = Literal["patient", "normal", "eager"]
TTSModel = Literal[
    "eleven_turbo_v2",
    "eleven_turbo_v2_5",
    "eleven_flash_v2",
    "eleven_flash_v2_5",
    "eleven_multilingual_v2",
    "eleven_v3_conversational",
]
Scalar = str | int | float | bool

KEY_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


# ── Shared registries ──────────────────────────────────────────────────────────


class DynamicVariable(Strict):
    description: str
    placeholder: Scalar


class Environment(Strict):
    api_base_url: str = Field(pattern=r"^https://[^/]+$")
    description: str = ""


class Environments(Strict):
    default: str
    environments: dict[str, Environment]

    @model_validator(mode="after")
    def _default_exists(self) -> "Environments":
        if self.default not in self.environments:
            raise ValueError(f"default environment {self.default!r} is not defined")
        return self


class VoiceDesign(Strict):
    """Voice Design prompt for one character (POST /v1/text-to-voice/design)."""

    name: str
    description: str = Field(min_length=20, max_length=1000)
    preview_text: str = Field(min_length=100, max_length=1000)
    model_id: Literal["eleven_multilingual_ttv_v2", "eleven_ttv_v3"] = "eleven_ttv_v3"
    guidance_scale: float = 5.0
    loudness: float = 0.5
    seed: int = Field(default=1, ge=0)


class VoiceDesigns(Strict):
    voices: dict[str, VoiceDesign]


# ── Tools ─────────────────────────────────────────────────────────────────────


class ToolParam(Strict):
    type: Literal["string", "integer", "number", "boolean"]
    description: str
    enum: list[str] | None = None


class ToolParams(Strict):
    required: list[str] = []
    properties: dict[str, ToolParam] = {}

    @model_validator(mode="after")
    def _required_known(self) -> "ToolParams":
        unknown = set(self.required) - set(self.properties)
        if unknown:
            raise ValueError(f"required params not in properties: {sorted(unknown)}")
        return self


class ToolSpec(Strict):
    """A server (webhook) or client tool shared by any number of characters."""

    name: str = Field(pattern=KEY_PATTERN.pattern)
    type: Literal["webhook", "client"]
    description: str
    parameters: ToolParams = ToolParams()
    timeout_secs: int = Field(default=10, ge=1, le=120)
    # webhook only: path on the Skill Garden API, joined to the environment's base URL.
    path: str | None = Field(default=None, pattern=r"^/v1/agent-tools/[a-z_]+$")
    # client only: whether the agent waits for the browser to return a result.
    expects_response: bool = False
    force_pre_tool_speech: bool = False
    disable_interruptions: bool = False

    @model_validator(mode="after")
    def _shape(self) -> "ToolSpec":
        if self.type == "webhook" and self.path is None:
            raise ValueError("webhook tools need a `path`")
        if self.type == "client" and self.path is not None:
            raise ValueError("client tools must not set `path`")
        reserved = {"conversation_id"} & set(self.parameters.properties)
        if reserved:
            raise ValueError(f"reserved parameter names: {sorted(reserved)}")
        return self


# ── Characters ────────────────────────────────────────────────────────────────


class DataField(Strict):
    type: Literal["string", "integer", "number", "boolean"]
    description: str
    enum: list[str] | None = None


class Criterion(Strict):
    id: str = Field(pattern=KEY_PATTERN.pattern)
    name: str
    goal: str


class Phase(Strict):
    """One workflow phase, compiled to an `override_agent` (subagent) node."""

    label: str
    prompt: str  # markdown file, relative to the character directory
    tools: list[str] = []
    turn_eagerness: TurnEagerness | None = None
    entry_behavior: Literal["generate_immediately", "wait_for_user", "auto"] = "auto"


class Edge(Strict):
    source: str
    target: str
    # Natural-language condition evaluated by ElevenLabs; omitted means unconditional.
    when: str | None = None
    label: str | None = None


class Workflow(Strict):
    phases: dict[str, Phase]
    edges: list[Edge]

    @model_validator(mode="after")
    def _graph(self) -> "Workflow":
        nodes = {"start", *self.phases}
        for edge in self.edges:
            if edge.source not in nodes or edge.target not in self.phases:
                raise ValueError(f"edge {edge.source}->{edge.target} references unknown phase")
        if not any(edge.source == "start" for edge in self.edges):
            raise ValueError("workflow needs an edge from `start`")
        return self


class PanelVoice(Strict):
    label: str = Field(pattern=r"^[A-Z][A-Za-z]+$")
    voice: str
    description: str


class CharacterSpec(Strict):
    name: str
    role: str
    voice: str
    llm: str
    temperature: float = Field(ge=0, le=1)
    tts_model: TTSModel = "eleven_flash_v2"
    tts_stability: float = Field(default=0.5, ge=0, le=1)
    tts_speed: float = Field(default=1.0, ge=0.7, le=1.2)
    expressive_mode: bool = False
    turn_eagerness: TurnEagerness = "normal"
    turn_timeout: float = Field(default=7.0, ge=1, le=30)
    max_duration_seconds: int = Field(ge=60, le=3600)
    max_duration_message: str = ""
    first_message: str
    tools: list[str] = []
    system_tools: list[Literal["end_call", "skip_turn"]] = ["end_call"]
    data_collection: dict[str, DataField] = {}
    evaluation: list[Criterion] = []
    workflow: Workflow | None = None
    panel_voices: list[PanelVoice] = []
    record_voice: bool = True
    tags: list[str] = []


class Turn(Strict):
    role: Literal["user", "agent"]
    message: str


class ParamCheck(Strict):
    path: str
    exact: str | None = None
    regex: str | None = None
    llm: str | None = None

    @model_validator(mode="after")
    def _one(self) -> "ParamCheck":
        if sum(v is not None for v in (self.exact, self.regex, self.llm)) > 1:
            raise ValueError("set at most one of exact / regex / llm")
        return self


class TestSpec(Strict):
    type: Literal["llm", "tool", "simulation"]
    description: str = ""
    chat_history: list[Turn] = []
    dynamic_variables: dict[str, Scalar] = {}
    # llm
    success_condition: str = ""
    success_examples: list[str] = []
    failure_examples: list[str] = []
    # tool
    tool: str | None = None
    tool_parameters: list[ParamCheck] = []
    verify_absence: bool = False
    # simulation
    scenario: str = ""
    success_conditions: list[str] = []
    max_turns: int = Field(default=6, ge=1, le=20)

    @model_validator(mode="after")
    def _shape(self) -> "TestSpec":
        if self.type == "tool" and not self.tool:
            raise ValueError("tool tests need `tool`")
        if self.type == "llm" and not self.success_condition:
            raise ValueError("llm tests need `success_condition`")
        if self.type == "simulation" and not (self.scenario and self.success_conditions):
            raise ValueError("simulation tests need `scenario` and `success_conditions`")
        if self.type != "simulation" and not self.chat_history:
            raise ValueError("llm and tool tests need a `chat_history`")
        return self


# ── Loading ───────────────────────────────────────────────────────────────────


class Character(BaseModel):
    """A character spec plus the prompts it references, loaded from disk."""

    model_config = ConfigDict(frozen=True)

    key: str
    spec: CharacterSpec
    prompt: str
    phase_prompts: dict[str, str]
    tests: dict[str, TestSpec]


class Sources(BaseModel):
    model_config = ConfigDict(frozen=True)

    root: Path
    guardrails: str
    dynamic_variables: dict[str, DynamicVariable]
    environments: Environments
    voices: VoiceDesigns
    tools: dict[str, ToolSpec]
    characters: dict[str, Character]


def _yaml(path: Path) -> Any:
    with path.open() as fh:
        return yaml.safe_load(fh)


def _key(path: Path) -> str:
    key = path.stem if path.is_file() else path.name
    if not KEY_PATTERN.match(key):
        raise ValueError(f"{path}: names must be snake_case")
    return key


def load_sources(root: Path) -> Sources:
    """Load and validate every source file under `agents/`."""
    tools: dict[str, ToolSpec] = {}
    for path in sorted((root / "tools").glob("*.yaml")):
        tool = ToolSpec.model_validate(_yaml(path))
        if tool.name != _key(path):
            raise ValueError(f"{path}: tool name must match the file name")
        tools[tool.name] = tool

    characters: dict[str, Character] = {}
    for directory in sorted(p for p in (root / "characters").iterdir() if p.is_dir()):
        key = _key(directory)
        spec = CharacterSpec.model_validate(_yaml(directory / "agent.yaml"))
        phase_prompts = (
            {
                phase_key: (directory / phase.prompt).read_text().strip()
                for phase_key, phase in spec.workflow.phases.items()
            }
            if spec.workflow
            else {}
        )
        tests_dir = root / "tests" / key
        tests = {
            _key(path): TestSpec.model_validate(_yaml(path))
            for path in sorted(tests_dir.glob("*.yaml"))
        }
        characters[key] = Character(
            key=key,
            spec=spec,
            prompt=(directory / "prompt.md").read_text().strip(),
            phase_prompts=phase_prompts,
            tests=tests,
        )

    unknown_test_dirs = {
        p.name for p in (root / "tests").iterdir() if p.is_dir() and p.name not in characters
    }
    if unknown_test_dirs:
        raise ValueError(f"tests for unknown characters: {sorted(unknown_test_dirs)}")

    return Sources(
        root=root,
        guardrails=(root / "shared" / "guardrails.md").read_text().strip(),
        dynamic_variables={
            name: DynamicVariable.model_validate(value)
            for name, value in _yaml(root / "dynamic_variables.yaml").items()
        },
        environments=Environments.model_validate(_yaml(root / "environments.yaml")),
        voices=VoiceDesigns.model_validate(_yaml(root / "voices.yaml")),
        tools=tools,
        characters=characters,
    )
