# Findings: living citizens (M7 scripted citizens + the first slice of the M8 live feed, 2026-10-29)

The 15 citizens of the v0 roster now live on the real planet: scripted utility brains drive them through the same
`world_api` facade agent minds will use, the town farms rice into its storehouse, wild plants grow back, and the api
streams everyone's position and doings over a WebSocket. Numbers below are from the stored world of generator `m3.2`
(seed 20261028) on an M-series Mac.

## The cast (`backend/data/citizens/citizens.yaml`)

| Id | Name | Region | Role | Age | Sex | Look | Home | Skills | Starts with |
|---|---|---|---|---|---|---|---|---|---|
| masanori | Masanori | town | lord of the castle | 55 | m | town-lord | castle-keep | governing, arms | |
| kenji | Kenji | town | samurai retainer | 34 | m | town-samurai | castle-keep | arms | |
| fumiko | Fumiko | town | merchant | 40 | f | town-merchant | main-e-2 | trade | |
| genzo | Genzo | town | rice farmer | 28 | m | town-farmer | farmhouse-1 | farming | |
| aiko | Aiko | town | weaver, the farmer's wife | 26 | f | town-weaver | farmhouse-1 | weaving, farming | |
| hana | Hana | town | the farmer's child | 9 | f | town-child | farmhouse-1 | | |
| ama | Ama | band A | band leader | 44 | f | band-a-leader | lean-to N | gathering, hunting, fire | 8 dried meat |
| oru | Oru | band A | elder healer | 63 | m | band-a-healer | lean-to W | gathering, healing, fire | 6 dried meat |
| tek | Tek | band A | hunter | 24 | m | band-a-hunter | lean-to E | gathering, hunting, fire | 10 dried meat |
| lia | Lia | band A | teen gatherer | 15 | f | band-a-gatherer-teen | lean-to N | gathering | 6 dried meat |
| suna | Suna | band A | gatherer | 30 | f | band-a-gatherer | lean-to E | gathering, fire | 8 dried meat |
| barro | Barro | band B | band leader | 38 | m | band-b-leader | lean-to N | gathering, hunting, fire | 8 dried meat |
| nim | Nim | band B | mother | 29 | f | band-b-mother | lean-to N | gathering, fire | 8 dried meat |
| kaz | Kaz | band B | young hunter | 19 | m | band-b-hunter | lean-to E | gathering, hunting | 10 dried meat |
| pip | Pip | band B | child | 7 | m | band-b-child | lean-to N | gathering | 4 dried meat |

Everyone knows everyone in their region and the places of their home ground (town folk: the town's named places;
bands: their camp). Each has an appearance (how strangers see them) and a one-line personality for phase B. The town
storehouse (`store-2`, at the storehouses' stand) starts with 400 measures of rice, about six days for the town.
Homes: the keep is now a home kind; camps contribute their lean-tos (`band_a_camp:shelter-n`, …) and fire pit.

## The town economy and the wild (sim)

| Piece | Rule |
|---|---|
| `work(task)` | farm (skill farming, in the rice fields, 60 min), store food (anyone in town, at a storehouse, 5 min), guard (arms; gates, castle, training ground; 45 min), trade (market), weave (at home), govern (castle); 60 min unless noted. Wrong place or missing skill fail in-world ("There are no fields here to tend.", "You don't know how to do that."). Work stops on worsening needs and at nightfall like walking. |
| Farming | an hour of tending ripens 12 measures of rice in the field (`item_moved` from `world` to the field's store); the farmer harvests what they can carry, the rest waits in the field. Farming counts as hard work for hunger and thirst (×1.25). |
| Storehouse | `work("store food")` puts all carried food in the storehouse within 6 m of its door; town folk (`region` town) `eat` from it when they carry none. Rice: 0.2 kg, 10 hunger a measure. |
| Regrowth | a gathered cell grows back one piece every `days × 1440 / cap` ticks until full (berries 3 days, roots 5, nuts 7, reeds 4, wood 6), one `resource_changed` event a piece. Cells nobody touches keep their starting stock. |
| New resources | reeds (wetland 40, and 12 on rivers through living ground) and wood (forests 40, grassland 6, savanna/hills 4). |
| Identity in state | role, region, skills, facing (`heading_deg`) and a starting inventory are part of the citizen (spawn event, snapshot v2). A run whose latest snapshot has another version isn't resumed: the engine starts a new one. |

## The brains (`backend/app/brains/`)

```
 engine tick ─▶ for each citizen: alive? ─▶ last action still running? ── yes ─▶ nothing
                                                   │ no (done, interrupted, or nothing yet)
                                                   ▼
            look_around() ─▶ senses: needs from body words, phase from time_of_day (local sun),
                             place words, water/fire/plants by kind and nearness, people by name
                    ─▶ reply to / greet a known person close by (once a day each) ─▶ say + wait(2)
                    ─▶ else score options and start the best:
                         flee (animals, M6) 200 > thirst 50-110 > hunger 45-105 > exhausted sleep 90
                         > night: home + sleep 70 > dusk: store the harvest, eat, home / fire 40-46
                         > role routine 30 > idle 1
                    ─▶ failed at once (or twice "already there")? ─▶ wait 10-25 min and look again
```

- Only `app.world_api` (and `app.core.rng`) is imported; a test parses the package's imports and forbids reaching
  behind the facade (`api.sim`). The facade gained three non-actions for minds: `alive`, `handle(number)` (an earlier
  action's handle, e.g. after a resume) and `notes` (the brain's working memory). Notes live in the world state, so
  snapshots carry them and a resumed run continues identically (tested with brand-new brain objects).
- Brains decide only at decision points (action ended or interrupted), so they perceive ~1 300 times a game day in
  total, not every tick. Their randomness is a SplitMix64 stream per citizen kept in its notes.
- Routines: the farmer farms and carries rice to the storehouse when he holds plenty (and at dusk); the weaver weaves
  at home in the morning and farms in the afternoon; the merchant trades at the market with a stroll every third
  hour; the samurai keeps watch at the main gate, the west gate, the castle and the training ground in turn; the lord
  holds court at the castle and walks to the temple or market now and then; the child plays around the well.
  Bands forage in outings (leader 4, hunter 5, healer 3, gatherers 5, child 2 gathers), most filling food first
  (roots, nuts, berries), with a daily chore (wood or reeds) they put down by the fire at dusk; they drink at the
  river near camp, rest by the fire at dusk and sleep in their lean-tos. Town folk eat at the storehouse at dawn and
  dusk, drink at the well, and sleep at home.
- Time of day comes from perception's `time_of_day` (local solar time): band A lives ~6 h ahead of the town, band B
  ~11 h behind (it starts the first run asleep).

## Spectator view and the live feed

- `CitizenEntity` (in `/entities`, `/entities?at=`, and the feed) gained `role`, `region`, `heading_deg` (yaw in the
  local tangent frame, 0 = facing south, 90 = east, 180 = north: `180 − compass bearing` of the last step, carried by
  `tick_summary`) and `activity` (idle, walking, sleeping, resting, gathering, eating, drinking, working, talking,
  dead), derived from the action, sleep, death and speech (talking = spoke in the last 3 ticks while not otherwise
  busy).
- `WS /api/v1/live[?run_id=]`: a listener thread in the api process LISTENs on `pebble_events`, replays each followed
  run (latest snapshot + events, the `/entities?at` reducer) and fans out JSON: a `snapshot` on connect, `event`
  messages for public `said`, `died`, `action_started`, `action_finished` (in event order, before their tick), one
  `tick` message after each tick's summary, and a `tick` with the same tick when speed or pause change. Clients of
  the latest run are closed with code 1012 when a newer run starts (reconnect for its snapshot); an unknown run closes
  with 4404. `GET /api/v1/live/schema` exports the message models; generated TS types: `LiveState`
  (`type: 'snapshot' | 'tick'`), `LiveEvent` (`event: LiveEventDetail`), the union `LiveLiveSchemaResponse`, and
  `CitizenEntity`.
- Measured against a scratch database with the engine at speed 10: 40 tick messages in 4 s, pause gives one `tick`
  with `paused: true` and then silence; `/entities` answers in ~9 ms.

## A 10-day run

`uv run python -m scripts.citizens_run 10` (no database) and `python -m app.engine --new-run --headless --ticks 14400`
against a scratch database give the same world (deterministic):

| Day | Deaths | Storehouse rice | Food the bands carry (hunger) | Events | Decisions (look_around) | Said | Plants regrown |
|---|---|---|---|---|---|---|---|
| 1 | 0 | 433 | 1 464 | 5 336 | 1 152 | 60 | 66 |
| 2 | 0 | 474 | 1 443 | 5 704 | 1 252 | 32 | 186 |
| 3 | 0 | 527 | 1 448 | 6 038 | 1 365 | 40 | 210 |
| 4 | 0 | 569 | 1 366 | 5 761 | 1 257 | 31 | 235 |
| 5 | 0 | 598 | 1 239 | 6 007 | 1 333 | 35 | 262 |
| 6 | 0 | 637 | 1 344 | 5 530 | 1 153 | 32 | 238 |
| 7 | 0 | 688 | 1 291 | 5 563 | 1 175 | 40 | 273 |
| 8 | 0 | 742 | 1 309 | 5 673 | 1 201 | 38 | 260 |
| 9 | 0 | 801 | 1 373 | 5 856 | 1 259 | 36 | 290 |
| 10 | 0 | 886 | 1 191 | 5 909 | 1 286 | 27 | 290 |

- Nobody died; on day 10 every body is healthy (health 100, hunger and thirst under 60), and nobody's health dips
  below 99 on the way (the living test now fails under 90). The storehouse more than doubled; the bands hold a
  steady day or two of food each and regrowth keeps pace near the camps.
- Time shares: town workers ~45 % working, ~45 % asleep; bands ~45 % asleep, 14-24 % gathering, 20-28 % resting
  (dusk by the fire, rests between outings; the healer rests most), 2-8 % walking. The longest awake stretch
  without progress (only waiting or resting) is 4.0 h (Oru); the town stays under 1.8 h.
- Tick cost without the database: simulation 0.28 ms mean (p99 0.4-0.9 ms), brains 0.6 ms mean (max 40 ms when
  several plan walks at once). With the database: 10 game days in 65 s (~4.5 ms a tick including writes and
  hourly snapshots), 92 MB for the whole run.

## Tests

`tests/brains/test_living.py` runs the 10 days once (~15 s) and checks: no deaths, nobody stalls 6 h awake, everyone
moves > 100 m every day, nobody stands on a blocked town cell, bands asleep within reach of their lean-to every
night (local 00:30-04:00) and foraging every day, the town's roles worked every day, the storehouse rises. Plus
determinism with brains (same seed = same day; resumed run = same future), the import isolation, the economy and
regrowth rules, the cast against the roster and the frontend's looks, activity derivation, facing, and the live feed
over a real WebSocket. Mutation pass: 31 mutants on brains, economy, regrowth, river reeds, snapshot notes, facing,
activity, the feed and the engine's version check; 30 killed, 1 equivalent survivor (dropping the bands' "not by
night" guard: night's home-and-sleep options outscore foraging anyway).

## Known limits and open points

- Perception used to list the 12 nearest things, so at a busy camp the river was often left out. It now groups like
  things and tells them by importance within ~120 words (D63, D64): water, home, food, shelter and fire are always
  told. In the 10-day run a full look would take 121 words at the median (163 at most); the budget trims 51 % of
  looks and only ever drops other buildings, wood and reeds, or items on the ground. Letting lakes into band
  perceptions exposed that a lake beside you was told "close by" (its cell's centre), so brains on the shore never
  drank and went to bed parched (health down to 40); a lake or the sea next to your cell is now "right beside you".
- Speech interrupts everyone in earshot (03), so a greeting near the fields costs a farmer the hour of tending in
  progress (nothing ripens from a cut-short session).
- "talking" is not in snapshots: a spectator view replayed from a snapshot shows someone who spoke in the two ticks
  before it as idle.
- Bands don't share food yet (`give` and the `GiftPolicy` hook are unused by brains); hunters gather like everyone
  else until M6 brings animals.
- Ground stacks of wood and reeds grow by the fire pits (one stack per drop) until fire (M6) burns them.
- NOTIFY reaches listeners only on commit, so the live feed test commits for real (`committing_engine` on the test
  database) rather than using the rolled-back `db_session`.
- When the engine reconnects after a lost database connection it rebuilds the simulation from the database; the
  citizens' brains are rebuilt on the fresh simulation too (their notes come back with the snapshot), so the
  reconnect test's "same as uninterrupted" check now covers 3 citizens living with brains.
