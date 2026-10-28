# Pebble

A small round 3D world, watchable in the browser: a walled medieval-Japanese town on one side, Stone Age bands, animals
and wild land everywhere else. First the world is built and lived in by scripted citizens; then AI agents take their
places, believing they simply live there, while every perception, word, thought and memory is recorded for anyone to
read.

- Design and plan: [docs/](docs/README.md)
- Experiment results: [docs/findings/](docs/findings/)

## Run locally

Needs Docker, uv and Node. One-time: `backend/scripts/setup.sh` (installs Pebble's own pnpm, devin-switch and Claude
Code into `.runtime/`).

```sh
make -C backend dev                                   # Postgres :5544 + API http://localhost:8100
cd frontend && ./scripts/pnpm.sh install && ./scripts/pnpm.sh dev   # http://localhost:5180
```

The simulation runs as its own process next to the API (the API only reads what it writes):

```sh
make -C backend engine                                # resume the latest run, or start one with the dev cast
make -C backend engine ENGINE_ARGS="--new-run --speed 10"   # new run, 10 game minutes per real second
```

It ticks one game minute per real second by default (`--speed 1..60`, `--paused`, `--headless --ticks N` to
fast-forward) and stops cleanly on Ctrl-C (it snapshots, and the next start resumes). Watch and steer it through
`GET /api/v1/clock`, `POST /api/v1/admin/clock` (`{"paused": true}`, `{"speed": 30}`), `GET /api/v1/entities[?at=tick]`
and `GET /api/v1/events?actor=…&type=…&since_tick=…`. `uv run python -m scripts.bench_sim 15 24` (in `backend/`)
measures tick cost and event volume.

The browser only talks to the frontend's own origin: vite (`dev` and `preview`) proxies `/api` to the backend
(`PEBBLE_API_TARGET`, default http://localhost:8100), so the world also loads through http://127.0.0.1:5180 or a
preview proxy. Set `VITE_API_URL` only to call the backend directly (its `FRONTEND_ORIGINS` must allow the origin).

`./scripts/pnpm.sh dev` and `build` first run `fetch-assets`, which downloads the pinned Polyfork files (~24 MB) into
gitignored folders.

`./scripts/pnpm.sh test` runs Playwright against the frontend on 5180 (starting it if needed). To test another
checkout's frontend, run it on its own port and set `PLAYWRIGHT_PORT`, e.g. `PLAYWRIGHT_PORT=5190 ./scripts/pnpm.sh test`
(the status test also needs that origin in the backend's `FRONTEND_ORIGINS`). On macOS the tests render WebGL on the GPU
(`--use-angle=metal`); headless Chrome's default software WebGL is too slow for the town.

Open http://localhost:5180 for the planet: the generated world from `GET /api/v1/world`, starting at the castle
town's main gate, with the engine's citizens living on it (`GET /api/v1/entities`, then the live feed).

| Control | What |
|---|---|
| WASD, Shift | walk (1.4 m/s), run (3.5 m/s); slower up and down steep slopes, no climbing slopes over 45° |
| T (or the `travel` button) | travel at 25 m/s (around the planet's land loop in ~10 min); walks through scattered trees and up any slope, walls and water still stop it |
| C (or the buttons) | camera: follow (third person), orbit (whole planet; zoom onto the player to walk again), fly (Q/E down/up) |
| drag, wheel | look, zoom |
| `drop` (the pegman) | click it, then click a spot on the planet (Esc cancels), or drag it onto the planet: the player lands there and the camera flies down behind them; water is refused |
| `go to` | jump to the castle town, a camp or a landmark |
| `people` | the citizens: what each is doing and how they are; `follow` (or the row) flies the camera to them and orbits them as they go (Esc or `stop following` returns to the player); `go to` drops the player next to them |
| clock (bottom right) | engine day and time; `pause`, `×1`, `×10`, `×60` set the engine's speed (`POST /api/v1/admin/clock`); the sun follows engine time |
| `time ×60` | without a feed (`/?mock=1`): run the client clock at one game hour per second |
| `?at=lat,lon[,bearing]` | start anywhere, e.g. `/?at=12.4,100,180` (band A camp); a drop or go to rewrites it so the spot can be shared; `?time=HH:MM` sets the town time |

`/town` shows the flat town alone; `/?mock=1` uses the small test world instead of the backend's (without citizens);
`?mockLive=1` adds a deterministic mock feed of the 15 citizens (dev and tests). Citizens within 400 m are drawn,
labelled within 40 m; what they say shows as a bubble for a few seconds. See
[the live citizens findings](docs/findings/2026-10-29-live-citizens-client.md).

Status: phase A, M5 simulation core (engine, bodies, world contract, event store).
