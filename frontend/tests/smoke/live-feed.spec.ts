import { expect, test } from '@playwright/test';
import { Vector3 } from 'three';

import type {
  LiveAnimal,
  LiveCitizen,
  LiveFire,
  LiveFrame,
} from '../../src/lib/live/live-contract';
import {
  applyEntities,
  applyMessage,
  EMPTY_LIVE,
  feedMinutes,
  pruneSpeech,
  SPEECH_MS,
  speedWords,
} from '../../src/lib/live/live-state';
import { MockLiveServer } from '../../src/lib/live/mock-live';
import { activityWords, npcLook } from '../../src/lib/live/npc-activity';
import { advance, citizenPath, pointAt } from '../../src/lib/live/walk-path';
import { CITIZEN_LOOKS } from '../../src/lib/world/citizen-looks';
import { directionFromLatLon } from '../../src/lib/world/globe';
import { createMockWorld } from '../../src/lib/world/mock-world';

/*
 * The live feed without a browser: the frame/event reducer, how activities show, and the mock feed.
 */

const AT = directionFromLatLon(35, 12);

function entity(overrides: Partial<LiveCitizen> = {}): LiveCitizen {
  return {
    id: 'dev-genzo',
    name: 'Genzo',
    look: 'town-farmer',
    appearance: 'a broad man in a straw hat',
    role: 'Rice farmer',
    region: 'town',
    heading_deg: 0,
    route: [],
    speed_mps: 0,
    activity: 'idle',
    position: { unit: AT.toArray(), height_m: 8, lat: 35, lon: 12 },
    cell: 1,
    alive: true,
    asleep: false,
    action: null,
    action_label: '',
    state: [],
    cause_of_death: null,
    ...overrides,
  };
}

function frame(
  type: LiveFrame['type'],
  tick: number,
  citizens: LiveCitizen[],
  run = 'run-1',
  wild: Pick<LiveFrame, 'animals' | 'fires'> = { animals: [], fires: [] },
): LiveFrame {
  return {
    type,
    run_id: run,
    tick,
    day: 0,
    time: '08:00',
    speed: 1,
    paused: false,
    citizens,
    ...wild,
  };
}

const said = (id: string, actor: string, words: unknown, run = 'run-1') => ({
  type: 'event' as const,
  run_id: run,
  tick: 3,
  event: { id, type: 'said', actor_id: actor, payload: { words } },
});

test('frames replace the citizens; stale ticks are ignored; a snapshot or a new run resyncs', () => {
  const genzo = entity();
  const walking = { ...genzo, activity: 'walking' as const };
  let state = applyMessage(EMPTY_LIVE, frame('snapshot', 5, [genzo]), 0);
  expect(state.tick).toBe(5);
  expect(state.citizens[0].activity).toBe('idle');
  state = applyMessage(state, frame('tick', 6, [walking]), 0);
  expect(state.citizens[0].activity).toBe('walking');
  // an older tick of the same run changes nothing
  expect(applyMessage(state, frame('tick', 4, [genzo]), 0)).toBe(state);
  // the extra tick of a speed or pause change (same tick) only changes the clock
  const paused = applyMessage(
    state,
    { ...frame('tick', 6, [genzo]), speed: 10, paused: true },
    0,
  );
  expect(paused).toMatchObject({ tick: 6, speed: 10, paused: true });
  expect(paused.citizens).toBe(state.citizens);
  // a snapshot always resyncs, even to an earlier tick
  expect(applyMessage(state, frame('snapshot', 4, [genzo]), 0).tick).toBe(4);
  // a new run starts over, dropping old speech
  state = applyMessage(state, said('e1', genzo.id, 'Hello'), 0);
  expect(state.speech).toHaveLength(1);
  const fresh = applyMessage(state, frame('tick', 1, [genzo], 'run-2'), 0);
  expect(fresh.runId).toBe('run-2');
  expect(fresh.tick).toBe(1);
  expect(fresh.speech).toEqual([]);
  // the entities answer: same rules
  const answer = {
    run_id: 'run-1',
    tick: 6,
    day: 0,
    time: '08:06',
    animals: [],
    fires: [],
  };
  expect(applyEntities(state, { ...answer, citizens: [entity()] })).toBe(state);
  const later = applyEntities(state, {
    ...answer,
    tick: 7,
    citizens: [entity({ action: 'eat', activity: 'eating' })],
  });
  expect(later.citizens[0].activity).toBe('eating');
});

test('frames carry the animals and the fires', () => {
  const deer: LiveAnimal = {
    id: 'deer:1',
    kind: 'deer',
    group: 'deer-group:1',
    position: { unit: [AT.x, AT.y, AT.z], height_m: 10, lat: 35, lon: 12 },
    heading_deg: 90,
    activity: 'grazing',
  };
  const pit: LiveFire = {
    id: 'band_a_camp:fire-pit',
    kind: 'pit',
    position: deer.position,
    lit: true,
    strength: 1,
  };
  let state = applyMessage(
    EMPTY_LIVE,
    frame('snapshot', 1, [], 'run-1', { animals: [deer], fires: [pit] }),
    0,
  );
  expect(state.animals).toEqual([deer]);
  expect(state.fires).toEqual([pit]);
  const running = { ...deer, activity: 'running' as const };
  const out = { ...pit, lit: false, strength: 0 };
  state = applyMessage(
    state,
    frame('tick', 2, [], 'run-1', { animals: [running], fires: [out] }),
    0,
  );
  expect(state.animals[0].activity).toBe('running');
  expect(state.fires[0].lit).toBe(false);
  expect(applyMessage(state, frame('tick', 1, []), 0)).toBe(state); // stale
});

test('the mock feed has grazing deer, prowling wolves and fires that burn at night', () => {
  const server = new MockLiveServer(createMockWorld());
  const first = server.entities();
  expect(new Set(first.animals.map((a) => a.kind))).toEqual(
    new Set(['deer', 'fox', 'wolf']),
  );
  const lit = (fires: LiveFire[]) =>
    fires.filter((fire) => fire.lit).map((fire) => fire.id);
  expect(lit(first.fires)).toEqual([
    'band_a_camp:fire-pit',
    'band_b_camp:fire-pit',
  ]); // 08:00: the gate baskets are out
  expect(
    first.animals.filter((a) => a.kind === 'wolf').map((a) => a.activity),
  ).toEqual(['sleeping', 'sleeping']);
});

test('said events become speech that expires after a few seconds', () => {
  let state = applyMessage(EMPTY_LIVE, frame('snapshot', 1, [entity()]), 0);
  state = applyMessage(
    state,
    said('e1', 'dev-genzo', 'Good rice this year'),
    1000,
  );
  state = applyMessage(
    state,
    said('e1', 'dev-genzo', 'Good rice this year'),
    1100,
  );
  state = applyMessage(state, said('e2', 'dev-genzo', 42), 1200);
  state = applyMessage(state, said('e3', 'dev-genzo', 'Hi', 'other-run'), 1300);
  expect(state.speech).toEqual([
    {
      id: 'e1',
      actorId: 'dev-genzo',
      words: 'Good rice this year',
      at: 1000,
    },
  ]);
  expect(pruneSpeech(state, 1000 + SPEECH_MS - 1)).toBe(state);
  expect(pruneSpeech(state, 1000 + SPEECH_MS).speech).toEqual([]);
});

test('feed time in game minutes since day 0', () => {
  expect(feedMinutes({ day: 0, time: '08:00' })).toBe(480);
  expect(feedMinutes({ day: 2, time: '23:59' })).toBe(2 * 1440 + 23 * 60 + 59);
});

test('activities pick their clip and pose', () => {
  const look = (activity: LiveCitizen['activity'], label = '') =>
    npcLook({ activity, action_label: label });
  expect(look('idle')).toEqual({
    clip: 'Idle',
    pose: 'standing',
    still: false,
  });
  expect(look('walking').clip).toBe('Walk');
  expect(look('eating').clip).toBe('Eating');
  expect(look('drinking').clip).toBe('Drinking');
  expect(look('talking').clip).toBe('Talking');
  expect(look('resting')).toEqual({
    clip: 'Sitting',
    pose: 'sitting',
    still: false,
  });
  expect(look('sleeping')).toEqual({
    clip: 'Idle',
    pose: 'sleeping',
    still: true, // no idle sway lying down
  });
  expect(look('dead')).toEqual({ clip: 'Idle', pose: 'lying', still: true });
  // the engine's work tasks
  expect(look('working', 'tending the rice paddies').clip).toBe('Harvesting');
  expect(look('working', 'filling the storehouse').clip).toBe('Pick up');
  expect(look('working', 'keeping watch').clip).toBe('Arms folded');
  expect(look('working', 'trading at the market').clip).toBe('Talking');
  expect(look('working', 'weaving at the loom').clip).toBe('Fixing');
  expect(look('working', 'holding court').clip).toBe('Talking');
  expect(look('working', 'planting the seed beds').clip).toBe('Planting');
  expect(look('working', 'chopping firewood').clip).toBe('Chopping wood');
  expect(look('gathering', 'firewood').clip).toBe('Pick up');
  expect(look('gathering', 'roots').clip).toBe('Pick up');
  expect(look('gathering', 'berries').clip).toBe('Harvesting');
});

test('activities in words', () => {
  const words = (
    activity: LiveCitizen['activity'],
    label = '',
    cause: string | null = null,
  ) => activityWords({ activity, action_label: label, cause_of_death: cause });
  expect(words('working', 'tending the rice paddies')).toBe(
    'tending the rice paddies',
  );
  expect(words('working')).toBe('working');
  expect(words('walking', 'the well')).toBe('walking to the well');
  expect(words('walking', 'to the north')).toBe('walking to the north');
  expect(words('walking', 'home')).toBe('walking home');
  expect(words('walking')).toBe('walking');
  expect(words('drinking', 'the well')).toBe('drinking at the well');
  expect(words('sleeping', 'the lean-to')).toBe('asleep');
  expect(words('dead', '', 'thirst')).toBe('dead (thirst)');
});

test('the mock feed has the 22 citizens around their home sites', () => {
  const world = createMockWorld();
  const server = new MockLiveServer(world);
  const answer = server.entities();
  expect(answer.tick).toBe(0);
  expect(answer.time).toBe('08:00');
  expect(answer.citizens.map((citizen) => citizen.look).sort()).toEqual(
    CITIZEN_LOOKS.map((look) => look.id).sort(),
  );
  const sites = new Map(world.sites.map((site) => [site.id, site]));
  const home = { town: 'town', band_a: 'band_a_camp', band_b: 'band_b_camp' };
  for (const citizen of answer.citizens) {
    const site = sites.get(home[citizen.region])!;
    const metres =
      new Vector3(...citizen.position.unit).angleTo(
        new Vector3(...site.anchor.position),
      ) * world.radius_m;
    expect(metres).toBeLessThan(citizen.region === 'town' ? 160 : 40);
  }
});

test('the clock speed in words', () => {
  expect(speedWords({ speed: 1, paused: false })).toBe('real time');
  expect(speedWords({ speed: 60, paused: false })).toBe('×60');
  expect(speedWords({ speed: 600, paused: true })).toBe('paused');
});

test('the mock feed streams each move like the engine: from where it stood, timed, ending where the next starts', async () => {
  const world = createMockWorld();
  const server = new MockLiveServer(world);
  server.setClock({ speed: 600 }); // a tick every 0.1 s
  const frames: LiveFrame[] = [];
  const socket = server.connect();
  socket.onmessage = ({ data }) => {
    const message = JSON.parse(data) as LiveFrame;
    if (message.type === 'tick') frames.push(message);
  };
  await new Promise((done) => setTimeout(done, 2_500));
  socket.close();
  server.stop();

  const metresApart = (a: number[], b: number[]) =>
    new Vector3(...a).angleTo(new Vector3(...b)) * world.radius_m;
  let moves = 0;
  for (const [k, frame] of frames.slice(1).entries()) {
    const last = frames[k];
    expect(frame.tick).toBe(last.tick + 1);
    for (const citizen of frame.citizens) {
      const before = last.citizens.find(({ id }) => id === citizen.id)!;
      if (metresApart(citizen.position.unit, before.position.unit) < 1e-6) {
        expect([citizen.route, citizen.speed_mps]).toEqual([[], 0]);
        continue;
      }
      moves += 1;
      // drawn from where it stood a tick ago, at 5 km/h × pace (elders 0.6), reaching where it is a tick later
      expect(citizen.route[0].unit).toEqual(before.position.unit);
      expect(citizen.route[0].t_s).toBe(0);
      expect(citizen.speed_mps).toBeGreaterThan(0.8);
      expect(citizen.speed_mps).toBeLessThan(1.4);
      const path = citizenPath(citizen, world.radius_m);
      advance(path, 60);
      const metres = metresApart(
        pointAt(path, new Vector3()).toArray(),
        citizen.position.unit,
      );
      expect(metres, `${citizen.id} at tick ${frame.tick}`).toBeLessThan(0.01);
    }
  }
  expect(moves).toBeGreaterThan(5);
});
