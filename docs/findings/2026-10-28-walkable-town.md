# Findings: the walkable town (M2, 2026-10-28)

What the M2 town contains, how walking works on it, what it costs to draw and what is still rough.

## Layout

Local metres, +x east, +z south, flat ground at y = 0 (spec: `backend/data/town/town.yaml`, served at `/api/v1/town`).

| Part | Where |
|---|---|
| Castle precinct | keep at (0, -6) on an island ringed by stone walls (±28 m) with 4 corner turrets, two storehouses, pines and cherry trees; castle gatehouse at (0, 28) |
| Moat + bridge | water ring 31..37 m out, moat road around it; bridge at (0, 35) crossing to the castle gate |
| Town wall | plaster wall at ±100 m with corner turrets; **main gate** (0, 100) facing the approach road from the south, **west gate** (-100, 76) |
| Streets | main street (x ±3) from the main gate to the moat; cross street z 58..64 from wall to wall; temple lane x 57..63 |
| Quarters | townhouses along the main and cross streets; market plaza with teahouse and notice board (10..30, 44..57); well plaza (-20, 50); temple quarter in the north-east (temple hall stands in for the shrine, pagoda, bell tower, forecourt); training ground with lookout tower in the north-west; storehouse yard (60..80, 80..90); two farmhouses in the south-west |
| Outside the west gate | rice fields (450 paddy tiles, drying racks, bamboo fence), a stream along x -160..-152 with the water wheel and a river boat |
| People | 6 townspeople: lord (stands in the courtyard), samurai (patrols the courtyard), merchant (market), farmer (loops the paddies), weaver (by the farmhouses), child (circles the well) |
| Spawn | (0, 120) on the approach road, facing north at the main gate |

## Placements (1220)

| Kind | Count | Kind | Count |
|---|---|---|---|
| rice_paddy | 450 | storehouse | 7 |
| plaster_wall | 382 | banner | 7 |
| bamboo_fence | 116 | sculpted_pine, reeds, bamboo, azalea | 6 each |
| stone_wall | 97 | cherry_tree, drying_rack | 5 each |
| townhouse | 36 | fire_basket | 4 |
| paving_tile | 36 | castle_gatehouse, sake_barrel, maple_tree | 3 each |
| lantern | 12 | bench, stone_basin, farmhouse | 2 each |
| corner_turret | 8 | 16 single props and buildings (keep, bridge, teahouse, temple hall, pagoda, bell tower, water wheel, ...) | 1 each |

## Collisions and height

- **Frontend (what the player feels):** Polyfork's convex colliders per model, placed like the model and flattened
  to the ground; a part blocks only where it overlaps the body band 0.3..1.7 m above the player's ground (so roofs
  and gate lintels don't block, low steps are walked over). Water blocks unless a walkable surface covers it.
  Ground height comes from raycasts into `surface` placements (bridge, paving, paddies).
- **Backend (what tests and later the simulation trust):** footprint rectangles, or per-kind `blockers` rectangles,
  rasterised on a 0.5 m grid with BFS reachability (`backend/app/world/walkability.py`).
- **They can drift.** The two are separate models of the same buildings. Example: the backend opens the gatehouse
  passage x ±1.3 m, the frontend's opened door leaves leave about ±1.05 m. Both say "walkable", but a change to one
  is not checked against the other yet.

## Asset fixes at runtime

| Asset | Problem | Fix |
|---|---|---|
| Castle gatehouse | colliders and model come with the doors shut | `openDoors` swings both leaves inward; `openDoorParts` turns the matching collider parts the same way (D29) |
| Moat bridge | built to stand on a moat floor 1.6 m below the banks | placed at y = -1.68 so its deck lips meet flat ground (D30); revisit with terrain in M3 |

Every rendered placement goes through the same `openDoors` + `assetBaseY`, so visuals match collisions.

## Performance

Measured at spawn in follow view, 1280x800, Chrome headless on an M-series Mac.

| Measure | Value |
|---|---|
| Draw calls (`gl.info.render.calls`, incl. the shadow pass) | 157 (766 when every placement is its own mesh) |
| Triangles per frame (incl. shadow pass) | 1.28 M |
| fps, GPU (`--use-angle=metal`), follow / orbit | 60 / 60 (vsync cap) |
| fps, default headless (software WebGL), follow / orbit | 4.2 / 2.6 |
| Ready (town + colliders + avatar + models), warm cache | 1.4-3.6 s |

How: one `InstancedMesh` per sub-mesh of each kind's GLB (39 kinds, 101 meshes), one shared material per GLB, flat
tiles skip the shadow pass, and one 2048 shadow map covers an 80 m box that follows the camera's view. Headless
Chrome renders WebGL in software by default, far too slow for the town, so Playwright launches it with the Metal
GPU on macOS.

## Known limitations

- The follow camera clips into buildings when you back against them.
- Water is checked at the player's centre point, so the body can overhang a bank a little.
- No interiors (D19): doors are open, but buildings are solid inside.
- Townspeople walk fixed looping routes on y = 0 and ignore collisions until the simulation drives them (M5).
- Polyfork's node animations (swaying trees, turning water wheel) don't play on instanced models.
- The stream simply ends at the town's extent until terrain and rivers arrive in M3.
