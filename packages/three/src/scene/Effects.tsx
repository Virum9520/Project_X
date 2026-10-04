"use client";

import { useFrame } from "@react-three/fiber";
import {
  Bloom,
  DepthOfField,
  EffectComposer,
  ToneMapping,
  Vignette,
} from "@react-three/postprocessing";
import type { DepthOfFieldEffect } from "postprocessing";
import { ToneMappingMode } from "postprocessing";
import { useRef } from "react";
import * as THREE from "three";

/**
 * Bloom for emissive (> 1) growth, roots and fireflies, plus depth of field that fades in at
 * Plant and Part zoom so the focused plant pops.
 */
export function Effects({
  focusTarget,
  depthOfField,
}: {
  focusTarget: THREE.Vector3;
  depthOfField: boolean;
}) {
  const dof = useRef<DepthOfFieldEffect>(null);
  useFrame((_, delta) => {
    const effect = dof.current;
    if (!effect) return;
    if (!effect.target) effect.target = new THREE.Vector3();
    effect.target.lerp(focusTarget, 1 - Math.exp(-4 * Math.min(delta, 0.1)));
    effect.bokehScale = THREE.MathUtils.damp(
      effect.bokehScale,
      depthOfField ? 2.2 : 0,
      3,
      Math.min(delta, 0.1),
    );
  });
  return (
    <EffectComposer multisampling={4}>
      <DepthOfField ref={dof} worldFocusRange={2.2} bokehScale={0} />
      <Bloom
        mipmapBlur
        luminanceThreshold={1}
        luminanceSmoothing={0.2}
        intensity={0.9}
        radius={0.7}
      />
      <Vignette offset={0.25} darkness={0.55} />
      <ToneMapping mode={ToneMappingMode.ACES_FILMIC} />
    </EffectComposer>
  );
}
