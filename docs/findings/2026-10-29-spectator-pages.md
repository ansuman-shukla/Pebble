# Findings: the spectator pages (M8: people, citizen lives, conversations, replay, stats, 2026-10-29)

Anyone can now read the world from the archive: who everyone is and what they are doing, one citizen's life line by
line with their needs over time, every conversation, the world at any past minute, and the world's stocks. All of it
is derived from the event store (06-observability: derived views, never the source of truth) by read-only endpoints;
"replay" is the same endpoint with `?at=tick` (D47 snapshots + events, the `/entities?at` reducer).

## Endpoints (`/api/v1`, all read-only, `run_id` defaults to the latest run)

| Endpoint | What | Replay |
|---|---|---|
| `GET /citizens` | everyone: id, name, look, role, region, age, alive, activity + action label, body words, the named place they are in, cause of death | `?at=` |
| `GET /citizens/{id}` | profile: appearance, age group, sex, skills, personality (from the citizens spec), home (named), activity, position, place, needs in numbers and words, what they carry (in words), places known (visited / heard of), people known, the 8 newest timeline lines | `?at=` |
| `GET /citizens/{id}/timeline` | their events as one-liners (`summary`, plus `detail` = what they were told, `related` = people in it): actions started/ended, speech said *and heard*, needs crossing thresholds, items, knowledge, injuries, death; `from_tick`, `to_tick`, `type` (default: all but `tick_summary`/`perceived`), `order=asc|desc`, `cursor` + `limit` (≤ 500) → `next_cursor` | `to_tick` |
| `GET /citizens/{id}/needs` | hunger/thirst/energy/health every `step` ticks from the tick summaries; default the last game day at ~288 points, capped at 1 000 points (the step is raised) | `to_tick` |
| `GET /conversations` | threads of `said` events, newest first: place and area, start/end, speakers, listeners, lines with who heard each; `from_tick`/`to_tick` (default the last game day), `place` (a place or area id), `limit` (≤ 200) | `to_tick` |
| `GET /stats` | population alive/dead, deaths (who, cause, when) and by cause, food stocks (each storehouse and field store, food carried per region, with the hunger it all removes), wild resources now vs the run's first snapshot and cells picked bare, events / lines said / actions / deaths per town day | `?at=` |

A tick the run hasn't reached is a 404 (like `/entities?at`), an unknown citizen is a 404.

### How the derived views are built

- **Replay** (`app/observability/replay.py`) now also keeps each citizen's skills, places (visited / rough) and people,
  from the snapshot or spawn event plus `knowledge_changed`; the "every change has an event" test covers it (it fails
  if either knowledge branch is dropped).
- **Names** (`app/services/places.py`): the api builds the simulation's static world once (`load_sim_world`, ~0.35 s
  on the first request) so places, homes and stores read exactly as citizens know them. `where(point)` = the smallest
  named place containing it (the well before the castle town), `area(point)` = the largest (the town, a camp, a
  landmark). Homes read "the keep", "a house in the castle town", "a lean-to at Band A camp"; storehouse stores
  read "the storehouse", field stores by their place ("the rice fields").
- **Timeline lines** are third person without the name ("walks to the well", "arrives at the well", "stops tending the
  rice paddies", 'hears Haru: "…"', "feels thirsty", "feels fed again", "puts plenty of rice in the storehouse",
  "gets to know Haru", "hears of the temple", "dies: dehydration"). An ended action's label comes from its start
  (same actor and action number, looked up for the page's ends only, up to a day back).
- **Conversations**: a line joins an open thread when its speaker or a hearer is already in it and the thread's last
  line is at most 10 game minutes earlier; otherwise it starts a thread. Hearing range (30 m talking, 150 m
  shouting) keeps threads in one place, so place isn't part of the key; a thread is named after the smallest place
  of its first line plus its area. A morning at band A's camp is one long thread of greetings.
- **Days** are town days (`game_time // 1440`; tick 0 is 08:00 of day 0).

### Performance (the main run: 15 citizens, ~10 000 ticks, ~40 000 events, 40 MB)

| Request | Time |
|---|---|
| `/citizens`, `/citizens?at=3000` | 9-20 ms |
| `/citizens/ama?at=3000` (incl. its recent lines) | 35 ms |
| `/citizens/ama/timeline?limit=500` (asc / desc to a past tick) | 46 / 15 ms |
| `/citizens/ama/needs?from_tick=0` (1 000 points) | 13 ms |
| `/conversations?from_tick=0&limit=200` (the whole run) | 13 ms |
| `/stats` | 25-80 ms |

The indexes the brief asked for already exist since the M5 migration (`ix_events_run_actor_tick` on
`(run_id, actor_id, tick)`, `ix_events_run_type_tick` on `(run_id, type, tick)`, `ix_events_run_tick`), so there is
no new migration. Heard speech is found with `type = 'said' AND payload->'heard_by' @> '["id"]'` (the type index
narrows it to the few hundred `said` events). Needs read only `payload->'bodies'->'id'` of every `step`-th summary.

## The pages (frontend)

| Route | What |
|---|---|
| `/people` | everyone by region (town, band A, band B): portrait, name, age, role, what they're doing and where, body words |
| `/people/:id` | portrait, role, age, region, appearance, personality, home, skills; **Show on map** (`/?follow=id`); now: activity, needs bars (words + numbers), what they carry; who and which places they know (links); needs over the last day (SVG lines); their life newest first, by day, loading more as you scroll; each line's time opens the World at that tick following them (`/?tick=N&follow=id`) |
| `/conversations` | the last game day's threads live, or one town day (`?day=N`, earlier/later buttons), filter by place or area (`?place=`); each thread opens the World at its first line (`/?tick=N&follow=speaker`) |
| `/timeline` | the replay scrubber over the run (`?at=N`; drag, keyboard, ±10 min / 1 h / 1 day, now): who was where doing what, what was said in the hour before, population and the storehouse then; **Open the world at this moment** (`/?tick=N`) |
| `/stats` | alive, dead, meals in stock, game day; food stocks, wild plants now vs at the start, deaths by cause, actions and lines per day |

Every spectator page takes `?at=N` (a banner says so, with **Back to live**); links between them keep it. Without
`at` they follow the engine's live feed:

```
 WS /api/v1/live ──▶ LiveUpdates (one socket for all pages, refcounted; closes 1 s after the last page leaves)
                      │ snapshot / tick / event, at most one refresh a second (the last message always lands)
                      ▼
       queryClient.invalidateQueries(meta.live && older than meta.staleMs)   (needs, timeline: 5 s)
 socket down ──▶ the same queries poll every 2 s (5 s for needs/timeline) until it reconnects (0.5 s → 15 s backoff,
                 1012 "new run" at once)
```

`src/lib/live/live-updates.ts` is the framework-free subscriber, `src/hooks/use-live-updates.ts` binds it to TanStack
Query and React (`useSyncExternalStore`), and the browser socket wrapper is shared with `use-live-citizens`
(`src/lib/api/live-socket.ts`). The feed's messages carry `CitizenEntity`, not the pages' richer views (places,
profiles, stats), so the pages invalidate instead of patching. Replayed answers carry no `live` meta and never
refresh. The page's `<main>` shows the link as `data-live-feed` (`live`/`connecting`/`down`). Tested with
Playwright's `routeWebSocket` playing the engine: no requests while the feed is quiet, a refetch within 2 s of a
tick, polling once the socket drops.

Portraits are the citizens' 3D looks rendered once each (first frame of the Idle clip, head and shoulders) by one
shared offscreen `WebGLRenderer` into PNG data URLs (`src/lib/world/portraits.ts`): fifteen canvases would need
fifteen WebGL contexts (Chrome allows ~16). The clips come from the Polyfork CDN; until a portrait is ready the
initial shows.

Charts are plain SVG (no chart library): needs lines with the 60/90 thresholds dashed, and bars.

## The World at a past tick

`/?tick=N` replays the globe: `useReplayCitizens` reads `GET /entities?at=N` once and hands it to the globe as a
paused frame in the live state's shape, so the live citizens' drawing (D61) shows everyone where they were; the live
feed stays off and the sky stops at that moment; a badge says so with **back to live** (drops `tick`, keeps the rest).
`?follow=id` follows the citizen as soon as the world is ready and they are in the frame (live or replayed). Tested in
`tests/smoke/world-replay.spec.ts`: every drawn citizen within 1 m of its `/entities?at=N` position, unchanged after
2.5 s, and somebody has moved since (so it is really the past).

## Gotchas

- SQLAlchemy's `.op("%")` binds tighter than `-`: `(tick - start).op("%")(step)` rendered `tick - (start % step)`;
  use `func.mod(tick - start, step)`.
- Grouping by an expression with bound parameters needs one labelled expression object (`day = (col // 1440)
  .label("day")`, then `group_by(day)`); writing the expression twice makes two parameters and Postgres rejects it.
- `?at=0` already includes everything that happened in tick 0 (speech before the first tick is tick 0).
- The dev cast's stores are empty (`dev.yaml` has no `stores`); stats tests use the real cast for food.
