/**
 * Turn-aware camera cuts for the Panel. The shot follows the speaker: a close shot on the
 * interviewer who is talking, a wide shot of both while the candidate answers. Cuts respect a
 * minimum dwell so quick back-and-forth never flickers; a cut that arrives too early is held as
 * `pending` and applied by `tick`.
 */
import type { PanelSpeaker } from "./speaker";

export type Shot = "wide" | PanelSpeaker;

export const MIN_DWELL_MS = 1500;

export interface DirectorState {
  shot: Shot;
  since: number;
  pending: Shot | null;
}

export const INITIAL_DIRECTOR: DirectorState = { shot: "wide", since: 0, pending: null };

export type DirectorEvent =
  | { type: "agent_speaking"; speaker: PanelSpeaker; now: number }
  | { type: "candidate_turn"; now: number }
  | { type: "tick"; now: number }
  | { type: "reset" };

function cut(state: DirectorState, target: Shot, now: number): DirectorState {
  if (target === state.shot) return state.pending ? { ...state, pending: null } : state;
  if (now - state.since >= MIN_DWELL_MS) return { shot: target, since: now, pending: null };
  return state.pending === target ? state : { ...state, pending: target };
}

export function directorReducer(state: DirectorState, event: DirectorEvent): DirectorState {
  switch (event.type) {
    case "agent_speaking":
      return cut(state, event.speaker, event.now);
    case "candidate_turn":
      return cut(state, "wide", event.now);
    case "tick":
      return state.pending ? cut(state, state.pending, event.now) : state;
    case "reset":
      return INITIAL_DIRECTOR;
  }
}

/** Relative width of `speaker`'s avatar column in the given shot. */
export function shotWeight(shot: Shot, speaker: PanelSpeaker): number {
  if (shot === "wide") return 1;
  return shot === speaker ? 1.8 : 0.6;
}
