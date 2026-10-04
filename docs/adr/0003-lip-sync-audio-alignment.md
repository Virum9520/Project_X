# ADR 0003: Lip-sync from audio alignment (spike c)

- Status: Accepted, live check pending
- Date: 2026-10-04
- Component: C06 (decision), C15 (implementation)

## Context
VRM avatars must lip-sync to live agent speech. ElevenLabs offers character alignment for agent
audio; the JS SDK also exposes output frequency data.

## Findings
- `@elevenlabs/client` and `@elevenlabs/react` expose `onAudioAlignment(alignment)` with
  `{ chars: string[], char_start_times_ms: number[], char_durations_ms: number[] }`.
- On the wire, alignment travels inside the `audio` client event (`audio_event.alignment`). There
  is no separate event to enable; `audio` is in every agent's `client_events` (see
  `CLIENT_EVENTS` in `sg_agentops.compiler`).
- Over WebRTC, alignment works only from `@elevenlabs/client` 1.15.2. Audio bytes travel on
  LiveKit tracks and alignment arrives as JSON on the data channel, with timings relative to each
  chunk.
- `getOutputByteFrequencyData()` and `getOutputVolume()` work for voice sessions (WebRTC audio is
  fixed at 48 kHz PCM).

## Decision
- Primary: map alignment characters to visemes (a small grapheme-to-viseme table, with
  co-articulation smoothing) and schedule them against the audio clock from the moment each chunk
  starts playing.
- Fallback: if alignment is missing or drifts more than 80 ms, drive mouth openness from
  `getOutputVolume()` / frequency bands.
- Pin `@elevenlabs/react` at 1.16 or later (C12 and C15 add it to `apps/web`).
- Sanjaya recaps (C20) use TTS-with-timestamps, which returns the same alignment shape, so one
  viseme mapper serves both.

## Live check (needs API key)
Build a dev page in C15 that logs alignment chunk arrival times against the playback clock for 20
utterances. Accept if the median offset is under 40 ms and the 95th percentile under 80 ms.
