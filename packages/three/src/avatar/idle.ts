/** Deterministic idle behaviour: blinks and small eye saccades. Pure: you advance it with dt. */

export interface IdleState {
  /** Eyelid closure, 0 (open) to 1 (closed). */
  blink: number;
  /** Gaze offsets, roughly -1..1. */
  lookX: number;
  lookY: number;
}

export interface IdleAnimator {
  update(dtSec: number): IdleState;
}

/** Small seeded PRNG (mulberry32) so tests and replays are reproducible. */
export function mulberry32(seed: number): () => number {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

const BLINK_DURATION = 0.16;

export function createIdleAnimator(seed = 1): IdleAnimator {
  const rand = mulberry32(seed);
  let untilBlink = 1.5 + rand() * 3;
  let blinkT = -1; // < 0 means not blinking
  let untilSaccade = 0.6 + rand() * 1.4;
  let lookX = 0;
  let lookY = 0;
  let targetX = 0;
  let targetY = 0;

  return {
    update(dtSec) {
      const dt = Math.max(0, dtSec);
      if (blinkT >= 0) {
        blinkT += dt;
        if (blinkT >= BLINK_DURATION) {
          blinkT = -1;
          untilBlink = 2 + rand() * 4;
        }
      } else {
        untilBlink -= dt;
        if (untilBlink <= 0) blinkT = 0;
      }
      untilSaccade -= dt;
      if (untilSaccade <= 0) {
        targetX = (rand() - 0.5) * 0.8;
        targetY = (rand() - 0.5) * 0.4;
        untilSaccade = 0.5 + rand() * 2;
      }
      // Saccades are fast: ease most of the way each frame.
      const k = 1 - Math.exp(-dt * 18);
      lookX += (targetX - lookX) * k;
      lookY += (targetY - lookY) * k;
      const blink = blinkT < 0 ? 0 : Math.sin((blinkT / BLINK_DURATION) * Math.PI);
      return { blink, lookX, lookY };
    },
  };
}
