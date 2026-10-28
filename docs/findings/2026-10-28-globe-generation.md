# Finding: generating the round world (M3)

Built against [the globe contract](../plans/2026-10-28-globe.md). Code: `backend/app/world/` (`grid`, `noise`,
`sphere`, `spec`, `terrain`, `hydrology`, `biomes`, `paths`, `generate`, `view`, `store`), spec in
`backend/data/world/{world,kinds}.yaml`, API `GET /api/v1/world`.

## Pipeline

```
world.yaml ─▶ grid (icosahedron f=60) ─▶ base terrain ─▶ site shapes ─▶ authored river channels
                                         (continents,     (plateaus,      (monotone cuts, plateaus pinned)
                                          loop band,       hill, volcano,          │
                                          ranges, noise)   falls + bowl)           ▼
   sites + anchors ◀─ land loop ◀─ biomes ◀─ climate ◀─ lakes + rivers (priority flood, accumulation)
```

| Step | What it does |
|---|---|
| grid | 12 corners, 30 edges, 20 faces; cells = vertices (order: corners, edge interiors, face interiors); triangles CCW from outside; neighbours sorted, padded with -1 |
| terrain | continental field = max(continent caps, land-loop band) on domain-warped positions + coast fBm + island fBm − authored seas; land height = lowland ramp + hills fBm + ridged relief + authored ranges; sea floor to −120 m over a wide shelf; then 6 Laplacian passes (strength 0.5) over all heights, clamped back to each side of sea level so the coastline stays |
| sites | town plateau h0 = 8 m (r 270 m, blend to 340 m); around every plateau and hill the ground rises or falls at most 0.6 (≈ 31°) from the rim; camps and cave = plateaus at terrain height; standing stones = hill (+18 m); volcano = cone 320 m with a 95 m crater, floor 290 m; great falls = upland at the 70 m lip, lake bowl 40 m lower |
| channels | authored rivers (`town-river` past the town's mill stream, `falls-river`, `falls-outflow`) are cut 3 m into the terrain as non-increasing profiles; plateau cells keep their height; a river leaving a lake bowl starts no higher than the bowl's surface |
| water | priority flood from the ocean; a depression ≥ 3 m deep holds a lake: open (fills to the spill level, drains on) if ≤ 8 m deep, else closed (surface 8 m above the bottom, a sink with dry slopes). Repeated until no new lake. Shallower depressions become exactly level flats |
| rivers | flow tree = flood parents; cells draining ≥ 60 cells are river; each spring traces down to the sea, a lake or a river it joins; lake outflows start in the lake |
| climate | temperature by latitude (30 °C → −25 °C, exponent 1.6) minus 0.08 °C/m; moisture = fBm + falloff with distance to water |
| biomes | water → frozen (ice, snow) → mountain → beach → hills → tundra → taiga → wetland → savanna → forest → grassland; frozen lakes become ice; sites paint volcanic / grassland / broadleaf / ice |
| land loop | Dijkstra through the spine waypoints over walkable cells inside the band (cost pulls toward the spine), loop-erased into a simple cycle |

## Stats (seed 20261028, generator `m3.2`)

| | |
|---|---|
| cells / triangles | 36,002 / 72,000 (cell spacing 30-44 m) |
| land (h ≥ 0) / walkable | 55.7 % / 54.5 % |
| heights | −120 m … 318.8 m (volcano rim); 50th-highest land cell 247 m |
| land slopes (grid edges) | 0.8 % over 40°, p95 29°, steepest 56° (falls cliff, volcano); coast edges p95 34° (m3.1: 10.3 %, 49°, 77°; coasts 44°) |
| rivers | 42 (667 cells); lakes 1.2 % of cells, none above 60° latitude (smoothing filled the polar hollows) |
| land loop | 348 cells, 13.7 km (≈ 2.75 h at 5 km/h), latitudes 4.6° … 71.2° |
| generation | 0.97 s (grid 0.21, terrain 0.36, sites 0.03, water 0.27, biomes 0.05, loop 0.05) |
| payload | 1.99 MB JSON, 0.86 MB gzip (level 6; level 9 is 3× slower for the same size) |

| Biome | Share | Biome | Share | Biome | Share |
|---|---|---|---|---|---|
| deep_ocean | 29.6 % | hills | 8.1 % | snow | 2.6 % |
| shallow_ocean | 14.7 % | grassland | 14.8 % | ice | 3.3 % |
| beach | 3.0 % | broadleaf_forest | 11.4 % | lake | 1.2 % |
| taiga | 1.9 % | mountain | 1.7 % | volcanic | 0.2 % |
| wetland | 0.5 % | savanna | 4.8 % | tundra | 2.2 % |

The wider shelf moved ~6 % of the planet from deep to shallow ocean. (m3.1 shares: deep 35.8, shallow 8.5, mountain 3.3 %.)

## Sites

| Site | lat, lon | h0 | Where |
|---|---|---|---|
| town | 38, 12 | 8.0 | Ashland, temperate grassland valley; Mill river along its west side (local x ≈ −156, the mill stream); Bright gulf ≈ 300 m east |
| band_a_camp | 12, 100 | 58.1 | Eastreach, 80 m from a river; 2.8 km from the town |
| band_b_camp | −6.3, −152.6 | 49.9 | Westmark, 80 m from water; 5.1 km from the town, 3.8 km from band A |
| smoking_mountain | 18, −20 | 290 (crater floor) | Ashland; the highest point, visible from far |
| great_falls | 5, 15 | 70 (lip) | Falls river runs across the upland and drops 37-40 m into its lake (surface 30 m), which drains south to the sea |
| elder_tree | 10, 2 | 107.0 | broadleaf forest |
| standing_stones | 28, −4 | 123.6 | grass hill on the loop road |
| painted_cave | 20, 108 | 74.9 | 390 m from band A |
| ice_gate | 71, −55 | 4.0 | the loop's ice bridge between two sounds |
| hot_springs | 46, −18 | 228.5 | snowy Greyspine range |

## How the land loop is guaranteed

1. `land_loop.waypoints` in the spec form a closed spine around the planet (continents, two land bridges, the ice gate).
2. The inner half of the band (`core_fraction` 0.5, measured on unwarped positions) is forced to land at least 3 m
   high and may not hold lakes; seas and coast noise can't cut it.
3. The ice gate site is a waypoint; two authored seas ("gate sounds") narrow the land around it.
4. The loop is the cheapest walk through the waypoints over walkable cells inside the band, loop-erased; generation
   fails if it can't close or misses the gate. Tests check: simple cycle of neighbours, all walkable, longitude winds
   exactly once (±360°), passes the gate cell, and every site is reachable from the town.

## Smoothing (m3.2)

- Six Laplacian passes on the base heights calm the ridged relief and hills fBm (`terrain.smoothing` in the spec);
  relief dropped from 150 to 130 m. Each land cell is clamped back to ≥ 1 m and each sea cell to ≤ −2 m afterwards, so
  the coastline is exactly the unsmoothed one.
- The town blend made a 180 m wall west of the town (smoothstep over 70 m, ~75°). Plateaus and hills now cap the
  rise or fall from their rim at 0.6 m per m, cutting a valley into higher ground instead of a wall.
- The town plateau reaches 270 m so every grid triangle under the town's 225 m ground disc is level (with 230 m the
  triangles across the disc edge sloped down and showed the disc's skirt).

## Known limits

- Grid edges vary from 30 to 44 m (the icosahedron is subdivided linearly, then projected); fine for v0.
- Lakes are flat at their surface height in `heights`; the client draws them as water at that height.
- Filled depressions that don't hold a lake become exactly level flats.
- Rivers are cell paths (fordable, no width); tributaries end on the river they join.
- The ice gate band is ~4-6 cells wide; noise decides the exact outline.
- Landmark placements name kinds that the frontend adds in parallel (`rock_spire`, `boulder`, `basalt_column`,
  `lava_rock`, `fumarole`, `obsidian`, `hot_spring_pool`, `giant_tree`, `snowy_spruce`, `ice_block`); their footprints
  in `data/world/kinds.yaml` are the drawn asset sizes (M4, D40).
- Other seeds generate valid worlds too (tested 1, 2, 3, 99, 12345), but site placement is authored for 20261028.
