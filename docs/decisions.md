# Decisions

## Accepted

| # | Decision | Why | Date |
|---|---|---|---|
| D1 | Phase A completes the world with scripted citizens; agents enter only after the M9 gate | agents should get a finished world and a frozen contract | 2026-10-28 |
| D2 | Pebble is fully contained: private devin-switch (`vendor/`, `.runtime/ds`), private Claude Code, `env -i` launchers | the main devin-switch is for daily work and must never be affected | 2026-10-28 |
| D3 | Mind backends: Claude Code for Claude models (4-5 citizens, Sonnet/Haiku), Devin via Pebble ds for the rest | Claude models don't act in the world through Devin; Devin gives many models from the shared pool | 2026-10-28 |
| D4 | The world is a real sphere on a hex grid, with a walkable land loop | "start somewhere, walk on, come back" must be true | 2026-10-28 |
| D5 | One session per citizen per game day; memory rebuilds context each morning | bounded context, memory under our control | 2026-10-28 |
| D6 | Self-disclosure is measured and logged, never censored | no backend can guarantee agents never notice; it's a research signal | 2026-10-28 |
| D7 | 15 citizens in v0: town 6, band A 5, band B 4 | small enough to run and read, big enough for social dynamics | 2026-10-28 |
| D8 | Backend/frontend organized like Associo (FastAPI + SQLModel + Alembic + Postgres + uv; Vite + React + TS + pnpm) | familiar production layout | 2026-10-28 |
| D9 | Memory, minds and observability live in the backend | one owner for world truth and what minds see | 2026-10-28 |
| D10 | Town look: castle town as in the reference image (stone-based keep, ~1600 style), pre-industrial technology | matches the reference and Polyfork's Medieval Japan kit | 2026-10-28 |
| D11 | Local Postgres via `docker compose`, port 5544, data bind-mounted in `.runtime/postgres` | contained in the repo, no clash with Associo's DB | 2026-10-28 |
| D12 | Python 3.12 | current stable for a new codebase | 2026-10-28 |
| D13 | World radius 2 km, 1 real s = 1 game min | readable distances for 15 citizens; game day = 24 real minutes | 2026-10-28 |
| D14 | Deaths in v0: the dead stay dead; restart from a seed when needed | no births until v2 | 2026-10-28 |
| D15 | 3D stack: react-three-fiber + drei | fits the React frontend | 2026-10-28 |
| D16 | Harness leaks in speech (paths, links): forbid in prompts, flag in the disclosure log, never rewrite speech | keep the experiment honest | 2026-10-28 |
| D17 | 3D assets from Polyfork (all low-poly parts free), vendored into the frontend with a manifest | kits match the town, forests, snow, volcanic landmarks; no hotlinking | 2026-10-28 |
| D18 | Phase A order: characters and assets (M1), then a walkable town (M2), then the globe (M3) and planet viewer (M4); later milestones renumbered | see and walk the town with its people early; the town spec is in local metres so it drops onto the globe unchanged | 2026-10-28 |
| D19 | "Navigate the town" = third-person walking through gate, bridge and streets with collisions; buildings are shells with opening doors, no interiors in v0 | Polyfork buildings have no interiors | 2026-10-28 |
| D20 | The repo is private; vendored Polyfork files are committed | Polyfork's licence forbids redistributing the files, which a public repo would do | 2026-10-28 |
| D21 | Frontend uses Tailwind v4 (Associo uses v3) | new codebase, current shadcn default | 2026-10-28 |
| D22 | Local ports: API 8100, frontend 5180 (Postgres 5544) | run next to Associo's 8000/5173 without clashes | 2026-10-28 |
| D23 | Frontend uses Pebble's own pnpm 12 (`frontend/scripts/pnpm.sh`, installed in `.runtime/`) with `minimumReleaseAge` 7 days; backend uses uv `exclude-newer = "7 days"` | dependencies must be at least a week old; the global pnpm 9 can't enforce it | 2026-10-28 |
| D24 | Polyfork files are gitignored; only the hash-pinned manifest and fetch script are committed (supersedes D20: the repo is still public) | Polyfork's licence forbids redistributing the files | 2026-10-28 |
| D25 | Character animation clips load from Polyfork's CDN at runtime; meshes and code are vendored | clips are Mixamo-derived and may only be served by Polyfork | 2026-10-28 |
| D26 | Citizen looks are configs for Polyfork's shared humanoid engine, authored in the frontend by look id; the backend citizens spec will reference look ids | covers Stone Age people with no custom modelling; one rig for all | 2026-10-28 |
| D27 | Missing animals are recoloured/rescaled relatives (elk, antelope, boar, polar bear, goat); seal and snake are dropped from v0 | catalogue gaps; remix GLBs lose their animations | 2026-10-28 |
| D28 | Milestone PRs are stacked (each branch starts from the previous milestone's branch, PR base = that branch) while earlier PRs await review | work continues without merging | 2026-10-28 |
| D29 | Doors of walk-through buildings (the gatehouse) are opened at runtime on the model, and the matching collider parts swing with them | Polyfork ships models and colliders with doors shut; the gate must be walkable and look open | 2026-10-28 |
| D30 | On flat ground the moat bridge is lowered (y = -1.68) so its deck meets the ground; revisit with terrain in M3 | the model is built to stand on a moat floor 1.6 m below the banks | 2026-10-28 |
| D31 | The town spec is authored YAML in local metres (x east, z south) with runs, tiles, areas and water; the backend's walkability grid is the reachability truth for tests and later the simulation | readable, diffable layout that drops onto the globe unchanged; one place to check that every building is reachable | 2026-10-28 |
| D32 | `/world` serves typed arrays as base64 little-endian bytes inside JSON (positions/heights float32, biomes uint8, triangles uint32), gzip level 6 | one request, one generated client type, 2.0 MB raw / 0.85 MB gzip; level 9 is 3× slower for the same size | 2026-10-28 |
| D33 | Generated worlds are stored in `worlds` per (seed, generator version, spec hash) as the served JSON (bytea), generated on first request or by `python -m app.world.generate`; the spec hash covers `world.yaml` and the site kinds | same inputs = same stored world; bumping `GENERATOR_VERSION` or editing the spec makes a new row instead of serving a stale one | 2026-10-28 |
| D34 | Site placements are local metres around an anchor (town placement format), mapped to the globe with the gnomonic mapping; wild kinds live in `data/world/kinds.yaml` next to the town's | the town and every site share one mapping that inverts exactly; the backend still only names kinds | 2026-10-28 |
| D35 | The land loop is authored as spine waypoints; the band's core is forced to walkable land and the loop is the cheapest walk through the waypoints (the ice gate is one) | the loop is guaranteed by construction, noise only shapes it; generation fails loudly if it can't close | 2026-10-28 |
| D36 | Lakes: a depression ≥ 3 m deep holds a lake that fills to its spill level when ≤ 8 m deep, else stays 8 m deep as a closed sink; other depressions fill into level flats; rivers follow the flood tree | filling every basin flooded 3 % of the planet with lakes; heights stay non-increasing along every river | 2026-10-28 |
| D37 | Rivers the story needs (the town's mill river, the great falls and its outflow) are authored polylines cut as monotone channels; the rest emerge from flow accumulation | the town's stream and the falls must exist on every run of the spec | 2026-10-28 |
| D38 | Noise is our own hash-based 3D gradient noise in numpy (numpy is the only new backend dependency) | same seed = same field on every numpy version; no extra package | 2026-10-28 |
| D39 | The elder tree is the `giant_tree` kind (Medieval Village oak, 6.2 m) drawn ×3.5, the one landmark exception to real-world scale | the catalogue has no giant tree; a gnarled multi-crown oak distinct from the forest oak reads as ancient when enlarged | 2026-10-28 |
| D40 | Kinds drawn at a non-real size go through one per-kind render scale (`KIND_SCALE` in `assets.ts`: `giant_tree` ×3.5, `ice_block` ×3); backend footprints in `data/world/kinds.yaml` are the drawn size, and a test checks every site footprint of the real world against asset size × scale | sites, scatter and the backend agree on one size per kind; scatter ranges are relative to the drawn size | 2026-10-29 |
| D41 | Globe scatter in two reach tiers around the camera target: ground cover (grass, flowers, ferns, pebbles, reeds) within 150 m, trees, bushes and rocks within 500 m; nothing grows on slopes over 40° | full density to 600 m was ~8.7 M triangles in a forest; tiers keep the densest forest at ~1.6 M and 71 draw calls; props on cliffs float on their downhill side | 2026-10-29 |
| D42 | The engine is the only writer of runs, events and snapshots; the api writes admin requests to `engine_commands` (+ `NOTIFY pebble_commands`), the engine polls them each loop; each tick is one transaction ending in `NOTIFY pebble_events` with the run, tick and seq range | one owner of world truth; the live feed (M8) fetches exact ranges; no extra broker | 2026-10-29 |
| D43 | Every discrete state change is exactly one event; continuous per-tick change (walkers' positions, needs drifting) is the tick's single `tick_summary`; the simulation numbers events with a deterministic per-run `seq`, the store assigns ULIDs and resolves `cause_seq` to `cause_id`; 06 gains `citizen_spawned` and `knowledge_changed` | a position event per walker per minute would dwarf everything else; deterministic seqs keep resumed runs comparable | 2026-10-29 |
| D44 | Snapshots every game hour and on shutdown (full state as JSONB); a run resumes from its latest snapshot and events past it are dropped and simulated again | resumable without a snapshot per tick; the simulation is deterministic, so the tail comes out the same | 2026-10-29 |
| D45 | Navigation: weighted A* (×2) on the town's 0.5 m grid, 8-connected without corner cutting; A* on the cell graph outside (edge = metres × mean terrain cost); handover at portals every 10 m along the town chart's edge. Costs beyond 01: tundra 1.2, wetland 1.5, volcanic 2, mountain 2.5, ice 3, rivers fordable at ≥ 1.5 | town routes stay on walkable cells and go through gates; weighting plans 8× faster for routes ~2 % longer | 2026-10-29 |
| D46 | Simulation randomness: one SplitMix64 stream per subsystem (pure Python, state = one integer) seeded from the run seed; tick 0 is 08:00 town time on day 0 with the client's sun formula | identical on every platform and numpy version; trivially snapshotted | 2026-10-29 |
| D47 | Body numbers 02 leaves open: need rate by age (child 0.8, teen 1.1, elder 0.9), ×1.25 walking/gathering, ×0.75 asleep, thirst ×1.5 on savanna/volcanic ground, starving −2 health/h, parched −6/h, healing +1/h (×2 asleep) only when neither hungry nor thirsty, resting +3 energy/h, a collapsed citizen sleeps until energy 30 | starvation kills in ~3 game days, thirst in ~1.5; tunable in one module | 2026-10-29 |
| D48 | Perception v0: sight blends 150 m → 20 m as the sun goes from 0° to −6°, ×0.4 in forest, ×1.3 on hills, no occlusion; a name is learned when a visible speaker says it; a place is learned roughly when a speaker who knows it names it; placing a citizen isn't anyone "coming into view" | in-world learning with no extra actions; occlusion can come later without changing the contract | 2026-10-29 |
| D49 | Durative actions: a new one interrupts the running one; sleep ends at sunrise, or when rested by day; sleepers wake on a shout, their name or getting hurt; gifts are accepted by anyone awake (a `GiftPolicy` hook for brains/minds) | brains can change plans at any time; towns can sleep through ordinary talk | 2026-10-29 |

## Open (recommendation first)

| # | Question | Recommendation | Alternatives |
|---|---|---|---|
| O8 | Public hosting split (v1) | frontend + read-only API + DB hosted; engine and minds stay on the Mac and push events | everything on one VM (needs Devin CLI + Claude Code there) |
| O9 | Who decides whether a gift is taken | M7 brains decide from needs and relationship; agent minds get a pending offer to accept or refuse | keep auto-accept for everyone awake |
| O10 | "Someone comes into view" interrupts constantly in a crowded town | interrupt only for strangers, animals and people who speak or approach; known people walking past are perceived but don't interrupt | keep 03's rule as is and let brains resume their action |
