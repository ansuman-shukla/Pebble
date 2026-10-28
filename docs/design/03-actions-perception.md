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
- **Time:** from the sun ("late afternoon", "the sun is about to set").
- **Others:** people you know by name; strangers by appearance ("a man in a fur cloak"); animals by kind.
- **Things:** visible food, water, items, structures, resources ("bushes heavy with berries").
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
| `fish()` / `hunt(animal)` | durative | outcome by skill, tool, strength, group; can hurt you |
| `eat(item)` / `drink()` | durative | from inventory or within reach |
| `pick_up(item)` / `drop(item)` / `give(item, person)` | instant | within reach; giving needs acceptance |
| `make_fire()` / `feed_fire()` | durative | needs wood and the skill |
| `rest(minutes)` / `sleep()` | durative | sleep ends at morning, on danger or when rested |
| `work(task)` | durative | role tasks (town): farm, store food, guard, trade, weave, govern; needs the skill and the place (cook, repair later) |
| `attack(target)` | durative | people or animals; consequences are real |
| `flee()` | durative | away from the nearest danger |
| `wait(minutes)` | durative | do nothing, stay alert |
| `recall(about)` | instant | agent phase only: "try to remember…" (see `05-memory.md`) |

**Interrupts** end a durative action early and say why: someone speaks to you or near you, a stranger or an animal
comes into view, someone you know walks up to you (within ~10 m), you are hurt, a need crosses a threshold, night
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
