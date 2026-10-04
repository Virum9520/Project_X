import type { GardenDataset } from "@sg/contracts";

import { apiGet } from "@/lib/api";

import { buildMockDataset } from "./mock";

/**
 * The single data-access seam for the Garden Dashboard. Call it from Server Components only.
 * No component imports the mock directly.
 *
 * Source (`GARDEN_DATA_SOURCE`):
 * - `api` (default): `GET /v1/garden/dataset` on `services/api`. If the API is unreachable or
 *   refuses, development falls back to the sample learner so the UI can be worked on without the
 *   backend; production throws, so the route's error boundary shows a retry instead of data that
 *   is not the learner's.
 * - `mock`: always the deterministic sample learner.
 */
export interface GardenData {
  dataset: GardenDataset;
  /** True when `dataset` is the sample learner; drives the visible "sample data" notice. */
  isMock: boolean;
  /** Why the sample data is showing instead of the API (development fallback only). */
  fallbackReason?: string;
}

export async function getGardenData(): Promise<GardenData> {
  if (process.env.GARDEN_DATA_SOURCE === "mock") {
    return { dataset: buildMockDataset(), isMock: true };
  }
  const result = await apiGet<GardenDataset>("/v1/garden/dataset");
  if (result.ok) return { dataset: result.data, isMock: false };
  if (process.env.NODE_ENV === "development") {
    return {
      dataset: buildMockDataset(),
      isMock: true,
      fallbackReason: `${result.status || "no response"}: ${result.detail}`,
    };
  }
  throw new Error(`Garden data unavailable (${result.status || "no response"}): ${result.detail}`);
}

/** The sample learner, for the auth-free `/dev/garden` preview. Never used for a real learner. */
export function getSampleGardenDataset(): GardenDataset {
  return buildMockDataset();
}
