"use client";

import { useFrame } from "@react-three/fiber";
import { useEffect, useRef, useState } from "react";
import * as THREE from "three";

import type { GroveLayout } from "../generator/layout";
import { hashString } from "../generator/random";

type EzTree = THREE.Group & { update(elapsed: number): void };

const PRESETS = ["Oak Medium", "Ash Medium", "Aspen Medium"] as const;
const TARGET_HEIGHT = 3.4;

function disposeTree(tree: THREE.Object3D) {
  tree.traverse((object) => {
    if (object instanceof THREE.Mesh) {
      object.geometry.dispose();
      const materials = Array.isArray(object.material) ? object.material : [object.material];
      for (const material of materials) material.dispose();
    }
  });
}

/**
 * One ez-tree "elder tree" per grove, sized by the grove's health. ez-tree ships its textures
 * inline (~4 MB), so it is imported lazily after first paint and trees are generated one per tick.
 */
export function ElderTree({ grove, health }: { grove: GroveLayout; health: number }) {
  const [tree, setTree] = useState<EzTree | null>(null);
  const group = useRef<THREE.Group>(null);

  useEffect(() => {
    let cancelled = false;
    let created: EzTree | null = null;
    const timer = setTimeout(
      async () => {
        const { Tree, TreePreset } = await import("@dgreenheck/ez-tree");
        if (cancelled) return;
        const preset = PRESETS[grove.index % PRESETS.length] ?? "Oak Medium";
        const options = structuredClone(TreePreset[preset]) as (typeof TreePreset)[typeof preset];
        options.seed = hashString(grove.id) % 65536;
        options.leaves.tint = new THREE.Color(grove.color)
          .lerp(new THREE.Color("#ffffff"), 0.25)
          .getHex();
        options.bark.tint = 0xc9b8a6;
        const t = new Tree() as unknown as EzTree & { loadFromJson(json: unknown): void };
        t.loadFromJson(options);
        const box = new THREE.Box3().setFromObject(t);
        t.scale.setScalar(TARGET_HEIGHT / Math.max(0.001, box.max.y - box.min.y));
        t.traverse((object) => {
          object.raycast = () => {};
          object.castShadow = true;
        });
        created = t;
        setTree(t);
      },
      400 + grove.index * 220,
    );
    return () => {
      cancelled = true;
      clearTimeout(timer);
      if (created) disposeTree(created);
    };
  }, [grove.id, grove.index, grove.color]);

  useFrame((state, delta) => {
    if (!tree || !group.current) return;
    tree.update(state.clock.elapsedTime);
    // Grows in when generated, then tracks grove health.
    const target = 0.7 + 0.45 * health;
    const s = THREE.MathUtils.damp(group.current.scale.x, target, 1.5, Math.min(delta, 0.1));
    group.current.scale.setScalar(s);
  });

  if (!tree) return null;
  return (
    <group ref={group} position={grove.elderTree} scale={0.001}>
      <primitive object={tree} />
    </group>
  );
}
