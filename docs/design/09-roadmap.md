# 09 · Roadmap

**Phase A builds a complete world with scripted citizens. Phase B lets agents in.** The gate between them is a
checklist, not a date. Each milestone is a separate branch/PR with small commits, tests and a short findings note.

```
 PHASE A: the world                                              PHASE B: the minds
 M0 scaffold → M1 globe → M2 3D viewer → M3 sim core → M4 ecology   M8 one agent → M9 memory
            → M5 scripted citizens → M6 live spectator → M7 GATE ──▶ → M10 disclosure log → M11 all 15
```

## Phase A: the world

| Milestone | Delivers | Done when |
|---|---|---|
| **M0 Scaffold** | `backend/` + `frontend/` skeletons per `08-architecture.md`, tooling, Makefile, docker-compose Postgres (5544, data in `.runtime/`), scripts moved to `backend/scripts/`, README | `make lint test` and `pnpm lint typecheck build` pass on an empty app; health endpoint renders in the frontend |
| **M1 Globe and world generation** | hex-sphere grid, procedural height/temperature/moisture/rivers/biomes, authored spec (town, 2 camps, 8 landmarks, land loop), persisted world, `/world` API | tests: deterministic by seed; land loop walkable; every landmark reachable on foot; biome shares in range |
| **M2 3D world viewer** | R3F globe terrain, ocean, rivers, sun and day/night, orbit → street-level and free-fly cameras, Polyfork coverage check + asset registry, props for forests, town, camps, landmarks | the whole static planet is browsable at 60 fps; Playwright smoke test renders it |
| **M3 Simulation core** | engine process, clock and tick loop, entities, bodies, `world_api` actions + perception + interrupts, event store, snapshots, pause/speed | invariant tests (`02-simulation.md`) pass; a test citizen driven through `world_api` can walk, drink, eat, sleep |
| **M4 Ecology** | plant regrowth, herbivore herds, predators (dusk/night hunting, fear of fire/groups), fish, fire | 10 game days headless: populations stable within caps, predators cause injuries only under the right conditions |
| **M5 Scripted citizens** | citizens spec (15 identities, roles, ages, homes, skills, knowledge), utility brains, town fields + storehouse, band food | 15 scripted citizens live 10+ game days without getting stuck; deaths only from real causes |
| **M6 Live spectator** | moving citizens and animals in 3D, live event feed (WS), speech bubbles, citizen pages, conversations, timeline/replay, stats | a spectator can follow any citizen live and replay any moment |
| **M7 World-complete gate** | review against the checklist below; findings note | every box ticked |

### M7 checklist: the world is complete when
- [ ] Terrain, biomes, oceans, rivers, poles and the land loop are generated and rendered.
- [ ] Town (castle, walls, gate, houses, pagoda, shrine, market, well, mill, paddies) and both camps are built.
- [ ] All 8 landmarks exist, are named and reachable.
- [ ] Every v0 animal exists, behaves and renders.
- [ ] Every v0 action and perception is used by scripted brains, and the contract is frozen.
- [ ] Bodies, needs, injuries and death work end-to-end.
- [ ] Every state change is an event; replay works from snapshots.
- [ ] 15 citizens run stably for 10+ game days.

## Phase B: the minds

| Milestone | Delivers | Done when |
|---|---|---|
| **M8 One agent** | world MCP proxy, `MindBackend` with Claude Code + Devin (Pebble ds), orchestrator, day-session loop, jail, scripted fallback | one agent citizen lives a full game day among 14 scripted ones; jail log shows 0 escapes |
| **M9 Memory** | stores, sleep consolidation, morning profile, per-prompt hints, `recall`, memory views | agent remembers people, places and facts across 5 game days within token budgets |
| **M10 Self-disclosure log** | regex + judge pipeline, events, spread tracking, stats dashboard | seeded test utterances classify correctly; dashboard shows rates by model |
| **M11 All 15 agents** | roster from `04-minds.md`, run, observe | a multi-day run with full archive; findings note |

## Later versions (one layer of realism each)
- **v1:** seasons and winter, weather, crafting + discovery, boats, the human player avatar, public hosting on your domain.
- **v2:** aging, births and generations, language barrier and emergent language, money/ownership/hierarchy rules,
  "acts of god" panel, in-world writing/painting and the library, seeds/snapshots for A/B worlds.
