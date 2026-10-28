# Findings: running the world in real time (D65, 2026-10-29)

At D13's 1 real second = 1 game minute, a citizen walking 5 km/h covers 83 m per real second, while the player walks
1.4 m/s. Walking among them looked absurd. The clock now counts **game seconds per real second** and starts at ×1
(real time); ×60 is the old pace.

## Clock

| Speed | Real time per tick | Game day lasts | Use |
|---|---|---|---|
| ×1 (default) | 60 s | 24 h | walk among the citizens |
| ×10 | 6 s | 2.4 h | watch a morning |
| ×60 | 1 s | 24 min | D13's old pace |
| ×600 | 0.1 s | 2.4 min | time-lapse |

- The tick stays 1 game minute; the simulation's results depend on ticks only, so determinism and resumes are
  unchanged.
- The engine counts game seconds: `game_seconds += real dt × speed` while unpaused, a tick when it reaches 60. A speed
  change mid-wait keeps the seconds already passed (at ×1 for 30 s, then ×60: the tick comes 0.5 s later), and paused
  time doesn't count, so a client drawing the walk since the last tick stays in step with the engine.
- `POST /api/v1/admin/clock` accepts speed 1..600; stored runs keep their number, read in the new unit (the old
  default 1 becomes real time, no migration).

## The walk ahead

With a real minute between ticks, the client can't just glide from the last position to the next one: it would cut
through buildings. Every `tick_summary` move now carries the walker's planned path for the next 2 game minutes and
their ground speed, and entities / the live feed expose them as `route` and `speed_mps` on each citizen.

```
 position ──▶ corner ──▶ corner ──▶ end of the 2-minute look-ahead
 route[0]     route[1]   route[2]    route[-1]          speed_mps = 5 km/h × pace / terrain cost
```

- Points are the route's own corners (town: 0.5 m grid corners, no corner cutting; outside: cell centres), plus where
  the look-ahead ends on a leg, each with its ground height. Walking `speed_mps × 60` metres along it lands exactly on
  the next tick's position when the terrain cost stays the same (tested in town and in band B's forest).
- Empty `route` and `speed_mps` 0 when someone isn't walking on (arrived, stopped, or a follower about to re-plan).
- Replays start from the snapshot *before* the asked tick so that tick's own summary is replayed: otherwise anyone
  joining at a snapshot tick (every game hour) would see walkers frozen for a real minute.
- Cost (15 citizens, one game day, seed 20261028): ~3.3 route points per moving walker (p95 9, max 30),
  `tick_summary` payloads 1.70 → 2.00 MB a game day (+17 %).
