# Findings: Polyfork coverage for town, camps, people and animals (2026-10-28)

What the Polyfork catalogue gives us for M1, where the gaps are and how we close them.

## Size and loading

| What | Number |
|---|---|
| Pinned assets (`frontend/src/lib/world/asset-manifest.json`) | 62 |
| Total GLB + params + colliders | ~23.7 MB |
| Town asset size | 50-400 KB each |
| Animal asset size | 0.9-1.9 MB each (GLBs carry baked Idle/Walk/Run clips; fish and shark: Idle/Swim/Swim fast) |

The initial town load stays well under the 30 MB budget; animals load lazily.

## Town (Medieval Japan kit)

| Need | Covered by |
|---|---|
| Castle | keep (tenshu), gatehouse, corner turrets, stone + plaster walls, moat bridge |
| Homes and work | townhouses, farmhouse, storehouse, water wheel (= mill), rice paddy tiles, drying racks, well |
| Religion and civic | temple hall, pagoda, bell tower, lookout tower, stair |
| Street dressing | teahouse, fences, lanterns, banners, trees |
| **Shrine** | **no dedicated part**: the temple hall stands in |
| **Market stalls** | **no dedicated part**: machiya shop fronts + teahouse form the market street |

Buildings ship convex-hull colliders (`-colliders.json`); we vendor them for M2 collisions.

## Stone Age camps

| Kit | Parts |
|---|---|
| Nature & Forest | stone fire pit, firewood, lean-to shelter, cook tripod, fallen log, rock |
| Easter Island | reed basket, reed torch, petroglyph boulder (for the painted cave) |

## People

- Every Polyfork humanoid comes from **one engine** driven by a config: age, figure, build, palette and a garment in
  each of 14 slots. Each character `.mjs` embeds the whole engine (~1 MB) with a 150+ item wardrobe.
- We vendor one (`farmer-363820`) as `src/vendor/polyfork/humanoid.mjs`, append `export { createCharacter }` (a
  reproducible, hash-pinned patch in the fetch script) and author our own 15 citizen configs in
  `src/lib/world/citizen-looks.ts`.
- **Stone Age gap** (no caveman characters) is closed with the wardrobe: hide tunics, fur stoles/mantles, long hair,
  beards, bare feet, spears (yari), baskets, ochre arm bands (tattoos).
- All 15 share the Mixamo-named 31-joint rig.

### Animation clips: the one runtime dependency

Clips (Idle/Walk/Run and more) are baked from Mixamo. Polyfork's licence lets them be served only from its CDN, so the
vendored `clips.mjs` fetches them from `https://polyfork.dev/cdn` at runtime. **Offline, citizens fail to animate.**

## Animals

| Status | Animals |
|---|---|
| Found | deer, rabbit, hare, fox, wolf, black bear, alpine ibex, lion, reef shark, reef fish, duck, pig |
| Not in catalogue | elk, antelope, seal, snake, polar bear, boar (searches return none or poor matches) |

Polyfork models use flat vertex colours, and remix GLBs lose their animations, so stand-ins are recoloured at runtime:

| Missing | Stand-in |
|---|---|
| elk | deer, darker, scale ×1.3 |
| antelope | deer, lighter, scale ×0.8 |
| boar | pig, dark brown |
| polar bear | black bear, white, scale ×1.15 |
| goat | alpine ibex (`goat-1dedee` has no clips) |
| seal, snake | dropped in v0 |

## Gotchas

- drei `<Html>` dropped one label (React root unmount race, also in the production build), so we render labels in
  our own single DOM overlay.
- Polyfork's anonymous remix bake quota is 40/hour, 100/month.

## Deferred

- M4: biome vegetation and rock kinds for the planet (Nature, Alpine, Prehistoric kits).
