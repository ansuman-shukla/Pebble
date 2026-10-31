# 03 · Actions and perception (the world contract)

> This is contract **v1 (draft)** (D96, D108-D110): v0's 22 actions (frozen in D74, kept as the record in
> `backend/tests/world_api/contract_v0.json`) plus `pace` on walk_to/follow, ten new actions and the new perception
> fields of `10-world-v1.md` §6. The draft lives in `backend/tests/world_api/contract_v1_draft.json` with a changelog;
> C1 owns it through wave 3 and Q1 freezes it as `contract_v1.json`. Actions marked *draft* answer
> "You can't do that yet." until the stream that builds them lands; fields marked *draft* stay unset until then.

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
- **Self:** body in coarse words ("very thirsty", "a little tired", "your leg hurts"), what you carry. *Draft:* your
  `purse` ("seven coins", "a short string of coins"), `load` ("carrying a heavy load"), `titles`, your `standing` on
  the ground you're on ("People here regard you well."), whether you are `wanted` ("You are wanted in the castle town
  for theft."), `held` or `confined`.
- **Place:** the place name if known ("the river by the camp"), else a description ("an unfamiliar pine forest").
  *Draft:* whose `ground` it is ("Band A's ground", "the Lord's woods", "the road to the Elder grove") and how
  `safe` it is (`safety`: inside the walls, by the fire, in company, on home ground, exposed).
- **Time:** from the sun, as a sentence ("It is late afternoon.", "The sun is about to set."), plus a coarse
  `time_of_day` (pre-dawn, dawn, early morning, mid-morning, midday, early afternoon, late afternoon, sunset, dusk,
  night) for code that shouldn't parse prose. *Draft:* `day_of_week` ("the seventh day of the week; court day").
- **Others:** people you know by name; strangers by appearance ("a man in a fur cloak"); animals by kind, a group
  once ("a herd of deer", "two wolves", "a shoal of fish") with what it is doing ("grazing", "asleep", "watching
  you", "coming at you"), remains as "the remains of a deer". Everyone in view is always told; people at the same
  spot doing the same share a phrase ("Aiko, Genzo and a man in a fur cloak a few paces to the north"). *Draft:* a
  person's `relation` to you ("your father", "your lord", "someone who struck you") and `regard` (their standing and
  the deeds you know: "who stole rice from the racks"); `doing` grows to postures and motions ("sitting by the
  fire", "running", "carrying a load", "held by Kenji").
- **Things:** visible food, water, items, structures, resources ("bushes heavy with berries"), fires ("a campfire
  burning", "embers glowing", "a cold fire basket"), with like things grouped
  ("three lean-tos, the nearest a few paces to the east", "plenty of wood on the ground"). Things are told by
  importance within a word budget: every water in sight, your home, the nearest food, shelter and fire (every fire
  within a few paces) always, then the rest (wood and reeds, items on the ground, other buildings) nearest first
  while the budget lasts. Each entry also carries how near it is and what kind of thing it is (water, food, shelter,
  fire, …; *draft:* node, store, market, remains) as fixed words, and what could be gathered there (berries, roots,
  nuts, reeds, wood; *draft:* rice, flint, obsidian, iron sand, gold).
- **Heard:** speech within range, with who said it if you can see them.
- *Draft:* at an open stall, the `market` block (each good, its price in words, and dear / fair / cheap); at your own
  chest, the `chest` block ("Your chest holds …").

Each citizen keeps **knowledge** the world tracks for it: known places (its mental map), known people, skills.
Walking somewhere new adds it to known places; being told about a place adds a rough idea of it.

## Actions

**Instant** actions return right away. **Durative** actions take game time and block until they finish or are
interrupted. **Free** actions take no time at all and leave the body be (a sleeper sleeps on).

| Action | Kind | Notes |
|---|---|---|
| `look_around()` | instant | current perception |
| `check_self()` | instant | body and inventory only |
| `say(words, volume)` | instant | normal / whisper / shout; heard by everyone in range |
| `walk_to(target, pace?)` | durative | a known place, a visible person/thing, or a direction + rough distance; `pace` walk (default) or run: running tires you and turns to a jog after about three minutes |
| `follow(person, pace?)` | durative | until they stop, vanish or you're interrupted; `pace` as walk_to |
| `gather(resource)` | durative | berries, roots, nuts, reeds, wood (*draft:* rice, flint, obsidian, iron sand, gold at their nodes) |
| `fish()` / `hunt(animal)` | durative | outcome by skill, tool (a spear), strength, group; can hurt you. Fish: at a river, lake or shallow sea shore. Hunt: an animal in view; you creep up on it, then strike |
| `eat(item)` / `drink()` | durative | from inventory or within reach; raw meat or fish eaten beside a fire is roasted (more filling), raw it can make you sick |
| `pick_up(item)` / `drop(item)` / `give(item, person)` | instant | within reach (a store within reach counts: taking from one that isn't yours is theft, 10 §2.6); giving needs acceptance (coins to the lord pay your household's dues); the words may say how many ("a fish", "two berries", "half the meat", "a few nuts"), else all of it |
| `make_fire()` / `feed_fire()` | durative | make: the fire skill and wood; lights a fire pit or basket within reach, else a campfire where you stand. Feed: wood carried, then wood lying beside the fire. A fire burns down unless fed |
| `rest(minutes)` / `sleep()` | durative | sleep ends at morning, on danger or when rested |
| `work(task)` | durative | role tasks (town): farm, store food, guard, trade, weave, govern, pray (*draft:* ring bell); needs the skill and the place |
| `attack(target)` | durative | people within reach or animals in view; consequences are real (a struck predator may bite back) |
| `flee()` | durative | run away from the nearest dangerous animal in view |
| `wait(minutes)` | durative | do nothing, stay alert |
| `recall(about)` | instant | agent phase only: "try to remember…" (see `05-memory.md`) |
| `gesture(kind, to?)` | instant | wave, bow, nod, shake_head, point, laugh, jump, to a person in view or nobody; seen by everyone awake who can see you, never heard |
| `set_goal(text, driver)` | free | what you are after now (a few words) and why: hunger, thirst, rest, danger, duty, ambition, social, night; only spectators learn it |
| `buy(item, amount)` / `sell(item, amount)` | instant, *draft* | at an open market stall, in coins; goods trade in lots (10 §2.5) |
| `stash(item, amount)` | instant | into your own store within reach: your household's chest (the merchant: the stall) |
| `craft(recipe)` | durative, *draft* | flint, obsidian or iron spear, stone or iron axe, sickle, cloth, pack, dried meat, at its station (10 §2.3) |
| `accuse(person, to)` | instant, *draft* | tells `to` every deed you know of `person` (10 §3.4) |
| `seize(person)` | durative, *draft* | take hold of someone within reach; held, they can only look, speak and wait |
| `judge(person, sentence)` | durative, *draft* | a held or confined person within reach: a fine in coins or hours confined |
| `tend(person)` | durative, *draft* | half an hour of healing for a hurt person within reach |

**Interrupts** end a durative action early and say why: someone speaks to you or near you, a stranger or an animal
comes into view, someone you know walks up to you (within ~10 m), a predator comes at you, you are hurt (this wakes
sleepers too), a need crosses a threshold, night falls, the target is gone. People you know merely walking by don't
interrupt. The result always says what happened and what changed ("You stop walking: a wolf is watching you from the
trees, 40 paces away."). Instant and free actions don't interrupt what you are doing.

## Rules
- You can only act on what you can perceive or reach. Unknown places can't be walked to by name.
- Failures are in-world ("There's no water within reach.", "You don't know how to do that.", "You can't do that
  yet.").
- The world never reveals ranges, numbers, IDs or anything outside the world.
- Later contracts may add `build(structure)`, `teach(person, skill)`, `paint(surface, image)`. Each new action ships
  with scripted-brain support and tests before any agent sees it.

## Contract ownership
The contract lives in the backend (`app/world_api/`) as typed Pydantic models: one source for the Python API used by
scripted brains, the MCP tool schemas used by agent minds, and the OpenAPI types used by the spectator UI. A model
change is a C1 follow-up PR with a changelog line in `contract_v1_draft.json` (and a decision row if it changes a
rule); `test_contract` also checks that v1 keeps every v0 shape.
