/*
 * How each of the 22 citizens looks, as configs for Polyfork's shared humanoid engine.
 * Town looks follow the Medieval Japan kit's own characters (the monk, the night watch and the farmers and
 * craftsmen of World v1 build on `kit-looks.ts`); the Stone Age bands are new outfits built from the engine's
 * wardrobe (hide tunics, fur stoles, long hair, bare feet, spears). Ids are referenced by the citizens spec;
 * roles follow docs/design/10-world-v1.md §3.1.
 */
import { KIT_LOOKS } from './kit-looks';
import type { CharacterConfig, Garment } from '@/vendor/polyfork/humanoid.mjs';

export type Region = 'town' | 'band_a' | 'band_b';

export interface CitizenLook {
  id: string;
  region: Region;
  role: string;
  config: CharacterConfig;
}

const SKIN = {
  fair: 0xd8b48e,
  warm: 0xd3ac85,
  olive: 0xb88a62,
  tan: 0xa8764e,
  brown: 0x8a5a3c,
  deep: 0x6e4630,
};
const HAIR = {
  black: 0x221e1c,
  brown: 0x4a3728,
  auburn: 0x6b3a22,
  dark: 0x2e2420,
};

// ---- town -------------------------------------------------------------------------------------

const cropped: Garment = {
  name: 'cropped-hair',
  sideburns: 'short',
  low: 0.14,
  cap: true,
};
const tunic = (length: string, sleeve: string): Garment => ({
  name: 'tunic',
  length,
  sleeve,
  neck: 'slit',
  belt: false,
});
const kimono = (length: string): Garment => ({
  name: 'coat',
  length,
  open: 0,
  encloses: true,
  sleeve: 'long',
  collar: true,
  lapel: 0.225,
  lapelW: 0.058,
  lapelGap: 0.03,
  lapelCross: 0.028,
  underCollar: 0.105,
  underCollarW: 0.26,
  sleeveEase: 0.085,
  sode: 0.06,
  sodeFrom: 0.1,
  sodeRise: 0.6,
  sodeW: 1.8,
  sodeBind: 'arm',
  vent: true,
  round: 0.8,
  pull: 1.0,
  hang: 0.28,
});
const obi = (swords: number, bow = false): Garment => ({
  name: 'obi',
  swords,
  knot: false,
  height: swords ? 0.07 : 0.15,
  drop: swords ? 0.012 : -0.13,
  cord: !swords,
  ...(bow && { bow: true, bowW: 0.215, bowH: 0.105, bowD: 0.034 }),
});
const lamellar = (
  length: number,
  extra: Record<string, unknown> = {},
): Garment => ({
  name: 'do-maru',
  length,
  tassets: 2,
  tassetShare: 0.12,
  cord: true,
  yoke: false,
  lace: false,
  kote: true,
  koteFrom: 0.02,
  ...extra,
});
const bun: Garment = {
  name: 'bun',
  knotUp: 0.5,
  knot: 1.55,
  knotOut: 1.25,
  knotBall: true,
  dome: 0.16,
};

const KIT_FARMER = KIT_LOOKS.farmer;

/** World v1's new town folk: the kit's monk and ashigaru, and the farmer base dressed for each trade. */
const TOWN_V1: CitizenLook[] = [
  {
    id: 'town-ashigaru',
    region: 'town',
    role: 'Ashigaru of the night watch',
    config: {
      ...KIT_LOOKS.ashigaru,
      figure: 'masculine',
      palette: {
        ...KIT_LOOKS.ashigaru.palette,
        skin: SKIN.olive,
        hair: HAIR.black,
      },
    },
  },
  {
    id: 'town-elder-farmer',
    region: 'town',
    role: 'Elder rice farmer',
    config: {
      ...KIT_FARMER,
      age: 'old',
      figure: 'masculine',
      build: 0.84,
      greyHair: true,
      palette: {
        ...KIT_FARMER.palette,
        straw: 0xa8915e,
        tunic: 0x6b5a45,
        shirt: 0x6b5a45,
        cuff: 0x6b5a45,
        belt: 0x2f3a36,
        denim: 0x7d6e58,
        skin: SKIN.tan,
      },
      wear: {
        hair: KIT_FARMER.wear.hair,
        top: {
          name: 'tunic',
          length: 'thigh',
          sleeve: 'long',
          neck: 'slit',
          belt: true,
          beltAt: 'low',
        },
        bottom: KIT_FARMER.wear.bottom,
        feet: 'waraji',
        hat: {
          name: 'jingasa',
          brim: 1.75,
          cone: 0.42,
          coneDrop: 0.02,
          cord: true,
        },
        face: 'goatee',
        righthand: 'cane',
      },
    },
  },
  {
    id: 'town-smith',
    region: 'town',
    role: 'Smith',
    config: {
      ...KIT_FARMER,
      figure: 'masculine',
      build: 1.15,
      palette: {
        ...KIT_FARMER.palette,
        tunic: 0x3e3a36,
        shirt: 0x3e3a36,
        cuff: 0x3e3a36,
        denim: 0x4a4440,
        apron: 0x5c4030,
        apronTie: 0x3b2a20,
        wrap: 0xe4ded0,
        skin: SKIN.tan,
        hair: HAIR.black,
      },
      wear: {
        hair: KIT_FARMER.wear.hair,
        hat: { name: 'headwrap' },
        face: 'moustache',
        top: { name: 'tunic', length: 'hip', sleeve: 'none', neck: 'slit' },
        coat: { name: 'apron', style: 'butcher', length: 'knee' },
        bottom: KIT_FARMER.wear.bottom,
        feet: 'waraji',
      },
    },
  },
  {
    id: 'town-digger',
    region: 'town',
    role: 'Iron-sand digger',
    config: {
      ...KIT_FARMER,
      figure: 'masculine',
      build: 0.82,
      palette: {
        ...KIT_FARMER.palette,
        straw: 0xd9c89a,
        tunic: 0x9c6b3a,
        shirt: 0x9c6b3a,
        cuff: 0x9c6b3a,
        belt: 0x3b3128,
        denim: 0x5a5048,
        pole: 0x8c7355,
        skin: SKIN.brown,
        hair: HAIR.black,
      },
      wear: {
        hair: KIT_FARMER.wear.hair,
        hat: { name: 'jingasa', brim: 1.15, cone: 0.55, coneDrop: 0.03 },
        face: 'stubble',
        top: {
          name: 'tunic',
          length: 'thigh',
          sleeve: 'none',
          neck: 'slit',
          belt: true,
          beltAt: 'low',
        },
        bottom: { name: 'pants', crop: 0.5, turnup: 0.06, band: false },
        feet: 'waraji',
        lefthand: 'shovel',
      },
    },
  },
  {
    id: 'town-monk',
    region: 'town',
    role: 'Monk of the temple',
    config: {
      ...KIT_LOOKS.buddhist_monk,
      figure: 'masculine',
      greyHair: true,
      palette: {
        ...KIT_LOOKS.buddhist_monk.palette,
        hair: 0x4a4642,
        brow: 0x3a3632,
        clipped: 0xb39477,
      },
      wear: { ...KIT_LOOKS.buddhist_monk.wear, hair: { name: 'buzz' } },
    },
  },
];

const TOWN: CitizenLook[] = [
  {
    id: 'town-lord',
    region: 'town',
    role: 'Lord of the castle',
    config: {
      age: 'old',
      figure: 'masculine',
      build: 1.05,
      palette: {
        coat: 0x4e5148,
        tunic: 0x4e5148,
        jinbaori: 0x8c2f2a,
        jinbaoriTrim: 0x3b3128,
        lamellar: 0x4e5148,
        plate: 0x4e5148,
        mon: 0xd9a441,
        denim: 0x8c7355,
        hose: 0x3b3128,
        sole: 0x544537,
        skin: SKIN.warm,
        hair: HAIR.brown,
      },
      wear: {
        hair: {
          name: 'cropped-hair',
          sideburns: 'short',
          low: 0.12,
          fringe: 0.05,
          cap: true,
        },
        top: tunic('hip', 'none'),
        coat: lamellar(0.78, { mon: 0.804, monAt: 0.5 }),
        bottom: { name: 'pants', band: false, crop: 0.28, hose: true },
        feet: { name: 'geta' },
        neck: {
          name: 'jinbaori',
          length: 'knee',
          skirtOpen: 'front',
          collarColour: 'coat',
        },
      },
    },
  },
  {
    id: 'town-samurai',
    region: 'town',
    role: 'Samurai retainer',
    config: {
      age: 'adult',
      figure: 'masculine',
      build: 0.95,
      palette: {
        tunic: 0x5f6c78,
        denim: 0x5a6268,
        hose: 0x5a6268,
        lamellar: 0x8a5a40,
        lace: 0xb8923a,
        plate: 0x7d5139,
        obi: 0xc8c0b0,
        saya: 0x2a2420,
        sole: 0xb9a17b,
        skin: SKIN.olive,
        hair: HAIR.black,
      },
      wear: {
        hair: {
          name: 'bun',
          knotUp: 0.9,
          knot: 1.0,
          knotBall: true,
          dome: 0.1,
        },
        top: tunic('hip', 'long'),
        coat: lamellar(0.62),
        bottom: { name: 'pants', band: false },
        feet: 'waraji',
        belt: obi(2),
      },
    },
  },
  {
    id: 'town-merchant',
    region: 'town',
    role: 'Merchant',
    config: {
      age: 'adult',
      figure: 'feminine',
      build: 1.0,
      palette: {
        coat: 0x38506b,
        coatTrim: 0x1f2933,
        obi: 0x8c6a2f,
        cord: 0x544537,
        underCollar: 0xe4ded0,
        denim: 0xd8cfbc,
        sole: 0x8a5a3a,
        skin: SKIN.fair,
        hair: HAIR.dark,
      },
      wear: {
        hair: bun,
        coat: kimono('ankle'),
        bottom: { name: 'pants', band: false },
        belt: obi(0, true),
        feet: { name: 'geta' },
        righthand: 'coin-pouch',
      },
    },
  },
  {
    id: 'town-farmer',
    region: 'town',
    role: 'Rice farmer',
    config: {
      age: 'adult',
      figure: 'masculine',
      build: 0.9,
      palette: {
        straw: 0xd9c89a,
        tunic: 0x38506b,
        denim: 0x6b5a45,
        belt: 0x544537,
        mino: 0xc7b899,
        minoShade: 0x9c825c,
        skin: SKIN.tan,
        hair: HAIR.black,
      },
      wear: {
        hair: cropped,
        hat: {
          name: 'jingasa',
          brim: 1.45,
          cone: 0.68,
          coneDrop: 0.03,
          cord: true,
        },
        top: {
          name: 'tunic',
          length: 'thigh',
          sleeve: 'elbow',
          neck: 'slit',
          belt: true,
          beltAt: 'low',
        },
        bottom: { name: 'pants', crop: 0.37, turnup: 0.09, band: false },
        feet: 'waraji',
        neck: { name: 'mino' },
      },
    },
  },
  {
    id: 'town-weaver',
    region: 'town',
    role: "Weaver, the farmer's wife",
    config: {
      age: 'adult',
      figure: 'feminine',
      build: 0.92,
      palette: {
        coat: 0x8a6a55,
        coatTrim: 0x735644,
        obi: 0x2f6a68,
        cord: 0x7a4a30,
        underCollar: 0xe4ded0,
        denim: 0xd8cfbc,
        sole: 0x8a5a3a,
        wrap: 0x38506b,
        skin: SKIN.warm,
        hair: HAIR.black,
      },
      wear: {
        hair: bun,
        hat: { name: 'headwrap' },
        coat: kimono('shank'),
        bottom: { name: 'pants', band: false },
        belt: obi(0),
        feet: 'waraji',
      },
    },
  },
  {
    id: 'town-child',
    region: 'town',
    role: "The farmer's child",
    config: {
      age: 'kid',
      figure: 'feminine',
      build: 1.0,
      palette: {
        tunic: 0xa8343a,
        cuff: 0xa8343a,
        belt: 0x2f6a68,
        denim: 0x6b5a45,
        sole: 0x8a5a3a,
        skin: SKIN.tan,
        hair: HAIR.black,
      },
      wear: {
        hair: { name: 'bob' },
        top: {
          name: 'tunic',
          length: 'knee',
          sleeve: 'elbow',
          neck: 'slit',
          belt: true,
        },
        bottom: { name: 'pants', crop: 0.5, band: false },
        feet: 'waraji',
      },
    },
  },
];

// ---- stone age bands --------------------------------------------------------------------------

const BAND_A = {
  hide: 0xa07850,
  hideDark: 0x7d5c3c,
  fur: 0x8a8378,
  cord: 0x5a4632,
};
const BAND_B = {
  hide: 0x6e4e36,
  hideDark: 0x553b28,
  fur: 0x5c4030,
  cord: 0x3a2c22,
  ochre: 0xa8432a,
};

const hide = (length: string): Garment => ({
  name: 'tunic',
  length,
  sleeve: 'none',
  neck: 'slit',
  belt: true,
  beltAt: 'low',
  beltH: 0.03,
});
const longHair = (length: number): Garment => ({
  name: 'long-hair',
  length,
  spread: 0.08,
  strands: 6,
  fringe: 0.04,
  dome: true,
  drape: true,
});
const furStole: Garment = { name: 'stole' };
const spear: Garment = 'yari';
const ochreBands: Garment = {
  name: 'tattoos',
  left: [
    { m: 'band', w: 0.013, u: 0.16, at: 60, half: 0.026, n: 2 },
    { m: 'band', w: 0.013, u: 0.3, at: 60, half: 0.026, n: 2 },
  ],
  right: [
    { m: 'band', w: 0.013, u: 0.16, at: 60, half: 0.026, n: 2 },
    { m: 'band', w: 0.013, u: 0.3, at: 60, half: 0.026, n: 2 },
  ],
};

const bandPalette = (
  band: typeof BAND_A | typeof BAND_B,
  skin: number,
  hair: number,
) => ({
  tunic: band.hide,
  cuff: band.hide,
  briefs: band.hideDark,
  bra: band.hideDark,
  belt: band.cord,
  strap: band.cord,
  fur: band.fur,
  mantle: band.fur,
  pole: 0x8c7355,
  poleGrip: band.cord,
  ink: 'ochre' in band ? band.ochre : 0x3a3431,
  skin,
  hair,
});

const BANDS: CitizenLook[] = [
  {
    id: 'band-a-leader',
    region: 'band_a',
    role: 'Band A leader',
    config: {
      age: 'adult',
      figure: 'feminine',
      build: 1.04,
      palette: {
        ...bandPalette(BAND_A, SKIN.olive, HAIR.brown),
        cord: BAND_A.cord,
        plume: 0xe8e0cc,
      },
      wear: {
        hair: longHair(0.24),
        hat: {
          name: 'headdress',
          band: 'cord',
          peak: false,
          stones: false,
          plumes: 3,
          height: 0.14,
        },
        top: hide('knee'),
        neck: furStole,
        righthand: spear,
      },
    },
  },
  {
    id: 'band-a-healer',
    region: 'band_a',
    role: 'Band A elder healer',
    config: {
      age: 'old',
      figure: 'masculine',
      build: 0.88,
      palette: { ...bandPalette(BAND_A, SKIN.tan, HAIR.brown) },
      wear: {
        hair: longHair(0.16),
        face: 'full-beard',
        top: hide('calf'),
        neck: { name: 'mantle', width: 'shoulder' },
        righthand: 'cane',
      },
    },
  },
  {
    id: 'band-a-hunter',
    region: 'band_a',
    role: 'Band A hunter',
    config: {
      age: 'adult',
      figure: 'masculine',
      build: 1.1,
      palette: { ...bandPalette(BAND_A, SKIN.olive, HAIR.black) },
      wear: {
        hair: longHair(0.12),
        face: 'stubble',
        top: hide('thigh'),
        neck: furStole,
        righthand: spear,
      },
    },
  },
  {
    id: 'band-a-gatherer-teen',
    region: 'band_a',
    role: 'Band A teen gatherer',
    config: {
      age: 'teen',
      figure: 'feminine',
      build: 0.9,
      palette: { ...bandPalette(BAND_A, SKIN.warm, HAIR.auburn) },
      wear: {
        hair: longHair(0.2),
        top: hide('knee'),
        lefthand: 'produce-basket',
      },
    },
  },
  {
    id: 'band-a-gatherer',
    region: 'band_a',
    role: 'Band A gatherer',
    config: {
      age: 'adult',
      figure: 'feminine',
      build: 0.96,
      palette: { ...bandPalette(BAND_A, SKIN.tan, HAIR.black) },
      wear: {
        hair: longHair(0.28),
        top: hide('knee'),
        neck: furStole,
        lefthand: 'produce-basket',
      },
    },
  },
  {
    id: 'band-b-leader',
    region: 'band_b',
    role: 'Band B leader',
    config: {
      age: 'adult',
      figure: 'masculine',
      build: 1.14,
      palette: { ...bandPalette(BAND_B, SKIN.brown, HAIR.black) },
      wear: {
        hair: longHair(0.2),
        face: 'full-beard',
        top: hide('thigh'),
        neck: { name: 'mantle', width: 'shoulder' },
        hands: ochreBands,
        righthand: spear,
      },
    },
  },
  {
    id: 'band-b-mother',
    region: 'band_b',
    role: 'Band B mother',
    config: {
      age: 'adult',
      figure: 'feminine',
      build: 1.0,
      palette: { ...bandPalette(BAND_B, SKIN.deep, HAIR.black) },
      wear: {
        hair: longHair(0.3),
        top: hide('calf'),
        neck: furStole,
        hands: ochreBands,
      },
    },
  },
  {
    id: 'band-b-hunter',
    region: 'band_b',
    role: 'Band B young hunter',
    config: {
      age: 'adult',
      figure: 'masculine',
      build: 1.0,
      palette: { ...bandPalette(BAND_B, SKIN.brown, HAIR.dark) },
      wear: {
        hair: longHair(0.1),
        top: hide('thigh'),
        hands: ochreBands,
        righthand: spear,
      },
    },
  },
  {
    id: 'band-b-child',
    region: 'band_b',
    role: 'Band B child',
    config: {
      age: 'kid',
      figure: 'masculine',
      build: 1.0,
      palette: { ...bandPalette(BAND_B, SKIN.brown, HAIR.black) },
      wear: {
        hair: longHair(0.08),
        top: hide('knee'),
      },
    },
  },
];

/** World v1's new band members: band A's toolmaker and band B's elder healer. */
const BANDS_V1: CitizenLook[] = [
  {
    id: 'band-a-toolmaker',
    region: 'band_a',
    role: 'Band A toolmaker and hunter',
    config: {
      age: 'adult',
      figure: 'masculine',
      build: 1.12,
      palette: {
        ...bandPalette(BAND_A, SKIN.brown, HAIR.dark),
        pack: BAND_A.hideDark,
        packTrim: BAND_A.cord,
        packStrap: BAND_A.cord,
      },
      wear: {
        hair: longHair(0.14),
        face: 'full-beard',
        top: hide('thigh'),
        back: 'pack',
        righthand: 'carving-knife',
      },
    },
  },
  {
    id: 'band-b-elder',
    region: 'band_b',
    role: 'Band B elder healer',
    config: {
      age: 'old',
      figure: 'feminine',
      build: 0.9,
      greyHair: true,
      palette: { ...bandPalette(BAND_B, SKIN.deep, 0xd8d4cc) },
      wear: {
        hair: longHair(0.26),
        top: hide('calf'),
        neck: { name: 'mantle', width: 'shoulder' },
        hands: ochreBands,
        righthand: 'cane',
      },
    },
  },
];

export const CITIZEN_LOOKS: CitizenLook[] = [
  ...TOWN,
  ...TOWN_V1,
  ...BANDS,
  ...BANDS_V1,
];
