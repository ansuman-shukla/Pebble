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

## Open (recommendation first)

| # | Question | Recommendation | Alternatives |
|---|---|---|---|
| O8 | Public hosting split (v1) | frontend + read-only API + DB hosted; engine and minds stay on the Mac and push events | everything on one VM (needs Devin CLI + Claude Code there) |
