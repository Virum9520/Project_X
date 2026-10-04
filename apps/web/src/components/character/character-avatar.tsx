"use client";

import type { Character } from "@sg/contracts";
import type { LipSyncDriver } from "@sg/three/avatar";
import { useEffect, useRef } from "react";

export const CHARACTER_META: Record<Character, { name: string; role: string; ring: string }> = {
  drona: { name: "Drona", role: "Teacher", ring: "#ffcf70" },
  arjuna: { name: "Arjuna", role: "Technical interviewer", ring: "#4fd1a1" },
  vidura: { name: "Vidura", role: "HR interviewer", ring: "#b99cf5" },
  bhima: { name: "Bhima", role: "Accountability", ring: "#ff8a5c" },
  krishna: { name: "Krishna", role: "Future self", ring: "#7bd0e6" },
  sanjaya: { name: "Sanjaya", role: "Recap narrator", ring: "#ff9ec7" },
};

/**
 * A character portrait in a circle that breathes (expands and contracts) at rest and swells with
 * the voice while speaking. Pass a lip-sync `driver` for per-frame amplitude, or `speaking` for a
 * steady pulse. Decorative: the name is exposed through `label`.
 */
export function CharacterAvatar({
  character,
  size = 160,
  speaking = false,
  driver,
  className = "",
}: {
  character: Character;
  size?: number;
  speaking?: boolean;
  driver?: LipSyncDriver;
  className?: string;
}) {
  const circle = useRef<HTMLDivElement>(null);
  const meta = CHARACTER_META[character];
  const live = speaking;

  useEffect(() => {
    const el = circle.current;
    if (!el) return;
    if (!driver && !live) {
      el.style.transform = "";
      return;
    }
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    let raf = 0;
    let last = performance.now();
    let amp = 0;
    const tick = (now: number) => {
      const dt = Math.min(0.1, (now - last) / 1000);
      last = now;
      let target = 0;
      if (driver) {
        const m = driver.frame(now, dt).mouth;
        target = Math.min(1, Math.max(...Object.values(m)) * 1.1);
      } else {
        target = 0.45 + 0.35 * Math.sin(now / 140);
      }
      amp += (target - amp) * Math.min(1, dt * 14);
      el.style.transform = `scale(${(0.97 + amp * 0.13).toFixed(3)})`;
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [driver, live]);

  return (
    <div
      className={`relative grid shrink-0 place-items-center ${className}`}
      style={{ width: size, height: size }}
      role="img"
      aria-label={meta.name}
    >
      <span
        aria-hidden
        className="avatar-ripple absolute inset-0 rounded-full"
        style={{
          boxShadow: `0 0 0 3px ${meta.ring}`,
          animationDuration: speaking ? "1.1s" : "2.8s",
        }}
      />
      <div
        ref={circle}
        className={`size-[88%] overflow-hidden rounded-full ${driver || live ? "" : "avatar-breathe"}`}
        style={{
          boxShadow: `0 0 0 3px ${meta.ring}, 0 12px 40px -8px ${meta.ring}66`,
          willChange: "transform",
        }}
      >
        {/* eslint-disable-next-line @next/next/no-img-element -- small static portraits */}
        <img
          src={`/characters/${character}.png`}
          alt=""
          draggable={false}
          className="size-full object-cover"
        />
      </div>
    </div>
  );
}
