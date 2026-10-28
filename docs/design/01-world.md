# 01 · World

## Shape and scale

The world is a **real sphere**: walk in one direction long enough and you come back home.

| Property | v0 value | Notes |
|---|---|---|
| Radius | 2 km (config) | circumference ~12.6 km, surface ~50 km² |
| Grid | hex sphere (subdivided icosahedron, Goldberg dual), frequency 60 | 10·60²+2 = 36,002 cells (12 pentagons), each ~40 m across |
| Walking speed | 5 km/h on flat ground | terrain multiplies cost (forest ×1.5, hills ×2, snow ×3, water impassable) |
| Walk around the world | ~2.5 game hours on the land loop | the world feels big because of terrain, danger and need, not raw distance |

```
        ⬡⬡⬡⬡⬡
     ⬡⬡⬡ 🏯 ⬡⬡⬡      every cell has 6 neighbours (12 have 5)
    ⬡⬡⬡⬡⬡⬡⬡⬡⬡⬡     cells hold terrain, biome, height, resources
     ⬡⬡ 🔥 ⬡⬡⬡⬡      entities have a continuous position + current cell
        ⬡⬡⬡⬡⬡
```

- The cell graph is the simulation's ground truth (pathfinding, perception ranges, resources). Rendering draws a smooth
  terrain mesh over it.
- **Required: a walkable land loop around the planet** (a ring of continents joined by land bridges or winter ice) so
  "leave home and come back from the other side" is possible on foot.
- Polyfork terrain kits are flat; we generate our own sphere terrain and only place Polyfork props (trees, rocks,
  houses, animals, people) on it, upright along the surface normal.

## Generation

Deterministic from `(seed, world spec)`:
1. **Procedural pass:** height (noise + continent masks), temperature by latitude and height, moisture, rivers flowing
   downhill to lakes/sea, biomes from temperature × moisture.
2. **Authored pass:** data files place the town, camps, landmarks and the land loop, then flatten/carve terrain to fit.
3. **Population pass:** plants, resources and animal herds by biome; citizens by region.

Same seed + same spec = same world. Specs and seeds are versioned with each run.

## Biomes

| Biome | Where | Key resources | Dangers |
|---|---|---|---|
| Ocean (deep / shallow) | ~40% of surface | fish, shellfish (shallows) | drowning, sharks (deep) |
| Beach / coast | shorelines | shellfish, driftwood, seaweed | - |
| Temperate grassland | mid latitudes | grasses, roots, deer, rabbits | wolves |
| Broadleaf forest | mid latitudes, wet | berries, nuts, mushrooms, wood, boar | bears |
| Conifer forest (taiga) | high latitudes | wood, pine nuts, elk | wolves, bears |
| Wetland / marsh | river mouths | reeds, birds, frogs, clay | snakes |
| Hills / mountains | continent spines | flint, stone, caves, goats | falls, cold |
| Savanna / dry scrub | warm, dry band | tubers, antelope | lions, heat |
| Tundra / snow / ice cap | poles, peaks | little; seals at coast | cold, polar bears |
| Rivers / lakes | everywhere downhill | fresh water, fish | currents |

## Regions

### The town (developed side)
A walled castle town in the style of the reference image: Japanese castle on a stone base, moat, wooden bridge, gate,
pagoda, shrine, market street, houses with tiled and thatched roofs, storehouses, a well, a water mill, rice paddies and
vegetable fields, bamboo, cherry trees, training ground with banners. About 300 m across, in a temperate river valley
near the coast. Walls and a fence keep animals out. Food is farmed and stored, so life is safer here.

### The wild (undeveloped side)
Everything else. Two Stone Age bands live in camps (hide shelters, fire pit, drying racks, flint knapping spot) near
water, far from the town and from each other. They gather, hunt and fish with stone tools and fire. No farming, no
metal, no writing; they can paint on cave walls.

## Landmarks (v0)
Each is a named place citizens can learn about, travel to and talk about.

1. **The castle**: heart of the town.
2. **Smoking mountain**: a volcano on the main continent, visible from far away.
3. **Great falls**: a river drops off a cliff into a lake.
4. **Elder tree**: a giant ancient tree in the broadleaf forest.
5. **Standing stones**: a ring of rocks on a grass hill (natural, or left by "those before").
6. **Painted cave**: a cave near band A's range with old paintings.
7. **Ice gate**: an ice bridge near the pole that closes the land loop.
8. **Hot springs**: warm pools in the mountains, welcome in the cold.

## Time and light
- One global game clock that runs in **real time by default**: speed = game seconds per real second, so at ×1 a game
  day lasts a real day and citizens walk at the player's pace (D61). Spectators can pause or pick ×10, ×60 (a game
  hour per real minute, a day in 24 real minutes) or ×600 for a time-lapse (a day in 2.4 real minutes).
- The simulation still ticks once per game minute (every 60 / speed real seconds); clients draw walkers moving along
  the path each tick streams ahead (`route`, `speed_mps`), so motion stays smooth even with a real minute between
  ticks.
- The sun lights one side of the planet: **local time depends on longitude**, so the town can be in daylight while a
  band on the far side sleeps. Night is dark and dangerous (predators hunt at dusk and night).
- v0 has no seasons or weather. v1 adds axial tilt (seasons, winter, snow line moving) and simple weather.
