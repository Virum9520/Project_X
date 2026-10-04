"""Offline validation of generated configs against the ElevenLabs API schema.

The `elevenlabs` CLI embeds the OpenAPI spec it was generated from. `vendor_schema()` extracts
the closure of the request-body schemas we generate (agent create, tool config, agent test) into
`schema/elevenlabs-convai.schema.json`, so CI can validate every config without network access
or an API key. Refresh it whenever the pinned CLI version changes:

    pnpm exec elevenlabs agents create --spec-raw > /tmp/spec.json
    uv run sg-agents schema refresh /tmp/spec.json
"""

import copy
import json
from functools import cache
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

SCHEMA_PATH = Path(__file__).parent / "schema" / "elevenlabs-convai.schema.json"

# Root schemas for each kind of file we generate.
ROOTS: dict[str, list[str]] = {
    "agent": ["Body_Create_Agent_v1_convai_agents_create_post"],
    "tool": ["WebhookToolConfig-Input", "ClientToolConfig-Input"],
    "test": [
        "CreateResponseUnitTestRequest",
        "CreateToolCallUnitTestRequest",
        "CreateSimulationTestRequest",
    ],
}


def vendor_schema(spec: dict[str, Any]) -> dict[str, Any]:
    """Return the minimal `components.schemas` closure needed to validate our configs."""
    all_schemas: dict[str, Any] = spec["components"]["schemas"]
    seen: set[str] = set()
    missing: set[str] = set()

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            ref = node.get("$ref")
            if isinstance(ref, str):
                name = ref.rsplit("/", 1)[-1]
                if name not in all_schemas:
                    missing.add(name)
                elif name not in seen:
                    seen.add(name)
                    walk(all_schemas[name])
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    for names in ROOTS.values():
        for name in names:
            seen.add(name)
            walk(all_schemas[name])

    schemas = {name: all_schemas[name] for name in sorted(seen)}
    # The upstream spec has a few dangling refs; treat them as unconstrained.
    for name in sorted(missing):
        schemas[name] = {"description": "Dangling upstream $ref; unconstrained."}
    return {
        "info": {"source": spec.get("info", {}).get("title"), "openapi": spec.get("openapi")},
        "components": {"schemas": schemas},
    }


def _strict(node: Any) -> Any:
    """Forbid unknown keys on every object schema that lists its properties.

    Upstream schemas mostly allow extra keys, which would let a typo (`turn_eagernes`) through
    silently. Each `anyOf`/`oneOf` branch is a full object schema, so per-branch strictness keeps
    union semantics intact.
    """
    if isinstance(node, dict):
        out = {key: _strict(value) for key, value in node.items()}
        if "properties" in out and "additionalProperties" not in out:
            out["additionalProperties"] = False
        out.pop("discriminator", None)
        return out
    if isinstance(node, list):
        return [_strict(value) for value in node]
    return node


@cache
def _document() -> dict[str, Any]:
    raw: dict[str, Any] = json.loads(SCHEMA_PATH.read_text())
    return {"components": _strict(copy.deepcopy(raw["components"]))}


def validate(kind: str, config: dict[str, Any]) -> list[str]:
    """Return human-readable schema errors for a generated config (empty when valid)."""
    document = _document()
    branches = [{"$ref": f"#/components/schemas/{name}"} for name in ROOTS[kind]]
    schema = {**document, **(branches[0] if len(branches) == 1 else {"anyOf": branches})}
    if len(branches) > 1:
        # Pick the branch whose `type` discriminator matches, for readable errors.
        wanted = config.get("type")
        for name in ROOTS[kind]:
            props = document["components"]["schemas"][name].get("properties", {})
            if props.get("type", {}).get("const") == wanted:
                schema = {**document, "$ref": f"#/components/schemas/{name}"}
                break
    validator = Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(config), key=lambda e: list(e.absolute_path))
    return [f"{'/'.join(str(p) for p in e.absolute_path) or '<root>'}: {e.message}" for e in errors]
