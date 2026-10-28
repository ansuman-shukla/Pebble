# Decisions

## Accepted

| # | Decision | Why | Date |
|---|---|---|---|
| D1 | Phase A completes the world with scripted citizens; agents enter only after the M7 gate | agents should get a finished world and a frozen contract | 2026-10-28 |
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

## Open (recommendation first)

| # | Question | Recommendation | Alternatives |
|---|---|---|---|
| O8 | Public hosting split (v1) | frontend + read-only API + DB hosted; engine and minds stay on the Mac and push events | everything on one VM (needs Devin CLI + Claude Code there) |
