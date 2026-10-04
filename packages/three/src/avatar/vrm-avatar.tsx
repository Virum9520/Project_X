"use client";

import { useFrame } from "@react-three/fiber";
import { VRMLoaderPlugin, VRMUtils, type VRM } from "@pixiv/three-vrm";
import { useEffect, useState } from "react";
import { GLTFLoader } from "three/examples/jsm/loaders/GLTFLoader.js";
import type { LipSyncDriver, LipSyncFrame } from "./lipsync-driver";
import type { AvatarRig } from "./rig";
import { MOUTH_VISEMES } from "./visemes";

const LOOK_RANGE_DEG = 12;

/** Apply a lip-sync frame to a VRM through its expression manager. */
export function createVrmRig(vrm: VRM): AvatarRig {
  return {
    apply(frame: LipSyncFrame, dtSec: number) {
      const expr = vrm.expressionManager;
      if (expr) {
        for (const v of MOUTH_VISEMES) expr.setValue(v, frame.mouth[v]);
        expr.setValue("blink", frame.blink);
      }
      if (vrm.lookAt) {
        vrm.lookAt.yaw = frame.lookX * LOOK_RANGE_DEG;
        vrm.lookAt.pitch = frame.lookY * LOOK_RANGE_DEG;
      }
      vrm.update(dtSec);
    },
  };
}

export interface VrmAvatarProps {
  /** URL of a `.vrm` file (VRM 0.x or 1.0). Must come from a trusted, same-origin or CDN path. */
  url: string;
  driver: LipSyncDriver;
  /** Called if the model cannot be loaded, so the caller can fall back. */
  onError?: (error: unknown) => void;
}

export function VrmAvatar({ url, driver, onError }: VrmAvatarProps) {
  const [vrm, setVrm] = useState<VRM | null>(null);

  useEffect(() => {
    let cancelled = false;
    const loader = new GLTFLoader();
    loader.register((parser) => new VRMLoaderPlugin(parser));
    loader.load(
      url,
      (gltf) => {
        const model = gltf.userData.vrm as VRM | undefined;
        if (!model) {
          onError?.(new Error("File is not a VRM model"));
          return;
        }
        VRMUtils.rotateVRM0(model);
        if (cancelled) {
          VRMUtils.deepDispose(model.scene);
          return;
        }
        setVrm(model);
      },
      undefined,
      (err) => onError?.(err),
    );
    return () => {
      cancelled = true;
      setVrm(null);
    };
    // onError is deliberately not a dependency: reloading the model on every render is wasteful.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [url]);

  // Dispose a model only after it has been replaced (or on unmount), once `<primitive>` no longer
  // renders it.
  useEffect(() => {
    if (!vrm) return;
    return () => VRMUtils.deepDispose(vrm.scene);
  }, [vrm]);

  useFrame((_, dt) => {
    if (!vrm) return;
    createVrmRigCached(vrm).apply(driver.frame(undefined, dt), dt);
  });

  return vrm ? <primitive object={vrm.scene} /> : null;
}

const rigs = new WeakMap<VRM, AvatarRig>();
function createVrmRigCached(vrm: VRM): AvatarRig {
  let rig = rigs.get(vrm);
  if (!rig) {
    rig = createVrmRig(vrm);
    rigs.set(vrm, rig);
  }
  return rig;
}
