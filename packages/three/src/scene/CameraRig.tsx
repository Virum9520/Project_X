"use client";

import { CameraControls } from "@react-three/drei";
import { useFrame } from "@react-three/fiber";
import { useEffect, useRef } from "react";

import type { GardenLayout } from "../generator/layout";
import type { PlantGrowth } from "../model/growth";
import { focusToString } from "../model/navigation";
import type { GardenFocus } from "../model/types";
import { framingFor } from "./framing";

/** Seconds of no input before the overview starts slowly circling the island. */
const IDLE_SECONDS = 8;

/** Smooth camera flights between zoom levels, built on camera-controls. */
export function CameraRig({
  layout,
  focus,
  growthOf,
  autoRotate,
}: {
  layout: GardenLayout;
  focus: GardenFocus;
  growthOf: (conceptId: string) => PlantGrowth | undefined;
  autoRotate: boolean;
}) {
  const controls = useRef<CameraControls>(null);
  const firstFlight = useRef(true);
  const idleSince = useRef(0);
  // Fly on focus changes only; new revisions should not yank the camera around.
  const growthRef = useRef(growthOf);
  growthRef.current = growthOf;
  const key = focusToString(focus);

  useEffect(() => {
    const c = controls.current;
    if (!c) return;
    const { position, target } = framingFor(focus, layout, growthRef.current);
    void c.setLookAt(
      position.x,
      position.y,
      position.z,
      target.x,
      target.y,
      target.z,
      !firstFlight.current,
    );
    firstFlight.current = false;
    idleSince.current = performance.now();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, layout]);

  useFrame((_, delta) => {
    const c = controls.current;
    if (!c || !autoRotate || focus.level !== "garden") return;
    if (performance.now() - idleSince.current > IDLE_SECONDS * 1000) {
      void c.rotate(delta * 0.04, 0, false);
    }
  });

  const R = layout.islandRadius;
  return (
    <CameraControls
      ref={controls}
      makeDefault
      smoothTime={0.6}
      draggingSmoothTime={0.15}
      minDistance={0.6}
      maxDistance={R * 3.4}
      maxPolarAngle={Math.PI * 0.48}
      onStart={() => {
        idleSince.current = Number.POSITIVE_INFINITY;
      }}
      onEnd={() => {
        idleSince.current = performance.now();
      }}
    />
  );
}
