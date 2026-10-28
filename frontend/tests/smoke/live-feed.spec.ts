import { expect, test } from '@playwright/test';
import { Vector3 } from 'three';

import type { CitizenEntity } from '../../src/lib/client/types.gen';
import {
  type LiveCitizen,
  type LiveFrame,
  normalizeCitizen,
} from '../../src/lib/live/live-contract';
import {
  applyEntities,
  applyMessage,
  EMPTY_LIVE,
  feedMinutes,
  pruneSpeech,
  SPEECH_MS,
} from '../../src/lib/live/live-state';
import { MockLiveServer } from '../../src/lib/live/mock-live';
import { activityWords, npcLook } from '../../src/lib/live/npc-activity';
import { CITIZEN_LOOKS } from '../../src/lib/world/citizen-looks';
import { directionFromLatLon, tangentFrame } from '../../src/lib/world/globe';
import { createMockWorld } from '../../src/lib/world/mock-world';

/*
 * The live feed without a browser: entities entering the client (the contract's fallbacks while the backend
 * doesn't send the new fields yet), the frame/event reducer, how activities show, and the mock feed.
 */

const AT = directionFromLatLon(35, 12);

function entity(overrides: Partial<CitizenEntity> = {}): CitizenEntity {
  return {
    id: 'dev-genzo',
    name: 'Genzo',
    look: 'town-farmer',
    appearance: 'a broad man in a straw hat',
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
  };
}

const said = (id: string, actor: string, words: unknown, run = 'run-1') => ({
  type: 'event' as const,
  run_id: run,
  tick: 3,
  event: { id, type: 'said', actor_id: actor, payload: { words } },
});

test("today's entities get an activity, role, region and heading", () => {
  const plain = normalizeCitizen(entity());
  expect(plain).toMatchObject({
    activity: 'idle',
    role: 'Rice farmer',
    region: 'town',
    heading_deg: 0,
  });
  expect(normalizeCitizen(entity({ action: 'walk_to' })).activity).toBe(
    'walking',
  );
  expect(normalizeCitizen(entity({ action: 'gather' })).activity).toBe(
    'gathering',
  );
  expect(normalizeCitizen(entity({ action: 'no_such_thing' })).activity).toBe(
    'idle',
  );
  expect(
    normalizeCitizen(entity({ asleep: true, action: 'walk_to' })).activity,
  ).toBe('sleeping');
  expect(
    normalizeCitizen(entity({ alive: false, asleep: true })).activity,
  ).toBe('dead');
  // fields the backend sends win
  const sent = {
    ...entity(),
    activity: 'eating',
    role: 'Cook',
    region: 'band_a',
    heading_deg: 42,
  };
  expect(normalizeCitizen(sent as never)).toMatchObject({
    activity: 'eating',
    role: 'Cook',
    region: 'band_a',
    heading_deg: 42,
  });
});

test('without a heading a citizen faces the way it moved (0 = south, 180 = north)', () => {
  const before = normalizeCitizen(entity());
  const { north, east } = tangentFrame(AT);
  const moved = (step: Vector3) => {
    const unit = AT.clone().multiplyScalar(2000).add(step).normalize();
    return normalizeCitizen(
      entity({ position: { ...before.position, unit: unit.toArray() } }),
      before,
    ).heading_deg;
  };
  expect(moved(north.clone().multiplyScalar(5))).toBeCloseTo(180, 3);
  expect(moved(north.clone().multiplyScalar(-5))).toBeCloseTo(0, 3);
  expect(moved(east.clone().multiplyScalar(5))).toBeCloseTo(90, 3);
  // standing still keeps the previous heading
  const turned = { ...before, heading_deg: 77 };
  expect(normalizeCitizen(entity(), turned).heading_deg).toBe(77);
});

test('frames replace the citizens; stale ticks are ignored; a snapshot or a new run resyncs', () => {
  const genzo = normalizeCitizen(entity());
  const walking = { ...genzo, activity: 'walking' as const };
  let state = applyMessage(EMPTY_LIVE, frame('snapshot', 5, [genzo]), 0);
  expect(state.tick).toBe(5);
  expect(state.citizens[0].activity).toBe('idle');
  state = applyMessage(state, frame('tick', 6, [walking]), 0);
  expect(state.citizens[0].activity).toBe('walking');
  // an older tick of the same run changes nothing
  expect(applyMessage(state, frame('tick', 4, [genzo]), 0)).toBe(state);
  expect(applyMessage(state, frame('tick', 6, [genzo]), 0)).toBe(state);
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
  const answer = { run_id: 'run-1', tick: 6, day: 0, time: '08:06' };
  expect(applyEntities(state, { ...answer, citizens: [entity()] })).toBe(state);
  const later = applyEntities(state, {
    ...answer,
    tick: 7,
    citizens: [entity({ action: 'eat' })],
  });
  expect(later.citizens[0].activity).toBe('eating');
});

test('said events become speech that expires after a few seconds', () => {
  let state = applyMessage(
    EMPTY_LIVE,
    frame('snapshot', 1, [normalizeCitizen(entity())]),
    0,
  );
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
    pose: 'lying',
    still: false,
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
  expect(words('walking')).toBe('walking');
  expect(words('drinking', 'the well')).toBe('drinking at the well');
  expect(words('sleeping', 'the lean-to')).toBe('asleep');
  expect(words('dead', '', 'thirst')).toBe('dead (thirst)');
});

test('the mock feed has the 15 citizens around their home sites', () => {
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
