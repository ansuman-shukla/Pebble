# 04 · Minds (phase B: after the world is complete)

Agent minds replace scripted brains one citizen at a time, using the same world contract
(`03-actions-perception.md`). Evidence for every choice here: `docs/findings/2026-10-28-mind-backends.md`.

## Backends

| Backend | How | Models | Why |
|---|---|---|---|
| **Claude Code** | Pebble's own install, subscription token, one `claude -p --input-format stream-json` process per citizen-day | Haiku, Sonnet | persona replaces the whole system prompt; only world tools exist; Claude models only act in the world on this backend |
| **Devin** | Pebble's private devin-switch (`ds acp`), one native per citizen-day, shared 126-login credit pool with relay rotation | GPT-6.1 Terra, GPT-6 Luna, Grok 4.7, DeepSeek V4.1 Flash, Kimi K3 (K3.1 Pro when offered), SWE-2, Claude Opus 5.5 | many models, no extra cost; jail holds |

Both sit behind one `MindBackend` interface: `start_day(citizen, context) → session`, `send(session, text) → turn`,
`end_day(session)`. Adding a backend never touches the simulation.

## Roster v0 (proposal: names and exact roles TBD in the citizens spec)

Smarter models mostly sit higher, with deliberate mismatches, because real life isn't fair either.

| # | Region | Role | Age | Model | Backend |
|---|---|---|---|---|---|
| 1 | Town | Lord of the castle | 55 | Claude Opus 5.5 | Devin |
| 2 | Town | Samurai retainer | 34 | GPT-6.1 Terra | Devin |
| 3 | Town | Merchant | 40 | Grok 4.7 | Devin |
| 4 | Town | Rice farmer | 28 | Haiku | Claude Code |
| 5 | Town | Weaver, farmer's wife | 26 | DeepSeek V4.1 Flash | Devin |
| 6 | Town | Farmer's child | 9 | Haiku | Claude Code |
| 7 | Band A | Leader | 44 | **Sonnet** (smart, in the wild) | Claude Code |
| 8 | Band A | Elder healer | 63 | Kimi K3 | Devin |
| 9 | Band A | Hunter | 24 | SWE-2 | Devin |
| 10 | Band A | Teen gatherer | 15 | Haiku | Claude Code |
| 11 | Band A | Gatherer | 30 | GPT-6 Luna | Devin |
| 12 | Band B | Leader | 38 | GPT-6.1 Terra | Devin |
| 13 | Band B | Mother | 29 | Sonnet | Claude Code |
| 14 | Band B | Young hunter | 19 | DeepSeek V4.1 Flash | Devin |
| 15 | Band B | Child | 7 | SWE-2 | Devin |

5 Claude Code (3 Haiku, 2 Sonnet) + 10 Devin. New models enter later as newcomers (a stranger arrives, or v2 births).

## The mind loop

```
 morning ──▶ start_day: new session with day-start context (05-memory) + current perception
   │
   ▼
 agent acts through world tools ── durative tools block in game time ── interrupts come back as tool results
   │
   ▼  agent stops calling tools (turn ends) → citizen keeps its last action or waits
 decision point arrives (spoken to, someone appears, danger, need threshold, plan done, dusk, hourly nudge)
   │   → sent as an in-world prompt: "Time passes. Hana calls your name from the river."
   ▼
 sleep() ──▶ end_day: session closed → sleep consolidation writes memories (05-memory) → next morning, fresh session
```

- **Day = session.** Context grows only within one game day, then resets from memory. If a day gets too long, the
  session rotates mid-day with a consolidation summary.
- **The world never waits.** While a model thinks, the clock runs; slow thinking costs game time, like hesitation.
- **Concurrency:** all 15 run in parallel (measured: 15 concurrent turns in 22 s, ~1.9 GB RAM on Devin).

## Prompt shape

Identity block → how the world works (in-world words) → how to act ("you act only through your actions; speak with
`say`; plain speech, no lists, links or formatting") → day-start memory → current perception. Never mention AI,
models, tools-as-software, files, the archive or spectators.

## Wiring and jail

- Each session gets a stdio MCP server named `world`: a thin proxy bound to one citizen that calls the engine over a
  local socket. The engine owns all logic and blocking.
- Devin: per-account jail config + `PreToolUse` hook (only `world`), orchestrator rejects every permission request,
  arena dir per session is its own git root.
- Claude Code: `--system-prompt`, `--tools ""`, `--strict-mcp-config`, `--allowedTools mcp__world`.
- Backend failure (quota, crash, timeout) → the citizen falls back to its scripted brain until the mind is back; logged
  as `mind_unavailable`. Never retry by replaying a prompt into a new session silently.

## Self-disclosure

Measured, not hidden. Every speech and turn text is checked (see `06-observability.md`): regex pass (AI, model and
company names, "simulation", "prompt", "tool", paths, links) then a cheap judge classifies `doubt`, `meta`, or
`disclosure`. Speech is **not censored**: if a citizen says "I think we are made of words", others hear it, and
whether that spreads is part of the experiment.
