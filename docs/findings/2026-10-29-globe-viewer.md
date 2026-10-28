# Findings: the globe viewer (M4 client, 2026-10-29)

What the planet client at `/` does, how it maps the town onto the sphere, what it costs to draw and what is still
rough. Built against the globe contract with a deterministic mock world, then switched to the real generated world
(`GET /api/v1/world`, seed 20261028, generator `m3.1`).

## Pages and controls

| URL | What |
|---|---|
| `/` | the globe (`pages/globe-page.tsx`) on the real world from `/api/v1/world` (generated SDK `worldReadWorld`) |
| `/?mock=1[&frequency=60]` | the dev/test mock world (default frequency 30, 9002 cells) |
| `/?at=lat,lon[,bearing]` | start somewhere else (bearing clockwise from north) |
| `/?time=HH:MM` | starting town time (default 08:00) |
| `/town` | the flat town on its own (debugging) |

WASD move, Shift run (3.5 m/s), **T travel (25 m/s, also a button): crosses the 12.6 km circumference in ~8 min**,
drag look, wheel zoom, C cycles follow / orbit / fly (Q/E down/up in fly). The `time ×60` button runs the clock at
1 real s = 1 game hour (normal: 1 real s = 1 game minute). Orbit zoomed below 400 m over the player hands over to
follow. The readout (bottom left) shows local time, lat/lon, biome and the site the player stands at (the town
within 300 m, a camp or landmark within 100 m of its anchor).

Useful `?at=` spots on the real world: band A camp `12.4,100,180`, standing stones `28.75,-4,180`, elder tree
`10.45,2.2,210`, great falls from the lake `2.25,12,58`, volcano from the south `-4,-20,0` (then fly up), ice gate
`71,-55,90`, densest broadleaf forest `4.3937,153.6401`.

## Modules

| Module | Role |
|---|---|
| `hooks/use-world.ts` | `/api/v1/world` through the generated client (types from `lib/client/types.gen`), or the mock with `?mock=1` |
| `lib/world/globe.ts` | decode the base64 arrays, lat/lon, tangent frame, gnomonic `siteMapping`, terrain lookup (`buildTerrain`: nearest cell by greedy walk over neighbours, height = ray hit on the rendered triangle) |
| `lib/world/local-mapping.ts` | `LocalMapping` (local metres to world); `FLAT_MAPPING` for `/town` |
| `lib/world/globe-walk.ts` | a step on the sphere: town collisions in local metres inside the town, water biomes block outside |
| `lib/world/scatter.ts` + `biome-props.ts` | props per cell from `hash(seed, cell)`; `perCell` counts are for frequency 60 and scale with cell area; no props on slopes over 40° |
| `lib/world/globe-mesh.ts` | terrain (flat faces coloured by biome, sand on shores, lakes as water) and river ribbons |
| `lib/world/assets.ts` `kindScale` | per-kind render scale (`giant_tree` ×3.5, `ice_block` ×3), applied to site placements and scatter |
| `lib/world/game-clock.ts` | the clock and the sun (no axial tilt) |
| `lib/world/mock-world.ts` | DEV/TEST ONLY mock in the contract's format |
| `components/world/globe/*` | surface, sky, smoke, sites, scatter, player, cameras, walker |

## The town on the planet

- Placements, ground areas, water and townspeople go through `anchorMapping(site.anchor, R)`: model matrices get
  the basis (east', up', south') at their spot, flat shapes are split into ≤ 8 m triangles before mapping.
- The town lays its own ground disc (radius 225 m, inside the 230 m plateau) at exactly R + h0, with a 4 m skirt;
  the terrain shader discards fragments inside that cone, so moat and stream water (0.4 m below the grass) are
  never covered by terrain triangles (whose chords sag below the sphere). On the real world the disc meets the
  plateau without a visible seam; walking out of the main gate south, the ground goes 8 m → terrain smoothly.
- Camps and landmarks have no ground of their own: each placement stands on the rendered terrain under it
  (`lift`), so a slightly uneven plateau never leaves props floating.

## Biome props

- Two reach tiers around the camera target (D41): ground cover (grass, dry/dune grass, flowers, ferns, small rocks,
  cattails, reeds) within 150 m, everything else within 500 m. Cells within 600 m are scattered and cached; the
  tiers are re-filtered every 20 m of focus movement, the cell set every 100 m.
- Full density to 600 m (the first draft) was 5.0 M triangles at a forest edge; the tiers bring the densest
  broadleaf view down to 1.6 M.
- Real terrain has steep faces (10 % of land edges over 40°, 5 % over 48°): props skip slopes over 40°.

## Lakes

The real world has 60 lakes whose surfaces lie above sea level (e.g. the great falls lake at 30 m). The terrain
arrays carry them as flat lake cells at their surface height, so the client draws a face whose corners are all lake
in the sea's near-shore colour; lake shores get a light sand tint (sea beaches a strong one). Before this the lakes
showed as sand (the face colouring only knew sea level).

## Performance (real world)

1280x800, headless Chrome with the Metal GPU (`--use-angle=metal`), M-series Mac. Triangles include the shadow pass.

| View | Draw calls | Triangles | fps |
|---|---|---|---|
| follow at the town spawn (gate approach) | 203 | 1.9 M | 60 |
| follow at the main gate | 206 | 1.9 M | 60 |
| follow in the densest broadleaf forest (4.39, 153.64) | 71 | 1.6 M | 60 |
| follow at band A camp | 92 | 1.4 M | 60 |
| orbit, whole planet (6000 m from the centre) | 263 | 1.9 M | 60 |
| orbit over the town (~500 m up) | 221 | 2.3 M | 60 |
| fly near the volcano | 259 | 2.3 M | 60 |
| travelling at 25 m/s through forest | 54 | 1.8 M | 60, no frame over 17 ms in 8 s |

- `/api/v1/world`: 0.85 MB gzip (2.0 MB JSON), ~0.2 s from the stored row; generating a new row (spec change) ~1 s.
- Ready (world decoded, town placements and walker loaded) in ~4-4.7 s from a cold page in headless Chrome.

## Exploring: drops, go to, the spring arm and solid objects

| Feature | How it works |
|---|---|
| Drop (pegman) | the click (or the drop of the dragged pegman) becomes a camera ray; `globe-pick.ts` marches it to the first point under the terrain, the town plateau or the sea surface. Water (sea, lakes, the moat, the stream) is refused with a message; on land `dropSpot` takes the nearest free spot (rings out to 12 m, so a click on a house lands beside it). The player faces along the view ray, or the camera's screen-up (north in orbit) when the camera looks down steeply. A pin follows the pointer, grey with "water" over water. |
| Camera flight | every switch into follow (a drop, go to, C, the orbit zoom handover) flies from the current view in 1.5 s: around the planet's centre along the great circle, altitude interpolated in log space and lifted over long hops so it never cuts through the planet; the view turns to the player in the first 40 %. |
| Go to | the town: its spawn by the main gate; camps and landmarks: the first free spot on rings 6..30 m around the anchor (south first), facing the anchor. |
| `?at=` | rewritten with `history.replaceState` after every drop / go to (`lat,lon,bearing`, other params kept). |
| Solid objects | `globe-walk.ts` resolves each step in a chart (D42): the town's walls and townspeople, each camp's and landmark's placements, and a wild chart of the scattered props around the player, all from Polyfork colliders; ground cover (grass, flowers, ferns, reeds, cattails, pebbles) never blocks. |
| Spring arm | the segment from the eye (1.4 m) to the wanted camera is clipped against the same collider volumes and sampled against the ground (D43); slopes behind the player tilt the camera up instead of pulling it in. |
| Walking | pace eases in and out (~0.3 s), slows to 40 % up and 75 % down a 45° slope, and the feet follow the terrain exactly (only real steps onto paving or a bridge are eased); the camera's eye height is smoothed so the terrain's facets don't bob the view. |

Costs, measured headless with the Metal GPU: a step resolves in ~0.02 ms, the camera's reach in ~0.007 ms; the wild
chart is rebuilt every 35 m of walking in 6-15 ms in the densest forest (~2000 collider parts). Running for 6 s at the
spawn, in the densest forest, at band A camp, along the main street and on a slope: 60 fps, no frame over 20 ms, 68-210
draw calls (orbit 227).

Notes:
- Low parts (under the body band's 0.3 m) are stepped over everywhere, so the fire pit's stone ring doesn't block; only
  its logs do.
- `hot_spring_pool` is `walk: none` in the backend world spec, so the pools don't block (the rocks around them do).
- `/town` (the flat debugging page) still uses the old follow camera without the spring arm.

## Known limitations

- No fire light or lantern glow at night yet; no seasons (no axial tilt, so the poles sit in permanent twilight).
- The town is drawn at full detail even from orbit (no LOD); fine at 60 fps but it is most of the orbit draw calls.
- The real terrain is rugged at 40 m cells (steep faces up to ~60°): slopes over 45° stop the walker, so some
  mountain flanks can only be crossed in travel mode.
- Small plateaus (elder tree, camps: radius 40-50 m) are only one or two cells, so the ground around them still slopes.
- The great falls outflow leaves its lake as a flat land strip at lake level (the authored channel cells are not
  lake), which reads as a causeway across the lake's south end.
- Rivers are 6 m ribbons along cell paths; on steep faces (the Mill river coming down the Greyspine) they show as
  bright strips.
- Water is checked at the player's centre against the nearest cell's biome and the surface height.
