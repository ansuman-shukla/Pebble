import type { CitizenSummary } from '@/lib/client/types.gen';

export type Region = CitizenSummary['region'];
export type Activity = CitizenSummary['activity'];

export const REGION_NAMES: Record<Region, string> = {
  town: 'Castle town',
  band_a: 'Band A',
  band_b: 'Band B',
};

/** Order of the people list: town first, then the two bands. */
export const REGION_ORDER: Region[] = ['town', 'band_a', 'band_b'];

/** "working · tending the rice paddies", "asleep", "dead (dehydration)" */
export function doingWords(citizen: {
  activity: Activity;
  action_label: string;
  cause_of_death?: string | null;
}): string {
  if (citizen.activity === 'dead')
    return citizen.cause_of_death ? `dead (${citizen.cause_of_death})` : 'dead';
  const label =
    citizen.action_label === 'your home' ? 'home' : citizen.action_label;
  return label ? `${citizen.activity} · ${label}` : citizen.activity;
}

export type Need = 'hunger' | 'thirst' | 'energy' | 'health';

export const NEED_COLORS: Record<Need, string> = {
  hunger: '#d97706',
  thirst: '#0284c7',
  energy: '#65a30d',
  health: '#dc2626',
};
