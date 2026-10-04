import type { GardenDataset } from "@sg/contracts";

import { buildMockDataset } from "./mock";

/**
 * The single data-access seam for the Garden Dashboard. Call it from Server Components only.
 *
 * TODAY: a deterministic mock learner (`./mock.ts`).
 * LATER (C09/C10 analytics API): replace the body with
 * `apiGet<GardenDataset>("/v1/garden/dataset")` from `@/lib/api` and map `ApiResult` errors to an
 * error state. The `GardenDataset` shape in `@sg/contracts` is the contract; no component imports
 * the mock directly. For a very large garden, swap the single dataset for per-revision snapshots
 * behind the same function names.
 */
export async function getGardenDataset(): Promise<GardenDataset> {
  return buildMockDataset();
}

/** True while the dashboard runs on mock data; drives the visible "sample data" notice. */
export const GARDEN_DATA_IS_MOCK = true;
