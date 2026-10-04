import type { PlantPart } from "@sg/contracts";
import * as THREE from "three";

import { createRng, range } from "../generator/random";

/**
 * Procedural concept plant, built once per plant at full size. Each vertex carries:
 * - `aGrow`  — where it sits along its part's growth, in [0, 1]. The growth shader reveals
 *              vertices with `aGrow` below the part's growth level, so parts extend from base to
 *              tip, leaves unfurl as the stem reaches them and blossoms open one by one.
 * - `aSpine` — the point it collapses onto while not yet grown (tube center, leaf base, flower center).
 * - `aAttach` — attachment point on the stem. Branches and blossoms slide down with a short stem.
 *
 * Coordinates are plant-local: the base sits at the origin, y is up.
 */

export interface PlantShape {
  height: number;
  parts: Record<PlantPart, THREE.BufferGeometry>;
  /** Plant-local points the camera looks at for each part (at full growth). */
  anchors: Record<PlantPart, THREE.Vector3>;
}

export interface PlantPalette {
  grove: string;
}

const UP = new THREE.Vector3(0, 1, 0);

class Builder {
  private positions: number[] = [];
  private colors: number[] = [];
  private grow: number[] = [];
  private spine: number[] = [];
  private attach: number[] = [];
  private indices: number[] = [];

  private vertex(
    p: THREE.Vector3,
    color: THREE.Color,
    grow: number,
    spine: THREE.Vector3,
    attach: THREE.Vector3,
  ) {
    this.positions.push(p.x, p.y, p.z);
    this.colors.push(color.r, color.g, color.b);
    this.grow.push(grow);
    this.spine.push(spine.x, spine.y, spine.z);
    this.attach.push(attach.x, attach.y, attach.z);
    return this.positions.length / 3 - 1;
  }

  /** Tapered tube along `curve`; `grow(t)` maps the curve parameter to `aGrow`. */
  tube(opts: {
    curve: THREE.Curve<THREE.Vector3>;
    radius: (t: number) => number;
    segments: number;
    radial: number;
    grow: (t: number) => number;
    color: (t: number) => THREE.Color;
    attach?: THREE.Vector3;
  }) {
    const { curve, segments, radial } = opts;
    const attach = opts.attach ?? new THREE.Vector3();
    const frames = curve.computeFrenetFrames(segments, false);
    const start = this.positions.length / 3;
    const p = new THREE.Vector3();
    for (let i = 0; i <= segments; i++) {
      const t = i / segments;
      const center = curve.getPointAt(t);
      const n = frames.normals[i]!;
      const b = frames.binormals[i]!;
      const r = opts.radius(t);
      const color = opts.color(t);
      for (let j = 0; j < radial; j++) {
        const a = (j / radial) * Math.PI * 2;
        p.copy(center)
          .addScaledVector(n, Math.cos(a) * r)
          .addScaledVector(b, Math.sin(a) * r);
        this.vertex(p, color, opts.grow(t), center, attach);
      }
    }
    for (let i = 0; i < segments; i++) {
      for (let j = 0; j < radial; j++) {
        const a = start + i * radial + j;
        const b = start + i * radial + ((j + 1) % radial);
        const c = a + radial;
        const d = b + radial;
        this.indices.push(a, c, b, b, c, d);
      }
    }
  }

  /** A slightly folded diamond leaf (or petal) from `base` toward `dir`. */
  leaf(opts: {
    base: THREE.Vector3;
    dir: THREE.Vector3;
    length: number;
    width: number;
    grow: number;
    color: THREE.Color;
    attach?: THREE.Vector3;
    spine?: THREE.Vector3;
  }) {
    const { base, length, width } = opts;
    const dir = opts.dir.clone().normalize();
    const side = new THREE.Vector3().crossVectors(dir, UP);
    if (side.lengthSq() < 1e-6) side.set(1, 0, 0);
    side.normalize();
    const fold = new THREE.Vector3().crossVectors(side, dir).normalize();
    const attach = opts.attach ?? new THREE.Vector3();
    const spine = opts.spine ?? base;
    const tip = base.clone().addScaledVector(dir, length);
    const mid = base.clone().addScaledVector(dir, length * 0.42);
    const left = mid
      .clone()
      .addScaledVector(side, width)
      .addScaledVector(fold, width * 0.35);
    const right = mid
      .clone()
      .addScaledVector(side, -width)
      .addScaledVector(fold, width * 0.35);
    const dark = opts.color.clone().multiplyScalar(0.82);
    const i0 = this.vertex(base, dark, opts.grow, spine, attach);
    const i1 = this.vertex(left, opts.color, opts.grow, spine, attach);
    const i2 = this.vertex(tip, opts.color, opts.grow, spine, attach);
    const i3 = this.vertex(right, opts.color, opts.grow, spine, attach);
    this.indices.push(i0, i1, i2, i0, i2, i3);
  }

  /** A five-petal blossom with a small octahedral center. */
  blossom(opts: {
    center: THREE.Vector3;
    facing: THREE.Vector3;
    size: number;
    grow: number;
    petal: THREE.Color;
    heart: THREE.Color;
    attach: THREE.Vector3;
    twist: number;
  }) {
    const { center, size, attach } = opts;
    const facing = opts.facing.clone().normalize();
    const u = new THREE.Vector3().crossVectors(facing, UP);
    if (u.lengthSq() < 1e-6) u.set(1, 0, 0);
    u.normalize();
    const v = new THREE.Vector3().crossVectors(facing, u).normalize();
    for (let k = 0; k < 5; k++) {
      const a = opts.twist + (k / 5) * Math.PI * 2;
      const dir = u
        .clone()
        .multiplyScalar(Math.cos(a))
        .addScaledVector(v, Math.sin(a))
        .addScaledVector(facing, 0.45);
      this.leaf({
        base: center,
        dir,
        length: size,
        width: size * 0.42,
        grow: opts.grow,
        color: opts.petal,
        attach,
        spine: center,
      });
    }
    const h = size * 0.28;
    const pts = [
      center.clone().addScaledVector(facing, h),
      center.clone().addScaledVector(u, h),
      center.clone().addScaledVector(v, h),
      center.clone().addScaledVector(u, -h),
      center.clone().addScaledVector(v, -h),
      center.clone().addScaledVector(facing, -h * 0.6),
    ];
    const idx = pts.map((p) => this.vertex(p, opts.heart, opts.grow, center, attach));
    const [top, a, b, c, d, bottom] = idx as [number, number, number, number, number, number];
    this.indices.push(top, a, b, top, b, c, top, c, d, top, d, a);
    this.indices.push(bottom, b, a, bottom, c, b, bottom, d, c, bottom, a, d);
  }

  build(): THREE.BufferGeometry {
    const g = new THREE.BufferGeometry();
    g.setAttribute("position", new THREE.Float32BufferAttribute(this.positions, 3));
    g.setAttribute("color", new THREE.Float32BufferAttribute(this.colors, 3));
    g.setAttribute("aGrow", new THREE.Float32BufferAttribute(this.grow, 1));
    g.setAttribute("aSpine", new THREE.Float32BufferAttribute(this.spine, 3));
    g.setAttribute("aAttach", new THREE.Float32BufferAttribute(this.attach, 3));
    g.setIndex(this.indices);
    g.computeVertexNormals();
    g.computeBoundingSphere();
    // Wilting and wind bend the plant in the shader, so leave some slack for culling.
    if (g.boundingSphere) g.boundingSphere.radius *= 1.4;
    return g;
  }
}

const tint = (hex: string, grove: THREE.Color, amount: number, lightness = 0) => {
  const c = new THREE.Color(hex).lerp(grove, amount);
  if (lightness) c.offsetHSL(0, 0, lightness);
  return c;
};

/** Builds a plant's four part geometries from its seed. Deterministic. */
export function buildPlantShape(seed: number, palette: PlantPalette): PlantShape {
  const rng = createRng(seed);
  const grove = new THREE.Color(palette.grove);
  const height = range(rng, 1.05, 1.4);

  // Roots: explanation. Exposed, glowing amber roots radiating over the ground, with rootlets.
  const roots = new Builder();
  const rootCount = 4 + Math.floor(rng() * 3);
  const rootColor = tint("#d39a5c", grove, 0.12);
  for (let i = 0; i < rootCount; i++) {
    const a = (i / rootCount) * Math.PI * 2 + range(rng, -0.3, 0.3);
    const dir = new THREE.Vector3(Math.cos(a), 0, Math.sin(a));
    const perp = new THREE.Vector3(-dir.z, 0, dir.x);
    const length = range(rng, 0.45, 0.8);
    const wiggle = range(rng, -0.12, 0.12);
    const curve = new THREE.CatmullRomCurve3([
      new THREE.Vector3(0, 0.05, 0),
      dir
        .clone()
        .multiplyScalar(length * 0.3)
        .setY(0.02)
        .addScaledVector(perp, wiggle * 0.5),
      dir
        .clone()
        .multiplyScalar(length * 0.65)
        .setY(0.005)
        .addScaledVector(perp, -wiggle),
      dir.clone().multiplyScalar(length).setY(-0.03),
    ]);
    roots.tube({
      curve,
      radius: (t) => 0.034 * (1 - t) + 0.002,
      segments: 10,
      radial: 5,
      grow: (t) => t,
      color: (t) => rootColor.clone().offsetHSL(0, 0, -0.08 * t),
    });
    const fork = curve.getPointAt(0.5);
    const forkDir = dir
      .clone()
      .addScaledVector(perp, wiggle > 0 ? 0.9 : -0.9)
      .normalize();
    roots.tube({
      curve: new THREE.CatmullRomCurve3([
        fork,
        fork
          .clone()
          .addScaledVector(forkDir, length * 0.2)
          .setY(0),
        fork
          .clone()
          .addScaledVector(forkDir, length * 0.38)
          .setY(-0.03),
      ]),
      radius: (t) => 0.016 * (1 - t) + 0.002,
      segments: 5,
      radial: 4,
      grow: (t) => 0.5 + t * 0.5,
      color: () => rootColor,
    });
  }

  // Stem: application. A gently curved stem with leaves that unfurl as it rises.
  const stem = new Builder();
  const lean = new THREE.Vector3(range(rng, -1, 1), 0, range(rng, -1, 1))
    .normalize()
    .multiplyScalar(range(rng, 0.04, 0.1));
  const stemPoint = (t: number) =>
    new THREE.Vector3(
      lean.x * Math.sin(t * Math.PI * 0.9),
      height * t,
      lean.z * Math.sin(t * Math.PI * 0.9),
    );
  const stemCurve = new THREE.CatmullRomCurve3(
    Array.from({ length: 6 }, (_, i) => stemPoint(i / 5)),
  );
  const stemBase = tint("#3f7d4c", grove, 0.1);
  const stemTop = tint("#7ccf7d", grove, 0.15);
  stem.tube({
    curve: stemCurve,
    radius: (t) => 0.055 * (1 - 0.72 * t) + 0.006,
    segments: 16,
    radial: 6,
    grow: (t) => t,
    color: (t) => stemBase.clone().lerp(stemTop, t),
  });
  const leafBase = tint("#3fae7a", grove, 0.28);
  const leafSpots = [
    0.1,
    0.16,
    ...Array.from({ length: 5 + Math.floor(rng() * 3) }, (_, i) => 0.28 + i * 0.1),
  ];
  leafSpots.forEach((t, i) => {
    if (t > 0.92) return;
    const base = stemCurve.getPointAt(t);
    const a = i * 2.4 + range(rng, -0.3, 0.3);
    const dir = new THREE.Vector3(Math.cos(a), range(rng, 0.35, 0.8), Math.sin(a));
    const size = i < 2 ? 0.16 : range(rng, 0.2, 0.3) * (1 - t * 0.35);
    stem.leaf({
      base,
      dir,
      length: size,
      width: size * 0.38,
      grow: t,
      color: leafBase.clone().offsetHSL(range(rng, -0.02, 0.02), 0, range(rng, -0.06, 0.06)),
    });
  });

  // Branches: transfer. Woody branches from the upper stem, each with a few leaves.
  const branches = new Builder();
  const branchCount = 3 + Math.floor(rng() * 3);
  const bark = tint("#7a6048", grove, 0.08);
  const branchLeaf = leafBase.clone().offsetHSL(0, 0, 0.05);
  for (let i = 0; i < branchCount; i++) {
    const at = 0.42 + (i / branchCount) * 0.42 + range(rng, -0.04, 0.04);
    const attach = stemCurve.getPointAt(at);
    const a = i * 2.39996 + range(rng, -0.4, 0.4);
    const out = new THREE.Vector3(Math.cos(a), 0, Math.sin(a));
    const length = range(rng, 0.42, 0.65) * (1.1 - at * 0.4);
    const pitch = range(rng, 0.55, 0.95);
    const curve = new THREE.CatmullRomCurve3([
      attach,
      attach
        .clone()
        .addScaledVector(out, length * 0.45)
        .add(new THREE.Vector3(0, length * pitch * 0.35, 0)),
      attach
        .clone()
        .addScaledVector(out, length)
        .add(new THREE.Vector3(0, length * pitch, 0)),
    ]);
    // Later branches start a little later, so transfer growth fans out branch by branch.
    const start = (i / branchCount) * 0.35;
    branches.tube({
      curve,
      radius: (t) => 0.026 * (1 - 0.8 * t) + 0.004,
      segments: 8,
      radial: 5,
      grow: (t) => start + t * (1 - start),
      color: (t) => bark.clone().lerp(stemTop, t * 0.6),
      attach,
    });
    for (let k = 0; k < 3; k++) {
      const t = 0.45 + k * 0.25;
      const base = curve.getPointAt(t);
      const la = a + (k % 2 ? 1 : -1) * 1.1;
      branches.leaf({
        base,
        dir: new THREE.Vector3(Math.cos(la), 0.6, Math.sin(la)),
        length: 0.15,
        width: 0.06,
        grow: start + t * (1 - start),
        color: branchLeaf,
        attach,
      });
    }
  }

  // Blossoms: retention. A crown around the stem tip; they open one by one.
  const blossoms = new Builder();
  const blossomCount = 4 + Math.floor(rng() * 3);
  const petal = tint("#f4b8d4", grove, 0.3, 0.04);
  const heart = new THREE.Color("#ffe08a");
  for (let i = 0; i < blossomCount; i++) {
    const t = i === 0 ? 1 : range(rng, 0.62, 0.95);
    const onStem = stemCurve.getPointAt(Math.min(1, t));
    const a = i * 2.39996;
    const out =
      i === 0 ? new THREE.Vector3(0, 1, 0) : new THREE.Vector3(Math.cos(a), 0.55, Math.sin(a));
    const center = onStem.clone().addScaledVector(out.clone().normalize(), i === 0 ? 0.05 : 0.11);
    blossoms.blossom({
      center,
      facing: out,
      size: i === 0 ? 0.13 : range(rng, 0.075, 0.1),
      grow: i / blossomCount,
      petal: petal.clone().offsetHSL(range(rng, -0.03, 0.03), 0, range(rng, -0.04, 0.04)),
      heart,
      attach: onStem,
      twist: range(rng, 0, Math.PI),
    });
  }

  return {
    height,
    parts: {
      roots: roots.build(),
      stem: stem.build(),
      branches: branches.build(),
      blossoms: blossoms.build(),
    },
    anchors: {
      roots: new THREE.Vector3(0, 0.03, 0),
      stem: stemPoint(0.45),
      branches: stemPoint(0.72),
      blossoms: stemPoint(1),
    },
  };
}
