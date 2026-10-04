"use server";

import type { SoundManifestPayload } from "@sg/audio";

import { apiGet } from "@/lib/api";
import { currentLearnerOrNull } from "@/lib/session";

/**
 * Server Action behind the sound toggle: fetch the signed asset URLs (they expire, so the browser
 * asks again rather than baking them into the page). Returns null when signed out, when nothing has been generated
 * yet or the API is unreachable; the soundscape then stays silent, which is a supported state.
 */
export async function loadSoundManifest(): Promise<SoundManifestPayload | null> {
  if (!(await currentLearnerOrNull())) return null;
  const result = await apiGet<SoundManifestPayload>("/v1/soundscape/manifest");
  return result.ok ? result.data : null;
}
