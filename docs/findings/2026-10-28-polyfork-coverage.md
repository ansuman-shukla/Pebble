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

- ~~M4: biome vegetation and rock kinds for the planet (Nature, Alpine, Prehistoric kits).~~ Done, see below.

## M4: biome vegetation and landmark kinds (2026-10-28)

34 more assets (**+3.2 MB**, manifest total 96 assets / 26.9 MB). All rest on y = 0, centred, real-world size (checked
by bounding box and in the `/gallery` plants & rocks view), so none needs an `assetBaseY` offset. 190-900 triangles
each, 1 primitive each except the alpine snow pieces, the volcanic vents and sagebrush (2-11).

### Kinds

| Kind | Asset | Kit | Tris | Size x·y·z (m) |
|---|---|---|---|---|
| oak_tree | broadleaf-oak-997c22 | Nature & Forest | 457 | 4.5·7.0·3.6 |
| birch_tree | birch-tree-181b33 | Nature & Forest | 619 | 3.0·6.5·2.1 |
| pine_tree | tall-pine-tree-ab4108 | Nature & Forest | 350 | 3.7·9.0·3.6 |
| young_pine | young-pine-0d7695 | Nature & Forest | 270 | 1.8·3.0·1.9 |
| snowy_spruce | snow-laden-spruce-36716e | Alpine and Snow | 765 | 3.0·6.1·3.0 |
| acacia_tree | espino-cd3edd | Chile Fiestas Patrias | 791 | 4.6·3.5·4.0 |
| tree_fern | tree-fern-78320e | Prehistoric Valley | 794 | 4.4·8.0·4.0 |
| dead_tree | dead-tree-6795fa | Nature & Forest | 536 | 3.2·5.0·1.9 |
| dwarf_pine | dwarf-pine-mat-faee77 | Alpine and Snow | 798 | 2.5·1.3·2.5 |
| bush | round-bush-cd2ac0 | Nature & Forest | 573 | 1.3·0.6·0.9 |
| dry_bush | sagebrush-700b03 | Frontier Town | 684 | 1.1·0.8·0.8 |
| fern | fern-plant-1559b8 | Nature & Forest | 802 | 1.0·0.7·1.0 |
| grass_tuft | grass-tuft-a40a08 | Nature & Forest | 368 | 0.3·0.4·0.3 |
| dry_grass | grass-tuft-62e90c | Salvage Commons | 532 | 0.3·0.3·0.3 |
| dune_grass | marram-grass-tuft-8c7a99 | Coast and Boardwalk | 574 | 1.2·0.9·1.1 |
| wildflower | wildflower-68d3a1 | Nature & Forest | 405 | 0.2·0.4·0.2 |
| cattail | cattail-reed-6abbb3 | Nature & Forest | 388 | 0.4·1.2·0.3 |
| driftwood | driftwood-log-90340b | Pirate Cove | 522 | 2.0·0.8·0.8 |
| termite_mound | termite-mound-9bc94b | Prehistoric Valley | 762 | 1.5·2.0·1.5 |
| small_rock | small-rock-db33a7 | Nature & Forest | 202 | 0.4·0.2·0.3 |
| boulder | large-boulder-a29b99 | Nature & Forest | 566 | 2.2·0.7·1.4 |
| coastal_boulder | large-coastal-boulder-a2cab1 | Pirate Cove | 190 | 2.4·1.5·1.7 |
| rock_outcrop | rock-outcrop-158ac3 | Alpine and Snow | 756 | 2.5·2.1·2.5 |
| boulder_field | boulder-field-cluster-08e364 | Alpine and Snow | 734 | 2.5·1.5·2.0 |
| scree | scree-heap-42cce5 | Alpine and Snow | 674 | 2.5·0.5·2.5 |
| ice_block | ice-chunk-b23ad7 | Space Base | 253 | 0.8·0.9·0.9 |
| rock_spire | rock-spire-13819c | Nature & Forest | 378 | 1.3·3.5·1.5 |
| basalt_column | basalt-column-outcrop-f1339d | Prehistoric Valley | 408 | 1.5·3.0·2.0 |
| lava_rock | lava-rock-pile-d56d19 | Prehistoric Valley | 866 | 2.0·0.9·1.5 |
| obsidian | obsidian-shard-cluster-c8f5d3 | Prehistoric Valley | 530 | 1.0·0.9·1.0 |
| fumarole | fumarole-vent-8280ba | Prehistoric Valley | 898 | 1.5·1.6·1.5 |
| geyser | geyser-cone-2b5033 | Prehistoric Valley | 524 | 3.0·1.2·3.0 |
| hot_spring_pool | hot-spring-pool-26312c | Prehistoric Valley | 680 | 3.0·3.3·2.5 (with steam) |
| giant_tree | oak-tree-50ee7c | Medieval Village | 686 | 5.1·6.2·4.2 (drawn ×3-4, D39) |

The biome table also reuses the camp/town kinds `rock` (medium rock), `fallen_log` and `reeds`.

### Biome coverage (`frontend/src/lib/world/biome-props.ts`)

| Biome | Kinds | Instances / cell | Tris / cell |
|---|---|---|---|
| broadleaf forest | 5 oak, 3 birch, bush, fern, grass, fallen log, rock | 19.6 (8 trees) | ~10.8k (6.1k without grass/fern) |
| taiga | 7 pine, 3 young pine, 0.5 snowy spruce, fern, small rock, fallen log | 12.8 (10.5 trees) | ~4.8k |
| wetland | cattail, reeds, grass, birch, tree fern, dead tree | 18.0 | ~8.3k |
| grassland | grass, wildflowers, bush, 0.4 oak, rock | 16.3 | ~6.3k (0.6k without grass/flowers) |
| savanna | dry grass, dry bush, 0.8 acacia, small rock, termite mound, dead tree | 13.8 | ~7.7k |
| hills | grass, small rock, rock, boulder, bush, oak, rock spire | 10.5 | ~4.0k |
| mountain | small rock, outcrop, scree, boulder field, dwarf pine, snowy spruce | 5.9 | ~3.3k |
| tundra | dry grass, small rock, dwarf pine, rock, boulder field | 9.3 | ~4.3k |
| snow | snowy spruce, boulder field, outcrop, ice block | 2.5 | ~1.7k |
| ice | ice block (scaled 1.5-3.5) | 1.2 | ~0.3k |
| beach | dune grass, driftwood, coastal boulder, small rock | 5.4 | ~2.4k |
| volcanic | lava rock, small rock, basalt column, obsidian, dead tree, fumarole | 4.4 | ~2.7k |
| oceans, lake | none | 0 | 0 |

Budget: a cell is ~1,400 m² (sphere area / 36,002), so a 600 m radius holds ~810 cells. All-forest worst case at full
radius is ~8.7M triangles; a mixed land view is ~2.5M. Recommendation for the globe viewer: draw grass, flowers, ferns
and small rocks only within ~150 m (~50 cells) and trees/rocks to 400-600 m, which keeps a forest view at ~2-5M
triangles. Draw calls are one instanced mesh per (kind, primitive): 71 primitives across all new kinds, at most ~25
kinds visible in one area.

### Gaps and substitutions

| Need | Search coverage | Used |
|---|---|---|
| acacia | ok, 1 hit | espino (Chile kit): Vachellia caven, a real South American acacia with the flat crown |
| dry savanna bush | poor | sagebrush (Frontier Town) |
| marsh tree (willow, mangrove, swamp cypress) | none (the only cypress is a columnar Mediterranean one) | birch (bog birch) + dead tree (snags) in wetlands |
| ice block / glacier | none ("Ice Chunk" in the Space Base kit is the only ice) | ice-chunk-b23ad7, scaled 1.2-3.5 in snow/ice |
| tundra, lichen, heather | none/poor | dwarf pine mat (snowy krummholz) + dry grass + small rocks |
| snow-free scree / outcrops | Alpine pieces all carry snow | alpine outcrop/scree/boulder field only in mountain, tundra and snow; hills use the mossy Nature boulder, medium and small rocks and the rock spire |
| geyser plume | cone only, no water column | geyser-cone-2b5033; an eruption plume would be a runtime effect |

Not used: Prehistoric Valley dinosaurs/eggs/fossils (out of setting), ginkgo (1,080 tris, no clear biome slot),
dawn redwood (20 m conifer; a broadleaf reads better as the elder tree), windblown larch, dead snag (has a figure).

### Gotchas

- Alpine and Snow vegetation and rocks stand on a white snow pad: in a green biome they show white discs, so they're
  limited to cold biomes and the snowy spruce is rare in the taiga (0.5 per cell). Biasing it to the coldest cells
  would need temperature in the scatter input.
- `hot_spring_pool` is 3.3 m tall because its steam column is modelled in; its footprint is 3 × 2.5 m.
- Polyfork thumbnails can be fetched from `https://polyfork.dev/files/{id}/renders/hero.png` to compare candidates.
