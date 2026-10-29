import { expect, test } from '@playwright/test';
import { Vector3 } from 'three';

import {
  FADE_S,
  follow,
  moveOn,
  newTrack,
} from '../../src/lib/live/drawn-track';
import type { RoutePoint } from '../../src/lib/client/types.gen';

/* Where a live citizen is drawn frame by frame (no browser): every move walked, one tick behind, only a resync
 * fades. */

const R = 2000;
const FRAME = 1 / 60;
/** A direction `x` metres east and `z` metres north of a spot on the planet (small distances: a flat chart). */
const at = (x: number, z: number): [number, number, number] =>
  new Vector3(x / R, z / R, 1).normalize().toArray();
const metres = (a: Vector3, b: Vector3) => a.angleTo(b) * R;

/** A tick of the feed: where the citizen is, and the timed route of its move (none when it stood still). */
function tick(position: [number, number], route: [number, number, number][]) {
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
  };
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
