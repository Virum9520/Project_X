"use client";

import { useEffect, useState } from "react";

import { useInView } from "./use-in-view";

/** Counts from zero to `to` with an ease-out once visible. Renders the final value without JS. */
export function CountUp({
  to,
  suffix = "",
  durationMs = 1600,
}: {
  to: number;
  suffix?: string;
  durationMs?: number;
}) {
  const [ref, inView] = useInView<HTMLSpanElement>("0px");
  const [value, setValue] = useState(to);

  useEffect(() => {
    if (!inView || window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    let frame = 0;
    const started = performance.now();
    const tick = (now: number) => {
      const t = Math.min(1, (now - started) / durationMs);
      setValue(Math.round(to * (1 - Math.pow(1 - t, 3))));
      if (t < 1) frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [inView, to, durationMs]);

  return (
    <span ref={ref} aria-label={`${to}${suffix}`}>
      <span aria-hidden>
        {value}
        {suffix}
      </span>
    </span>
  );
}
