# Findings: the world-complete gate (M9, 2026-10-29)

The review of Phase A against the M9 checklist in `docs/design/09-roadmap.md`. Every box is ticked: Phase A is
complete and Phase B (agent minds) can start. Numbers are from the stored world of generator `m3.2`
(seed 20261028) on an M-series Mac. The full backend suite (`make -C backend pre-commit`) passes, as do the frontend
checks and the Playwright suite.

## Verdict

| # | Checklist item | | Evidence |
|---|---|---|---|
| 1 | Terrain, biomes, oceans, rivers, poles and the land loop are generated and rendered | ✅ | `tests/world/test_generate.py` (`test_same_seed_and_spec_give_identical_worlds`, `test_biome_shares_are_in_range`, `test_poles_are_frozen`, `test_rivers_flow_downhill_and_end_in_water`, `test_land_loop_is_a_closed_walkable_cycle_around_the_planet`, `test_the_ice_gate_is_a_narrow_ice_bridge_at_high_latitude`), `test_hydrology.py`, `test_biomes.py`; Playwright `planet.spec.ts`, `globe.spec.ts`, `water.spec.ts`, `biome-props.spec.ts`; screenshots `orbit`, `ice-gate` |
| 2 | Town (castle, walls, gate, houses, pagoda, shrine, market, well, mill, paddies) and both camps are built | ✅ | `tests/world/test_town.py::test_town_has_the_landmark_buildings`, `test_walkability.py` (gates, walls, moat, every building front reachable), `test_spec.py::test_sites_match_the_world_description`; Playwright `walk.spec.ts`, `explore.spec.ts` (a camp lean-to is solid); screenshots `town`, `market`, `market-mill-paddies`, `camp-a`, `camp-b` |
| 3 | All 8 landmarks exist, are named and reachable | ✅ | `test_generate.py::test_every_site_is_reachable_on_foot_from_the_town`, `test_great_falls_drops_off_a_cliff_into_a_lake`, `test_the_volcano_is_volcanic_with_a_crater`; Playwright `"Go to" drops the player at every named site`; the HUD names each site; screenshots `landmarks-*` (the castle is in `town`) |
| 4 | Every v0 animal exists, behaves and renders | ✅ | `tests/sim/test_ecology.py` (habitats, caps, sleep cycles, flight, predator rules, respawn), `tests/brains/test_living.py::test_animal_populations_stay_within_caps_among_the_people`, `test_predators_hurt_people_only_alone_at_dusk_or_night_away_from_fire`; Playwright `gallery shows all 15 citizens animated and every animal labelled`, `live-wild.spec.ts`; the dev API run has 269 animals of all 15 kinds; screenshot `animals` |
| 5 | Every v0 action and perception is used by scripted brains, and the contract is frozen | ✅ | 21 of 22 actions used in a 10-day run (table below), `recall` is agent-only (D74); `test_living.py::test_the_brains_use_every_action_but_recall`; `tests/world_api/test_contract.py` freezes the contract (D74) |
| 6 | Bodies, needs, injuries and death work end-to-end | ✅ | `tests/sim/test_clock_bodies.py` (`test_needs_rise_at_the_documented_rates`, `test_starvation_and_dehydration_kill_with_the_right_cause`, `test_healing_needs_food_and_water`, `test_collapse_at_zero_energy_and_values_stay_in_range`), `test_ecology.py::test_repeated_attacks_can_kill`, `tests/api/test_stats_api.py::test_stats_record_deaths_by_cause`, `test_animal_deaths_are_not_counted_as_people` (fixed here) |
| 7 | Every state change is an event; replay works from snapshots | ✅ | `tests/sim/test_invariants.py` (`test_every_state_change_is_exactly_one_event`, `test_a_snapshot_resumes_into_the_same_future`, `test_snapshots_survive_json_round_trips`), `test_ecology.py::test_every_animal_and_fire_change_is_an_event`, `tests/observability/test_engine.py::test_a_run_resumes_from_its_snapshot_and_replays_the_lost_tail`, `test_replay_knowledge.py`; Playwright `world-replay.spec.ts` |
| 8 | 15 citizens run stably for 10+ game days | ✅ | `tests/brains/test_living.py` (one 10-day run: nobody dies, nobody stalls or walks through walls, bands sleep at camp and forage, farmers fill the storehouse, hunters hunt, fires burn through the night); `scripts.contract_usage 10`: 15/15 alive after 10 days, ~30 s headless |

## The contract in use (item 5)

`uv run python -m scripts.contract_usage 10` runs the 15 scripted citizens among the animals for 10 game days and
counts every action they start and every part of every perception they get.

| Action | Calls | Outcomes |
|---|---:|---|
| look_around | 13 139 | |
| check_self | 690 | |
| say | 407 | done 407 |
| walk_to | 6 811 | place 3 135, direction 2 979, thing 693, person 4; done 6 302, failed 39, interrupted 470 |
| follow | 112 | done 112 |
| gather | 1 462 | done 900, failed 153, interrupted 406 |
| fish | 95 | done 25, failed 49, interrupted 21 |
| hunt | 37 | done 10, failed 14, interrupted 13 |
| eat | 510 | done 343, failed 1, interrupted 166 |
| drink | 389 | done 243, failed 4, interrupted 142 |
| pick_up | 11 | done 10, failed 1 |
| drop | 37 | done 37 |
| give | 15 | done 9, failed 6 |
| make_fire | 65 | done 51, interrupted 14 |
| feed_fire | 110 | done 110 |
| rest | 1 735 | done 795, interrupted 940 |
| sleep | 154 | done 147, interrupted 3 |
| work | 903 | done 452, interrupted 446 |
| attack | 2 | done 2 (wolves driven off by spear carriers) |
| flee | 1 | interrupted 1 |
| wait | 894 | done 617, interrupted 276 |
| recall | 0 | agent phase only (D74) |

Perception parts, per look: `place`, `time`, `time_of_day` and `things` in all 13 139; `people` 11 433; `animals`
2 792; `heard` 823; feelings 8 740 and carried things 9 704. Every thing kind (water, sea, food, home, shelter, fire,
material, item, building), every wild plant, both heard volumes the brains speak at (normal, shout), 9 of 10 times of
day and 5 of 6 nearness words occur. Not seen in the run: "pre-dawn" (everyone is asleep then), "far away" (beyond
sight range, so it only appears in walk answers) and whispers (scripted brains don't whisper); unit tests cover all
three (D75).

## Fixes made for the gate

- **Brains used 18 of 22 actions.** `follow`, `give` and `attack` were never called and `check_self` only by chance.
  Now (D75): spear carriers drive off a predator that comes within 50 m, hunters home with meat walk up to someone
  at camp and hand over half, town children sometimes tag along after someone close by, and after a meal or a drink
  a citizen checks how full they are and goes on. Tests: `test_a_spear_carrier_drives_off_a_wolf_that_comes_close`,
  `test_a_hunter_back_at_camp_shares_half_the_meat`, `test_the_brains_use_every_action_but_recall`.
- **The contract was not frozen.** `tests/world_api/test_contract.py` compares the action list, the `WorldApi`
  methods and the JSON schemas of every action, result and perception with the committed `contract_v0.json` (D74).
- **Stats counted animal deaths as citizens' deaths.** `/stats` listed `deer:74 killed by a wolf` among the deaths
  and in `deaths_by_cause` and the per-day counts; it now counts only citizens
  (`test_animal_deaths_are_not_counted_as_people`).
- Earlier on this branch: the spectator label names the person a walk goes to, `follow` keeps going until the person
  stops, and `give` / `drop` / `pick_up` read how many from the item words ("half the meat", "two fish").

## Accepted v0 limits (D76)

- Animals walk in straight steps between goals (no path planning, D67) and are seen over walls (no line of sight).
- Food never spoils; only hunters share food (their meat).
- Bands sleep around the camp fire rather than inside the lean-tos; people sharing a lean-to or house stand at the
  same doorway spot.
- Seated and lying poses keep the walking facing.
- The town's drawn stream and moat are scenery; the well is the town's only water (D73).

## Screenshots

Taken from a worktree vite on 5202 against the dev API (a fresh run: 15 citizens, 269 animals, 6 fires), with
`?at=lat,lon,bearing` and the mouse wheel; kept locally, not committed:

- `/tmp/pebble-gate-orbit.png`: the planet from orbit (oceans, ice cap, biomes, rivers, the smoking mountain)
- `/tmp/pebble-gate-ice-gate.png`: the ice gate's ice blocks and snowy spruces on the polar ice bridge
- `/tmp/pebble-gate-town.png`: the approach to the main gate, walls, townhouses, the castle keep and the pagoda
- `/tmp/pebble-gate-market.png`: the market with Fumiko trading, the moat, castle walls and the shrine
- `/tmp/pebble-gate-market-mill-paddies.png`: the rice paddies, the water wheel (mill), drying racks and the stream
- `/tmp/pebble-gate-camp-a.png`, `/tmp/pebble-gate-fire-night.png`: band A asleep around its burning fire at night
- `/tmp/pebble-gate-camp-b.png`: band B's camp with its fire burning before dawn
- `/tmp/pebble-gate-landmarks-{smoking-mountain,great-falls,elder-tree,standing-stones,painted-cave,hot-springs}.png`
- `/tmp/pebble-gate-animals.png`: a deer herd grazing
