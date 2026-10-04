/**
 * Shared 3D building blocks for Skill Garden.
 *
 * This entry point is pure TypeScript (no React, no WebGL), so it is safe in Server Components and
 * tests: garden types, the deterministic generator, growth mapping, navigation and mock data.
 * The React Three Fiber scene lives in `@sg/three/scene` and must be loaded client-side only.
 */
export * from "./model/types";
export * from "./model/growth";
export * from "./model/navigation";
export * from "./generator/random";
export * from "./generator/terrain";
export * from "./generator/layout";
export * from "./mock/garden";
