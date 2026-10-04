"use client";

import type { LiveGrowthEvent } from "@sg/contracts";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { activePulses, parseGrowthEvent, pulses } from "@/lib/session/growth-sse";
import { listenGrowth, liveGrowthSupported } from "@/lib/practice/live";

/** A plant keeps glowing this long after its last growth event. */
export const LIVE_PULSE_MS = 9000;

/**
 * Static-site version of the live growth stream: there is no server to stream from, so growth
 * comes from practice sessions in this browser (any tab) over a BroadcastChannel. Same contract
 * as the full app's hook: `pulseConceptIds` for the scene, `onEvent` for every event.
 */
export function useLiveGrowth(
  options: { enabled?: boolean; onEvent?: (e: LiveGrowthEvent) => void } = {},
) {
  const { enabled = true } = options;
  const [lastPulse, setLastPulse] = useState<ReadonlyMap<string, number>>(new Map());
  const [now, setNow] = useState(0);
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
    window.setTimeout(() => setNow(Date.now()), LIVE_PULSE_MS + 50);
  }, []);

  useEffect(() => {
    if (!enabled) return;
    return listenGrowth(receive);
  }, [enabled, receive]);

  const pulseConceptIds = useMemo(
    () => activePulses(lastPulse, now, LIVE_PULSE_MS),
    [lastPulse, now],
  );
  return { connected: enabled && liveGrowthSupported(), pulseConceptIds };
}
