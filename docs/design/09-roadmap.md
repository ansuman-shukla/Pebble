# 09 · Roadmap

**Phase A builds a complete world with scripted citizens. Phase B lets agents in.** The gate between them is a
checklist, not a date. Each milestone is a separate branch/PR with small commits, tests and a short findings note.

```
 PHASE A: the world                                                       PHASE B: the minds
 M0 scaffold → M1 characters + assets → M2 walkable town → M3 globe        M10 one agent → M11 memory
   → M4 planet viewer → M5 sim core → M6 ecology → M7 scripted citizens    → M12 disclosure log → M13 all 15
   → M8 live spectator → M9 GATE ──▶
```

## Phase A: the world

| Milestone | Delivers | Done when |
|---|---|---|
| **M0 Scaffold** | `backend/` + `frontend/` skeletons per `08-architecture.md`, tooling, Makefile, docker-compose Postgres (5544, data in `.runtime/`), scripts moved to `backend/scripts/`, README | `make lint test` and `pnpm lint typecheck build` pass on an empty app; health endpoint renders in the frontend |
| **M1 Characters and assets** | Polyfork fetch script + committed manifest + vendored files, asset registry (kinds → files), coverage check for town, camps, animals and people, 15 citizen looks (town from Medieval Japan characters, Stone Age bands by remixing existing humanoids), Idle/Walk/Run clips, a gallery page | every v0 kind resolves to a vendored file; the gallery shows all 15 citizens and the v0 animals animating; gaps listed in a findings note |
| **M2 Walkable town** | authored town spec in local metres (so it drops onto the globe unchanged in M3), town API, town scene (castle, walls, moat, bridge, gate, houses, pagoda, shrine, market, well, mill, paddies), third-person walker with collisions, opening doors, orbit and free-fly cameras | spec tests: no overlapping footprints, every building reachable from the gate; you can walk in through the gate to the castle and along every street without passing through buildings; Playwright smoke test |
| **M3 Globe and world generation** | hex-sphere grid, procedural height/temperature/moisture/rivers/biomes, authored spec (town placed from M2, 2 camps, 8 landmarks, land loop), persisted world, `/world` API | tests: deterministic by seed; land loop walkable; every landmark reachable on foot; biome shares in range |
| **M4 Planet viewer** | R3F globe terrain, ocean, rivers, sun and day/night, orbit → street-level (into the walkable town) and free-fly cameras, props for forests, camps, landmarks | the whole static planet is browsable at 60 fps; Playwright smoke test renders it |
| **M5 Simulation core** | engine process, clock and tick loop, entities, bodies, `world_api` actions + perception + interrupts, event store, snapshots, pause/speed | invariant tests (`02-simulation.md`) pass; a test citizen driven through `world_api` can walk, drink, eat, sleep |
| **M6 Ecology** | plant regrowth, herbivore herds, predators (dusk/night hunting, fear of fire/groups), fish, fire | 10 game days headless: populations stable within caps, predators cause injuries only under the right conditions |
| **M7 Scripted citizens** | citizens spec (15 identities, roles, ages, homes, skills, knowledge), utility brains, town fields + storehouse, band food | 15 scripted citizens live 10+ game days without getting stuck; deaths only from real causes |
| **M8 Live spectator** | moving citizens and animals in 3D, live event feed (WS), speech bubbles, citizen pages, conversations, timeline/replay, stats | a spectator can follow any citizen live and replay any moment |
| **M9 World-complete gate** | review against the checklist below; findings note | every box ticked |

### M9 checklist: the world is complete when
- [x] Terrain, biomes, oceans, rivers, poles and the land loop are generated and rendered.
- [x] Town (castle, walls, gate, houses, pagoda, shrine, market, well, mill, paddies) and both camps are built.
- [x] All 8 landmarks exist, are named and reachable.
- [x] Every v0 animal exists, behaves and renders.
- [x] Every v0 action and perception is used by scripted brains, and the contract is frozen.
- [x] Bodies, needs, injuries and death work end-to-end.
- [x] Every state change is an event; replay works from snapshots.
- [x] 15 citizens run stably for 10+ game days.

## Phase B: the minds

| Milestone | Delivers | Done when |
|---|---|---|
| **M10 One agent** | world MCP proxy, `MindBackend` with Claude Code + Devin (Pebble ds), orchestrator, day-session loop, jail, scripted fallback | one agent citizen lives a full game day among 14 scripted ones; jail log shows 0 escapes |
| **M11 Memory** | stores, sleep consolidation, morning profile, per-prompt hints, `recall`, memory views | agent remembers people, places and facts across 5 game days within token budgets |
| **M12 Self-disclosure log** | regex + judge pipeline, events, spread tracking, stats dashboard | seeded test utterances classify correctly; dashboard shows rates by model |
| **M13 All 15 agents** | roster from `04-minds.md`, run, observe | a multi-day run with full archive; findings note |

## Later versions (one layer of realism each)
- **v1:** seasons and winter, weather, crafting + discovery, boats, the human player avatar, public hosting on your domain.
- **v2:** aging, births and generations, language barrier and emergent language, money/ownership/hierarchy rules,
  "acts of god" panel, in-world writing/painting and the library, seeds/snapshots for A/B worlds.
