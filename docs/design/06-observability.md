# 06 · Observability

The archive is the product as much as the 3D world: anyone can open a citizen and read what they saw, said, thought
and did, and how they changed. Lives in the backend (`app/observability/`).

## Event store

One append-only `events` table in Postgres. Every state change and every mind output is exactly one event.

| Field | Meaning |
|---|---|
| `id` | ULID (time-ordered) |
| `run_id`, `world_seed` | which run / world |
| `tick`, `game_time`, `real_time` | when |
| `actor_kind`, `actor_id` | citizen, animal, world, player, god (interventions) |
| `type` | see below |
| `cell`, `position` | where |
| `visibility` | `public` (anyone in range could see/hear it) or `private` (thoughts, memory) |
| `cause_id` | event that caused this one (interrupt chains, replies) |
| `mind` | backend, model, session id (agent events only) |
| `payload` | JSONB, typed per event type (Pydantic) |

Event types (v0): `tick_summary`, `perceived`, `action_started`, `action_finished`, `action_interrupted`, `said`,
`thought` (turn text), `need_changed` (on threshold crossings only), `injured`, `died`, `item_moved`,
`resource_changed`, `knowledge_changed` (places/people learned), `citizen_spawned`, `animal_spawned`,
`fire_changed`, `intervention`, `snapshot`. Continuous change (walkers' positions, needs drifting) is the tick's
single `tick_summary` (D46).
Phase B adds: `mind_turn` (latency, tool calls), `mind_unavailable`, `memory_written`, `belief_updated`,
`relationship_changed`, `self_disclosure`.

## Raw transcripts
Each mind session's full JSON-RPC / stream-json log is stored gzipped on disk (`mind_sessions` table holds paths,
model, backend, citizen, game day, timings). Nothing is dropped; the event store is the structured index over it.

## Self-disclosure log

```
 every `said` / `thought` ──▶ regex pass ──hit──▶ judge (cheap model) ──▶ self_disclosure event
                              AI, model/company names,   none | doubt | meta | disclosure
                              simulation, prompt, tool,   + quote, trigger (cause_id), model,
                              file paths, links           backend, citizen, heard_by
```

- `doubt`: questions whether the world/self is real ("are we only dreams?").
- `meta`: talks about the harness or story ("the tool says…", a file path, "in this role-play").
- `disclosure`: says it is an AI/model/program.
- `heard_by` lists citizens who heard it, so we can follow whether awareness spreads.
- Dashboard: rate per model per game day, triggers, spread graph. Speech is never altered.

## Derived views (rebuilt from events, never the source of truth)
- **Citizen life:** timeline, needs over time, places visited, people met.
- **Conversations:** threads of `said` events grouped by place and time window.
- **Relationship graph:** who talks to, helps, harms whom.
- **Biographies:** a cheap model writes a daily chapter per citizen from the archive. Omniscient; spectators only;
  never shown to any citizen.
- **World stats:** population, deaths by cause, food stocks, resource depletion, disclosures by model.

## Spectator API (read-only)
`/world` (map, cells, structures), `/entities` (positions now / at tick), `/citizens/{id}` (profile, memory views,
timeline, biography), `/events` (filter by actor, type, place, time), `/conversations`, `/stats`, plus a WebSocket
for the live event feed. Replay = the same endpoints with `?at=tick`.

## Ops telemetry
Process health, tick duration, mind latency and errors go to standard logging (Logfire optional, as in Associo).
That is for operating the system; the event store is for studying the world.
