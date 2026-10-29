# Findings: Polyfork asset pack for World v1 (2026-10-29)

What the catalogue gives the World v1 bible (`docs/design/10-world-v1.md`), which kind draws which asset, and the
gaps other streams fill at runtime. Decisions D132-D134.

## Size

| What | Number |
|---|---|
| New pinned assets | 25 (+2.3 MB GLB + params + colliders) |
| Manifest total | 121 assets, 29.2 MB |
| New triangles | 298-1 668 per asset, 1-12 primitives |
| Remix bakes used | **0** (quota left 100/100 this month) |

All were added with `node scripts/fetch-polyfork-assets.mjs --add <ids>`: plain `/cdn` GLBs, no remix (D132).

## Kind → asset

Every kind rests on y = 0, centred, at real size (checked in the gallery's new *props & tools* view).

### Nodes and their stages (kinds named by the node kind)

| Kind | Asset | Kit | Tris | Size x·y·z (m) | Stage hooks in the model |
|---|---|---|---|---|---|
| berry_bush | berry-bush-ee4812 | Cozy Farm | 720 | 0.73·0.97·0.65 | `fruit-0` … `fruit-7` (8 pieces; the bible's round(9 × stock/cap) needs 9: map 0-9 onto 0-8) |
| root_patch | taro-plant-8c0493 | Easter Island | 738 | 1.35·1.04·1.29 | `corm` + `leaf-N`, baked `tick` sway |
| reed_bed | totora-reed-bed-36d78f | Easter Island | 917 | 2.25·2.5·2.33 | two skinned reed meshes with a baked `tick` gust clip |
| nut_tree | broadleaf-oak-997c22 (the oak_tree asset) | Nature & Forest | 457 | 4.5·7.0·3.6 | – |
| tree_stump | tree-stump-ec3f48 | Nature & Forest | 505 | 0.82·0.48·0.72 | same kit as the oak, birch and pines |
| flint_seam | ballast-heap-2fb138 | Countryside Railway | 808 | 3.17·0.81·1.92 | `heap` + 3 `weed-N`; grey, no snow pad |
| obsidian_field | lava-rock-pile-d56d19 (the lava_rock asset) | Prehistoric Valley | 866 | 2·0.9·1.5 | black heap ("as flint, black") |

Already vendored and named in the bible: `rice_paddy`, `fallen_log`, `driftwood`, `dead_tree` (deadwood),
`firewood` (log pile), every tree species, `drying_rack` (hasa field racks), `bell_tower`, `storehouse`, `banner`.

### Dens, remains, roads and markers

| Kind | Asset | Kit | Tris | Size (m) | Note |
|---|---|---|---|---|---|
| cave_mouth | smuggler-cave-mouth-69a07e | Pirate Cove | 1 027 | 5.02·3.99·1.88 | grey rock arch over a dark mouth |
| bone_scatter | bone-scatter-90313d | Dungeon & Crypt | 621 | 0.88·0.16·1.47 | remains and den dressing |
| signpost | trail-signpost-bd29a7 | Nature & Forest | 420 | 1.15·2·1.16 | rigged boards `board-top`, `board-mid` (two arms: the two places) |
| log_bridge | log-plank-bridge-a5f74f | Nature & Forest | 480 | 4·1.33·1.72 | 4 m span; tile it along wider crossings |
| boundary_stone | garden-rock-2d3b51 | Little Tokyo | 340 | 0.9·0.52·0.82 | mossy grey stone; the claim marker pairs it with a `banner` |
| cairn | pipi-horeko-cairn-f5db4b | Easter Island | 732 | 0.99·1.79·1 | stacked-stone band marker, no snow |

### Stores, stations and furniture

| Kind | Asset | Kit | Tris | Size (m) | Note |
|---|---|---|---|---|---|
| market_stall | market-stall-94937d | Medieval Village | 592 | 1.96·2.02·1.13 | detachable `crates` (dress by stock) |
| forge | blacksmith-forge-09fa85 | Medieval Village | 1 668 | 5.08·3.96·4.03 | open smithy with its own `anvil` and `fire` parts |
| anvil | anvil-1286cb | Medieval Village | 686 | 0.81·0.82·0.76 | anvil on a stump, a station on its own |
| chest | timber-crate-ba0739 | Dungeon & Crypt | 588 | 0.79·0.66·0.79 | rigged `lid` (opens on stash / pick_up) |
| grain_sack | grain-sack-401d96 | Medieval Village | 448 | 0.58·0.73·0.55 | rice and grain sacks, granary dressing |
| coin_pouch | coin-pouch-be4dd8 | single asset | 340 | 0.29·0.34·0.29 | coins on the ground |
| camp_drying_rack | drying-net-rack-93ec3b | Pirate Cove | 576 | 2.2·1.66·0.82 | pole frame with a hanging `net` (the band's meat rack) |
| sleeping_mat | straw-pile-ebd54d | Dungeon & Crypt | 627 | 1.2·0.25·0.9 | straw bedding for band mats |
| field_barricade | field-barricade-a646b9 | Medieval Japan | 626 | 2·1.4·0.84 | pieces of the gaol pen |

Backend footprints for these kinds (R1's `data/town/kinds.yaml`, P1's `data/world/kinds.yaml`) take x·z from the
size column (rotation 0, models face +z).

### Hand props (`HAND_PROPS`, D133)

| Hand prop | From | Size (m) |
|---|---|---|
| axe | hand-axe-cee9e7 (Dungeon & Crypt) | 0.3·0.6·0.08 |
| hoe | garden-hoe-3974ad (Cozy Farm) | 0.4·1.5·0.26 |
| hammer | hammer-fa3e51 | 0.16·0.32·0.04 |
| torch | torch-stake-d82a2c (Pirate Cove), `flame` part | 0.29·1.5·0.3 |
| spear | yari-spear-e72c1f (Medieval Japan); the engine also has `yari` | 2.6·0.07·0.18 |
| basket | kete-reed-basket-6ca36c (already vendored; the engine also has `produce-basket`) | 0.45·0.41·0.22 |
| coin_pouch | coin-pouch-be4dd8 (the engine also has `coin-pouch`) | 0.29·0.34·0.29 |
| sack | grain-sack-401d96 (the bundle on the back) | 0.58·0.73·0.55 |
| pick | humanoid wardrobe `pick` (no model in the catalogue) | – |
| fishing_rod | humanoid wardrobe `fishing-rod` (no model in the catalogue) | – |

Other right-hand wardrobe items worth knowing: `ore-sack`, `shovel`, `monk-staff`, `bottle`, `paper-cup`,
`carving-knife`, `produce-basket`, `coin-pouch`. A wardrobe item rebuilds the character mesh; a model is attached to
the hand bone and can be dropped while lying (M1's choice per prop).

## Kit looks (`kit-looks.ts`, D134)

The Medieval Japan kit's `buddhist-monk-39f498`, `ashigaru-foot-soldier-806707` and `farmer-363820` as
`CharacterConfig`s in their default colourway, for R1's Ennen, Goro and Tokuji (and Tetsu/Daisuke: farmer base +
`apron`, `headwrap` or `straw-hat`).

- The monk and ashigaru modules embed a **newer engine** than our pinned one (33 k vs 25 k lines). Every garment they
  use (`kesa`, `mala`, `monk-staff`, `do-maru`, `jingasa`, `work-gloves`, `yari`, `mino`) exists in the pinned
  engine, so we keep it: bumping it would rebuild all 15 v0 looks.
- Built on the pinned engine they make the same meshes per slot as the modules do; vertex counts differ because the
  modules pass a coarser body `seg` that `CharacterConfig` doesn't expose (our looks keep the engine default, like
  the 15 v0 looks), and the monk's staff hand stays open (the module's `hand.grip` isn't exposed either).

## Gaps and how they are covered

| Bible need | Catalogue | Covered by |
|---|---|---|
| loom | none ("loom", "weaving", "spinning", "textile": no match; the kit's jinmaku camp curtain reads as a banner) | procedural, as the bible's slot table says (L4/M1); no asset |
| gaol | no cage or stocks in a fitting style | a pen of `field_barricade` (kit piece) around the gaol place |
| sickle, gold pan, stone axe, knapping stone, cup, cloth bolt, meat, hide | none or out of style | M1/L4: procedural or tinted stand-ins (stone axe = hand axe with a grey head) |
| sapling | no broadleaf sapling | the node's own tree kind drawn at growth scale (L3) |
| paddy stages (water, seedlings, green, gold, stubble) | only as `season`/`harvested` remix knobs | L3 tints at runtime: remixes are not vendored (D132) |
| rice sheaves, sacks, meat on racks | hasa rack sheaves are one mesh | L4 dressing hooks (`crates`, `grain_sack` instances) |
| waterhole, fishing ripples, iron-sand patch, gold glints | – | water surfaces, L2 ground marks, L3 effects |
| geode | `mineral-geode-cluster-299927` exists | not vendored: no bible kind draws a geode (crystals read as fantasy); flint and obsidian use scree heaps |

## Gotchas

- `wooden-crate-b9c96a` (Medieval Village) has no `-params.json` (404) and the fetch script needs one; the Dungeon &
  Crypt `timber-crate-ba0739` (same look, rigged lid) replaced it.
- The reed bed and the dune grass (`marram-grass-tuft-8c7a99`) are **skinned** meshes: `scene.clone(true)` leaves
  them bound to the source skeleton and they vanish (the gallery drew the dune grass as a bare disc). Clone with
  `SkeletonUtils.clone`; `kindParts` (instanced bind pose) is fine.
- Remix GLBs (`/cdn/{id}-remix.glb?p=…`) cost a bake each from an anonymous quota of 40/hour and 100/month, and a
  pinned remix URL would hit the bake endpoint again on every fresh `fetch-assets` (each worktree): never pin one.
- Polyfork search (`GET /api/assets?q=…&free=1`) answers 403 to Python's default user agent; send a curl-like one.
