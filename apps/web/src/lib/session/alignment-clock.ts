/**
 * Maps ElevenLabs `onAudioAlignment` chunks onto the lip-sync driver's utterance clock.
 *
 * Alignment times are relative to each audio chunk. `LipSyncDriver.pushAlignment(a, audioStartMs)`
 * wants the offset of the chunk's start from the start of the utterance, which we take as the
 * arrival time of the chunk minus the arrival time of the utterance's first chunk. Over WebRTC
 * chunks arrive close to playback, which ADR 0003's live check measures. Call `reset()` on
 * interruption and when the agent stops speaking.
 */
export class AlignmentClock {
  private first: number | null = null;

  constructor(private readonly now: () => number = () => performance.now()) {}

  /** `audioStartMs` for a chunk that just arrived. */
  offsetForChunk(): number {
    const t = this.now();
    if (this.first === null) this.first = t;
    return Math.max(0, t - this.first);
  }

  reset(): void {
    this.first = null;
  }
}
