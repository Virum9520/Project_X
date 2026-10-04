"""Compile `agents/` sources into the raw configs the `elevenlabs` CLI pushes.

Inputs (human-edited): `characters/*/agent.yaml` + markdown prompts, `tools/*.yaml`,
`tests/<character>/*.yaml`, `shared/guardrails.md`, `dynamic_variables.yaml`,
`environments.yaml`, and `voices.json` (voice IDs written by `sg-agents voices create`).

Outputs (generated, committed, never hand-edited): `agent_configs/`, `tool_configs/`,
`test_configs/`, and the CLI registries `agents.json`, `tools.json`, `tests.json`. The CLI writes
remote IDs into the registries on push; the compiler preserves them and resolves tool, test and
voice references through them, so a build after a push wires everything together.
"""

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sg_agentops import schema
from sg_agentops.sources import Character, Sources, TestSpec, ToolSpec, load_sources

TOOL_TOKEN_HEADER = "X-SG-Tool-Token"
# `secret__` dynamic variables are usable in tool headers but never shown to the LLM.
TOOL_TOKEN_VARIABLE = "secret__sg_tool_token"
CONVERSATION_ID_VARIABLE = "system__conversation_id"

# Events the browser needs: audio (+ alignment for lip-sync), captions, tool calls, interruptions.
CLIENT_EVENTS = [
    "audio",
    "interruption",
    "user_transcript",
    "agent_response",
    "agent_response_correction",
    "client_tool_call",
    "agent_tool_response",
]

GENERATED_DIRS = ("agent_configs", "tool_configs", "test_configs")
VARIABLE_PATTERN = re.compile(r"\{\{\s*([A-Za-z0-9_]+)\s*\}\}")


@dataclass
class BuildResult:
    files: dict[Path, str] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    unresolved: list[str] = field(default_factory=list)

    def write(self, root: Path) -> list[Path]:
        """Write outputs and delete stale generated files. Returns the paths that changed."""
        changed: list[Path] = []
        for path, content in sorted(self.files.items()):
            target = root / path
            if not target.exists() or target.read_text() != content:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(content)
                changed.append(path)
        for stale in self.stale(root):
            (root / stale).unlink()
            changed.append(stale)
        return changed

    def drift(self, root: Path) -> list[Path]:
        """Paths whose on-disk content differs from what a build would write."""
        out = [
            p
            for p, c in self.files.items()
            if not (root / p).exists() or (root / p).read_text() != c
        ]
        return sorted(out + self.stale(root))

    def stale(self, root: Path) -> list[Path]:
        existing = {
            p.relative_to(root)
            for d in GENERATED_DIRS
            if (root / d).exists()
            for p in (root / d).rglob("*.json")
        }
        return sorted(existing - set(self.files))


def _dump(data: Any) -> str:
    return json.dumps(data, indent=4, sort_keys=True, ensure_ascii=False) + "\n"


def _read_json(path: Path, default: Any) -> Any:
    return json.loads(path.read_text()) if path.exists() else default


def _variables(*texts: str) -> set[str]:
    return {m for text in texts for m in VARIABLE_PATTERN.findall(text)}


class Compiler:
    def __init__(self, sources: Sources, environment: str) -> None:
        if environment not in sources.environments.environments:
            raise ValueError(f"unknown environment {environment!r}")
        self.src = sources
        self.root = sources.root
        self.api_base_url = sources.environments.environments[environment].api_base_url
        self.result = BuildResult()
        self.voice_ids: dict[str, str | None] = {
            key: entry.get("voice_id")
            for key, entry in _read_json(self.root / "voices.json", {"voices": {}})[
                "voices"
            ].items()
        }
        self.registries = {
            name: {
                entry["config"]: entry
                for entry in _read_json(self.root / f"{name}.json", {name: []})[name]
            }
            for name in ("agents", "tools", "tests")
        }

    # ── helpers ──

    def _error(self, message: str) -> None:
        self.result.errors.append(message)

    def _pending(self, message: str) -> None:
        if message not in self.result.unresolved:
            self.result.unresolved.append(message)

    def _remote_id(self, registry: str, config_path: str, what: str) -> str | None:
        remote_id: str | None = self.registries[registry].get(config_path, {}).get("id")
        if not remote_id:
            self._pending(f"{what}: no remote id yet (push it first)")
        return remote_id

    def _tool_ids(self, names: list[str], owner: str) -> list[str]:
        ids: list[str] = []
        for name in names:
            if name not in self.src.tools:
                self._error(f"{owner}: unknown tool {name!r}")
                continue
            tool_id = self._remote_id("tools", f"tool_configs/{name}.json", f"tool {name}")
            if tool_id:
                ids.append(tool_id)
        return ids

    def _voice_id(self, voice: str, owner: str) -> str:
        if voice not in self.src.voices.voices:
            self._error(f"{owner}: voice {voice!r} is not defined in voices.yaml")
        voice_id = self.voice_ids.get(voice)
        if not voice_id:
            self._pending(f"voice {voice}: no voice_id yet (run `sg-agents voices design {voice}`)")
            return "UNRESOLVED_VOICE"
        return voice_id

    def _validate(self, kind: str, path: str, config: dict[str, Any]) -> None:
        for err in schema.validate(kind, config):
            self._error(f"{path}: {err}")

    def _placeholders(self, names: set[str], owner: str) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for name in sorted(names):
            if name.startswith("system__"):
                continue
            declared = self.src.dynamic_variables.get(name)
            if declared is None:
                self._error(f"{owner}: dynamic variable {{{{{name}}}}} is not declared")
                continue
            out[name] = declared.placeholder
        return out

    # ── tools ──

    def compile_tool(self, tool: ToolSpec) -> dict[str, Any]:
        params: dict[str, Any] = {
            name: {"type": p.type, "description": p.description}
            | ({"enum": p.enum} if p.enum else {})
            for name, p in tool.parameters.properties.items()
        }
        common: dict[str, Any] = {
            "type": tool.type,
            "name": tool.name,
            "description": tool.description,
            "response_timeout_secs": tool.timeout_secs,
            "force_pre_tool_speech": tool.force_pre_tool_speech,
            "disable_interruptions": tool.disable_interruptions,
        }
        if tool.type == "client":
            return common | {
                "expects_response": tool.expects_response,
                "parameters": {
                    "type": "object",
                    "description": f"Arguments for {tool.name}",
                    "required": tool.parameters.required,
                    "properties": params,
                },
                "dynamic_variables": {"dynamic_variable_placeholders": {}},
            }
        # Server tools authenticate with a short-lived, session-scoped token minted by
        # POST /v1/sessions. The conversation ID is filled by ElevenLabs, not the LLM.
        params["conversation_id"] = {"type": "string", "dynamic_variable": CONVERSATION_ID_VARIABLE}
        return common | {
            "api_schema": {
                "url": f"{self.api_base_url}{tool.path}",
                "method": "POST",
                "content_type": "application/json",
                "request_headers": {TOOL_TOKEN_HEADER: {"variable_name": TOOL_TOKEN_VARIABLE}},
                "request_body_schema": {
                    "type": "object",
                    "description": f"Arguments for {tool.name}",
                    "required": [*tool.parameters.required, "conversation_id"],
                    "properties": params,
                },
            },
            "dynamic_variables": {
                "dynamic_variable_placeholders": self._placeholders(
                    {TOOL_TOKEN_VARIABLE}, f"tool {tool.name}"
                )
            },
        }

    # ── tests ──

    def compile_test(
        self, character: Character, key: str, test: TestSpec, variables: dict[str, Any]
    ) -> dict[str, Any]:
        owner = f"test {character.key}/{key}"
        history = [
            {"role": turn.role, "message": turn.message, "time_in_call_secs": 2 * i + 1}
            for i, turn in enumerate(test.chat_history)
        ]
        unknown = set(test.dynamic_variables) - set(self.src.dynamic_variables)
        if unknown:
            self._error(f"{owner}: unknown dynamic variables {sorted(unknown)}")
        config: dict[str, Any] = {
            "name": f"sg/{character.key}/{key}",
            "type": test.type,
            "chat_history": history,
            "dynamic_variables": variables | test.dynamic_variables,
        }
        if test.type == "llm":
            config |= {
                "success_condition": test.success_condition,
                "success_examples": [
                    {"response": r, "type": "success"} for r in test.success_examples
                ],
                "failure_examples": [
                    {"response": r, "type": "failure"} for r in test.failure_examples
                ],
            }
        elif test.type == "tool":
            assert test.tool is not None
            reachable = set(character.spec.tools)
            if character.spec.workflow:
                reachable |= {t for p in character.spec.workflow.phases.values() for t in p.tools}
            if test.tool not in reachable:
                self._error(f"{owner}: tool {test.tool!r} is not available to {character.key}")
            tool = self.src.tools.get(test.tool)
            tool_id = self._remote_id(
                "tools", f"tool_configs/{test.tool}.json", f"tool {test.tool}"
            )
            config["tool_call_parameters"] = {
                "referenced_tool": {"id": tool_id or "", "type": tool.type if tool else "webhook"},
                "verify_absence": test.verify_absence,
                "parameters": [
                    self._param_check(c.path, c.exact, c.regex, c.llm) for c in test.tool_parameters
                ],
            }
        else:
            config |= {
                "simulation_scenario": test.scenario,
                "success_conditions": test.success_conditions,
                "simulation_max_turns": test.max_turns,
            }
        return config

    @staticmethod
    def _param_check(
        path: str, exact: str | None, regex: str | None, llm: str | None
    ) -> dict[str, Any]:
        if exact is not None:
            return {"path": path, "eval": {"type": "exact", "expected_value": exact}}
        if regex is not None:
            return {"path": path, "eval": {"type": "regex", "pattern": regex}}
        if llm is not None:
            return {"path": path, "eval": {"type": "llm", "description": llm}}
        return {"path": path, "eval": {"type": "anything"}}

    # ── agents ──

    def _prompt(self, character: Character) -> str:
        return f"{character.prompt}\n\n{self.src.guardrails}"

    def _agent_variables(self, character: Character) -> dict[str, Any]:
        """Placeholders for every variable the agent's prompts, messages or tools use."""
        spec, owner = character.spec, f"character {character.key}"
        texts = (self._prompt(character), *character.phase_prompts.values())
        if TOOL_TOKEN_VARIABLE in _variables(*texts):
            self._error(f"{owner}: prompts must never reference {TOOL_TOKEN_VARIABLE}")
        used = _variables(*texts, spec.first_message, spec.max_duration_message)
        tools = set(spec.tools)
        if spec.workflow:
            tools |= {t for p in spec.workflow.phases.values() for t in p.tools}
        if any(self.src.tools[t].type == "webhook" for t in tools if t in self.src.tools):
            used.add(TOOL_TOKEN_VARIABLE)
        return self._placeholders(used, owner)

    def compile_agent(
        self, character: Character, variables: dict[str, Any], test_ids: list[str]
    ) -> dict[str, Any]:
        spec, owner = character.spec, f"character {character.key}"
        prompt = self._prompt(character)

        tts: dict[str, Any] = {
            "model_id": spec.tts_model,
            "voice_id": self._voice_id(spec.voice, owner),
            "stability": spec.tts_stability,
            "speed": spec.tts_speed,
            "expressive_mode": spec.expressive_mode,
        }
        if spec.panel_voices:
            tts["supported_voices"] = [
                {
                    "label": v.label,
                    "voice_id": self._voice_id(v.voice, owner),
                    "description": v.description,
                }
                for v in spec.panel_voices
            ]

        config: dict[str, Any] = {
            "name": spec.name,
            "tags": ["skill-garden", f"character:{character.key}", *spec.tags],
            "conversation_config": {
                "agent": {
                    "first_message": spec.first_message,
                    "language": "en",
                    "max_conversation_duration_message": spec.max_duration_message,
                    "dynamic_variables": {"dynamic_variable_placeholders": variables},
                    "prompt": {
                        "prompt": prompt,
                        "llm": spec.llm,
                        "temperature": spec.temperature,
                        "ignore_default_personality": True,
                        "tool_ids": self._tool_ids(spec.tools, owner),
                        "built_in_tools": {
                            name: {
                                "type": "system",
                                "name": name,
                                "description": "",
                                "params": {"system_tool_type": name},
                            }
                            for name in spec.system_tools
                        },
                    },
                },
                "tts": tts,
                "turn": {"turn_eagerness": spec.turn_eagerness, "turn_timeout": spec.turn_timeout},
                "conversation": {
                    "max_duration_seconds": spec.max_duration_seconds,
                    "client_events": CLIENT_EVENTS,
                },
            },
            "platform_settings": {
                # Private agents: the browser needs a backend-issued conversation token.
                "auth": {"enable_auth": True},
                # Clients may not override prompts, tools, knowledge base (ADR 0001), voices or
                # limits; per-session context flows only through dynamic variables.
                "overrides": {
                    "conversation_config_override": {
                        "agent": {
                            "first_message": False,
                            "language": False,
                            "prompt": {
                                "prompt": False,
                                "llm": False,
                                "tool_ids": False,
                                "knowledge_base": False,
                            },
                        },
                        "tts": {"voice_id": False, "supported_voices": False},
                        "conversation": {"text_only": False, "max_duration_seconds": False},
                    }
                },
                "data_collection": {
                    name: {"type": f.type, "description": f.description}
                    | ({"enum": f.enum} if f.enum else {})
                    for name, f in spec.data_collection.items()
                },
                "evaluation": {
                    "criteria": [
                        {
                            "id": c.id,
                            "name": c.name,
                            "type": "prompt",
                            "conversation_goal_prompt": c.goal,
                        }
                        for c in spec.evaluation
                    ]
                },
                "privacy": {"record_voice": spec.record_voice},
                "testing": {"attached_tests": [{"test_id": t} for t in test_ids]},
            },
        }
        if spec.workflow:
            config["workflow"] = self._workflow(character)
        return config

    def _workflow(self, character: Character) -> dict[str, Any]:
        workflow = character.spec.workflow
        assert workflow is not None
        edges: dict[str, Any] = {}
        order: dict[str, list[str]] = {"start": [], **{k: [] for k in workflow.phases}}
        for edge in workflow.edges:
            edge_id = f"{edge.source}__{edge.target}"
            condition: dict[str, Any] = (
                {"type": "llm", "condition": edge.when, "label": edge.label or edge.when[:40]}
                if edge.when
                else {"type": "unconditional", "label": edge.label}
            )
            edges[edge_id] = {
                "source": edge.source,
                "target": edge.target,
                "forward_condition": condition,
            }
            order[edge.source].append(edge_id)

        nodes: dict[str, Any] = {
            "start": {"type": "start", "position": {"x": 0, "y": 0}, "edge_order": order["start"]}
        }
        for i, (key, phase) in enumerate(workflow.phases.items(), start=1):
            node: dict[str, Any] = {
                "type": "override_agent",
                "label": phase.label,
                "position": {"x": 320 * i, "y": 0},
                "edge_order": order[key],
                "entry_behavior": phase.entry_behavior,
                "additional_prompt": character.phase_prompts[key],
                "additional_tool_ids": self._tool_ids(phase.tools, f"{character.key}.{key}"),
                "additional_knowledge_base": [],
            }
            if phase.turn_eagerness:
                node["conversation_config"] = {"turn": {"turn_eagerness": phase.turn_eagerness}}
            nodes[key] = node
        return {"nodes": nodes, "edges": edges, "prevent_subagent_loops": False}

    # ── whole build ──

    def build(self) -> BuildResult:
        files = self.result.files
        tools_registry = []
        for name, tool in self.src.tools.items():
            path = f"tool_configs/{name}.json"
            config = self.compile_tool(tool)
            self._validate("tool", path, config)
            files[Path(path)] = _dump(config)
            tools_registry.append(
                self.registries["tools"].get(path, {}) | {"type": tool.type, "config": path}
            )

        tests_registry, agents_registry = [], []
        for key, character in self.src.characters.items():
            variables = self._agent_variables(character)
            test_ids = []
            for test_key, test in character.tests.items():
                path = f"test_configs/{key}/{test_key}.json"
                config = self.compile_test(character, test_key, test, variables)
                self._validate("test", path, config)
                files[Path(path)] = _dump(config)
                tests_registry.append(
                    self.registries["tests"].get(path, {}) | {"type": test.type, "config": path}
                )
                test_id = self._remote_id("tests", path, f"test {key}/{test_key}")
                if test_id:
                    test_ids.append(test_id)

            path = f"agent_configs/{key}.json"
            config = self.compile_agent(character, variables, test_ids)
            self._validate("agent", path, config)
            files[Path(path)] = _dump(config)
            agents_registry.append(self.registries["agents"].get(path, {}) | {"config": path})

        files[Path("tools.json")] = _dump({"tools": tools_registry})
        files[Path("tests.json")] = _dump({"tests": tests_registry})
        files[Path("agents.json")] = _dump({"agents": agents_registry})

        for name in set(self.voice_ids) - set(self.src.voices.voices):
            self._error(f"voices.json: {name!r} has no design in voices.yaml")
        return self.result


def build(root: Path, environment: str | None = None) -> BuildResult:
    sources = load_sources(root)
    return Compiler(sources, environment or sources.environments.default).build()


def agent_ids(root: Path) -> dict[str, str]:
    """Character key -> ElevenLabs agent ID, from the CLI registry (only pushed agents)."""
    registry = _read_json(root / "agents.json", {"agents": []})["agents"]
    return {Path(entry["config"]).stem: entry["id"] for entry in registry if entry.get("id")}


def unregistered(root: Path) -> list[str]:
    """Configs a push would create because their registry entry has no remote ID yet."""
    result = build(root)
    registries = {
        name: json.loads(result.files[Path(f"{name}.json")])
        for name in ("agents", "tools", "tests")
    }
    return [
        entry["config"]
        for name, registry in registries.items()
        for entry in registry[name]
        if not entry.get("id")
    ]
