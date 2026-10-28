/*
 * DEV/TEST ONLY: a deterministic stand-in for the engine's live feed (`?mockLive=1`). Fifteen citizens with the
 * 15 look ids live around the town and the two camps of whatever world is loaded: they work, gather, eat, drink,
 * rest, talk (emitting `said` events) and walk between spots at the engine's pace (5 km/h = 83 m per tick).
 * Messages have the contract's shapes; sockets are fake WebSockets driven by the same tick loop, so the client's
 * connect / reconnect path is the one the real feed uses. `window.__pebbleMockLive` lets tests drop connections
 * and make someone speak.
 */
import { Vector3 } from 'three';

import type {
  Activity,
  LiveCitizen,
  LiveEventMessage,
  LiveFrame,
  LiveMessage,
} from './live-contract';
import type { Site, WorldView } from '@/lib/client/types.gen';
import { CITIZEN_LOOKS } from '@/lib/world/citizen-looks';
import {
  anchorMapping,
  latLonFromDirection,
  type SiteMapping,
} from '@/lib/world/globe';

/** The engine's walking pace (backend `WALK_M_PER_TICK`), metres per tick. */
const WALK_M_PER_TICK = 5000 / 60;
/** Tick 0 is 08:00 on day 0, one tick per game minute (backend `app/sim/clock.py`). */
const START_MINUTE = 8 * 60;
const DAY_MINUTES = 24 * 60;
const NIGHT = { from: 22 * 60, to: 5 * 60 };

type Spot = [number, number];

type Step =
  | { walk: Spot; to: string }
  | {
      activity: Exclude<Activity, 'walking' | 'dead'>;
      label?: string;
      ticks: number;
      say?: string;
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
    home: [-78, 93],
    plan: [
      { activity: 'working', label: 'weaving at the loom', ticks: 14 },
      { walk: [-24, 54], to: 'the well' },
      { activity: 'drinking', label: 'the well', ticks: 4 },
      { walk: [-78, 93], to: 'home' },
      { activity: 'eating', label: 'a bowl of rice', ticks: 6 },
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
    home: [0, 3],
    plan: [
      { activity: 'idle', label: 'the courtyard', ticks: 10 },
      { activity: 'resting', label: 'the courtyard', ticks: 10 },
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
    home: [1.8, 1.6],
    plan: [
      { activity: 'resting', label: 'the fire pit', ticks: 8 },
      { walk: [32, 24], to: 'the thicket' },
      { activity: 'gathering', label: 'firewood', ticks: 8 },
      { walk: [1.8, 1.6], to: 'camp' },
      {
        activity: 'talking',
        label: 'Mena',
        ticks: 4,
        say: 'The berries by the thicket are ripe again.',
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
    home: [-1.6, -1.8],
    plan: [
      { activity: 'resting', label: 'the fire pit', ticks: 6 },
      { activity: 'eating', label: 'roasted roots', ticks: 5 },
      { walk: [-24, 18], to: 'the root patch' },
      { activity: 'gathering', label: 'roots', ticks: 10 },
      { walk: [-1.6, -1.8], to: 'camp' },
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
    home: [1.8, 1.6],
    plan: [
      {
        activity: 'talking',
        label: 'Sela',
        ticks: 4,
        say: 'We move to the hills when the nuts are gone.',
      },
      { walk: [28, 30], to: 'the nut trees' },
      { activity: 'gathering', label: 'nuts', ticks: 9 },
      { walk: [1.8, 1.6], to: 'camp' },
      { activity: 'resting', label: 'the fire pit', ticks: 6 },
    ],
  },
  {
    id: 'sela',
    name: 'Sela',
    look: 'band-b-mother',
    appearance: 'a woman with a baby sling',
    site: 'band_b_camp',
    pace: 1,
    home: [-1.6, -1.8],
    plan: [
      { activity: 'resting', label: 'the fire pit', ticks: 5 },
      { activity: 'eating', label: 'dried fish', ticks: 5 },
      { walk: [-26, 20], to: 'the berry bushes' },
      { activity: 'gathering', label: 'berries', ticks: 8 },
      { walk: [-1.6, -1.8], to: 'camp' },
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
    home: [0, -5],
    plan: [
      { activity: 'sleeping', label: 'the lean-to', ticks: 12 },
      { activity: 'idle', label: 'camp', ticks: 4 },
      { walk: [8, 8], to: 'the drying rack' },
      { activity: 'gathering', label: 'sticks', ticks: 5 },
      { walk: [0, -5], to: 'the lean-to' },
    ],
  },
];

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

export interface MockClock {
  speed: number;
  paused: boolean;
}

export class MockLiveServer {
  readonly runId = 'mock-run';
  /** Like a new engine run: tick 0 is 08:00 on day 0. */
  private tick = 0;
  private clock: MockClock = { speed: 1, paused: false };
  private timer: ReturnType<typeof setInterval> | null = null;
  private sockets = new Set<MockSocket>();
  private states: PersonState[];
  private events = 0;
  private pending: LiveEventMessage[] = [];
  /** Connections so far (tests read it to see a reconnect). */
  connects = 0;

  constructor(world: WorldView) {
    const sites = new Map<string, Site>(
      world.sites.map((site) => [site.id, site]),
    );
    this.states = PEOPLE.map((person) => {
      const site = sites.get(person.site);
      if (!site) throw new Error(`the world has no ${person.site} site`);
      return {
        person,
        mapping: anchorMapping(site.anchor, world.radius_m),
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
      citizens: this.citizens(),
    };
  }

  connect(): LiveSocket {
    const socket = new MockSocket(this);
    this.sockets.add(socket);
    this.connects += 1;
    setTimeout(() => {
      if (!this.sockets.has(socket)) return;
      socket.onopen?.();
      socket.deliver(this.frame('snapshot'));
    }, 0);
    this.schedule();
    return socket;
  }

  setClock(change: Partial<MockClock>) {
    this.clock = { ...this.clock, ...change };
    this.schedule();
  }

  /** Someone says something right now (tests): the `said` event goes out at once. */
  sayNow(actor: string, words: string) {
    this.say(actor, words);
    const events = this.pending.splice(0);
    for (const socket of this.sockets)
      events.forEach((event) => socket.deliver(event));
  }

  /** Simulates the server going away: every open socket closes abnormally. */
  dropConnections() {
    for (const socket of [...this.sockets]) this.detach(socket, 1006);
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

  private schedule() {
    this.stop();
    if (this.clock.paused || this.sockets.size === 0) return;
    this.timer = setInterval(() => this.step(), 1000 / this.clock.speed);
  }

  private step() {
    this.tick += 1;
    const night = isNight(this.tick);
    for (const state of this.states) this.advance(state, night);
    const frame = this.frame('tick');
    const events = this.pending.splice(0);
    for (const socket of this.sockets) {
      socket.deliver(frame);
      events.forEach((event) => socket.deliver(event));
    }
  }

  private advance(state: PersonState, night: boolean) {
    if (night) return;
    const { plan } = state.person;
    const step = plan[state.step];
    if ('walk' in step) {
      const [tx, tz] = step.walk;
      const [x, z] = state.at;
      const distance = Math.hypot(tx - x, tz - z);
      const reach = WALK_M_PER_TICK * state.person.pace;
      if (distance > 1e-6)
        state.heading = (Math.atan2(tx - x, tz - z) * 180) / Math.PI;
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
    if ('say' in step && step.say) this.say(state.person.id, step.say);
  }

  private say(actor: string, words: string) {
    this.events += 1;
    this.pending.push({
      type: 'event',
      run_id: this.runId,
      tick: this.tick,
      event: {
        id: `mock-said-${this.events}`,
        type: 'said',
        actor_id: actor,
        payload: { words, volume: 'normal', heard_by: [] },
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
      citizens: this.citizens(),
    };
  }

  private citizens(): LiveCitizen[] {
    const night = isNight(this.tick);
    return this.states.map((state) => {
      const { person } = state;
      const step = person.plan[state.step];
      const look = ROLES.get(person.look);
      if (!look) throw new Error(`unknown look ${person.look}`);
      const unit = state.mapping
        .toWorld(state.at[0], 0, state.at[1], new Vector3())
        .normalize();
      const { lat, lon } = latLonFromDirection(unit);
      const activity: Activity = night
        ? 'sleeping'
        : 'walk' in step
          ? 'walking'
          : step.activity;
      return {
        id: person.id,
        name: person.name,
        look: person.look,
        appearance: person.appearance,
        position: { unit: unit.toArray(), height_m: state.height, lat, lon },
        cell: 0,
        alive: true,
        asleep: activity === 'sleeping',
        action: actionOf(activity),
        action_label: night
          ? ''
          : 'walk' in step
            ? step.to
            : (step.label ?? ''),
        state: [],
        cause_of_death: null,
        heading_deg: state.heading,
        activity,
        role: look.role,
        region: look.region,
      };
    });
  }
}

const stepTicks = (step: Step) => ('walk' in step ? 0 : step.ticks);

function isNight(tick: number) {
  const minute = (START_MINUTE + tick) % DAY_MINUTES;
  return minute >= NIGHT.from || minute < NIGHT.to;
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
