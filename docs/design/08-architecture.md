# 08 · Architecture and repository layout

Organized like Associo: a `backend/` (FastAPI, SQLModel, Alembic, Postgres, uv) and a `frontend/` (Vite, React, TS,
pnpm), each self-contained with its own tooling. The memory system, the minds and the observability pipeline all live
in the backend.

## Processes

```
                ┌──────────────────────────── backend ────────────────────────────┐
  browser ◀──── │ api (uvicorn app.main:app)          engine (python -m app.engine)│
  frontend      │  read-only spectator REST + WS  ◀─┐  clock · sim · scripted brains│
  (vite/static) │                                   │  phase B: mind orchestrator,  │
                │            Postgres ◀─────────────┴─ world MCP socket, memory     │
                │   events, world state, memory      LISTEN/NOTIFY → live feed     │
                └──────────────────────────────────────────────┬──────────────────┘
                                                               │ spawns (phase B)
                                     ┌─────────────────────────┴────────────────┐
                                     │ Pebble ds acp (Devin)   Pebble claude -p │
                                     │  natives + `world` MCP proxy per session  │
                                     └──────────────────────────────────────────┘
```

- **engine** is the only writer of world state. **api** only reads (plus admin endpoints for pause/speed/interventions
  that go to the engine).
- Live feed: the engine writes events and `NOTIFY`s; the api streams them to browsers over WebSocket.
- Postgres runs locally from `docker compose`, port 5544 (so it never clashes with Associo's DB), data bind-mounted
  in `.runtime/postgres` to keep everything inside the repo.

## Repository tree (target)

```
Pebble/
├── backend/
│   ├── pyproject.toml · uv.lock · Makefile · alembic.ini · .env.example · README.md
│   ├── app/
│   │   ├── main.py              FastAPI app (spectator API)
│   │   ├── engine.py            engine entrypoint
│   │   ├── api/                 deps.py · main.py · routes/{world,entities,citizens,events,conversations,stats,live,admin}.py
│   │   ├── core/                config.py · db.py · logging.py · rng.py
│   │   ├── db/                  models.py · enums.py · schemas/
│   │   ├── crud/                one module per table group
│   │   ├── alembic/             env.py · versions/
│   │   ├── world/               hex-sphere grid · generation · biomes · spec loader (static world)
│   │   ├── sim/                 clock · loop · bodies · ecology · actions · perception · interrupts
│   │   ├── brains/              scripted utility brains for citizens and animals
│   │   ├── world_api/           THE contract: Pydantic action/perception models + Python facade
│   │   ├── minds/               phase B: backends/{claude_code,devin_acp}.py · orchestrator · mcp_proxy · jail_hook · prompts
│   │   ├── memory/              phase B: stores · consolidation · retrieval · views
│   │   ├── observability/       event bus · event types · transcripts · self_disclosure · biographies · stats
│   │   ├── services/            use cases behind routes (citizen profile, timeline, replay)
│   │   ├── prompt-templates/    persona · decision · consolidation · judge · biography (Jinja)
│   │   └── lib/                 small shared helpers
│   ├── data/                    world spec: world.yaml · regions/ · landmarks/ · town/ · citizens/
│   ├── scripts/                 setup.sh · ds.sh · claude.sh · import_ds_accounts.py · apply_npc_config.py
│   └── tests/                   world/ · sim/ · brains/ · world_api/ · api/ · minds/ · memory/ · observability/
├── frontend/
│   ├── package.json · pnpm-lock.yaml · vite.config.ts · tsconfig*.json · eslint.config.js · .prettierrc
│   ├── knip.json · components.json · playwright.config.ts · openapi.json · index.html · .env.example
│   ├── public/assets/polyfork/  vendored GLBs + licences
│   ├── src/
│   │   ├── main.tsx · index.css
│   │   ├── pages/               world-page · citizen-page · conversations-page · timeline-page · stats-page
│   │   ├── components/          world/ (canvas, globe, terrain, props, creatures, cameras, sky, overlays)
│   │   │                        citizens/ · events/ · conversations/ · timeline/ · stats/ · layout/ · ui/ (shadcn)
│   │   ├── hooks/               use-live-events · use-world · use-citizen · use-game-clock …
│   │   ├── lib/                 api/ (query wrappers) · client/ (generated) · world/ (pure three.js: sphere math,
│   │   │                        mesh builders, asset registry, LOD)
│   │   ├── contexts/            replay time · selection
│   │   └── types/
│   └── tests/                   smoke/ · regression/ · fixtures/ (Playwright)
├── docs/                        design/ · findings/ · decisions.md · README.md
├── experiments/                 spikes only (devin_jail); never imported by backend/frontend
├── docker-compose.yml           Postgres for local dev
├── vendor/                      (gitignored) private devin-switch
└── .runtime/                    (gitignored) ds state, Claude Code, Postgres data, transcripts, run logs
```

`scripts/` at the repo root moves to `backend/scripts/` in milestone M0; the jail hook moves into `app/minds/` in
phase B (then `apply_npc_config.py` is re-run so every account points at the new path).

## Tooling (same as Associo)

| | Backend | Frontend |
|---|---|---|
| Package manager | uv (Python 3.12) | pnpm |
| Format / lint | ruff format · ruff check | prettier · eslint |
| Types | mypy (strict on `world_api`, `sim`) | tsc |
| Dead code | - | knip |
| Tests | pytest (+ mutation testing on sim and memory) | Playwright |
| API types | FastAPI OpenAPI | `openapi.json` → hey-api client |
| Make targets | `sync format lint test pre-commit dev engine` | `pnpm dev build lint typecheck test generate-client` |

## Isolation rules (non-negotiable)
- Nothing reads or writes the main devin-switch, the installed `ds`, global Devin/Claude config, or other repos.
- All launchers start with `env -i` and set `HOME`, `DS_HOME`, `CLAUDE_CONFIG_DIR` inside `.runtime/`.
- Secrets live only in `.env` / `.runtime` (gitignored) and are never logged or committed.
