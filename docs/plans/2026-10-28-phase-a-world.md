# Plan: Phase A, building the world (M0-M9)

Execution brief for the milestones in `docs/design/09-roadmap.md`. Read `docs/README.md` and the design docs first;
this file adds the build order, asset sources and working rules. No agent minds are connected in phase A.

## Build order and branches

One branch + PR per milestone, from the latest `main`, named `ansuman/<type>/<slug>`; small conventional commits.

| Milestone | Branch (suggested) | First deliverable to show |
|---|---|---|
| M0 | `ansuman/build/m0-scaffold` | empty backend + frontend pass lint/tests; health endpoint shown in the browser |
| M1 | `ansuman/feat/m1-characters-assets` | gallery of the 15 citizens (Stone Age remixes included) and v0 animals, animating |
| M2 | `ansuman/feat/m2-walkable-town` | walk in through the gate and along the town's streets in third person |
| M3 | `ansuman/feat/m3-globe` | `/world` returns a seeded hex-sphere with biomes, rivers, town, camps, landmarks |
| M4 | `ansuman/feat/m4-planet-viewer` | the static planet in the browser, orbit down into the town |
| M5 | `ansuman/feat/m5-sim-core` | a test citizen walks, drinks, eats, sleeps through `world_api` |
| M6 | `ansuman/feat/m6-ecology` | herds, predators, plant regrowth, fire over 10 headless game days |
| M7 | `ansuman/feat/m7-scripted-citizens` | 15 citizens live 10+ game days |
| M8 | `ansuman/feat/m8-live-spectator` | follow any citizen live; replay any moment |
| M9 | `ansuman/docs/m9-world-gate` | checklist ticked, findings note |

## Accepted defaults (from `docs/decisions.md`)
Castle-town look (~1600, stone-based keep); Postgres via `docker compose` on port 5544 with data in
`.runtime/postgres`; Python 3.12; world radius 2 km; 1 real s = 1 game min; the dead stay dead; react-three-fiber +
drei; harness leaks are logged, not rewritten.

## 3D assets: Polyfork

- Site: https://polyfork.dev. **Every low-poly part is free**, commercial use, no attribution. No account needed for
  `/cdn` files; whole-kit zips (`/dl/kit-<id>.zip`) need a free account.
- Agent guide (fetch at the start of asset work, it stays current): https://polyfork.dev/prompt.txt
- REST (no key): `GET /api/kits`, `GET /api/kits/{id}`, `GET /api/assets?q=…`, `GET /api/assets/{id}`,
  `GET /api/assets/{id}/matching`, `GET /cdn/{id}.glb`, `GET /cdn/{id}-params.json`, `GET /cdn/{id}.mjs`.
- Optional MCP: `https://polyfork.dev/mcp` (HTTP). Optional key `POLYFORK_KEY` in `.env` only.
- Assets carry real size in metres, origin on the ground, palette, triangle count, rig/IK flags.

### Kit → world mapping

| World part | Kit (id) | Use | Skip |
|---|---|---|---|
| Town | **Medieval Japan** (`medieval-japan-cb01ad`, 60 parts) | castle gatehouse, corner yagura turrets, ishigaki stone wall, dobei plaster wall, moat bridge, machiya townhouse, minka farmhouse, kura storehouse, temple hall, teahouse, roofed well, stream water wheel, rice paddy tiles, hasa drying racks, bamboo fence, cherry/maple/sculpted pine, lanterns, banners; people: daimyo lord, samurai, ashigaru, farmer, monk | - |
| Temperate forest, grassland, camps | **Nature & Forest** (`nature-forest-kit-f29d6a`) | oak, maple, birch, pines, bushes, rocks, fallen logs, reeds, stone fire pit, lean-to shelter, firewood; forest deer, rabbit, red fox, black bear | truck, ranger station, outhouse, signage, picnic table |
| Taiga, mountains, poles | **Alpine and Snow** (`alpine-and-snow-092f66`) | snow-laden spruce, dwarf pine, rock outcrops, scree, boulder fields, frozen waterfall; ibex, mountain hare | ski lifts, snowcat, huts, modern gear |
| Volcano, hot springs, landmarks | **Prehistoric Valley** (`prehistoric-valley-8638dc`) | hot spring pool, geyser, fumarole, basalt columns, lava rocks, obsidian, tree ferns, ginkgo, dawn redwood, hollow logs | all dinosaurs, eggs, fossils |
| Stone Age material culture | **Easter Island** (`easter-island-rapa-nui-368e86`) | obsidian blade, reed torch, petroglyph boulder, plants | moai and island-specific monuments (except as optional landmark) |
| Coast and sea | **Coast and Boardwalk**, **Coral Reef** | rocks, driftwood, reef, fish | boardwalk, modern props |
| Other animals | search `/api/assets` | wolf, boar, goat, lion, shark, seal, fish (all found as free assets) | - |

### Known gaps (check in M1, fill or report)
- **Stone Age people:** no caveman/hunter-gatherer characters found. Check https://polyfork.dev/characters, try
  remixing villagers via params (clothing palette), and file the gap with Polyfork's `report_need`. Fallback: simple
  parametric stand-ins.
- **Elk, polar bear, antelope, snake:** not found or not checked yet; search, otherwise drop or substitute in v0.
- Kits have their own flat procedural terrains; we only use their props (our ground is the sphere).

### Asset rules
- Vendor files into `frontend/public/assets/polyfork/<asset-id>/` (GLB + params JSON + licence), never hotlink.
- A committed manifest (`frontend/src/lib/world/asset-manifest.json`: id, title, kit, size, triangles, sha256) and a
  fetch script (`frontend/scripts/fetch-polyfork-assets.mjs`) make downloads reproducible.
- The backend names prop **kinds** only (`castle_gatehouse`, `pine_tree`, `deer`); the frontend registry maps kinds to
  files. Placement data (positions, rotation, scale) comes from the backend world spec.
- Budget: ≤ 30 MB initial assets, instanced repeated props, LOD for distant views.

## Working rules
- Stay inside `/Users/ansuman/Documents/Pebble`. Never touch the main devin-switch, the installed `ds`, global
  Devin/Claude config or other repos. Launchers use `env -i` with state in `.runtime/`.
- Follow the Associo-style layout in `docs/design/08-architecture.md`; ask before inventing a new top-level pattern.
- Tests that fail when the feature breaks (determinism, invariants, reachability); Playwright smoke for the viewer.
- Record non-obvious findings in `pocket.md` (local) and committed summaries in `docs/findings/`.
- Decisions not covered by the docs: stop and ask, with a recommendation.
