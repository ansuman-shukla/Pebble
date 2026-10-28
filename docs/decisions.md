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

## Open (recommendation first)

| # | Question | Recommendation | Alternatives |
|---|---|---|---|
| O1 | Town era and look | castle town as in the reference image (stone-based keep, ~1600 style), technology kept pre-industrial | Kamakura-era (~1300) look without a stone castle |
| O2 | Local Postgres | `docker compose`, port 5544, data bind-mounted in `.runtime/postgres` | Homebrew Postgres with data dir in `.runtime/` |
| O3 | Python version | 3.12 | 3.11 like Associo |
| O4 | World size and speed | radius 2 km, 1 real s = 1 game min | bigger radius with faster game clock |
| O5 | Deaths in v0 (no births yet) | the dead stay dead; restart the run from a seed when needed | respawn newcomers |
| O6 | 3D stack | react-three-fiber + drei | plain three.js in a React shell |
| O7 | Harness leaks in speech (file paths, markdown links) | forbid in persona prompts and flag in the disclosure log; don't rewrite speech | strip them before others hear |
| O8 | Public hosting split (v1) | frontend + read-only API + DB hosted; engine and minds stay on the Mac and push events | everything on one VM (needs Devin CLI + Claude Code there) |
