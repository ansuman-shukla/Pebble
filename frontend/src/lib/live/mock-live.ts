/*
 * DEV/TEST ONLY: a deterministic stand-in for the engine's live feed (`?mockLive=1`). Twenty-two citizens with the
 * 22 look ids live around the town and the two camps of whatever world is loaded: they work, gather, eat, drink,
 * rest, talk (emitting `said` events) and walk straight between spots at the engine's pace (5 km/h = 83 m per
 * tick), streaming each tick's step and the next two ticks of the walk, timed, as the engine does (`route`, its
 * `t_s`, `speed_mps`); animals graze and prowl
 * and fires burn (`mock-wild.ts`). Like a new engine run
 * it starts at ×1 (a tick a real minute); tests speed it up with `setClock`.
 * Messages have the contract's shapes; sockets are fake WebSockets driven by the same tick loop, so the client's
 * connect / reconnect path is the one the real feed uses. `window.__pebbleMockLive` lets tests drop connections
 * and make someone speak, start a new run, or act as if there were no run.
 */
import { Vector3 } from 'three';

import {
  type Activity,
  LIVE_CLOSE,
  type LiveCitizen,
  type LiveEventMessage,
  type LiveFrame,
  type LiveMessage,
  TICK_SECONDS,
  tickMs,
} from './live-contract';
import { MockWild } from './mock-wild';
import type { FedBody } from './motion';
import type {
  CitizenEntity,
  LiveEventDetail,
  Position,
  RoutePoint,
  Site,
  WorldView,
} from '@/lib/client/types.gen';
import { CITIZEN_LOOKS } from '@/lib/world/citizen-looks';
import {
  anchorMapping,
  latLonFromDirection,
  type SiteMapping,
} from '@/lib/world/globe';

/** The engine's walking pace (backend `WALK_M_PER_TICK`), metres per tick. */
const WALK_M_PER_TICK = 5000 / 60;
/** How many ticks of a walk each frame streams ahead (backend `WALK_AHEAD_TICKS`). */
const WALK_AHEAD_TICKS = 2;
/** Tick 0 is 08:00 on day 0, one tick per game minute (backend `app/sim/clock.py`). */
const START_MINUTE = 8 * 60;
const DAY_MINUTES = 24 * 60;
const NIGHT = { from: 22 * 60, to: 5 * 60 };
/** Dark enough for fires and for the animals' night (sunset to sunrise, roughly). */
const DARK = { from: 18 * 60 + 30, to: 6 * 60 };

type Spot = [number, number];

/** A slot with furniture someone sits or lies on (the backend's `data/slots.yaml`): its facing and seat height. */
interface Seat {
  heading: number;
  /** Where the hips rest; 0 on a mat. */
  height: number;
}

type Step =
  | { walk: Spot; to: string }
  | {
      activity: Exclude<Activity, 'walking' | 'dead'>;
      label?: string;
      ticks: number;
      say?: string;
      /** Done on the furniture of the slot they stand on (the walk before it ends there). */
      seat?: Seat;
    };

interface MockPerson {
  id: string;
  name: string;
  look: string;
  appearance: string;
  site: 'town' | 'band_a_camp' | 'band_b_camp';
  /** Pace relative to a young adult (children 0.7, elders 0.6). */
  pace: number;
  home: Spot;
  plan: Step[];
}

const WELL: Spot = [-21, 52];

/** A log seat by a camp's fire pit (slots.yaml `fire_pit` seat-N): 2.2 m out at a compass bearing, facing the fire. */
function fireSeat(bearing: number): [Spot, Seat] {
  const turn = (bearing * Math.PI) / 180;
  return [
    [2.2 * Math.sin(turn), -2.2 * Math.cos(turn)],
    { heading: (360 - bearing) % 360, height: 0.4 },
  ];
}
/** fire_pit seat-4 and seat-7, seat-8. */
const [EAST_LOG, EAST_SEAT] = fireSeat(121);
const [WEST_LOG, WEST_SEAT] = fireSeat(289);
const [NORTH_WEST_LOG, NORTH_WEST_SEAT] = fireSeat(311);
/** The lord's seat in the castle court (castle_keep lord-seat, the keep at (0, -6)). */
const LORD_SEAT_AT: Spot = [0, 3.5];
const LORD_SEAT: Seat = { heading: 0, height: 0.45 };
/** The weaver's stool at farmhouse-1's loom (loom seat, the loom at (-87, 91.4)). */
const LOOM_STOOL_AT: Spot = [-87, 92.15];
const LOOM_STOOL: Seat = { heading: 180, height: 0.3 };
/** A mat under band B's north lean-to (lean_to mat-1, the lean-to at (0, -6)), heads in. */
const LEAN_TO_MAT_AT: Spot = [-0.45, -6.2];
const LEAN_TO_MAT: Seat = { heading: 0, height: 0 };

type Motion = CitizenEntity['motion'];
type Posture = CitizenEntity['posture'];

/** The backend's motion table (`app/sim/motion.py`) for the mock's doings; work and gathering go by their label. */
const MOTIONS: Record<Exclude<Activity, 'walking'>, Motion> = {
  dead: 'lie',
  idle: 'idle',
  running: 'run',
  sleeping: 'lie',
  resting: 'sit_ground',
  gathering: 'gather_low',
  eating: 'eat',
  drinking: 'drink',
  working: 'idle',
  hunting: 'stalk',
  fishing: 'fish',
  tending_fire: 'tend',
  talking: 'talk',
};
const LABEL_MOTIONS: Record<string, Motion> = {
  berries: 'gather_high',
  nuts: 'gather_high',
  'tending the rice paddies': 'farm',
  'planting the seed beds': 'farm',
  'weaving at the loom': 'craft',
  'mending the drying rack': 'craft',
  'filling the storehouse': 'pick_up',
  'chopping firewood': 'chop',
};
const POSTURES: Partial<Record<Motion, Posture>> = {
  sit: 'sitting',
  sit_ground: 'sitting_ground',
  lie: 'lying',
  inside: 'inside',
  gather_low: 'crouching',
  pan: 'crouching',
  tend: 'crouching',
  craft: 'crouching',
  pray: 'sitting_ground',
};
/** Why they do what they do (the feed's `goal` and `driver`), by doing. */
const GOALS: Partial<Record<Activity, [string, CitizenEntity['driver']]>> = {
  working: ['get the day’s work done', 'duty'],
  gathering: ['bring food home', 'hunger'],
  eating: ['eat something', 'hunger'],
  drinking: ['have a drink', 'thirst'],
  resting: ['get my strength back', 'rest'],
  sleeping: ['sleep till morning', 'night'],
  talking: ['hear the news', 'social'],
};
/** Rank, titles, purse and standing (10-world-v1 §3.1-3.2); everyone else is a rank-2 adult with no coins. */
const SOCIETY: Record<
  string,
  Pick<CitizenEntity, 'rank' | 'titles' | 'coins' | 'standing'>
> = {
  tadamasa: { rank: 5, titles: ['lord'], coins: 2015, standing: 70 },
  kenji: { rank: 4, titles: ['samurai'], coins: 60, standing: 55 },
  genzo: { rank: 2, titles: [], coins: 60, standing: 50 },
  aiko: { rank: 2, titles: [], coins: 60, standing: 50 },
  sora: { rank: 1, titles: [], coins: 5, standing: 50 },
  oru: { rank: 4, titles: ['leader'], coins: 0, standing: 70 },
  brak: { rank: 4, titles: ['leader'], coins: 0, standing: 70 },
};
const COMMONER = { rank: 2, titles: [], coins: 0, standing: 50 };

const PEOPLE: MockPerson[] = [
  {
    id: 'genzo',
    name: 'Genzo',
    look: 'town-farmer',
    appearance: 'a broad man in a straw hat',
    site: 'town',
    pace: 1,
    home: [-128, 44],
    plan: [
      { activity: 'working', label: 'tending the rice paddies', ticks: 12 },
      { walk: [-128, 68], to: 'the seed beds' },
      { activity: 'working', label: 'planting the seed beds', ticks: 9 },
      { walk: WELL, to: 'the well' },
      { activity: 'drinking', label: 'the well', ticks: 4 },
      { walk: [-128, 44], to: 'the rice fields' },
    ],
  },
  {
    id: 'aiko',
    name: 'Aiko',
    look: 'town-weaver',
    appearance: 'a young woman in an indigo robe',
    site: 'town',
    pace: 1,
    home: LOOM_STOOL_AT,
    plan: [
      {
        activity: 'working',
        label: 'weaving at the loom',
        ticks: 14,
        seat: LOOM_STOOL,
      },
      { walk: [-24, 54], to: 'the well' },
      { activity: 'drinking', label: 'the well', ticks: 4 },
      { walk: [-78, 93], to: 'home' },
      { activity: 'eating', label: 'a bowl of rice', ticks: 6 },
      { walk: LOOM_STOOL_AT, to: 'the loom' },
    ],
  },
  {
    id: 'sora',
    name: 'Sora',
    look: 'town-child',
    appearance: 'a small boy with a topknot',
    site: 'town',
    pace: 0.7,
    home: [-23, 47],
    plan: [
      { activity: 'idle', label: 'by the well', ticks: 3 },
      {
        activity: 'talking',
        label: 'Haru',
        ticks: 3,
        say: 'Haru! Haru! Can I help at the stall?',
      },
      { walk: [-26, 40], to: 'the street' },
      { activity: 'gathering', label: 'pebbles', ticks: 6 },
      { walk: [-23, 47], to: 'the well' },
    ],
  },
  {
    id: 'haru',
    name: 'Haru',
    look: 'town-merchant',
    appearance: 'a thin old man with a walking stick',
    site: 'town',
    pace: 0.6,
    home: [20, 54],
    plan: [
      { activity: 'idle', label: 'the market', ticks: 1 },
      {
        activity: 'talking',
        label: 'a customer',
        ticks: 6,
        say: 'Fresh rice and good salt today, a fair price for both!',
      },
      { activity: 'idle', label: 'the market', ticks: 8 },
      { walk: [58, 72], to: 'the storehouse' },
      { activity: 'working', label: 'filling the storehouse', ticks: 6 },
      { walk: [20, 54], to: 'the market' },
    ],
  },
  {
    id: 'kenji',
    name: 'Kenji',
    look: 'town-samurai',
    appearance: 'a stern man with two swords',
    site: 'town',
    pace: 1,
    home: [0, 30],
    plan: [
      { activity: 'idle', label: 'the castle bridge', ticks: 6 },
      { walk: [0, 112], to: 'the main gate' },
      { activity: 'idle', label: 'the main gate', ticks: 6 },
      { walk: [0, 30], to: 'the castle bridge' },
    ],
  },
  {
    id: 'tadamasa',
    name: 'Lord Tadamasa',
    look: 'town-lord',
    appearance: 'a grey-bearded lord in a dark robe',
    site: 'town',
    pace: 0.9,
    home: [0, 2.4],
    plan: [
      { activity: 'idle', label: 'the courtyard', ticks: 10 },
      { walk: LORD_SEAT_AT, to: 'his seat' },
      {
        activity: 'resting',
        label: 'the courtyard',
        ticks: 10,
        seat: LORD_SEAT,
      },
      { walk: [0, 2.4], to: 'the courtyard' },
      { activity: 'eating', label: 'his midday meal', ticks: 5 },
    ],
  },
  {
    id: 'oru',
    name: 'Oru',
    look: 'band-a-leader',
    appearance: 'a tall man in a fur stole',
    site: 'band_a_camp',
    pace: 0.9,
    home: EAST_LOG,
    plan: [
      {
        activity: 'resting',
        label: 'the fire pit',
        ticks: 8,
        seat: EAST_SEAT,
      },
      { walk: [32, 24], to: 'the thicket' },
      { activity: 'gathering', label: 'firewood', ticks: 8 },
      { walk: EAST_LOG, to: 'camp' },
      {
        activity: 'talking',
        label: 'Mena',
        ticks: 4,
        say: 'The berries by the thicket are ripe again.',
        seat: EAST_SEAT,
      },
    ],
  },
  {
    id: 'mena',
    name: 'Mena',
    look: 'band-a-healer',
    appearance: 'an old woman with long white hair',
    site: 'band_a_camp',
    pace: 0.6,
    home: NORTH_WEST_LOG,
    plan: [
      {
        activity: 'resting',
        label: 'the fire pit',
        ticks: 6,
        seat: NORTH_WEST_SEAT,
      },
      {
        activity: 'eating',
        label: 'roasted roots',
        ticks: 5,
        seat: NORTH_WEST_SEAT,
      },
      { walk: [-24, 18], to: 'the root patch' },
      { activity: 'gathering', label: 'roots', ticks: 10 },
      { walk: NORTH_WEST_LOG, to: 'camp' },
    ],
  },
  {
    id: 'tak',
    name: 'Tak',
    look: 'band-a-hunter',
    appearance: 'a lean man with a spear',
    site: 'band_a_camp',
    pace: 1,
    home: [5, 4],
    plan: [
      { activity: 'idle', label: 'camp', ticks: 4 },
      { walk: [-40, -30], to: 'the water' },
      { activity: 'drinking', label: 'the water', ticks: 4 },
      { walk: [60, -20], to: 'the far ridge' },
      { activity: 'idle', label: 'the far ridge', ticks: 6 },
      { walk: [5, 4], to: 'camp' },
    ],
  },
  {
    id: 'lio',
    name: 'Lio',
    look: 'band-a-gatherer-teen',
    appearance: 'a wiry girl with braided hair',
    site: 'band_a_camp',
    pace: 1,
    home: [-2, 6],
    plan: [
      { walk: [18, -26], to: 'the berry bushes' },
      { activity: 'gathering', label: 'berries', ticks: 10 },
      { walk: [-2, 6], to: 'camp' },
      { activity: 'eating', label: 'berries', ticks: 4 },
    ],
  },
  {
    id: 'ana',
    name: 'Ana',
    look: 'band-a-gatherer',
    appearance: 'a strong woman with a reed basket',
    site: 'band_a_camp',
    pace: 1,
    home: [3, 4.6],
    plan: [
      { activity: 'working', label: 'mending the drying rack', ticks: 7 },
      { walk: [-36, -12], to: 'the reed bed' },
      { activity: 'gathering', label: 'reeds', ticks: 9 },
      { walk: [3, 4.6], to: 'the drying rack' },
    ],
  },
  {
    id: 'brak',
    name: 'Brak',
    look: 'band-b-leader',
    appearance: 'a heavy-set man with a beard',
    site: 'band_b_camp',
    pace: 0.9,
    home: EAST_LOG,
    plan: [
      {
        activity: 'talking',
        label: 'Sela',
        ticks: 4,
        say: 'We move to the hills when the nuts are gone.',
        seat: EAST_SEAT,
      },
      { walk: [28, 30], to: 'the nut trees' },
      { activity: 'gathering', label: 'nuts', ticks: 9 },
      { walk: EAST_LOG, to: 'camp' },
      {
        activity: 'resting',
        label: 'the fire pit',
        ticks: 6,
        seat: EAST_SEAT,
      },
    ],
  },
  {
    id: 'sela',
    name: 'Sela',
    look: 'band-b-mother',
    appearance: 'a woman with a baby sling',
    site: 'band_b_camp',
    pace: 1,
    home: NORTH_WEST_LOG,
    plan: [
      {
        activity: 'resting',
        label: 'the fire pit',
        ticks: 5,
        seat: NORTH_WEST_SEAT,
      },
      {
        activity: 'eating',
        label: 'dried fish',
        ticks: 5,
        seat: NORTH_WEST_SEAT,
      },
      { walk: [-26, 20], to: 'the berry bushes' },
      { activity: 'gathering', label: 'berries', ticks: 8 },
      { walk: NORTH_WEST_LOG, to: 'camp' },
    ],
  },
  {
    id: 'dun',
    name: 'Dun',
    look: 'band-b-hunter',
    appearance: 'a young man with a short spear',
    site: 'band_b_camp',
    pace: 1,
    home: [4.6, 3.6],
    plan: [
      { activity: 'working', label: 'chopping firewood', ticks: 6 },
      { walk: [40, -34], to: 'the stream' },
      { activity: 'drinking', label: 'the stream', ticks: 4 },
      { walk: [4.6, 3.6], to: 'camp' },
    ],
  },
  {
    id: 'pip',
    name: 'Pip',
    look: 'band-b-child',
    appearance: 'a small child in a hide tunic',
    site: 'band_b_camp',
    pace: 0.7,
    home: LEAN_TO_MAT_AT,
    plan: [
      {
        activity: 'sleeping',
        label: 'the lean-to',
        ticks: 12,
        seat: LEAN_TO_MAT,
      },
      { walk: [0, -4.4], to: 'camp' },
      { activity: 'idle', label: 'camp', ticks: 4 },
      { walk: [8, 8], to: 'the drying rack' },
      { activity: 'gathering', label: 'sticks', ticks: 5 },
      { walk: LEAN_TO_MAT_AT, to: 'the lean-to' },
    ],
  },
  {
    id: 'goro',
    name: 'Goro',
    look: 'town-ashigaru',
    appearance: 'a young foot soldier with a long spear',
    site: 'town',
    pace: 1,
    home: [-94, 76],
    plan: [
      { activity: 'working', label: 'keeping watch', ticks: 10 },
      { walk: [-94, 66], to: 'the cross street' },
      { activity: 'idle', label: 'the west gate', ticks: 4 },
      { walk: [-94, 76], to: 'the west gate' },
    ],
  },
  {
    id: 'tokuji',
    name: 'Tokuji',
    look: 'town-elder-farmer',
    appearance: 'a stooped old man under a wide straw hat',
    site: 'town',
    pace: 0.6,
    home: [-136, 30],
    plan: [
      { activity: 'working', label: 'tending the rice paddies', ticks: 16 },
      { walk: [-136, 38], to: 'the next paddy' },
      { activity: 'resting', label: 'the rice fields', ticks: 6 },
      { walk: [-136, 30], to: 'the rice fields' },
    ],
  },
  {
    id: 'tetsu',
    name: 'Tetsu',
    look: 'town-smith',
    appearance: 'a broad man in a leather apron',
    site: 'town',
    pace: 1,
    home: [53.5, 59],
    plan: [
      { activity: 'working', label: 'working at the forge', ticks: 14 },
      { walk: [22, 58], to: 'the market' },
      {
        activity: 'talking',
        label: 'Haru',
        ticks: 3,
        say: 'Two sickles by tomorrow.',
      },
      { walk: [53.5, 59], to: 'the forge' },
    ],
  },
  {
    id: 'daisuke',
    name: 'Daisuke',
    look: 'town-digger',
    appearance: 'a wiry man with a shovel',
    site: 'town',
    pace: 1,
    // on the cross street in front of his townhouse (cross-n-8): he goes in through its door first
    home: [36, 60],
    plan: [
      { walk: [36, 56], to: 'home' },
      { activity: 'resting', label: 'home', ticks: 8 },
      { walk: [58, 72], to: 'the storehouse' },
      { activity: 'working', label: 'filling the storehouse', ticks: 5 },
      { walk: [36, 60], to: 'the cross street' },
      { activity: 'idle', label: 'the cross street', ticks: 1 },
    ],
  },
  {
    id: 'ennen',
    name: 'Ennen',
    look: 'town-monk',
    appearance: 'a shaven-headed monk with a ringed staff',
    site: 'town',
    pace: 0.8,
    home: [70, -62],
    plan: [
      { activity: 'working', label: 'praying at the temple', ticks: 15 },
      { walk: [84, -70], to: 'the bell tower' },
      { activity: 'idle', label: 'the bell tower', ticks: 3 },
      { walk: [70, -62], to: 'the temple' },
    ],
  },
  {
    id: 'bo',
    name: 'Bo',
    look: 'band-a-toolmaker',
    appearance: 'a thickset bearded man with a hide pack',
    site: 'band_a_camp',
    pace: 1,
    home: [-0.5, 4],
    plan: [
      { activity: 'working', label: 'knapping a spear point', ticks: 10 },
      { walk: [30, 22], to: 'the flint' },
      { activity: 'gathering', label: 'flint', ticks: 6 },
      { walk: [-0.5, 4], to: 'camp' },
    ],
  },
  {
    id: 'vesa',
    name: 'Vesa',
    look: 'band-b-elder',
    appearance: 'a white-haired old woman in a fur mantle',
    site: 'band_b_camp',
    pace: 0.6,
    home: WEST_LOG,
    plan: [
      {
        activity: 'resting',
        label: 'the fire pit',
        ticks: 10,
        seat: WEST_SEAT,
      },
      { walk: [-20, 16], to: 'the root patch' },
      { activity: 'gathering', label: 'roots', ticks: 8 },
      { walk: WEST_LOG, to: 'camp' },
    ],
  },
];

/**
 * The band A camp as the engine's first dawn showed it (tests, audit F2/F22): four people talking and eating on one
 * spot by the fire while two walk straight through them back and forth, head-on.
 */
const CROWDED_CAMP: Record<string, Pick<MockPerson, 'home' | 'plan'>> = {
  oru: {
    home: [1, 1],
    plan: [{ activity: 'talking', label: 'Mena', ticks: 60 }],
  },
  mena: {
    home: [1, 1],
    plan: [{ activity: 'eating', label: 'roasted roots', ticks: 60 }],
  },
  lio: {
    home: [1, 1],
    plan: [{ activity: 'eating', label: 'berries', ticks: 60 }],
  },
  bo: {
    home: [1, 1],
    plan: [{ activity: 'talking', label: 'Oru', ticks: 60 }],
  },
  tak: {
    home: [-12, 1],
    plan: [
      { walk: [14, 1], to: 'the drying rack' },
      { walk: [-12, 1], to: 'the water' },
    ],
  },
  ana: {
    home: [14, 1],
    plan: [
      { walk: [-12, 1], to: 'the water' },
      { walk: [14, 1], to: 'the drying rack' },
    ],
  },
};

const ROLES = new Map(CITIZEN_LOOKS.map((look) => [look.id, look]));

interface PersonState {
  person: MockPerson;
  mapping: SiteMapping;
  height: number;
  at: Spot;
  heading: number;
  step: number;
  /** Ticks left in the current (non-walking) step. */
  left: number;
  /** The last tick they walked in: from where, and the game seconds it took to get where they are. */
  walked?: { tick: number; from: Spot; seconds: number };
}

/** A WebSocket's client side as the live hook uses it (the real one and the mock's). */
export interface LiveSocket {
  onopen: (() => void) | null;
  onmessage: ((event: { data: string }) => void) | null;
  onclose: ((event: { code: number }) => void) | null;
  onerror: (() => void) | null;
  close(): void;
}

class MockSocket implements LiveSocket {
  onopen: (() => void) | null = null;
  onmessage: ((event: { data: string }) => void) | null = null;
  onclose: ((event: { code: number }) => void) | null = null;
  onerror: (() => void) | null = null;
  constructor(private readonly server: MockLiveServer) {}
  close() {
    this.server.detach(this, 1000);
  }
  deliver(message: LiveMessage) {
    this.onmessage?.({ data: JSON.stringify(message) });
  }
}

/** TEST ONLY, set before the page loads: the mock starts `ticks` in, held at `speed`, `elapsed` game seconds into its
 * tick (a page opened mid-tick). */
export interface MockStartHook {
  __pebbleMockStart?: { ticks: number; speed: number; elapsed: number };
}

export interface MockClock {
  speed: number;
  paused: boolean;
}

export class MockLiveServer {
  runId = 'mock-run-1';
  /** Like a new engine run: tick 0 is 08:00 on day 0. */
  private tick = 0;
  private clock: MockClock = { speed: 1, paused: false };
  /** When (performance.now) the current tick began counting: its tick, or the last clock change (it restarts the timer). */
  private beat = performance.now();
  /** Game seconds of the tick passed before the clock was held (`__pebbleMockStart`); a running timer starts afresh. */
  private held = 0;
  private timer: ReturnType<typeof setInterval> | null = null;
  private sockets = new Set<MockSocket>();
  private states: PersonState[];
  private wild: MockWild;
  private readonly world: WorldView;
  private events = 0;
  private pending: LiveEventMessage[] = [];
  /** Body words a test gave someone (`feel`); everyone else feels fine. */
  private feelings = new Map<string, string[]>();
  /** What a test made someone do (`perform`), over their plan. */
  private performing = new Map<string, Partial<LiveCitizen> & FedBody>();
  /** Homes and plans a test scene gives some (`crowdCamp`); everyone else lives their own. */
  private scene: Record<string, Pick<MockPerson, 'home' | 'plan'>> = {};
  /** Connections so far (tests read it to see a reconnect). */
  connects = 0;
  /** Like a backend without a run (tests): every connection is accepted, then closed with 4404. */
  noRun = false;

  constructor(world: WorldView) {
    this.world = world;
    this.states = this.freshStates();
    this.wild = new MockWild(world);
    const { __pebbleMockStart: start } = globalThis as MockStartHook;
    if (start) {
      this.advanceTicks(start.ticks);
      this.clock = { speed: start.speed, paused: true };
      this.held = start.elapsed;
    }
  }

  private freshStates(): PersonState[] {
    const sites = new Map<string, Site>(
      this.world.sites.map((site) => [site.id, site]),
    );
    return PEOPLE.map((own) => {
      const person = { ...own, ...this.scene[own.id] };
      const site = sites.get(person.site);
      if (!site) throw new Error(`the world has no ${person.site} site`);
      return {
        person,
        mapping: anchorMapping(site.anchor, this.world.radius_m),
        height: site.anchor.height_m,
        at: [...person.home],
        heading: 0,
        step: 0,
        left: stepTicks(person.plan[0]),
      };
    });
  }

  /** The `GET /api/v1/entities` answer. */
  entities() {
    const { day, time } = this.clockWords();
    return {
      run_id: this.runId,
      tick: this.tick,
      day,
      time,
      tick_elapsed_s: this.tickElapsed(),
      citizens: this.citizens(),
      animals: this.wild.animals(isDark(this.tick)),
      fires: this.wild.fires(isDark(this.tick)),
    };
  }

  connect(): LiveSocket {
    const socket = new MockSocket(this);
    this.sockets.add(socket);
    this.connects += 1;
    setTimeout(() => {
      if (!this.sockets.has(socket)) return;
      socket.onopen?.();
      if (this.noRun) this.detach(socket, LIVE_CLOSE.noRun);
      else socket.deliver(this.frame('snapshot'));
    }, 0);
    this.schedule();
    return socket;
  }

  setClock(change: Partial<MockClock>) {
    this.clock = { ...this.clock, ...change };
    this.schedule();
    // like the engine: one extra tick (same tick number) carries the new speed or pause
    const frame = this.frame('tick');
    for (const socket of this.sockets) socket.deliver(frame);
  }

  /** Someone says something right now (tests): the `said` event goes out at once. */
  sayNow(actor: string, words: string) {
    const speaker = this.states.find((state) => state.person.id === actor);
    if (!speaker) throw new Error(`no mock citizen ${actor}`);
    this.say(speaker, words);
    const events = this.pending.splice(0);
    for (const socket of this.sockets)
      events.forEach((event) => socket.deliver(event));
  }

  /** Someone feels `words` (tests: "hungry", "weak and aching"): a snapshot carries it at once. */
  feel(actor: string, words: string[]) {
    this.feelings.set(actor, words);
    const frame = this.frame('snapshot');
    for (const socket of this.sockets) socket.deliver(frame);
  }

  /**
   * Someone does `doing` (tests and close-ups: any activity, motion, posture, seat heading; `null` lets them go back
   * to their plan): standing where they are, or, doing something on the move (walking, running, hunting), walking on
   * along their plan drawn that way. A snapshot carries it at once.
   */
  perform(actor: string, doing: (Partial<LiveCitizen> & FedBody) | null) {
    if (doing) this.performing.set(actor, doing);
    else this.performing.delete(actor);
    const frame = this.frame('snapshot');
    for (const socket of this.sockets) socket.deliver(frame);
  }

  /** An event of any type goes out right now (tests: a gesture, a blow), with anything queued. */
  sendNow(
    type: string,
    actor: string,
    payload: Record<string, unknown>,
    told: Pick<LiveEventDetail, 'line' | 'importance'> = {
      line: type,
      importance: 0,
    },
  ) {
    this.queueEvent(type, actor, payload, told);
    const events = this.pending.splice(0);
    for (const socket of this.sockets)
      events.forEach((event) => socket.deliver(event));
  }

  /** Queues an event of any type for the next tick, like the engine's own (tests: a death, a sale), told as the
   * backend's line registry would tell it; it happens where its citizen actor stands unless `told` says where. */
  queueEvent(
    type: string,
    actor: string | null,
    payload: Record<string, unknown>,
    told: Pick<LiveEventDetail, 'line' | 'importance'> &
      Partial<Pick<LiveEventDetail, 'position'>>,
  ) {
    const state = this.states.find((one) => one.person.id === actor);
    this.events += 1;
    this.pending.push({
      type: 'event',
      run_id: this.runId,
      tick: this.tick + 1,
      event: {
        id: `mock-${type}-${this.events}`,
        type,
        actor_id: actor,
        payload,
        position: state ? placeOf(state) : null,
        ...told,
      },
    });
  }

  /** Jumps the feed `ticks` ahead at once (tests: to the evening): one `tick` frame with where everything is. */
  skip(ticks: number) {
    this.advanceTicks(ticks);
    this.held = 0;
    this.pending.splice(0);
    const frame = this.frame('tick');
    for (const socket of this.sockets) socket.deliver(frame);
  }

  /** Simulates the server going away: every open socket closes abnormally. */
  dropConnections(code = 1006) {
    for (const socket of [...this.sockets]) this.detach(socket, code);
  }

  /** A new run whose band A camp is crowded like the engine's first dawn (CROWDED_CAMP; tests). */
  crowdCamp() {
    this.scene = CROWDED_CAMP;
    this.restartRun();
  }

  /** A new run starts (like the engine's `--new-run`): open sockets close with 1012, the clock starts at 08:00. */
  restartRun() {
    this.runId = `mock-run-${Number(this.runId.split('-').pop()) + 1}`;
    this.tick = 0;
    this.held = 0;
    this.states = this.freshStates();
    this.wild = new MockWild(this.world);
    this.feelings.clear();
    this.performing.clear();
    this.dropConnections(LIVE_CLOSE.resync);
  }

  detach(socket: MockSocket, code: number) {
    if (!this.sockets.delete(socket)) return;
    socket.onclose?.({ code });
    if (this.sockets.size === 0) this.schedule();
  }

  stop() {
    if (this.timer !== null) clearInterval(this.timer);
    this.timer = null;
  }

  private advanceTicks(ticks: number) {
    for (let k = 0; k < ticks; k++) {
      this.tick += 1;
      const night = isNight(this.tick);
      for (const state of this.states) this.advance(state, night);
      this.wild.step(isDark(this.tick));
    }
  }

  /** Game seconds of the current tick passed, like the backend's `tick_elapsed_s`. */
  private tickElapsed() {
    if (this.clock.paused) return this.held;
    const seconds = ((performance.now() - this.beat) / 1000) * this.clock.speed;
    return Math.min(seconds, TICK_SECONDS);
  }

  private schedule() {
    this.stop();
    this.beat = performance.now();
    if (this.clock.paused || this.sockets.size === 0) return;
    this.held = 0;
    this.timer = setInterval(() => this.step(), tickMs(this.clock.speed));
  }

  private step() {
    this.beat = performance.now();
    this.tick += 1;
    const night = isNight(this.tick);
    for (const state of this.states) this.advance(state, night);
    this.wild.step(isDark(this.tick));
    const frame = this.frame('tick');
    const events = this.pending.splice(0);
    for (const socket of this.sockets) {
      socket.deliver(frame);
      events.forEach((event) => socket.deliver(event));
    }
  }

  private advance(state: PersonState, night: boolean) {
    const performed = this.performing.get(state.person.id)?.activity;
    if (night || (performed && !MOVING.has(performed))) return;
    const { plan } = state.person;
    const step = plan[state.step];
    if ('walk' in step) {
      const [tx, tz] = step.walk;
      const [x, z] = state.at;
      const distance = Math.hypot(tx - x, tz - z);
      const reach = WALK_M_PER_TICK * state.person.pace;
      if (distance > 1e-6)
        state.heading = (Math.atan2(tx - x, tz - z) * 180) / Math.PI;
      state.walked = {
        tick: this.tick,
        from: [x, z],
        seconds: (Math.min(distance, reach) / reach) * TICK_SECONDS,
      };
      if (distance <= reach) {
        state.at = [tx, tz];
        this.next(state);
      } else
        state.at = [
          x + ((tx - x) * reach) / distance,
          z + ((tz - z) * reach) / distance,
        ];
      return;
    }
    state.left -= 1;
    if (state.left <= 0) this.next(state);
  }

  private next(state: PersonState) {
    const { plan } = state.person;
    state.step = (state.step + 1) % plan.length;
    const step = plan[state.step];
    state.left = stepTicks(step);
    if ('say' in step && step.say) this.say(state, step.say);
  }

  private say(state: PersonState, words: string) {
    this.events += 1;
    this.pending.push({
      type: 'event',
      run_id: this.runId,
      tick: this.tick,
      event: {
        id: `mock-said-${this.events}`,
        type: 'said',
        actor_id: state.person.id,
        payload: { words, volume: 'normal', heard_by: [] },
        line: `${state.person.name}: “${words}”`,
        importance: 1,
        position: placeOf(state),
      },
    });
  }

  private clockWords() {
    const minute = START_MINUTE + this.tick;
    const pad = (value: number) => String(value).padStart(2, '0');
    return {
      day: Math.floor(minute / DAY_MINUTES),
      time: `${pad(Math.floor((minute % DAY_MINUTES) / 60))}:${pad(minute % 60)}`,
    };
  }

  private frame(type: LiveFrame['type']): LiveFrame {
    return {
      type,
      run_id: this.runId,
      tick: this.tick,
      ...this.clockWords(),
      speed: this.clock.speed,
      paused: this.clock.paused,
      tick_elapsed_s: this.tickElapsed(),
      citizens: this.citizens(),
      animals: this.wild.animals(isDark(this.tick)),
      fires: this.wild.fires(isDark(this.tick)),
    };
  }

  private citizens(): LiveCitizen[] {
    const night = isNight(this.tick);
    return this.states.map((state) => {
      const { person } = state;
      const step = person.plan[state.step];
      const look = ROLES.get(person.look);
      if (!look) throw new Error(`unknown look ${person.look}`);
      const position = placeOf(state);
      const activity: Activity = night
        ? 'sleeping'
        : 'walk' in step
          ? 'walking'
          : step.activity;
      const walked =
        state.walked?.tick === this.tick ? state.walked : undefined;
      const route = walked ? this.route(state, walked) : [];
      return {
        id: person.id,
        name: person.name,
        look: person.look,
        appearance: person.appearance,
        position,
        route,
        // the arc of the first leg over its time (the site's local metres stretch a little away from its anchor)
        speed_mps:
          route.length > 1
            ? (new Vector3(...route[0].unit).angleTo(
                new Vector3(...route[1].unit),
              ) *
                this.world.radius_m) /
              (route[1].t_s ?? TICK_SECONDS)
            : 0,
        cell: 0,
        alive: true,
        asleep: activity === 'sleeping',
        action: actionOf(activity),
        action_label: night
          ? ''
          : 'walk' in step
            ? step.to
            : (step.label ?? ''),
        state: this.feelings.get(person.id) ?? [],
        cause_of_death: null,
        heading_deg: state.heading,
        activity,
        role: look.role,
        region: look.region,
        ...this.spectator(state, activity, route.length > 1),
        ...this.performed(person.id),
      };
    });
  }

  /** The feed's spectator fields (10-world-v1 §6.4) for what someone is doing. */
  /** What a test made someone do, its posture told from its motion (as the backend tells it) unless given. */
  private performed(id: string): Partial<LiveCitizen> & FedBody {
    const doing = this.performing.get(id);
    if (!doing?.motion) return doing ?? {};
    return { posture: POSTURES[doing.motion] ?? 'standing', ...doing };
  }

  private spectator(
    state: PersonState,
    activity: Activity,
    moved: boolean,
  ): Pick<
    CitizenEntity,
    | 'motion'
    | 'posture'
    | 'slot_heading'
    | 'slot_height_m'
    | 'goal'
    | 'driver'
    | 'target'
    | 'needs'
    | 'carrying'
    | 'coins'
    | 'rank'
    | 'standing'
    | 'titles'
  > {
    const step = state.person.plan[state.step];
    // on a seat, a mat or a stool, as the backend's motion reads a slot (D119): resting there sits on it
    const seat =
      !moved && 'seat' in step && step.activity === activity
        ? step.seat
        : undefined;
    const motion =
      seat && activity === 'resting'
        ? 'sit'
        : mockMotion(activity, labelOf(step), moved);
    const [goal, driver] = GOALS[activity] ?? ['', null];
    const target =
      'walk' in step && activity === 'walking'
        ? {
            kind: 'place' as const,
            id: null,
            name: step.to,
            position: placeOf({ ...state, at: step.walk }).unit,
          }
        : null;
    return {
      motion,
      posture: seat
        ? motion === 'lie'
          ? 'lying'
          : 'sitting'
        : (POSTURES[motion] ?? 'standing'),
      slot_heading: seat?.heading ?? null,
      slot_height_m: seat && seat.height > 0 ? seat.height : null,
      goal,
      driver,
      target,
      needs: {
        hunger: activity === 'eating' ? 55 : 20,
        thirst: activity === 'drinking' ? 55 : 15,
        energy: activity === 'sleeping' || activity === 'resting' ? 35 : 80,
        health: 100,
      },
      carrying: activity === 'gathering' ? { [labelOf(step)]: 3 } : {},
      ...(SOCIETY[state.person.id] ?? COMMONER),
    };
  }

  /** This tick's step from where they stood, then (still walking) the next ticks of the walk, timed. */
  private route(
    state: PersonState,
    walked: NonNullable<PersonState['walked']>,
  ): RoutePoint[] {
    const step = state.person.plan[state.step];
    const reach = WALK_M_PER_TICK * state.person.pace;
    const spots: [Spot, number][] = [
      [walked.from, 0],
      [state.at, walked.seconds],
    ];
    if ('walk' in step) {
      const end = walkAhead(state.at, step.walk, WALK_AHEAD_TICKS * reach);
      const metres = Math.hypot(end[0] - state.at[0], end[1] - state.at[1]);
      if (metres > 1e-6)
        spots.push([end, walked.seconds + (metres / reach) * TICK_SECONDS]);
    }
    return spots.map(([[x, z], seconds]) => ({
      unit: state.mapping.toWorld(x, 0, z, new Vector3()).normalize().toArray(),
      height_m: state.height,
      t_s: seconds,
    }));
  }
}

/** Doings on the move: someone performing one walks on along their plan. */
const MOVING: ReadonlySet<Activity> = new Set([
  'walking',
  'running',
  'hunting',
]);

const stepTicks = (step: Step) => ('walk' in step ? 0 : step.ticks);

const labelOf = (step: Step) => ('label' in step && step.label) || '';

/** Like the backend: the dead and sleepers lie whatever their step is about; a mover walks; else by label or doing. */
export function mockMotion(
  activity: Activity,
  label: string,
  moved: boolean,
): Motion {
  if (activity !== 'walking' && MOTIONS[activity] === 'lie') return 'lie';
  if (moved) return 'walk';
  if (activity === 'walking') return 'idle';
  return LABEL_MOTIONS[label] ?? MOTIONS[activity];
}

/** Where someone stands, as the feed says it. */
function placeOf(state: PersonState): Position {
  const { x, y, z } = state.mapping
    .toWorld(state.at[0], 0, state.at[1], new Vector3())
    .normalize();
  const { lat, lon } = latLonFromDirection(new Vector3(x, y, z));
  return { unit: [x, y, z], height_m: state.height, lat, lon };
}

/** Where `metres` of walking from `from` towards `to` ends (at `to` if it is closer). */
function walkAhead([x, z]: Spot, [tx, tz]: Spot, metres: number): Spot {
  const distance = Math.hypot(tx - x, tz - z);
  if (distance <= metres) return [tx, tz];
  return [
    x + ((tx - x) * metres) / distance,
    z + ((tz - z) * metres) / distance,
  ];
}

function isNight(tick: number) {
  const minute = (START_MINUTE + tick) % DAY_MINUTES;
  return minute >= NIGHT.from || minute < NIGHT.to;
}

function isDark(tick: number) {
  const minute = (START_MINUTE + tick) % DAY_MINUTES;
  return minute >= DARK.from || minute < DARK.to;
}

const ACTIONS: Partial<Record<Activity, string>> = {
  walking: 'walk_to',
  gathering: 'gather',
  working: 'work',
  eating: 'eat',
  drinking: 'drink',
  talking: 'say',
  resting: 'rest',
  sleeping: 'sleep',
};

const actionOf = (activity: Activity) => ACTIONS[activity] ?? null;

declare global {
  interface Window {
    /** DEV/TEST ONLY: the mock live server of `?mockLive=1`. */
    __pebbleMockLive?: MockLiveServer;
  }
}
