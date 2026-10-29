import { expect, test } from '@playwright/test';
import { Vector3 } from 'three';

import {
  type Doing,
  FADE_S,
  follow,
  keepRight,
  LANE_M,
  moveOn,
  newTrack,
  shownDoing,
} from '../../src/lib/live/drawn-track';
import type { RoutePoint } from '../../src/lib/client/types.gen';

/* Where a live citizen is drawn frame by frame (no browser): every move walked, one tick behind, only a resync fades;
 * shown moving while it walks. */

const R = 2000;
const FRAME = 1 / 60;
/** A direction `x` metres east and `z` metres north of a spot on the planet (small distances: a flat chart). */
const at = (x: number, z: number): [number, number, number] =>
  new Vector3(x / R, z / R, 1).normalize().toArray();
const metres = (a: Vector3, b: Vector3) => a.angleTo(b) * R;

/** A tick of the feed: where the citizen is, the timed route of its move (none when it stood still), its doing. */
function tick(
  position: [number, number],
  route: [number, number, number][],
  doing: Partial<Doing> = {},
) {
  const points: RoutePoint[] = route.map(([x, z, t]) => ({
    unit: at(x, z),
    height_m: 8,
    t_s: t,
  }));
  const speed =
    points.length > 1 ? Math.hypot(route[1][0], route[1][1]) / route[1][2] : 0;
  return {
    position: { unit: at(...position) },
    route: points,
    speed_mps: speed,
    heading_deg: 0,
    activity: route.length > 0 ? 'walking' : 'idle',
    action_label: '',
    cause_of_death: null,
    ...doing,
  } satisfies Doing & Record<string, unknown>;
}

/** A walk east at 83.3 m a tick: where it stands after `ticks`, and the route of the tick that got it there. */
const walkingEast = (ticks: number) => {
  const x = (ticks - 1) * 83.3;
  return tick(
    [x + 83.3, 0],
    [
      [x, 0, 0],
      [x + 83.3, 0, 60],
      [x + 250, 0, 180],
    ],
  );
};
/** It turned north (a new plan) where it stood after `ticks` ticks east. */
const turnedNorth = (ticks: number) => {
  const x = ticks * 83.3;
  return tick(
    [x, 83.3],
    [
      [x, 0, 0],
      [x, 83.3, 60],
      [x, 250, 180],
    ],
  );
};
/** Walking pace, metres a frame at the clock's rate (with a little slack). */
const pace = (rate: number) => 1.389 * rate * FRAME * 1.05;

/** Shown enough to see a jump. */
const SEEN = 0.2;

/** Draws `seconds` of real time at the clock's rate, frame by frame: the largest step between frames seen (m). */
function play(
  track: ReturnType<typeof newTrack>,
  seconds: number,
  rate: number,
  seen: { opacity: number; spot: Vector3 }[] = [],
) {
  let last = {
    opacity: track.opacity,
    spot: moveOn(track, 0, rate, new Vector3()).clone(),
  };
  let jump = 0;
  for (let frame = 0; frame < Math.round(seconds / FRAME); frame++) {
    const now = {
      opacity: track.opacity,
      spot: moveOn(track, FRAME, rate, new Vector3()).clone(),
    };
    now.opacity = track.opacity;
    if (Math.min(last.opacity, now.opacity) > SEEN)
      jump = Math.max(jump, metres(last.spot, now.spot));
    seen.push(now);
    last = now;
  }
  return jump;
}

for (const rate of [1, 10]) {
  test(`at ×${rate} a walk that starts and ends within a tick is drawn walking all the way, never jumping`, () => {
    const track = newTrack(tick([0, 0], []), R);
    play(track, 5, rate);
    // the tick it walked 20 m east (in 14.4 s of game time), then it stood there
    follow(
      track,
      tick(
        [20, 0],
        [
          [0, 0, 0],
          [20, 0, 14.4],
        ],
      ),
      R,
      rate,
    );
    expect(track.fade).toBeNull();
    const seen: { opacity: number; spot: Vector3 }[] = [];
    const jump = play(track, 60 / rate, rate, seen);
    expect(jump).toBeLessThan((20 / 14.4) * rate * FRAME * 1.05); // its walking pace, frame by frame
    expect(seen.every(({ opacity }) => opacity === 1)).toBe(true);
    expect(metres(seen.at(-1)!.spot, new Vector3(...at(20, 0)))).toBeLessThan(
      0.01,
    );
    // the next tick: standing where the walk ended, nothing to catch up
    follow(track, tick([20, 0], []), R, rate);
    expect(track.offset.length()).toBeLessThan(1e-9);
  });
}

test('a citizen first seen mid-walk is drawn one tick behind: where its step began, walking it', () => {
  const track = newTrack(walkingEast(1), R);
  const spot = moveOn(track, 0, 1, new Vector3());
  expect(metres(spot, new Vector3(...at(0, 0)))).toBeLessThan(0.01);
  expect(play(track, 60, 1)).toBeLessThan(pace(1));
  expect(
    metres(moveOn(track, 0, 1, new Vector3()), new Vector3(...at(83.3, 0))),
  ).toBeLessThan(0.01);
});

test('a replayed moment (no tick follows) draws a mover where the frame says it is, shown doing what it says', () => {
  const track = newTrack(shortWalk({ activity: 'sleeping' }), R, true);
  const spot = moveOn(track, 0, 0, new Vector3());
  expect(metres(spot, new Vector3(...at(20, 0)))).toBeLessThan(0.01);
  expect(shownDoing(track).activity).toBe('sleeping');
});

for (const rate of [1, 10]) {
  test(`at ×${rate} a citizen first seen mid-walk that then changes its plan turns where the step ended: no slide, no fade`, () => {
    const track = newTrack(walkingEast(1), R);
    play(track, 60 / rate, rate);
    follow(track, turnedNorth(1), R, rate);
    expect(track.fade).toBeNull();
    expect(track.offset.length() * R).toBeLessThan(0.01);
    const seen: { opacity: number; spot: Vector3 }[] = [];
    expect(play(track, 60 / rate, rate, seen)).toBeLessThan(pace(rate));
    expect(seen.every(({ opacity }) => opacity === 1)).toBe(true);
    expect(
      metres(seen.at(-1)!.spot, new Vector3(...at(83.3, 83.3))),
    ).toBeLessThan(0.01);
  });

  test(`at ×${rate} a page opened mid-tick walks the rest of its first step before the next one: no slide, no fade`, () => {
    const track = newTrack(walkingEast(1), R);
    play(track, 25 / rate, rate); // the snapshot came 35 s into the tick: the next tick comes 25 s later
    follow(track, turnedNorth(1), R, rate);
    expect(track.fade).toBeNull();
    const seen: { opacity: number; spot: Vector3 }[] = [];
    expect(play(track, 35 / rate, rate, seen)).toBeLessThan(pace(rate));
    expect(metres(seen.at(-1)!.spot, new Vector3(...at(83.3, 0)))).toBeLessThan(
      0.01,
    ); // round the corner where the sim turned, 35 s later than the others
    expect(play(track, 25 / rate, rate, seen)).toBeLessThan(pace(rate));
    // the tick after: on north; it stays 35 s behind while it walks on
    follow(
      track,
      tick(
        [83.3, 166.6],
        [
          [83.3, 83.3, 0],
          [83.3, 166.6, 60],
        ],
      ),
      R,
      rate,
    );
    expect(track.fade).toBeNull();
    expect(play(track, 60 / rate, rate, seen)).toBeLessThan(pace(rate));
    expect(
      metres(seen.at(-1)!.spot, new Vector3(...at(83.3, 118))),
    ).toBeLessThan(0.1);
    expect(play(track, 60 / rate, rate, seen)).toBeLessThan(pace(rate));
    expect(
      metres(seen.at(-1)!.spot, new Vector3(...at(83.3, 166.6))),
    ).toBeLessThan(0.01); // where it stopped: caught up
    expect(seen.every(({ opacity }) => opacity === 1)).toBe(true);
  });
}

test('a body behind on its walk whose next path starts somewhere else (a resync) fades, not walking there', () => {
  const track = newTrack(walkingEast(1), R);
  play(track, 25, 1);
  follow(
    track,
    tick(
      [400, 83.3],
      [
        [400, 0, 0],
        [400, 83.3, 60],
      ],
    ),
    R,
    1,
  );
  expect(track.fade).not.toBeNull();
});

test('a body more than a tick behind (no frames drawn for two ticks: a hidden tab) resyncs with a fade', () => {
  const track = newTrack(walkingEast(1), R);
  follow(track, walkingEast(2), R, 1);
  expect(track.fade).toBeNull(); // a tick behind: it walks on
  follow(track, walkingEast(3), R, 1);
  expect(track.fade).not.toBeNull();
});

test('a long walk is drawn tick after tick from where the last one left it', () => {
  const track = newTrack(tick([0, 0], []), R);
  for (let k = 0; k < 3; k++) {
    const x = k * 83.3;
    follow(
      track,
      tick(
        [x + 83.3, 0],
        [
          [x, 0, 0],
          [x + 83.3, 0, 60],
          [x + 250, 0, 180],
        ],
      ),
      R,
      10,
    );
    expect(track.offset.length() * R).toBeLessThan(0.01);
    expect(track.path.time).toBeLessThan(0.01);
    expect(play(track, 6, 10)).toBeLessThan(1.389 * 10 * FRAME * 1.05);
  }
});

test('a tick that comes late finds the walker a little on: it eases onto the new path, no fade', () => {
  const track = newTrack(tick([0, 0], []), R);
  follow(
    track,
    tick(
      [83.3, 0],
      [
        [0, 0, 0],
        [83.3, 0, 60],
        [250, 0, 180],
      ],
    ),
    R,
    10,
  );
  play(track, 6.5, 10); // half a second late at ×10: 7 m into the look-ahead
  follow(track, tick([83.3, 0], []), R, 10); // but it stopped where the step ended
  expect(track.fade).toBeNull();
  expect(track.offset.length() * R).toBeCloseTo(6.9, 0);
  expect(play(track, 3, 10)).toBeLessThan(0.5); // eased back, not snapped
  expect(track.offset.length() * R).toBeLessThan(0.01);
});

test('a resync far away fades out where the body was and in on its path, never jumping while seen', () => {
  const track = newTrack(tick([0, 0], []), R);
  play(track, 1, 1);
  follow(track, tick([400, 0], []), R, 1); // a reconnect after the tab slept
  expect(track.fade).not.toBeNull();
  const seen: { opacity: number; spot: Vector3 }[] = [];
  const jump = play(track, FADE_S + 0.1, 1, seen);
  expect(jump).toBeLessThan(0.01);
  const hidden = seen.findIndex(
    ({ spot }) => metres(spot, new Vector3(...at(0, 0))) > 1,
  );
  expect(seen[hidden - 1].opacity).toBeLessThan(0.15); // gone where it was ...
  expect(seen[hidden].opacity).toBeLessThan(0.15); // ... before it shows up on the path
  expect(
    seen
      .slice(0, hidden)
      .every(({ opacity }, k) => k === 0 || opacity <= seen[k - 1].opacity),
  ).toBe(true);
  expect(seen.at(-1)!.opacity).toBe(1);
  expect(track.fade).toBeNull();
  expect(metres(seen.at(-1)!.spot, new Vector3(...at(400, 0)))).toBeLessThan(
    0.01,
  );
});

test('a resync during a resync fades out where the body was last seen, never showing it in between', () => {
  const track = newTrack(tick([0, 0], []), R);
  follow(track, tick([400, 0], []), R, 1);
  play(track, FADE_S / 4, 1); // fading out at the old spot
  follow(track, tick([800, 0], []), R, 1); // another reconnect before it showed up at 400 m
  const seen: { opacity: number; spot: Vector3 }[] = [];
  expect(play(track, FADE_S + 0.1, 1, seen)).toBeLessThan(0.01);
  const shown = seen.filter(({ opacity }) => opacity > 0.15);
  expect(
    shown.every(
      ({ spot }) =>
        metres(spot, new Vector3(...at(0, 0))) < 0.01 ||
        metres(spot, new Vector3(...at(800, 0))) < 0.01,
    ),
  ).toBe(true);
  expect(metres(seen.at(-1)!.spot, new Vector3(...at(800, 0)))).toBeLessThan(
    0.01,
  );
});

/** A walk east of 20 m in 14.4 s within the tick, ending in `doing`. */
const shortWalk = (doing: Partial<Doing>) =>
  tick(
    [20, 0],
    [
      [0, 0, 0],
      [20, 0, 14.4],
    ],
    doing,
  );

/** What the citizen is shown doing over the next tick, a second at a time (the activity whenever it changes). */
function shownOver(track: ReturnType<typeof newTrack>, rate = 1) {
  const shown = [shownDoing(track)];
  for (let second = 0; second < 60; second++) {
    moveOn(track, 1 / rate, rate, new Vector3());
    const now = shownDoing(track);
    if (now !== shown.at(-1)) shown.push(now);
  }
  return shown;
}

for (const rate of [1, 10]) {
  test(`at ×${rate} a walk that ends in sleep within the tick is shown walking until the drawn body gets there`, () => {
    const track = newTrack(
      tick([0, 0], [], { activity: 'walking', action_label: 'home' }),
      R,
    );
    follow(track, shortWalk({ activity: 'sleeping' }), R, rate);
    const shown = shownOver(track, rate);
    expect(shown.map(({ activity }) => activity)).toEqual([
      'walking',
      'sleeping',
    ]);
    expect(shown[0].action_label).toBe('home'); // still "walking home" on the way
    // it lay down where the walk ended, after 14.4 s of walking
    const track2 = newTrack(
      tick([0, 0], [], { activity: 'walking', action_label: 'home' }),
      R,
    );
    follow(track2, shortWalk({ activity: 'sleeping' }), R, rate);
    moveOn(track2, 14 / rate, rate, new Vector3());
    expect(shownDoing(track2).activity).toBe('walking');
    moveOn(track2, 0.5 / rate, rate, new Vector3());
    expect(shownDoing(track2).activity).toBe('sleeping');
  });
}

test('someone who dies mid-walk is shown walking up to where they fell, then dead', () => {
  const track = newTrack(tick([0, 0], [], { activity: 'running' }), R);
  follow(track, shortWalk({ activity: 'dead', cause_of_death: 'wolf' }), R, 1);
  expect(shownOver(track).map(({ activity }) => activity)).toEqual([
    'running',
    'dead',
  ]);
});

test('someone who moves before doing anything moving is shown walking until they get there', () => {
  // standing about, then a walk that collapsed in exhaustion within the tick
  const track = newTrack(tick([0, 0], []), R);
  follow(track, shortWalk({ activity: 'sleeping' }), R, 1);
  expect(shownOver(track).map(({ activity }) => activity)).toEqual([
    'walking',
    'sleeping',
  ]);
  // first seen in a snapshot like that
  const seen = newTrack(shortWalk({ activity: 'sleeping' }), R);
  expect(shownOver(seen).map(({ activity }) => activity)).toEqual([
    'walking',
    'sleeping',
  ]);
});

test('a sleeper who wakes and walks off is shown walking at once; standing still shows the new activity at once', () => {
  const track = newTrack(tick([0, 0], [], { activity: 'sleeping' }), R);
  follow(
    track,
    tick(
      [83.3, 0],
      [
        [0, 0, 0],
        [83.3, 0, 60],
      ],
      { activity: 'walking', action_label: 'the well' },
    ),
    R,
    1,
  );
  expect(shownOver(track).map(({ activity }) => activity)).toEqual(['walking']);
  follow(track, tick([83.3, 0], [], { activity: 'drinking' }), R, 1);
  expect(shownDoing(track).activity).toBe('drinking');
});

test('the walk on along the plan is not held: once the drawn body is where the frame says, it shows the frame', () => {
  const track = newTrack(walkingEast(1), R);
  play(track, 6.5, 10); // a tick late: on into the plan ahead
  follow(track, tick([83.3, 0], [], { activity: 'idle' }), R, 10);
  expect(shownDoing(track).activity).toBe('idle');
});

/** Draws `seconds` of real time at ×1 in the keep-right lane: the drawn spots, frame by frame. */
function inLane(track: ReturnType<typeof newTrack>, seconds: number) {
  const spots: Vector3[] = [];
  for (let frame = 0; frame < Math.round(seconds / FRAME); frame++)
    spots.push(
      keepRight(
        track,
        FRAME,
        moveOn(track, FRAME, 1, new Vector3()),
        R,
      ).clone(),
    );
  return spots;
}

/** Metres south (negative: north) of the east-west street through the origin. */
const south = (spot: Vector3) => -(spot.y / spot.z) * R;

test('a walker keeps right of its route, stepping into the lane and back out without a jump', () => {
  const track = newTrack(shortWalk({}), R);
  const spots = inLane(track, 14.4);
  const steps = spots.slice(1).map((spot, i) => metres(spots[i], spot));
  expect(Math.max(...steps)).toBeLessThan(0.04); // a side step on top of its pace, never a jump
  // walking east: its right is south
  expect(south(spots[Math.round(5 / FRAME)])).toBeCloseTo(LANE_M, 2);
  expect(south(spots[0])).toBeLessThan(0.05); // set off from where it stood
  const after = inLane(track, 3); // stood still at the end of its walk: back onto its spot
  expect(Math.abs(south(after.at(-1)!))).toBeLessThan(0.01);
  const settle = after.slice(1).map((spot, i) => metres(after[i], spot));
  expect(south(after[0])).toBeGreaterThan(0.3); // it steps back gradually...
  expect(Math.max(...settle)).toBeLessThan(0.05); // ...a few centimetres a frame
});

test('two walkers passing on one street are drawn at least 0.6 m apart', () => {
  const east = newTrack(
    tick(
      [20, 0],
      [
        [0, 0, 0],
        [20, 0, 14.4],
      ],
    ),
    R,
  );
  const west = newTrack(
    tick(
      [0, 0],
      [
        [20, 0, 0],
        [0, 0, 14.4],
      ],
    ),
    R,
  );
  const [a, b] = [inLane(east, 7.2), inLane(west, 7.2)];
  expect(metres(a.at(-1)!, b.at(-1)!)).toBeGreaterThanOrEqual(0.6); // side by side mid-street
  expect(south(a.at(-1)!)).toBeGreaterThan(0.3);
  expect(south(b.at(-1)!)).toBeLessThan(-0.3);
});
