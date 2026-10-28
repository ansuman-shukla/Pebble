# 02 · Simulation

The simulation is the single authority on what is true. It runs in its own process, advances on a fixed tick, and
writes every change to the event store.

## Clock and tick

- **Tick = 1 game minute.** At default speed one tick runs every real second. Speed is configurable (pause, ×1…×60).
- Each tick: advance durative actions → move entities → update bodies → ecology → perception/interrupts → emit events.
- Positions are continuous on the sphere; the client interpolates between ticks.
- Seeded RNG per subsystem; state snapshots every game hour so any run can be resumed or replayed.

## Entities

| Kind | Examples | Stored as |
|---|---|---|
| Citizen | 15 people | entity with body, inventory, knowledge, role |
| Animal | deer, boar, wolf, bear, lion, fish shoals, birds | entity (herds/shoals as groups) |
| Item | berries, meat, fish, wood, flint, spear, hide, rice | stacks in inventories, on the ground or in stores |
| Structure | houses, castle, walls, fire pit, shelter, storehouse, well, paddy | entity anchored to cells |
| Resource | berry bushes, nut trees, reeds, flint seam, fish stock | per-cell counters that deplete and regrow |

## Citizen body (v0)

| Need / stat | Range | Rises / falls | Effect |
|---|---|---|---|
| Hunger | 0-100 | +4/game hour (×age, ×work) | >60 hungry, >90 starving → health loss |
| Thirst | 0-100 | +6/game hour (×heat, ×work) | >90 → fast health loss |
| Energy | 0-100 | −5/awake hour, +12/sleep hour | 0 → collapse asleep where they stand |
| Health | 0-100 | injuries, starvation, thirst; heals slowly when needs are met | 0 → death |
| Warmth | (v1) | with seasons | cold damage |

**Age groups** change speed, strength, carry weight and need rates:

| Group | Ages | Speed | Strength | Carry |
|---|---|---|---|---|
| Child | 5-12 | 0.7 | 0.3 | 5 kg |
| Teen | 13-17 | 1.0 | 0.7 | 15 kg |
| Young adult | 18-30 | 1.0 | 1.0 | 25 kg |
| Middle-aged | 31-50 | 0.9 | 0.9 | 25 kg |
| Elder | 51+ | 0.6 | 0.5 | 10 kg |

Death causes in v0: starvation, dehydration, animal attack, drowning. The body stays where it fell. v0 has no births
and no aging over time (ages are fixed); both arrive with v2.

## Ecology (v0)

- **Plants** are per-cell resource counters by biome. Gathering depletes them; they regrow over game days (berries
  ~3 days, roots ~5, nuts ~7). Overuse near camps causes real scarcity.
- **Herbivores** (deer, rabbit, boar, goat, elk, antelope) graze, wander in herds, flee from citizens and predators.
- **Predators** (wolf, bear, lion, polar bear, shark) hunt mostly at dusk and night. They attack a citizen within a
  short range when hungry, unless the citizen is near fire or in a group of 3+. Attacks cause injuries; repeated
  attacks can kill.
- **Fish** are stocks in water cells; shallow water fish can be caught by hand or spear, deep water needs a boat (v1).
- Populations have soft caps per biome and respawn slowly, so hunting pressure matters.
- v0 numbers (D62-D66): ~270 animals in groups (herds, packs, shoals) whose sizes are the caps; a dead member is
  replaced after 1-6 game days. Predators hunt below +4° sun when hungry; a person is safe within 15 m of a lit
  fire, with 2 others within 10 m, or inside the walls. Fish are a per-cell stock (shallow sea, lakes, rivers)
  that grows back in ~4 days; visible shoals swim near the shores.

## Fire, food and the town economy (v0)

- **Fire** needs wood and the fire skill (both regions have it). It gives light, warmth, cooks meat (raw meat can make
  you sick) and keeps animals away. It burns out unless fed. A piece of wood burns an hour, a fire holds twelve; light: night sight
  ~30 m within 12 m; animals keep 25 m away; warmth arrives with seasons (v1).
- **Town** fields grow rice and vegetables when tended; harvests go to a shared storehouse open to town members. The
  well never runs dry. Walls keep animals out. (Money, ownership and taxes come in v2.)
- **Bands** live from gathering, hunting and fishing; food spoils after a few days unless dried (drying racks).

## Scripted brains (v0 citizens and animals)

Before agents arrive, every citizen runs a **utility brain**: each tick it scores options from its needs, danger, time
of day and role (thirsty → nearest known water; hungry → food; night → home and sleep; predator → flee; idle → chores,
wander, chat with greetings). Scripted brains use **exactly the same action API** as agent minds will
(`03-actions-perception.md`). If a scripted brain can't live a normal life through that API, the API is incomplete.

## Invariants (tested)

- Same seed + same inputs → same world state.
- Needs, deaths and resource counts never go out of range.
- Every state change has exactly one event.
- No citizen can act on something it can't perceive or reach.
