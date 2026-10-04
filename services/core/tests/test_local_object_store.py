from pathlib import Path

import pytest

from sg_core.providers.storage import LocalFileObjectStore, ObjectNotFoundError


async def test_roundtrip_list_delete(tmp_path: Path) -> None:
    store = LocalFileObjectStore(tmp_path)
    await store.put("voice-consents/u/a.webm", b"abc", content_type="audio/webm")
    assert await store.exists("voice-consents/u/a.webm")
    got = await store.get("voice-consents/u/a.webm")
    assert got.data == b"abc" and got.content_type == "audio/webm"
    assert await store.list_keys("voice-consents/") == ["voice-consents/u/a.webm"]
    await store.delete("voice-consents/u/a.webm")
    assert not await store.exists("voice-consents/u/a.webm")
    with pytest.raises(ObjectNotFoundError):
        await store.get("voice-consents/u/a.webm")
    await store.delete("voice-consents/u/a.webm")  # idempotent


async def test_keys_cannot_escape_the_root(tmp_path: Path) -> None:
    store = LocalFileObjectStore(tmp_path / "root")
    with pytest.raises(ValueError):
        await store.put("../outside.txt", b"x")
