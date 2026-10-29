import type { AnimalKind } from '../../src/lib/world/assets';

export const SPEEDS: Partial<Record<AnimalKind, [number, number]>> = {
  deer: [1.0, 11],
  elk: [1.1, 10],
  antelope: [1.1, 13],
  rabbit: [0.5, 9],
  hare: [0.5, 9],
  boar: [0.8, 8],
  goat: [0.8, 7],
  duck: [0.4, 2],
  fox: [0.9, 9],
  wolf: [1.2, 10],
  bear: [1.0, 11],
  polar_bear: [1.0, 10],
  lion: [1.0, 12],
};
