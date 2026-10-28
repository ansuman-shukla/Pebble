/*
 * The player: a traveller from outside the 15 citizens, in a plain outfit that reads in any era of the world
 * (undyed tunic, pants, straw hat, sandals, a shoulder bag).
 */
import type { CharacterConfig } from '@/vendor/polyfork/humanoid.mjs';

export const VISITOR_LOOK: CharacterConfig = {
  age: 'adult',
  figure: 'masculine',
  build: 1.0,
  palette: {
    straw: 0xd9c89a,
    tunic: 0x8a7a5e,
    cuff: 0x8a7a5e,
    belt: 0x544537,
    denim: 0x5c564c,
    sole: 0x9c825c,
    skin: 0xc49a72,
    hair: 0x3a2c22,
  },
  wear: {
    hair: { name: 'cropped-hair', sideburns: 'short', low: 0.14, cap: true },
    hat: 'straw-hat',
    top: {
      name: 'tunic',
      length: 'thigh',
      sleeve: 'elbow',
      neck: 'slit',
      belt: true,
      beltAt: 'low',
    },
    bottom: { name: 'pants', crop: 0.3, band: false },
    feet: 'waraji',
    back: 'shoulder-bag',
  },
};
