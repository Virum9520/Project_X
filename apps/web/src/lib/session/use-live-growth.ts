"use client";

import type { LiveGrowthEvent } from "@sg/contracts";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { activePulses, parseGrowthEvent, pulses } from "./growth-sse";

/** A plant keeps glowing this long after its last growth event. */
export const LIVE_PULSE_MS = 9000;

/**
 * Subscribes to the learner's live growth stream (`/api/live/growth`, proxied to
 * `GET /v1/live/growth`). Every open tab of the learner gets the same events, so the dashboard
 * glows while a voice session runs elsewhere. EventSource reconnects by itself and resumes from
 * `Last-Event-ID`.
 *
 * `pulseConceptIds` feeds `GardenScene`'s `pulseConceptIds` (through the dashboard's
 * `recentGrowthPlantKeys`); `onEvent` receives every event, for the evidence ticker.
 */
export function useLiveGrowth(
  options: { enabled?: boolean; onEvent?: (e: LiveGrowthEvent) => void } = {},
) {
  const { enabled = true } = options;
  const [lastPulse, setLastPulse] = useState<ReadonlyMap<string, number>>(new Map());
  const [now, setNow] = useState(0);
  const [connected, setConnected] = useState(false);
  const onEvent = useRef(options.onEvent);
  useEffect(() => {
    onEvent.current = options.onEvent;
  });

  const receive = useCallback((data: string) => {
    const event = parseGrowthEvent(data);
    if (!event) return;
    onEvent.current?.(event);
    if (!pulses(event)) return;
    const at = Date.now();
    setNow(at);
    setLastPulse((prev) => new Map(prev).set(event.conceptId, at));
    // Re-render once the glow is due to end.
    window.setTimeout(() => setNow(Date.now()), LIVE_PULSE_MS + 50);
  }, []);

  useEffect(() => {
    if (!enabled || typeof EventSource === "undefined") return;
    const source = new EventSource("/api/live/growth");
    source.onopen = () => setConnected(true);
    source.onerror = () => setConnected(false);
    source.addEventListener("growth", (e) => receive((e as MessageEvent<string>).data));
    return () => {
      source.close();
      setConnected(false);
    };
  }, [enabled, receive]);

  const pulseConceptIds = useMemo(
    () => activePulses(lastPulse, now, LIVE_PULSE_MS),
    [lastPulse, now],
  );
  return { connected, pulseConceptIds };
}
