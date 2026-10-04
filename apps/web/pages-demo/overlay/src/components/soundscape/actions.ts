import type { SoundManifestPayload } from "@sg/audio";

/** Static demo: no generated audio is hosted, so the soundscape stays silent. */
export async function loadSoundManifest(): Promise<SoundManifestPayload | null> {
  return null;
}
