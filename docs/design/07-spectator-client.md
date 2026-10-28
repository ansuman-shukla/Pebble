# 07 · Spectator client

A web app where anyone can watch the planet live, follow a citizen, and read lives in detail. Built like
Associo's frontend (Vite + React + TypeScript, Tailwind + shadcn/ui, TanStack Query, react-router, generated API client),
with the 3D world on **react-three-fiber + drei** (three.js).

## Pages

| Page | What you see |
|---|---|
| **World** | the 3D globe; camera modes; time controls; live feed; click anything to inspect |
| **Citizen** | portrait, role, age, model badge (phase B), needs over time, timeline, people, memory views, biography, self-disclosures |
| **Conversations** | threads of speech by place and time; jump to the moment in the world |
| **Timeline / replay** | scrub through game time; the world and feeds follow the scrubber |
| **Stats** | population, deaths by cause, food and resources, (phase B) disclosure rate by model |

## World view

- **Cameras:** orbit the whole planet (bird's eye), zoom smoothly down to street level, follow a citizen in third person,
  free fly. Keyboard + mouse; touch later.
- **Terrain:** one mesh built from the cell grid (height + biome colours), water sphere for oceans, rivers as strips.
- **Light:** the sun is a directional light that circles the planet with the game clock: real day and night sides,
  dusk colours, fire light at camps and lanterns in town.
- **Props:** Polyfork assets placed by the backend's world data: trees, rocks, bushes per biome; the town's castle,
  walls, houses, pagoda, bridge, paddies; camps; landmarks. Instanced meshes and LOD keep it fast.
- **Creatures:** citizens and animals move with interpolated positions; simple walk/idle/sleep/eat poses (Polyfork
  IK-walking assets where available).
- **Overlays (toggle):** names, biome map, paths walked today, perception and hearing radius, danger.
- **Live:** WebSocket feed of events; speech shows as bubbles over heads and in the feed.

## Assets

- Polyfork (free low-poly, commercial use, no attribution). Download into `frontend/public/assets/polyfork/` with each
  asset's licence and params JSON, rather than hotlinking, so the world can't break if an asset changes.
- An asset registry (`src/lib/world/assets.ts`) maps world prop kinds (`pine_tree`, `castle_keep`, `deer`…) to files,
  scale and palette. The backend only names kinds; it never knows file paths.
- Coverage check before building: confirm Polyfork has (or we can remix) feudal-Japan town pieces, Stone Age camp
  pieces, people, and every v0 animal. Gaps are listed and filled with simple parametric stand-ins.

## Player (v1)
One optional human avatar, controlled in third person, perceived by citizens as an ordinary stranger, with every
action logged as `actor_kind = player`. Not in v0.

## Quality
- Playwright smoke tests: world page loads and renders a frame, citizen page shows data, replay scrub works.
- Performance budget: 60 fps orbiting the globe on an M-series Mac, ≤ 30 MB initial assets.
