# Garden frame-time budgets (C23 part B)

The garden is a three.js scene (`packages/three`). Two kinds of check protect its performance.

## 1. Static scene budget (runs in CI, no GPU)

`SCENE_BUDGET` in `packages/three/src/perf/frameBudget.ts` bounds the work per frame: plants per
garden, vertices per plant, total plant vertices and layout generation time. The unit tests in
`packages/three/test/perf-budget.test.ts` enforce it:

```bash
pnpm --filter @sg/three test
```

A change that adds geometry or slows layout generation fails here. If a budget needs to move,
change the number in `frameBudget.ts` in the same PR and say why.

## 2. Measured frame times (manual, in a real browser)

`FRAME_BUDGETS` defines p50, p95, p99 and long-frame-share limits for two device classes:

| Class | p50 | p95 | p99 | Frames over 33 ms |
| --- | --- | --- | --- | --- |
| `desktop` (GPU, 60 fps target) | 16.7 ms | 22 ms | 33.4 ms | at most 1% |
| `lowEnd` (laptop or phone, 30 fps floor) | 33.4 ms | 45 ms | 66.7 ms | at most 5% |

To measure:

1. Run `pnpm dev` and open the garden in Chrome with a realistic garden loaded.
2. Start the probe (`measureFrames` samples `requestAnimationFrame` deltas):
   `const stop = measureFrames()`.
3. Orbit, zoom and select plants for about 10 seconds, then `const durations = stop()`.
4. Summarize and check: `checkFrameBudget(summarizeFrames(durations), FRAME_BUDGETS.desktop)`.
   `summarizeFrames` drops the first 30 frames (shader compilation). An empty array means within
   budget; otherwise each string names the violated limit. At least 100 frames are required.
5. For the low-end figure, use Chrome DevTools CPU throttling (4x or 6x slowdown) or a real
   mid-range laptop or phone, and check against `FRAME_BUDGETS.lowEnd`.

Record results (device, browser, plants in the garden, stats) in the PR or in `docs/PROGRESS.md`.
Headless runs are not representative of user hardware.
