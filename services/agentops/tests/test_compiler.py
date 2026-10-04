import json
import shutil
from pathlib import Path

import pytest

from sg_agentops import compiler, schema

REPO_AGENTS = Path(__file__).resolve().parents[3] / "agents"


@pytest.fixture
def agents(tmp_path: Path) -> Path:
    """A scratch copy of the real agents/ sources."""
    root = tmp_path / "agents"
    shutil.copytree(REPO_AGENTS, root, ignore=shutil.ignore_patterns(".voice-previews", ".env"))
    return root


def _json(path: Path) -> dict:  # type: ignore[type-arg]
    return json.loads(path.read_text())


def test_committed_configs_are_valid_and_up_to_date() -> None:
    result = compiler.build(REPO_AGENTS)
    assert result.errors == []
    assert result.drift(REPO_AGENTS) == [], "run `uv run sg-agents build` and commit the result"


def test_every_character_has_a_designed_voice_and_tests() -> None:
    result = compiler.build(REPO_AGENTS)
    configs = [p for p in result.files if p.parts[0] == "agent_configs"]
    assert len(configs) == 8
    tests = {p.parts[1] for p in result.files if p.parts[0] == "test_configs"}
    assert tests == {p.stem for p in configs}


def test_schema_rejects_unknown_keys_and_bad_enums() -> None:
    config = _json(REPO_AGENTS / "agent_configs" / "drona.json")
    config["conversation_config"]["turn"]["turn_eagernes"] = "patient"
    config["conversation_config"]["tts"]["model_id"] = "eleven_bogus"
    errors = schema.validate("agent", config)
    assert any("turn_eagernes" in e for e in errors)
    assert any("eleven_bogus" in e for e in errors)


def test_registry_ids_resolve_into_agents_tools_and_tests(agents: Path) -> None:
    tools = _json(agents / "tools.json")
    for entry in tools["tools"]:
        entry["id"] = f"tool_{Path(entry['config']).stem}"
    (agents / "tools.json").write_text(json.dumps(tools))
    tests = _json(agents / "tests.json")
    for entry in tests["tests"]:
        entry["id"] = f"test_{Path(entry['config']).stem}"
    (agents / "tests.json").write_text(json.dumps(tests))
    voices = {"voices": {k: {"voice_id": f"voice_{k}"} for k in ("drona", "arjuna", "vidura")}}
    (agents / "voices.json").write_text(json.dumps(voices))

    result = compiler.build(agents)
    assert result.errors == []
    result.write(agents)

    drona = _json(agents / "agent_configs" / "drona.json")
    prompt = drona["conversation_config"]["agent"]["prompt"]
    assert "tool_record_observation" in prompt["tool_ids"]
    assert drona["conversation_config"]["tts"]["voice_id"] == "voice_drona"
    teach = drona["workflow"]["nodes"]["teach"]
    assert teach["additional_tool_ids"] == ["tool_show_diagram"]
    attached = {t["test_id"] for t in drona["platform_settings"]["testing"]["attached_tests"]}
    assert "test_teach_back" in attached

    panel = _json(agents / "agent_configs" / "panel.json")
    labels = {
        v["label"]: v["voice_id"] for v in panel["conversation_config"]["tts"]["supported_voices"]
    }
    assert labels == {"Arjuna": "voice_arjuna", "Vidura": "voice_vidura"}

    tool_test = _json(agents / "test_configs" / "drona" / "records_observation.json")
    assert tool_test["tool_call_parameters"]["referenced_tool"]["id"] == "tool_record_observation"

    # Registry IDs survive a rebuild.
    assert compiler.build(agents).drift(agents) == []


def test_unresolved_ids_are_pending_not_errors() -> None:
    result = compiler.build(REPO_AGENTS)
    assert any("voice drona" in u for u in result.unresolved)


def test_server_tools_authenticate_with_secret_token_and_bind_conversation() -> None:
    tool = _json(REPO_AGENTS / "tool_configs" / "record_observation.json")
    api = tool["api_schema"]
    assert api["request_headers"] == {"X-SG-Tool-Token": {"variable_name": "secret__sg_tool_token"}}
    body = api["request_body_schema"]
    assert body["properties"]["conversation_id"] == {
        "type": "string",
        "dynamic_variable": "system__conversation_id",
    }
    assert "conversation_id" in body["required"]


def test_agents_are_private_and_not_overridable() -> None:
    for path in (REPO_AGENTS / "agent_configs").glob("*.json"):
        config = _json(path)
        settings = config["platform_settings"]
        assert settings["auth"]["enable_auth"] is True, path.name
        override = settings["overrides"]["conversation_config_override"]
        assert not any(override["agent"]["prompt"].values()), path.name
        assert override["agent"]["prompt"]["knowledge_base"] is False, path.name
        assert not any(override["tts"].values()), path.name
        prompt = config["conversation_config"]["agent"]["prompt"]["prompt"]
        assert "secret__" not in prompt, path.name


def test_unknown_tool_reference_is_an_error(agents: Path) -> None:
    spec = agents / "characters" / "bhima" / "agent.yaml"
    spec.write_text(spec.read_text().replace("tools: [get_briefing,", "tools: [no_such_tool,"))
    result = compiler.build(agents)
    assert any("unknown tool 'no_such_tool'" in e for e in result.errors)


def test_undeclared_dynamic_variable_is_an_error(agents: Path) -> None:
    prompt = agents / "characters" / "sanjaya" / "prompt.md"
    prompt.write_text(prompt.read_text() + "\nFavourite colour: {{favourite_colour}}\n")
    result = compiler.build(agents)
    assert any("favourite_colour" in e for e in result.errors)


def test_prompts_may_not_reference_the_tool_token(agents: Path) -> None:
    prompt = agents / "characters" / "drona" / "prompt.md"
    prompt.write_text(prompt.read_text() + "\nToken: {{secret__sg_tool_token}}\n")
    result = compiler.build(agents)
    assert any("must never reference" in e for e in result.errors)


def test_stale_generated_files_are_reported_and_removed(agents: Path) -> None:
    stale = agents / "agent_configs" / "retired.json"
    stale.write_text("{}")
    result = compiler.build(agents)
    assert Path("agent_configs/retired.json") in result.drift(agents)
    result.write(agents)
    assert not stale.exists()


def test_unregistered_lists_configs_without_remote_ids() -> None:
    pending = compiler.unregistered(REPO_AGENTS)
    assert "agent_configs/drona.json" in pending
    assert "tool_configs/record_observation.json" in pending
