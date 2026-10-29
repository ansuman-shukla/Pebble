import { expect, test } from '@playwright/test';

import type { Doing } from '../../src/lib/live/drawn-track';
import type { LiveCitizen } from '../../src/lib/live/live-contract';
import { citizenLabels } from '../../src/lib/world/citizen-labels';

/* What the globe's citizen chips and bubbles say (no browser). */

/** No body has shown anything yet: chips go by the feed. */
const NOTHING_SHOWN = new Map<string, Doing>();

function citizen(overrides: Partial<LiveCitizen> = {}): LiveCitizen {
  return {
    id: 'genzo',
    name: 'Genzo',
    look: 'town-farmer',
    appearance: 'a broad man in a straw hat',
    role: 'Rice farmer',
    region: 'town',
    heading_deg: 0,
    route: [],
    speed_mps: 0,
    activity: 'working',
    position: { unit: [0, 0, 1], height_m: 8, lat: 35, lon: 12 },
    cell: 1,
    alive: true,
    asleep: false,
    action: 'work',
    action_label: 'tending the rice paddies',
    state: [],
    cause_of_death: null,
    motion: 'farm',
    posture: 'standing',
    slot_heading: null,
    goal: '',
    driver: null,
    target: null,
    needs: { hunger: 10, thirst: 10, energy: 90, health: 100 },
    carrying: {},
    coins: 0,
    rank: null,
    standing: null,
    titles: [],
    ...overrides,
  };
}

const ringOf = (state: string[]) =>
  citizenLabels([citizen({ state })], NOTHING_SHOWN, [])[0].ring;

test('a chip names the citizen, says what they do and shows its icon', () => {
  expect(citizenLabels([citizen()], NOTHING_SHOWN, [])).toEqual([
    {
      id: 'npc-genzo',
      subject: 'genzo',
      kind: 'name',
      text: 'Genzo',
      detail: 'tending the rice paddies',
      icon: 'work',
      ring: undefined,
    },
  ]);
  const walking = citizen({ activity: 'walking', action_label: 'the well' });
  expect(citizenLabels([walking], NOTHING_SHOWN, [])[0].detail).toBe(
    'walking to the well',
  );
  const icons = (
    [
      ['idle', 'stand'],
      ['walking', 'walk'],
      ['running', 'run'],
      ['sleeping', 'sleep'],
      ['resting', 'rest'],
      ['gathering', 'gather'],
      ['eating', 'eat'],
      ['drinking', 'drink'],
      ['hunting', 'hunt'],
      ['fishing', 'fish'],
      ['tending_fire', 'fire'],
      ['talking', 'talk'],
      ['dead', 'dead'],
    ] as const
  ).map(
    ([activity]) =>
      citizenLabels([citizen({ activity })], NOTHING_SHOWN, [])[0].icon,
  );
  expect(icons).toEqual([
    'stand',
    'walk',
    'run',
    'sleep',
    'rest',
    'gather',
    'eat',
    'drink',
    'hunt',
    'fish',
    'fire',
    'talk',
    'dead',
  ]);
});

test('a chip tells what the drawn body is shown doing, not what the feed already says', () => {
  // Pip's tick says she sleeps, but her drawn body still walks home (D100)
  const pip = citizen({
    id: 'pip',
    name: 'Pip',
    activity: 'sleeping',
    action_label: '',
    state: ['hungry'],
  });
  const walkingHome = new Map<string, Doing>([
    [
      'pip',
      { activity: 'walking', action_label: 'home', cause_of_death: null },
    ],
  ]);
  expect(citizenLabels([pip], walkingHome, [])).toEqual([
    {
      id: 'npc-pip',
      subject: 'pip',
      kind: 'name',
      text: 'Pip',
      detail: 'walking home',
      icon: 'walk',
      ring: 'need',
    },
  ]);
  // someone else's held walk leaves her chip alone
  const elsewhere = new Map<string, Doing>([
    ['genzo', walkingHome.get('pip')!],
  ]);
  expect(citizenLabels([pip], elsewhere, [])[0]).toMatchObject({
    detail: 'asleep',
    icon: 'sleep',
  });
});

test('hungry or thirsty rings orange, hurt rings red and wins, mild words ring nothing', () => {
  expect(ringOf([])).toBeUndefined();
  expect(
    ringOf(['a little hungry', 'a little thirsty', 'tired']),
  ).toBeUndefined();
  expect(ringOf(['a little weak'])).toBeUndefined();
  expect(ringOf(['hungry'])).toBe('need');
  expect(ringOf(['starving'])).toBe('need');
  expect(ringOf(['thirsty'])).toBe('need');
  expect(ringOf(['terribly thirsty'])).toBe('need');
  expect(ringOf(['weak and aching'])).toBe('hurt');
  expect(ringOf(['starving', 'close to death'])).toBe('hurt');
});

test('each speaker gets one bubble with their latest words, over their own anchor', () => {
  const labels = citizenLabels(
    [citizen(), citizen({ id: 'hana', name: 'Hana' })],
    NOTHING_SHOWN,
    [
      { id: 'e1', actorId: 'hana', words: 'Good morning!', at: 1 },
      { id: 'e2', actorId: 'genzo', words: 'Rain soon.', at: 2 },
      { id: 'e3', actorId: 'hana', words: 'Father, look!', at: 3 },
    ],
  );
  expect(labels.filter((label) => label.kind === 'speech')).toEqual([
    { id: 'say-hana', subject: 'hana', kind: 'speech', text: 'Father, look!' },
    { id: 'say-genzo', subject: 'genzo', kind: 'speech', text: 'Rain soon.' },
  ]);
});
