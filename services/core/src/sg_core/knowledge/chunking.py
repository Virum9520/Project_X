"""Split extracted pages into overlapping, page-attributed chunks for embedding.

Chunks end at sentence or paragraph boundaries where possible, target about `TARGET_CHARS`
characters (roughly 350 tokens), and repeat the tail of the previous chunk (`OVERLAP_CHARS`) so
an answer that straddles a boundary is still retrievable. Each chunk records the first and last
page it draws from. Pure and deterministic.
"""

import re
from dataclasses import dataclass

from sg_core.knowledge.extract import Page

TARGET_CHARS = 1400
MAX_CHARS = 2000
OVERLAP_CHARS = 200

_SENTENCE_END = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"'(\[])")


@dataclass(frozen=True, slots=True)
class TextChunk:
    ordinal: int
    content: str
    page_start: int
    page_end: int

    @property
    def token_count(self) -> int:
        return estimate_tokens(self.content)


def estimate_tokens(text: str) -> int:
    """Cheap token estimate (about four characters per token)."""
    return max(1, (len(text) + 3) // 4)


@dataclass(frozen=True, slots=True)
class _Unit:
    text: str
    page: int


def _units(pages: list[Page]) -> list[_Unit]:
    units: list[_Unit] = []
    for page in pages:
        for paragraph in re.split(r"\n\s*\n", page.text):
            paragraph = paragraph.strip()
            if not paragraph:
                continue
            for sentence in _SENTENCE_END.split(paragraph):
                sentence = sentence.strip()
                while len(sentence) > MAX_CHARS:  # no punctuation: hard split on whitespace
                    cut = sentence.rfind(" ", 0, TARGET_CHARS)
                    cut = cut if cut > 0 else TARGET_CHARS
                    units.append(_Unit(sentence[:cut].strip(), page.number))
                    sentence = sentence[cut:].strip()
                if sentence:
                    units.append(_Unit(sentence, page.number))
    return units


def _overlap(units: list[_Unit]) -> list[_Unit]:
    """Trailing units (up to OVERLAP_CHARS of text) to repeat at the start of the next chunk."""
    carried: list[_Unit] = []
    total = 0
    for unit in reversed(units):
        if len(unit.text) > OVERLAP_CHARS or total + len(unit.text) > OVERLAP_CHARS:
            break
        carried.insert(0, unit)
        total += len(unit.text) + 1
    return carried


def chunk_pages(pages: list[Page]) -> list[TextChunk]:
    chunks: list[TextChunk] = []
    current: list[_Unit] = []
    fresh = 0  # units in `current` that are not overlap carried from the previous chunk
    size = 0

    def emit() -> None:
        content = " ".join(u.text for u in current)
        chunks.append(TextChunk(len(chunks), content, current[0].page, current[-1].page))

    for unit in _units(pages):
        if fresh and size + len(unit.text) + 1 > TARGET_CHARS:
            emit()
            current = _overlap(current)
            fresh = 0
            size = sum(len(u.text) + 1 for u in current)
        current.append(unit)
        fresh += 1
        size += len(unit.text) + 1
    if fresh:
        emit()
    return chunks
