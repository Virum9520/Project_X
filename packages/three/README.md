# @sg/three

Shared 3D for Skill Garden. Source-only; Turbopack transpiles it.

| Entry | Contents | Where it runs |
|---|---|---|
| `@sg/three` | Garden types, deterministic generator (`generateGardenLayout`), growth mapping (`plantGrowth`), semantic-zoom navigation, mock garden data | Anywhere (pure TS) |
| `@sg/three/scene` | `GardenScene` (React Three Fiber) and camera/atmosphere helpers | Client only |

```tsx
"use client";
import dynamic from "next/dynamic";

const GardenScene = dynamic(() => import("@sg/three/scene").then((m) => m.GardenScene), {
  ssr: false,
});

<GardenScene snapshot={snapshot} focus={focus} onFocusChange={setFocus} />;
```

## How the garden maps to evidence

- Grove = domain, plant = concept. Every curriculum concept appears; unassessed ones are seeds.
- Explanation → roots, application → stem, transfer → branches, retention → blossoms.
- Independent evidence renders solid. Assisted-only growth renders as dithered "ghost" growth.
  Live provisional growth (`PlantSnapshot.provisional`) glows and pulses until confirmed.
- `due` plants droop slightly; `wilting` plants droop and fade.
- Placement depends only on the snapshot's structure and the seed, so plants stay put across
  revisions and only their growth animates (time travel).

## Zoom and keyboard

Garden → Grove → Plant → Part. Click to zoom in; Esc zooms out; arrow keys move between siblings;
Enter zooms in. Focus round-trips through URLs with `focusToString` / `focusFromString`.

## Development

- `pnpm --filter @sg/three test` runs the unit tests (generator, growth, navigation, mock, geometry).
- `/lab/garden` in `apps/web` is a showcase on mock data: time travel, simulated live growth,
  filter dimming, time of day and quality.
