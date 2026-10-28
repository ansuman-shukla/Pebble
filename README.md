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

Status: phase A, M0 scaffold.
