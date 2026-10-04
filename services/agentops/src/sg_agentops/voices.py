"""Voice Design: generate previews per character, then save the chosen one as a voice.

Previews land in `agents/.voice-previews/<key>/` (gitignored) for listening, with a
`previews.json` manifest. Creating a voice records its ID in `agents/voices.json`, which the
compiler reads; the design inputs (seed, model, prompt hash) are stored alongside so a voice can
be traced back to the prompt that produced it.
"""

import base64
import hashlib
import json
from pathlib import Path
from typing import Any

from sg_agentops.sources import VoiceDesign, load_sources
from sg_core.providers.elevenlabs import client_from_settings


def _prompt_hash(design: VoiceDesign) -> str:
    raw = f"{design.model_id}|{design.seed}|{design.description}|{design.preview_text}"
    return hashlib.sha256(raw.encode()).hexdigest()[:12]


def _previews_dir(root: Path, key: str) -> Path:
    return root / ".voice-previews" / key


async def design(root: Path, keys: list[str] | None) -> None:
    designs = load_sources(root).voices.voices
    selected = keys or list(designs)
    unknown = set(selected) - set(designs)
    if unknown:
        raise SystemExit(f"error: unknown voices {sorted(unknown)}")

    async with client_from_settings() as client:
        for key in selected:
            d = designs[key]
            result = await client.design_voice(
                voice_description=d.description,
                text=d.preview_text,
                model_id=d.model_id,
                guidance_scale=d.guidance_scale,
                loudness=d.loudness,
                seed=d.seed,
            )
            out = _previews_dir(root, key)
            out.mkdir(parents=True, exist_ok=True)
            manifest: list[dict[str, Any]] = []
            for n, preview in enumerate(result.previews, start=1):
                ext = "mp3" if "mpeg" in preview.media_type else "audio"
                path = out / f"preview-{n}.{ext}"
                path.write_bytes(base64.b64decode(preview.audio_base_64))
                manifest.append(
                    {"n": n, "generated_voice_id": preview.generated_voice_id, "file": path.name}
                )
            (out / "previews.json").write_text(
                json.dumps({"prompt_hash": _prompt_hash(d), "previews": manifest}, indent=2) + "\n"
            )
            print(f"{key}: {len(manifest)} previews in {out.relative_to(root.parent)}")
    print("Listen, then: uv run sg-agents voices create <key> --preview N")


async def create(root: Path, key: str, preview: int) -> None:
    designs = load_sources(root).voices.voices
    if key not in designs:
        raise SystemExit(f"error: unknown voice {key!r}")
    d = designs[key]
    manifest = json.loads((_previews_dir(root, key) / "previews.json").read_text())
    if manifest["prompt_hash"] != _prompt_hash(d):
        raise SystemExit(
            f"error: voices.yaml changed since previews were made; re-run design for {key}"
        )
    chosen = next((p for p in manifest["previews"] if p["n"] == preview), None)
    if chosen is None:
        raise SystemExit(f"error: no preview {preview} for {key}")

    async with client_from_settings() as client:
        voice_id = await client.create_voice_from_preview(
            voice_name=d.name,
            voice_description=d.description,
            generated_voice_id=chosen["generated_voice_id"],
            labels={"app": "skill-garden", "character": key},
        )

    path = root / "voices.json"
    data = json.loads(path.read_text())
    data["voices"][key] = {
        "voice_id": voice_id,
        "name": d.name,
        "model_id": d.model_id,
        "seed": d.seed,
        "prompt_hash": manifest["prompt_hash"],
        "generated_voice_id": chosen["generated_voice_id"],
    }
    path.write_text(json.dumps(data, indent=4, sort_keys=True) + "\n")
    print(f"{key}: voice {voice_id} saved to agents/voices.json; run `uv run sg-agents build`")
