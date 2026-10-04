/**
 * React Three Fiber garden scene. Client-only: import it from a `'use client'` module and load
 * it with `next/dynamic(..., { ssr: false })`. Pure helpers live in the `@sg/three` entry point.
 */
export { GardenScene, type GardenSceneProps, type GardenQuality } from "./GardenScene";
export { atmosphereAt, localHour, type Atmosphere } from "./atmosphere";
export { framingFor, type Framing } from "./framing";
export { partAnchor, plantCenter, plantHeight } from "./anchors";
