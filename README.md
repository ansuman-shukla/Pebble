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

`./scripts/pnpm.sh dev` and `build` first run `fetch-assets`, which downloads the pinned Polyfork files (~24 MB) into
gitignored folders.

`./scripts/pnpm.sh test` runs Playwright against the frontend on 5180 (starting it if needed). To test another
checkout's frontend, run it on its own port and set `PLAYWRIGHT_PORT`, e.g. `PLAYWRIGHT_PORT=5190 ./scripts/pnpm.sh test`
(the status test also needs that origin in the backend's `FRONTEND_ORIGINS`). On macOS the tests render WebGL on the GPU
(`--use-angle=metal`); headless Chrome's default software WebGL is too slow for the town.

Open http://localhost:5180 to walk the town (WASD, Shift run, drag to look, C camera).

Status: phase A, M2 walkable town.
