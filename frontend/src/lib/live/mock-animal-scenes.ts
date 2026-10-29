/*
 * DEV/TEST ONLY: scripted animal scenes of the mock live feed (`?mockLive=1`) on the grass by band A's camp, so
 * every behaviour the globe draws (10 §4.6, D144) can be watched and tested by day, at the bible's speeds:
 *
 *   hunt     two wolves prowl in from their den, stalk a grazing herd, two deer look up (alert), one pounces on the
 *            third (it bolts a few metres and falls where it is caught), the others flee and trot off; the wolves
 *            bite, feed for 90 minutes, walk home and sleep; the carcass is remains a day after the kill
 *   burrow   a fox stalks a rabbit, which looks up, hops to its burrow and freezes; the fox's chase misses
 *   den      a bear prowls from its den, stalks a boar, pounces, rears and bites, the boar fights back and dies; the
 *            bear feeds, goes home and sleeps
 *   savanna  a lion stalks two antelope, they flee faster than it runs, then trot and look back
 *   water    two deer drink, walk off to graze and come back
 *   line-up  one of each land kind side by side, all doing the same standing behaviour, two ticks each
 *
 * Each scene loops (the hunts every two game days, so the remains show); a frame's activity is what the animal does
 * as its tick ends and its route is the move that got it there, timed from the tick's start (D100), so a kill's
 * route ends where the prey falls. Shapes are the feed's; `mock-wild.ts` places the local metres on the globe.
 */
import {
  type AnimalActivity,
  type LiveAnimal,
  TICK_SECONDS,
} from './live-contract';
import type { Position, RoutePoint, Target } from '@/lib/client/types.gen';

type Spot = [number, number];
type Kind = LiveAnimal['kind'];
type Gait = LiveAnimal['gait'];

/** A stretch of a beat's move: on to a spot at a speed (m/s), or a pause (seconds). */
type Leg = { to: Spot; speed: number } | { wait: number };

interface Beat {
  ticks: number;
  activity: AnimalActivity;
  goal: string;
  gait?: Gait;
  /** Where it goes during the beat, from where the last beat left it (spots relative to the scene's origin). */
  legs?: Leg[];
  /** The actor it is about: it faces it while standing and names it as its target. */
  target?: string;
}

interface Actor {
  id: string;
  kind: Kind;
  group: string;
  /** Its name in words for others' targets ("a deer"). */
  name: string;
  at: Spot;
  beats: Beat[];
}

interface Scene {
  origin: Spot;
  /** Ticks before the scene starts over (its last beat fills up to it). */
  period: number;
  actors: Actor[];
}

/** One game day of ticks: a carcass becomes remains this long after the kill. */
const DAY = 24 * 60;
/** How far ahead of the tick's move a route carries the plan, like the engine's (game seconds). */
const AHEAD_S = 2 * TICK_SECONDS;

const go = (to: Spot, speed: number): Leg => ({ to, speed });
const wait = (seconds: number): Leg => ({ wait: seconds });

const HUNT: Scene = {
  origin: [-160, 60],
  period: 2 * DAY,
  actors: [
    ...(
      [
        ['deer:201', [0, 0], [150, 260], [190, 290]],
        ['deer:202', [6, 3], [160, 270], [198, 296]],
      ] satisfies [string, Spot, Spot, Spot][]
    ).map(([id, at, far, stop]): Actor => ({
      id,
      kind: 'deer',
      group: 'deer-group:200',
      name: 'a deer',
      at,
      beats: [
        { ticks: 5, activity: 'grazing', goal: 'grazing' },
        {
          ticks: 1,
          activity: 'alert',
          goal: 'watching the wolves',
          target: 'wolf:211',
        },
        {
          ticks: 1,
          activity: 'fleeing',
          gait: 'run',
          goal: 'fleeing the wolves',
          target: 'wolf:211',
          legs: [wait(20), go(far, 11), go(stop, 5)],
        },
        {
          ticks: 3,
          activity: 'alert',
          goal: 'watching the wolves',
          target: 'wolf:211',
        },
        { ticks: 200, activity: 'grazing', goal: 'grazing' },
        {
          ticks: 7,
          activity: 'walking',
          goal: 'back to the meadow',
          legs: [go(at, 1)],
        },
        { ticks: 1, activity: 'grazing', goal: 'grazing' },
      ],
    })),
    {
      id: 'deer:203',
      kind: 'deer',
      group: 'deer-group:200',
      name: 'a deer',
      at: [-4, 6],
      beats: [
        { ticks: 6, activity: 'grazing', goal: 'grazing' },
        // bolts as the wolf leaps and falls where it is caught
        {
          ticks: DAY,
          activity: 'dead',
          gait: 'run',
          goal: '',
          legs: [wait(20), go([-2, 9], 11)],
        },
        { ticks: 1, activity: 'remains', goal: '' },
      ],
    },
    ...(
      [
        [
          'wolf:211',
          [-260, -200],
          [-45, -30],
          [-18, -12],
          [-2.6, 8.2],
          'pouncing',
        ],
        [
          'wolf:212',
          [-264, -196],
          [-50, -24],
          [-22, -6],
          [-3.2, 10.4],
          'chasing',
        ],
      ] satisfies [string, Spot, Spot, Spot, Spot, AnimalActivity][]
    ).map(([id, den, near, close, kill, leap]): Actor => ({
      id,
      kind: 'wolf',
      group: 'wolf-group:210',
      name: 'a wolf',
      at: den,
      beats: [
        {
          ticks: 4,
          activity: 'prowling',
          goal: 'hunting',
          legs: [go(near, 1.2)],
        },
        {
          ticks: 2,
          activity: 'stalking',
          gait: 'stalk',
          goal: 'stalking the deer',
          target: 'deer:203',
          legs: [go(close, 0.72)],
        },
        {
          ticks: 1,
          activity: leap,
          gait: 'run',
          goal: 'chasing the deer',
          target: 'deer:203',
          legs: [wait(17.6), go(kill, 10)],
        },
        {
          ticks: 1,
          activity: 'attacking',
          goal: 'killing the deer',
          target: 'deer:203',
        },
        { ticks: 90, activity: 'feeding', goal: 'feeding', target: 'deer:203' },
        {
          ticks: 5,
          activity: 'walking',
          goal: 'going home',
          legs: [go(den, 1.2)],
        },
        { ticks: 1, activity: 'sleeping', goal: 'asleep' },
      ],
    })),
  ],
};

const BURROW: Scene = {
  origin: [-60, 150],
  period: 240,
  actors: [
    {
      id: 'rabbit:221',
      kind: 'rabbit',
      group: 'rabbit-group:220',
      name: 'a rabbit',
      at: [0, 0],
      beats: [
        { ticks: 2, activity: 'grazing', goal: 'grazing' },
        {
          ticks: 1,
          activity: 'alert',
          goal: 'watching the fox',
          target: 'fox:222',
        },
        {
          ticks: 1,
          activity: 'fleeing',
          gait: 'run',
          goal: 'to its burrow',
          target: 'fox:222',
          legs: [wait(10), go([30, -25], 9)],
        },
        { ticks: 6, activity: 'frozen', goal: 'hiding', target: 'fox:222' },
        { ticks: 100, activity: 'grazing', goal: 'grazing' },
        {
          ticks: 2,
          activity: 'walking',
          goal: 'grazing',
          legs: [go([0, 0], 0.5)],
        },
        { ticks: 1, activity: 'grazing', goal: 'grazing' },
      ],
    },
    {
      id: 'fox:222',
      kind: 'fox',
      group: 'fox-group:222',
      name: 'a fox',
      at: [-66, 38],
      beats: [
        {
          ticks: 1,
          activity: 'prowling',
          goal: 'hunting',
          legs: [go([-24, 12], 0.9)],
        },
        {
          ticks: 2,
          activity: 'stalking',
          gait: 'stalk',
          goal: 'stalking the rabbit',
          target: 'rabbit:221',
          legs: [go([-12, 6], 0.54)],
        },
        {
          ticks: 1,
          activity: 'chasing',
          gait: 'run',
          goal: 'chasing the rabbit',
          target: 'rabbit:221',
          legs: [wait(10), go([28.5, -24], 9)],
        },
        { ticks: 60, activity: 'idle', goal: 'resting after a missed hunt' },
        {
          ticks: 3,
          activity: 'prowling',
          goal: 'hunting',
          legs: [go([-66, 38], 0.9)],
        },
        { ticks: 1, activity: 'idle', goal: 'resting' },
      ],
    },
  ],
};

const DEN: Scene = {
  origin: [-250, 190],
  period: 2 * DAY,
  actors: [
    {
      id: 'boar:231',
      kind: 'boar',
      group: 'boar-group:230',
      name: 'a boar',
      at: [0, 0],
      beats: [
        { ticks: 4, activity: 'grazing', goal: 'rooting' },
        {
          ticks: 1,
          activity: 'fleeing',
          gait: 'run',
          goal: 'fleeing the bear',
          target: 'bear:232',
          legs: [wait(10.4), go([-1.5, 1.2], 8)],
        },
        {
          ticks: 1,
          activity: 'attacking',
          goal: 'fighting the bear',
          target: 'bear:232',
        },
        { ticks: DAY, activity: 'dead', goal: '' },
        { ticks: 1, activity: 'remains', goal: '' },
      ],
    },
    {
      id: 'bear:232',
      kind: 'bear',
      group: 'bear-group:232',
      name: 'a bear',
      at: [80, -60],
      beats: [
        { ticks: 2, activity: 'sleeping', goal: 'asleep' },
        {
          ticks: 1,
          activity: 'prowling',
          goal: 'hunting',
          legs: [go([32, -24], 1)],
        },
        {
          ticks: 1,
          activity: 'stalking',
          gait: 'stalk',
          goal: 'stalking the boar',
          target: 'boar:231',
          legs: [go([10, -8], 0.6)],
        },
        {
          ticks: 1,
          activity: 'pouncing',
          gait: 'run',
          goal: 'chasing the boar',
          target: 'boar:231',
          legs: [wait(10), go([-0.2, -0.3], 11)],
        },
        {
          ticks: 2,
          activity: 'attacking',
          goal: 'killing the boar',
          target: 'boar:231',
        },
        { ticks: 90, activity: 'feeding', goal: 'feeding', target: 'boar:231' },
        {
          ticks: 2,
          activity: 'walking',
          goal: 'going home',
          legs: [go([80, -60], 1)],
        },
        { ticks: 1, activity: 'sleeping', goal: 'asleep' },
      ],
    },
  ],
};

const SAVANNA: Scene = {
  origin: [-120, -150],
  period: 480,
  actors: [
    ...(
      [
        ['antelope:241', [0, 0], [240, -100], [295, -122]],
        ['antelope:242', [5, -4], [246, -106], [300, -128]],
      ] satisfies [string, Spot, Spot, Spot][]
    ).map(([id, at, far, stop]): Actor => ({
      id,
      kind: 'antelope',
      group: 'antelope-group:240',
      name: 'an antelope',
      at,
      beats: [
        { ticks: 3, activity: 'grazing', goal: 'grazing' },
        {
          ticks: 1,
          activity: 'fleeing',
          gait: 'run',
          goal: 'fleeing the lion',
          target: 'lion:243',
          legs: [wait(8), go(far, 13)],
        },
        {
          ticks: 1,
          activity: 'trotting',
          gait: 'trot',
          goal: 'getting away from the lion',
          legs: [go(stop, 6)],
        },
        {
          ticks: 2,
          activity: 'alert',
          goal: 'watching the lion',
          target: 'lion:243',
        },
        { ticks: 300, activity: 'grazing', goal: 'grazing' },
        {
          ticks: 6,
          activity: 'walking',
          goal: 'back to the grass',
          legs: [go(at, 1.1)],
        },
        { ticks: 1, activity: 'grazing', goal: 'grazing' },
      ],
    })),
    {
      id: 'lion:243',
      kind: 'lion',
      group: 'lion-group:243',
      name: 'a lion',
      at: [-120, 60],
      beats: [
        {
          ticks: 2,
          activity: 'prowling',
          goal: 'hunting',
          legs: [go([-55, 28], 1)],
        },
        {
          ticks: 1,
          activity: 'stalking',
          gait: 'stalk',
          goal: 'stalking the antelope',
          target: 'antelope:241',
          legs: [go([-40, 20], 0.6)],
        },
        // seen at 40 m: it races them, and gives up when they pull away
        {
          ticks: 1,
          activity: 'chasing',
          gait: 'run',
          goal: 'chasing the antelope',
          target: 'antelope:241',
          legs: [wait(8), go([100, -45], 12)],
        },
        { ticks: 60, activity: 'idle', goal: 'resting after a missed hunt' },
        {
          ticks: 5,
          activity: 'prowling',
          goal: 'hunting',
          legs: [go([-120, 60], 1)],
        },
        { ticks: 1, activity: 'idle', goal: 'resting' },
      ],
    },
  ],
};

const WATER: Scene = {
  origin: [-40, -60],
  period: 120,
  actors: (
    [
      ['deer:251', [0, 0]],
      ['deer:252', [3, 2]],
    ] satisfies [string, Spot][]
  ).map(([id, at]): Actor => ({
    id,
    kind: 'deer',
    group: 'deer-group:250',
    name: 'a deer',
    at,
    beats: [
      { ticks: 30, activity: 'drinking', goal: 'drinking' },
      {
        ticks: 1,
        activity: 'walking',
        goal: 'grazing',
        legs: [go([at[0] + 40, at[1] + 20], 1)],
      },
      { ticks: 60, activity: 'grazing', goal: 'grazing' },
      {
        ticks: 1,
        activity: 'walking',
        goal: 'to the waterhole',
        legs: [go(at, 1)],
      },
      { ticks: 1, activity: 'drinking', goal: 'drinking' },
    ],
  })),
};

/** The standing behaviours the line-up shows in turn, two ticks each. */
const LINE_UP_DOINGS: AnimalActivity[] = [
  'idle',
  'grazing',
  'alert',
  'stalking',
  'frozen',
  'pouncing',
  'attacking',
  'feeding',
  'drinking',
  'sleeping',
  'dead',
];
const LINE_UP_KINDS: Kind[] = [
  'deer',
  'elk',
  'antelope',
  'goat',
  'boar',
  'rabbit',
  'hare',
  'duck',
  'fox',
  'wolf',
  'lion',
  'bear',
  'polar_bear',
];

const LINE_UP: Scene = {
  origin: [-150, -40],
  period: 2 * LINE_UP_DOINGS.length,
  actors: LINE_UP_KINDS.map((kind, k): Actor => ({
    id: `${kind}:${261 + k}`,
    kind,
    group: `line-up:${261 + k}`,
    name: kind,
    at: [4 * k, 0],
    beats: LINE_UP_DOINGS.map((activity) => ({
      ticks: 2,
      activity,
      gait: activity === 'stalking' ? 'stalk' : 'walk',
      goal: activity,
    })),
  })),
};

const SCENES: readonly Scene[] = [HUNT, BURROW, DEN, SAVANNA, WATER, LINE_UP];

/** Ids of the scripted animals (the rest of the mock's animals wander, `mock-wild.ts`). */
export const SCENE_IDS: ReadonlySet<string> = new Set(
  SCENES.flatMap((scene) => scene.actors.map((actor) => actor.id)),
);

// --- playing the scripts ---

/** A beat of an actor's script laid out in scene time: its move as spots passed at seconds after its start. */
interface Segment {
  /** Tick (within the scene's period) the beat starts at. */
  start: number;
  ticks: number;
  beat: Beat;
  points: { spot: Spot; t: number }[];
  /** Heading (degrees) it faces before its move and once the move is done (when it doesn't face a target). */
  before: number;
  after: number;
}

const add = ([x, z]: Spot, [ox, oz]: Spot): Spot => [x + ox, z + oz];
const bearing = ([x, z]: Spot, [tx, tz]: Spot) =>
  (Math.atan2(tx - x, tz - z) * 180) / Math.PI;
const lerpSpot = ([x, z]: Spot, [tx, tz]: Spot, share: number): Spot => [
  x + (tx - x) * share,
  z + (tz - z) * share,
];

/** Lays out an actor's beats in its scene's time, the last one filling the period. */
function layOut(actor: Actor, scene: Scene): Segment[] {
  const segments: Segment[] = [];
  let at = add(actor.at, scene.origin);
  let start = 0;
  let heading = 0;
  actor.beats.forEach((beat, k) => {
    const before = heading;
    const last = k === actor.beats.length - 1;
    const ticks = last ? scene.period - start : beat.ticks;
    if (ticks <= 0) throw new Error(`${actor.id}'s script outlasts its scene`);
    const points = [{ spot: at, t: 0 }];
    let t = 0;
    for (const leg of beat.legs ?? []) {
      if ('wait' in leg) {
        t += leg.wait;
        points.push({ spot: at, t });
        continue;
      }
      const to = add(leg.to, scene.origin);
      const metres = Math.hypot(to[0] - at[0], to[1] - at[1]);
      if (metres > 1e-6) heading = bearing(at, to);
      t += metres / leg.speed;
      points.push({ spot: to, t });
      at = to;
    }
    if (t > ticks * TICK_SECONDS)
      throw new Error(`${actor.id}'s ${beat.activity} move outlasts its beat`);
    segments.push({ start, ticks, beat, points, before, after: heading });
    start += ticks;
  });
  return segments;
}

/** Where a segment's move is `t` seconds after its start. */
function spotAt(segment: Segment, t: number): Spot {
  const { points } = segment;
  if (t <= points[0].t) return points[0].spot;
  for (let k = 1; k < points.length; k++)
    if (t <= points[k].t) {
      const span = points[k].t - points[k - 1].t;
      return lerpSpot(
        points[k - 1].spot,
        points[k].spot,
        span > 0 ? (t - points[k - 1].t) / span : 1,
      );
    }
  return points[points.length - 1].spot;
}

/** The spots passed between seconds `from` and `to` of a segment (both ends included), with their times. */
function stretch(segment: Segment, from: number, to: number) {
  const inside = segment.points.filter((p) => p.t > from && p.t < to);
  return [
    { spot: spotAt(segment, from), t: from },
    ...inside,
    { spot: spotAt(segment, to), t: to },
  ];
}

const moves = (spots: { spot: Spot }[]) =>
  spots.some(
    ({ spot }) =>
      Math.hypot(spot[0] - spots[0].spot[0], spot[1] - spots[0].spot[1]) > 1e-3,
  );

/** What a scene's actor is doing at the end of tick `index` of its period, and the move that got it there. */
interface ActorTick {
  at: Spot;
  heading: number;
  beat: Beat;
  /** Spots of the tick's move and the plan after it, seconds from the tick's start; empty standing. */
  route: { spot: Spot; t: number }[];
  speed: number;
}

function tickOf(segments: Segment[], index: number): ActorTick {
  const segment = segments.find(
    ({ start, ticks }) => index >= start && index < start + ticks,
  );
  if (!segment) throw new Error(`no beat at tick ${index}`);
  const from = (index - segment.start) * TICK_SECONDS;
  const to = from + TICK_SECONDS;
  const at = spotAt(segment, to);
  const walked = stretch(segment, from, to);
  // the move and the plan after it, up to where the move ends (no standing tail)
  const moveEnds = Math.min(
    to + AHEAD_S,
    segment.points[segment.points.length - 1].t,
  );
  const route = moves(walked)
    ? stretch(segment, from, Math.max(moveEnds, from))
        .filter((p, n, all) => n === 0 || p.t > all[n - 1].t)
        .map(({ spot, t }) => ({ spot, t: t - from }))
    : [];
  const legSpeeds = (segment.beat.legs ?? []).flatMap((leg) =>
    'speed' in leg ? [leg.speed] : [],
  );
  const done = to >= segment.points[segment.points.length - 1].t;
  const heading = moves(walked)
    ? bearing(walked[0].spot, at)
    : done
      ? segment.after
      : segment.before;
  return {
    at,
    heading,
    beat: segment.beat,
    route,
    speed: route.length ? (legSpeeds[0] ?? 0) : 0,
  };
}

/** Puts a scene's local metres on the globe (band A's camp chart). */
export type Place = (spot: Spot) => Position;

/** The scripted animals at a mock tick (tick 0: the snapshot, as the period's last tick ends). */
export function sceneAnimals(tick: number, place: Place): LiveAnimal[] {
  return SCENES.flatMap((scene) => {
    const index = (((tick - 1) % scene.period) + scene.period) % scene.period;
    const laid = scene.actors.map(
      (actor) => [actor, tickOf(layOut(actor, scene), index)] as const,
    );
    const where = new Map(laid.map(([actor, now]) => [actor.id, now.at]));
    const names = new Map(scene.actors.map((actor) => [actor.id, actor.name]));
    return laid.map(([actor, now]) => {
      const { beat } = now;
      const targetAt = beat.target ? where.get(beat.target) : undefined;
      const target: Target | null =
        beat.target && targetAt
          ? {
              kind: 'animal',
              id: beat.target,
              name: names.get(beat.target) ?? beat.target,
              position: place(targetAt).unit,
            }
          : null;
      const facing =
        now.route.length === 0 && targetAt && beat.activity !== 'dead'
          ? bearing(now.at, targetAt)
          : now.heading;
      const route: RoutePoint[] = now.route.map(({ spot, t }) => {
        const { unit, height_m } = place(spot);
        return { unit, height_m, t_s: t };
      });
      return {
        id: actor.id,
        kind: actor.kind,
        group: actor.group,
        position: place(now.at),
        heading_deg: facing,
        activity: beat.activity,
        route,
        speed_mps: now.speed,
        gait: beat.gait ?? 'walk',
        goal: beat.goal,
        target,
      };
    });
  });
}
