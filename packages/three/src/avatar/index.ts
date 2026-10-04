// Entry point for `@sg/three/avatar`. Client-only (three.js / R3F): import from 'use client' files.
export * from "./visemes";
export * from "./alignment";
export * from "./timeline";
export * from "./idle";
export * from "./lipsync-driver";
export * from "./rig";
export { useLipSync } from "./use-lip-sync";
export { Avatar, AvatarStage, type AvatarProps } from "./avatar";
export { ProceduralAvatar } from "./procedural-avatar";
export { VrmAvatar, createVrmRig } from "./vrm-avatar";
export { mockAlignment } from "./mock";
