"""Turn spoken-character timing into per-segment camera keyframes.

ElevenLabs `with-timestamps` returns a start and end time for every character of the text it
spoke. The narration offsets in `Segment` index into that, so the camera can arrive at a plant the
moment Sanjaya starts talking about it. When the alignment is missing or its length does not match
the narration (the vendor normalised the text), timing falls back to a proportional estimate over
the audio duration, and with no audio at all to a reading-speed estimate.
"""

from dataclasses import dataclass

from sg_api.recap.script import RecapScript
from sg_core.providers.elevenlabs import CharacterAlignment

READING_CHARS_PER_SECOND = 14.0  # about 170 words per minute of narration
MIN_SEGMENT_MS = 600


@dataclass(frozen=True, slots=True)
class Keyframe:
    segment_id: str
    focus: str
    start_ms: int
    end_ms: int


def _ms(seconds: float) -> int:
    return max(0, round(seconds * 1000))


def keyframes(
    script: RecapScript,
    alignment: CharacterAlignment | None = None,
    *,
    duration_seconds: float | None = None,
) -> tuple[list[Keyframe], int, str]:
    """Returns (keyframes, total duration ms, timing source: aligned | proportional | estimated)."""
    total_chars = max(1, len(script.narration))
    exact = (
        alignment is not None
        and len(alignment.characters) == len(script.narration)
        and len(alignment.start_times) == len(alignment.end_times) == len(script.narration)
        and bool(script.narration)
    )
    if exact and alignment is not None:
        starts = [alignment.start_times[s.start_char] for s in script.segments]
        ends = [alignment.end_times[max(s.start_char, s.end_char - 1)] for s in script.segments]
        source = "aligned"
    else:
        if alignment is not None and alignment.end_times:
            duration_seconds = duration_seconds or max(alignment.end_times)
            source = "proportional"
        elif duration_seconds:
            source = "proportional"
        else:
            source = "estimated"
        total_s = duration_seconds or total_chars / READING_CHARS_PER_SECOND
        starts = [total_s * s.start_char / total_chars for s in script.segments]
        ends = [total_s * s.end_char / total_chars for s in script.segments]

    frames: list[Keyframe] = []
    previous_end = 0
    for seg, a, b in zip(script.segments, starts, ends, strict=True):
        start = max(previous_end, _ms(a))
        end = max(start + MIN_SEGMENT_MS, _ms(b))
        frames.append(Keyframe(seg.id, seg.focus, start, end))
        previous_end = end
    return frames, (frames[-1].end_ms if frames else 0), source
