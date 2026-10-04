"use client";

import { useFrame } from "@react-three/fiber";
import { useCallback, useLayoutEffect, useRef, type ReactNode } from "react";
import * as THREE from "three";

/**
 * Screen-space HTML anchored to 3D points. The HTML lives in the page's own React tree (outside
 * the Canvas); a projector inside the Canvas writes each element's transform every frame. This
 * avoids one React root per label and keeps labels styleable and accessible like normal DOM.
 */

export interface OverlayAnchor {
  /** World position, or a function of elapsed seconds for moving anchors (orbiting cards). */
  position: THREE.Vector3 | ((elapsed: number) => THREE.Vector3);
  /** Extra screen-space offset in CSS pixels. */
  offset?: readonly [number, number];
}

interface Entry {
  anchor: OverlayAnchor;
  element: HTMLElement | null;
}

export type OverlayRegistry = Map<string, Entry>;

export function createOverlayRegistry(): OverlayRegistry {
  return new Map();
}

const projected = new THREE.Vector3();

/** Mount inside the Canvas. */
export function OverlayProjector({ registry }: { registry: OverlayRegistry }) {
  useFrame(({ camera, size, clock }) => {
    for (const entry of registry.values()) {
      const element = entry.element;
      if (!element) continue;
      const { position, offset = [0, 0] } = entry.anchor;
      projected.copy(typeof position === "function" ? position(clock.elapsedTime) : position);
      projected.project(camera);
      const visible =
        projected.z < 1 && Math.abs(projected.x) < 1.15 && Math.abs(projected.y) < 1.15;
      const x = (projected.x * 0.5 + 0.5) * size.width + offset[0];
      const y = (-projected.y * 0.5 + 0.5) * size.height + offset[1];
      element.style.transform = `translate3d(${x.toFixed(1)}px, ${y.toFixed(1)}px, 0) translate(-50%, -50%)`;
      element.style.visibility = visible ? "visible" : "hidden";
      // Nearer labels stack above farther ones.
      element.style.zIndex = String(Math.round((1 - projected.z) * 10000));
    }
  });
  return null;
}

/** Mount outside the Canvas, inside a positioned container. */
export function OverlayItem({
  registry,
  id,
  anchor,
  children,
}: {
  registry: OverlayRegistry;
  id: string;
  anchor: OverlayAnchor;
  children: ReactNode;
}) {
  const element = useRef<HTMLDivElement | null>(null);
  useLayoutEffect(() => {
    registry.set(id, { anchor, element: element.current });
  });
  useLayoutEffect(() => () => void registry.delete(id), [registry, id]);
  const ref = useCallback((node: HTMLDivElement | null) => {
    element.current = node;
  }, []);
  return (
    <div
      ref={ref}
      style={{
        position: "absolute",
        left: 0,
        top: 0,
        visibility: "hidden",
        pointerEvents: "auto",
        willChange: "transform",
      }}
    >
      {children}
    </div>
  );
}
