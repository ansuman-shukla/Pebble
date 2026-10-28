# 05 · Memory

Lives in the backend (`app/memory/`). Two separate things:

```
 ARCHIVE (for us and spectators)              MIND (for the citizen)
 ───────────────────────────────              ──────────────────────
 every event, every raw transcript            a small, curated slice of its own past
 append-only, kept forever                    rebuilt each morning, ≤ a few thousand tokens
 omniscient: thoughts of everyone             only what this citizen perceived, said or did
```

The mind side is built only from the citizen's own perceptions, speech, actions and thoughts, never from the archive's
omniscient view or from biographies.

## What a citizen remembers

| Layer | Content | Written by | Size in context |
|---|---|---|---|
| **Identity** | name, age, origin, personality, values, backstory | world spec (fixed) | ~300 tokens, always |
| **Now** | body, place, time, inventory, current action | simulation (fresh each prompt) | ~150 tokens, always |
| **Plan** | today's intentions, 1-2 longer goals | the citizen (in its turn text, extracted at consolidation) | ~150 tokens, always |
| **People** | per person: name, how you know them, trust/warmth, last met, 1-2 notes | consolidation | relevant ones only |
| **Episodes** | short dated memories: what, where, who, how important | consolidation (+ automatic candidates during the day) | top ~10 at morning |
| **Beliefs / facts** | "the river by the cave is safe at noon", "Taro leads us", with valid-from / valid-until and what replaced them | consolidation | relevant ones only |
| **Skills** | what they can actually do | simulation (ground truth) | ~50 tokens |
| **Reflections** | a few lasting lessons about life | consolidation, rewritten and capped | ~200 tokens |

Facts keep their **history**: when "Taro leads us" becomes "Taro is dead; Kenji leads us", the old fact is closed,
not deleted. Spectators can see how beliefs changed. Expired facts ("the berries by the hill are ripe") stop counting
when their window ends.

## Writing: sleep consolidation

Inspired by how sleep sorts memories, and by giving memory writing to a dedicated learner instead of the actor:

1. During the day, the simulation records **candidate** episodes from the citizen's perceptions and actions with a
   cheap importance score (danger, new person, new place, food found/lost, strong words, injury).
2. At `sleep()`, a **consolidation run** (a cheap model, separate from the citizen's own mind, never in its context)
   reads that day's transcript + candidates + current memory, then:
   - writes at most ~10 new episodes (deduplicated against what already exists),
   - opens/closes beliefs, updates people entries,
   - rewrites reflections and the plan within their caps.
3. Everything the consolidator writes is an event too (`memory_written`, `belief_updated`, …), so memory changes are
   observable.

## Reading: three paths

1. **Morning profile:** identity + now + plan + skills + reflections + top episodes for today's likely situation
   (recency × importance × relevance to where they are and who is nearby). Budget ≤ 2,500 tokens.
2. **Per-prompt hints:** when a decision point mentions a person or place, attach that person's line and up to 3
   short related memories (≤ 300 characters each). Budget ≤ 400 tokens.
3. **`recall(about)`:** the citizen can try to remember; returns up to 5 short memories. Budget ≤ 300 tokens.

Retrieval in v0 uses Postgres full-text search + structured tags (people, place, kind) + recency and importance; no
embeddings (no paid embeddings API). A local embedding model can be added later behind the same interface.

## Forgetting
Importance decays with time; memories below a threshold are no longer retrieved (still archived). Later: age shapes
memory (children keep less detail, elders forget recent things faster).

## Human-readable views
For spectators, each citizen's memory is rendered as Markdown pages (profile, people, beliefs over time, diary).
The in-world **library** (v2) holds only things written or painted inside the world, never these views.
