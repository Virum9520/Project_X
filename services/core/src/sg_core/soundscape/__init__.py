"""Living soundscape (C20): asset catalogue, generation, manifest."""

from sg_core.soundscape.catalog import (
    ASSET_VERSION,
    MOODS,
    SEASONS,
    SFX_NAMES,
    AssetSpec,
    all_specs,
    music_specs,
    sfx_specs,
)
from sg_core.soundscape.generate import (
    GenerationReport,
    generate_assets,
    load_manifest,
    write_manifest,
)

__all__ = [
    "ASSET_VERSION",
    "MOODS",
    "SEASONS",
    "SFX_NAMES",
    "AssetSpec",
    "GenerationReport",
    "all_specs",
    "generate_assets",
    "load_manifest",
    "music_specs",
    "sfx_specs",
    "write_manifest",
]
