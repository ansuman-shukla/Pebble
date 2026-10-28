# Findings: the globe viewer (M4 client, 2026-10-29)

What the planet client at `/` does, how it maps the town onto the sphere, what it costs to draw and what is still
rough. Built against the globe contract with a deterministic mock world until `GET /api/v1/world` exists.

## Pages and controls

| URL | What |
|---|---|
| `/` | the globe (`pages/globe-page.tsx`); `/api/v1/world`, falling back to the mock on 404 |
| `/?mock=1[&frequency=60]` | the dev/test mock world (default frequency 30, 9002 cells) |
| `/?at=lat,lon[,bearing]` | start somewhere else (bearing clockwise from north) |
| `/?time=HH:MM` | starting town time (default 08:00) |
| `/town` | the flat town on its own (debugging) |

WASD move, Shift run (3.5 m/s), **T travel (25 m/s, also a button): crosses the 12.6 km circumference in ~8 min**,
drag look, wheel zoom, C cycles follow / orbit / fly (Q/E down/up in fly). The `time ×60` button runs the clock at
1 real s = 1 game hour (normal: 1 real s = 1 game minute). Orbit zoomed below 400 m over the player hands over to
follow.

## Modules

| Module | Role |
|---|---|
| `lib/world/world-view.ts` | hand-written `WorldView` types (swap for the generated client types) |
| `lib/world/globe.ts` | decode the base64 arrays, lat/lon, tangent frame, gnomonic `siteMapping`, terrain lookup (`buildTerrain`: nearest cell by greedy walk over neighbours, height = ray hit on the rendered triangle) |
| `lib/world/local-mapping.ts` | `LocalMapping` (local metres to world); `FLAT_MAPPING` for `/town` |
| `lib/world/globe-walk.ts` | a step on the sphere: town collisions in local metres inside the town, water biomes block outside |
| `lib/world/scatter.ts` + `biome-props.ts` | props per cell from `hash(seed, cell)`; `perCell` counts are for frequency 60 and scale with cell area |
| `lib/world/game-clock.ts` | the clock and the sun (no axial tilt) |
| `lib/world/mock-world.ts` | DEV/TEST ONLY mock in the contract's format |
| `components/world/globe/*` | surface, sky, smoke, sites, scatter, player, cameras, walker |

## The town on the planet

- Placements, ground areas, water and townspeople go through `anchorMapping(site.anchor, R)`: model matrices get
  the basis (east', up', south') at their spot, flat shapes are split into ≤ 8 m triangles before mapping.
- The town lays its own ground disc (radius 225 m, inside the 230 m plateau) at exactly R + h0, with a 4 m skirt;
  the terrain shader discards fragments inside that cone, so moat and stream water (0.4 m below the grass) are
  never covered by terrain triangles (whose chords sag below the sphere).
- Camps and landmarks have no ground of their own: each placement stands on the rendered terrain under it
  (`lift`), so a slightly uneven plateau never leaves props floating.

## Performance

1280x800, Chrome with the Metal GPU, mock world.

| View | Draw calls | Triangles | fps |
|---|---|---|---|
| follow at the town spawn (f30 / f60) | 183 / 183 | 2.3 M / 2.4 M | 60 / 60 |
| follow in a forest (f30 / f60) | 191 / 191 | 3.8 M / 3.8 M | 60 / 60 |
| orbit, whole planet (f30 / f60) | 233 / 233 | 1.9 M / 2.0 M | 60 / 60 |

Ready in ~3 s (warm cache). Triangle counts include the shadow pass; most are the town's instances.

## Known limitations

- No fire light or lantern glow at night yet; no seasons (no axial tilt, so the poles sit in permanent twilight).
- Camps and landmarks have no collisions (only the town's apply).
- The town is drawn at full detail even from orbit (no LOD); fine at 60 fps but ~1.9 M triangles.
- The mock's rivers are carved one cell wide, so at frequency 60 they cut narrow canyons.
- Water is checked at the player's centre against the nearest cell's biome and the surface height.
