# Findings: the live citizens on the planet (M8 client, first slice, 2026-10-29)

What the browser does with the engine's citizens: where the data comes from, how a citizen is drawn between ticks,
what each activity looks like, the People panel and the clock, what it costs and what is still rough. Built against
the live contract (`.runtime/briefs/live-contract.md`) with a deterministic mock feed, then switched to the real
feed once the backend half (citizens spec, brains, WebSocket `/api/v1/live`, extended entity fields) landed.

## Pages and controls

| URL / control | What |
|---|---|
| `/` | the real world with the backend's citizens (`GET /api/v1/entities`, then the feed) |
| `/?mockLive=1` | the dev/test mock feed: 15 citizens (the 15 look ids) around the town and both camps, starting at 08:00 |
| `/?mock=1` | the mock world without a feed (the engine's citizens don't belong on it); `&mockLive=1` adds the mock feed |
| `people` | the People panel: name, role, region, activity in words, body state; a row or `follow` → the camera follows that citizen (Esc or `stop following` returns to the player); `go to` → drops the player next to them |
| clock (bottom right) | engine day and time; `pause`, `×1`, `×10`, `×60` call `POST /api/v1/admin/clock` (the mock: its own clock) |
| `time ×60` | only without a feed (the client-side clock of M4) |

## Data flow

```
GET /api/v1/entities ──┐
                       ▼
 WebSocket /api/v1/live (snapshot on connect, tick per engine tick, said/… events)
   │  dropped? reconnect 0.5 s, 1 s, 2 s … 15 s; the next snapshot resyncs everything
   │  closed 4404 (no run yet)? "no run yet", same backoff; closed 1012 (a newer run)? reconnect at once
   ▼
 lib/live/live-contract.ts ── the generated models (CitizenEntity, LiveState, LiveEvent) under the live names
   ▼
 live-state reducer ── frames replace citizens; stale ticks of a run are ignored; a new run starts over;
   │                    said events become speech for 4 s
   ▼
 GlobeNpcs (canvas) ─ People panel / clock / NpcHooks (DOM)
```

- `/` opens the WebSocket through vite's `/api` proxy (`ws: true`). A failed WebSocket handshake logs a console error
  in Chrome (proved with a 403 on `ws://localhost:8100/api/v1/live`), which is why the client waited for the route.
- The backend accepts every socket before it looks for a run, so "no run" arrives as an open socket closed with 4404.
  The client counts a connection as live only from its first message, and resets the backoff there (resetting it on
  open would retry a missing run every 0.5 s forever).
- The mock feed is a fake WebSocket driven by the same tick loop, so the reconnect path is the real one;
  `window.__pebbleMockLive` lets tests drop connections (`dropConnections(code)`), make someone speak (`sayNow`),
  start a new run (`restartRun()`, closes with 1012), refuse connections like a backend without a run (`noRun`) and
  change its clock (`setClock`).

## Drawing a citizen

- **Between ticks**: from where the citizen is drawn now to the new position over one tick at the feed's speed
  (`tickMs(speed)` in `live-contract.ts`: 1 s at ×1, 17 ms at ×60, a minute at one tick a minute). A frame that
  arrives mid-glide starts the next glide from the drawn spot, so nothing jumps. Without this, Kenji's walk to the gate
  was one 83 m jump (the test's mutation check). The interval used to be measured between frames and capped at 2 s,
  so with ticks further apart walkers arrived early and stood still until the next tick.
- **Heading**: eases to `heading_deg` at 8/s in the citizen's own tangent frame (0 = south, 180 = north).
- **Ground**: the town's plateau height on its ground disc, else `terrain.heightAt` (the drawn surface). Paving and
  bridges aren't probed (feet sink a few centimetres into paving).
- **Activity → clip** (`lib/live/npc-activity.ts`): walking → Walk paced to the walk (Idle once arrived); working →
  the engine's task words: Arms folded (watch/guard), Talking (trade/market/court), Fixing (weave/loom/mend), Pick up
  (storehouse/carry), Chopping wood (wood/log), Planting (plant/sow/seed), else Harvesting; gathering → Harvesting, Pick up (roots, reeds,
  nuts, stones, sticks, wood); eating → Eating; drinking → Drinking; talking → Talking; resting → Sitting (the body
  lowered 0.42 m so it sits on the ground); sleeping → Idle with the rig rotated onto its back; dead → the same, frozen;
  idle → Idle.
- **Clips per activity**: every model loads Idle and Walk; a new activity's clip joins the set and the character is
  re-bound (Polyfork fetches each clip once per page); Idle plays until the new clip is in.
- **Reach**: full models within 400 m of the camera (hidden again past 420 m); a model is created the first time its
  citizen comes within reach. Farther citizens are not drawn (no markers yet).
- **Labels**: "name · activity in words" within 40 m (children's and teens' labels hang lower); speech bubbles (white,
  wrapping at 14 rem) over the name for 4 s after a `said` event.
- **Solid**: every citizen is a 0.3 m standing cylinder around their feet in whichever chart resolves the player's
  step (the town, a camp, a landmark or the wild); a citizen walking into a standing player pushes them aside.
- **Following**: a second follow rig orbits the citizen (drag to turn, wheel to zoom, the same spring arm and ground
  clearance); the player stands still meanwhile. The walk keeps two wild charts, so following someone 4 km away
  doesn't rebuild the wild collisions every frame.

## Time is compressed 60×, so walkers glide fast

One tick is one game minute and runs every real second at ×1, and the engine walks 5 km/h = 83 m per tick. So at ×1 a
walking citizen covers 83 m per real second on screen. The walk clip is paced to the game pace (83 m / 60 s =
1.4 m/s, a calm walk), so a walker glides across the town in a couple of seconds with relaxed legs. This is the
contract's time scale, not a client bug; slowing it down would need a different tick length or a "real time" speed.

## Performance (real world, mock feed)

1280×800, headless Chrome with the Metal GPU, M-series Mac.

| View | Draw calls | Triangles | fps | worst frame |
|---|---|---|---|---|
| follow at the town spawn, 6 townspeople loaded | 203 | 3.1 M | 60 | 21-28 ms |
| following Oru at band A's camp (5 + 6 loaded) | 75 | 2.6 M | 60 | 33 ms |
| following Brak at band B's camp (all 15 loaded) | 65 | 2.8 M | 60 | 25 ms |
| back at the town spawn after visiting both camps | 207 | 3.2 M | 60 | 27 ms |
| town spawn, clock paused | 200 | 3.1 M | 60 | 18 ms |

The occasional 20-30 ms frame comes with ticks (every citizen re-renders and labels whose words change re-register);
paused, no frame passes 18 ms.

## Tests

- `tests/smoke/live-feed.spec.ts` (no browser): the reducer (stale ticks, the same-tick clock change, snapshots,
  new runs, speech expiry and dedupe), clips and words per activity, the mock's 15 citizens.
- `tests/smoke/live-npcs.spec.ts` (browser, `/?mockLive=1`): 15 citizens glide (no step over 35 m between 100 ms
  samples while someone walks 82 m) and stay on the ground (±0.5 m of the plateau or `terrain.heightAt`, computed by
  the test); loaded citizens play their activity's clip; the camps' people aren't loaded from the town; draw calls under
  300; a `said` event's bubble shows for 3.5-5.5 s; the People panel lists 15, follow flies the camera to Oru (focus on
  him, camera within 45 m, his model loads) and Esc flies back; go to lands within 5 m of the lord, his label reads
  "Lord Tadamasa · standing about", walking into him stops > 0.5 m away; the sky takes engine time over `?time=`; ×60
  runs > 20 ticks a second, pause stops it; a dropped feed reconnects and ticks on; with a tick every 8 s Kenji keeps
  gliding 1-6 s into the tick; a new run (1012) reconnects within 1 s and resyncs to 08:00; no run (4404) shows
  "no run yet" and retries with backoff (1-3 tries in 3 s) until a run starts.
- The same spec against the real feed (`/`, the shared dev engine): 15 citizens ready, someone moves or changes activity
  within 5 s, drawn positions match `GET /api/v1/entities?at=<page tick>` (exactly for those standing still), drawn
  activities match the engine's, loaded citizens play their clip, the People panel lists 15.
- `tests/smoke/explore-walk.spec.ts`: a citizen blocks the way in the town and out in the wild.
- Mutation checks (one substitution, one spec, restore): 16/16 killed: no interpolation, the town plateau off by 1 m,
  people not solid, a fixed Idle clip, no reconnect, speech for 1.5 s, follow without the citizen rig, everyone loaded
  at any distance, the sky not taking engine time, stale ticks applied, Planting dropped, the heading's sign, sleepers'
  activity, duplicate speech.

## Rough edges

- `tickMs` and the sky's rate (`globe-page.tsx`: game minutes per real second = `speed`) both assume the engine's
  `speed` is ticks per real second; a change to what `speed` means has to change both.
- Between ticks a walker cuts the corner of its route (the feed sends positions, not routes): at 83 m per tick it can
  pass through a house for a moment.
- No markers for citizens beyond 400 m; the People panel is the way to find them.
- The mock's walks are straight lines between hand-picked spots, through fences and the moat.
