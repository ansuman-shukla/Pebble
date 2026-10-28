# 03 · Actions and perception (the world contract)

This is the only interface between a mind and the world. Scripted brains call it through Python; agent minds call
the same thing through the `world` MCP server. Everything is phrased in-world: no numbers they wouldn't know, no paths,
no technical errors.

## Perception

What a citizen can sense depends on light, terrain and distance.

| Sense | Range |
|---|---|
| Sight, day | ~150 m (forest ×0.4, hills give a view bonus) |
| Sight, night | ~20 m; ~30 m around a fire |
| Hearing, normal speech | ~30 m |
| Hearing, shout | ~150 m |
| Whisper | ~3 m |

A perception describes, in words:
- **Self:** body in coarse words ("very thirsty", "a little tired", "your leg hurts"), what you carry.
- **Place:** the place name if known ("the river by the camp"), else a description ("an unfamiliar pine forest").
- **Time:** from the sun, as a sentence ("It is late afternoon.", "The sun is about to set."), plus a coarse
  `time_of_day` (pre-dawn, dawn, early morning, mid-morning, midday, early afternoon, late afternoon, sunset, dusk,
  night) for code that shouldn't parse prose.
- **Others:** people you know by name; strangers by appearance ("a man in a fur cloak"); animals by kind, a group
  once ("a herd of deer", "two wolves", "a shoal of fish") with what it is doing ("grazing", "asleep", "watching
  you", "coming at you"), remains as "the remains of a deer". Everyone in view is always told; people at the same spot doing the same share a phrase ("Aiko, Genzo and a man in a fur cloak
  a few paces to the north").
- **Things:** visible food, water, items, structures, resources ("bushes heavy with berries"), fires ("a campfire
  burning", "embers glowing", "a cold fire basket"), with like things grouped
  ("three lean-tos, the nearest a few paces to the east", "plenty of wood on the ground"). Things are told by
  importance within a word budget: every water in sight, your home, the nearest food, shelter and fire (every fire within a few paces) always, then
  the rest (wood and reeds, items on the ground, other buildings) nearest first while the budget lasts. Each entry
  also carries how near it is and what kind of thing it is (water, food, shelter, fire, …) as fixed words.
- **Heard:** speech within range, with who said it if you can see them.

Each citizen keeps **knowledge** the world tracks for it: known places (its mental map), known people, skills.
Walking somewhere new adds it to known places; being told about a place adds a rough idea of it.

## Actions

**Instant** actions return right away. **Durative** actions take game time and block until they finish or are
interrupted.

| Action | Kind | Notes |
|---|---|---|
| `look_around()` | instant | current perception |
| `check_self()` | instant | body and inventory only |
| `say(words, volume)` | instant | normal / whisper / shout; heard by everyone in range |
| `walk_to(target)` | durative | a known place, a visible person/thing, or a direction + rough distance |
| `follow(person)` | durative | until they stop, vanish or you're interrupted |
| `gather(resource)` | durative | berries, roots, nuts, reeds, wood, flint… |
| `fish()` / `hunt(animal)` | durative | outcome by skill, tool (a spear), strength, group; can hurt you. Fish: at a river, lake or shallow sea shore. Hunt: an animal in view; you creep up on it, then strike |
| `eat(item)` / `drink()` | durative | from inventory or within reach; raw meat or fish eaten beside a fire is roasted (more filling), raw it can make you sick |
| `pick_up(item)` / `drop(item)` / `give(item, person)` | instant | within reach (for town folk a storehouse within reach counts); giving needs acceptance; the words may say how many ("a fish", "two berries", "half the meat", "a few nuts"), else all of it |
| `make_fire()` / `feed_fire()` | durative | make: the fire skill and wood; lights a fire pit or basket within reach, else a campfire where you stand. Feed: wood carried, then wood lying beside the fire. A fire burns down unless fed |
| `rest(minutes)` / `sleep()` | durative | sleep ends at morning, on danger or when rested |
| `work(task)` | durative | role tasks (town): farm, store food, guard, trade, weave, govern; needs the skill and the place (cook, repair later) |
| `attack(target)` | durative | people within reach or animals in view; consequences are real (a struck predator may bite back) |
| `flee()` | durative | run away from the nearest dangerous animal in view |
| `wait(minutes)` | durative | do nothing, stay alert |
| `recall(about)` | instant | agent phase only: "try to remember…" (see `05-memory.md`) |

**Interrupts** end a durative action early and say why: someone speaks to you or near you, a stranger or an animal
comes into view, someone you know walks up to you (within ~10 m), a predator comes at you, you are hurt (this wakes sleepers too),
a need crosses a threshold, night
falls, the target is gone. People you know merely walking by don't interrupt. The result always says
what happened and what changed ("You stop walking: a wolf is watching you from the trees, 40 paces away.").

## Rules
- You can only act on what you can perceive or reach. Unknown places can't be walked to by name.
- Failures are in-world ("There's no water within reach.", "You don't know how to do that.").
- The world never reveals ranges, numbers, IDs or anything outside the world.
- v1+ adds `craft(recipe)`, `build(structure)`, `teach(person, skill)`, `paint(surface, image)`, `trade`. Each new
  action ships with scripted-brain support and tests before any agent sees it.

## Contract ownership
The contract lives in the backend (`app/world_api/`) as typed Pydantic models: one source for the Python API used by
scripted brains, the MCP tool schemas used by agent minds, and the OpenAPI types used by the spectator UI.
