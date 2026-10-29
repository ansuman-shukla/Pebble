# 00 · Vision

## What Pebble is

A small, round 3D world that anyone can watch in the browser. One corner is a walled, prosperous town in the style of
medieval Japan. The rest of the planet is wild: Stone Age bands with fire and stone tools, animals, forests, snow and
sea. The people of this world will eventually be AI agents who believe they are simply people living there. Nobody
tells them what to do. Scarcity (food, water, warmth, safety) is what pushes them to plan, cooperate, fight, trade and
build.

Everything they perceive, say, think, remember and do is recorded in a structured way, so spectators (and we) can go
back and read any life in detail.

## Research questions

1. Under scarcity, how do agents organize themselves? Leadership, sharing, conflict, trade.
2. How does knowledge spread between the developed town and the Stone Age bands, if at all?
3. Do different models (and smarter vs weaker models in high vs low roles) behave measurably differently?
4. How often, when and why do agents notice they are not "real", and does that awareness spread?
5. What memory design keeps agents coherent over long lives without huge contexts?

## Principles

- **World first, minds later.** The world is complete and playable with scripted NPCs before any agent enters it.
  Agents get exactly the actions and perceptions the world already supports; nothing is invented for them later.
- **The world is the authority.** Agents can say anything, but only the simulation decides what happens. Physics,
  needs, recipes and danger are enforced in code, never in prompts.
- **Never wait for a model.** The simulation keeps running; minds act through durative actions and get interrupted
  by what they perceive.
- **Archive everything, show the mind a little.** Full raw logs are kept forever for observers. Each agent sees only
  a small, curated slice of its own past.
- **No in-world knowledge of the outside.** Agents never see paths, tools, models or the archive. Biographies we write
  about them are never shown to them.
- **Grow in versions.** v0 is simple and runs reliably. Each later version adds one layer of realism (seasons, crafting,
  language, aging, money…).
- **Contained.** Pebble never touches the main devin-switch, global Devin/Claude config, or anything outside the repo.

## Non-goals (for v0)

- Realistic physics, combat animation, or a full survival game for human players.
- Telling agents what to build or optimizing them toward goals.
- Public multiplayer. One optional human avatar comes later.
- Agents editing the world's code or rules.

## Success for v0

World v1 (`10-world-v1.md`, D77) raises the bar before Phase B: 22 citizens, money, law and a world where every
usable thing is drawn and simulated.


- A complete little planet renders in the browser: terrain, biomes, the town, landmarks, animals, 15 citizens.
- Scripted citizens live a believable routine (eat, drink, sleep, wander, flee animals) for many game days without
  getting stuck.
- Every event is in the event store and visible in the spectator UI (live and replay).
- The world exposes the full action and perception contract that agent minds will later use.
