import { expect, type Page, test } from '@playwright/test';
import {
  Box3,
  type Bone,
  BoxGeometry,
  Group,
  Mesh,
  type Object3D,
  type SkinnedMesh,
  Vector3,
} from 'three';

import type { LiveMessage } from '../../src/lib/live/live-contract';
import { applyMessage, EMPTY_LIVE } from '../../src/lib/live/live-state';
import {
  type Bearer,
  BAKED_HIP,
  CAPTURED_SPEED,
  fallbackMotion,
  gaitOf,
  GESTURES,
  JOG_FROM,
  type Motion,
  motionClips,
  motionLook,
  motionOf,
  MOTIONS,
  RUN_FROM,
} from '../../src/lib/live/motion';
import { CITIZEN_LOOKS } from '../../src/lib/world/citizen-looks';
import { freeHand, holderOf, propModel } from '../../src/lib/world/hand-props';
import { animateHumanoid } from '../../src/lib/world/humanoid-clips';
import {
  ease,
  easeSeconds,
  hopHeight,
  JUMP_HEIGHT,
  layer,
  newPlacement,
  placementOf,
  rigOf,
  keepClipPose,
  startEasing,
  unlayer,
} from '../../src/lib/world/poses';
import {
  holdPosture,
  restOf,
  SEAT_HEIGHT,
  settle,
  showWorn,
} from '../../src/lib/world/rest-posture';
import { visualRate } from '../../src/lib/world/visual-rate';
import { openGlobe } from './globe-helpers';
import { createCharacter } from '../../src/vendor/polyfork/humanoid.mjs';

/*
 * How citizens' bodies move (no browser; the clips come from Polyfork's CDN): the motion table of 10 §4.5 (each
 * motion's clip, prop, rest and layer), the fallback from activities, gaits paced so planted feet don't slip at ×1 and
 * ×10, seats, procedural layers (gestures, the jump, the creep, prayer), easing between postures, props in hand and
 * the cues the feed's events give bodies.
 */

const lookOf = (id: string) => {
  const look = CITIZEN_LOOKS.find((candidate) => candidate.id === id);
  if (!look) throw new Error(`no look ${id}`);
  return look;
};

const FARMER: Bearer = {
  look: 'town-farmer',
  region: 'town',
  spear: false,
  dark: false,
};

test.describe('the motion table', () => {
  test('every motion plays a Polyfork clip', async () => {
    const clips = [...new Set(MOTIONS.flatMap(motionClips))];
    expect(clips.length).toBeGreaterThan(15);
    const character = createCharacter(lookOf('town-farmer').config);
    // each clip is fetched from Polyfork's CDN (a name it doesn't have fails the load)
    const animation = await animateHumanoid(character, { clips });
    for (const clip of clips)
      expect(animation.actions[clip], clip).toBeTruthy();
  });

  test('work shows its clip and the tool in hand', () => {
    const look = (motion: Motion, bearer: Partial<Bearer> = {}) =>
      motionLook(motion, { ...FARMER, ...bearer });
    expect(look('chop')).toMatchObject({
      clip: 'Chopping wood',
      prop: { kind: 'axe', at: 'right' },
      pace: 1,
    });
    expect(look('mine')).toMatchObject({
      clip: 'Chopping wood',
      pace: 0.8,
      prop: { kind: 'pick' },
    });
    expect(look('farm')).toMatchObject({
      clip: 'Planting',
      prop: { kind: 'hoe' },
    });
    expect(look('gather_high')).toMatchObject({
      clip: 'Harvesting',
      prop: { kind: 'basket', at: 'left' },
    });
    expect(look('gather_low')).toMatchObject({
      clip: 'Crouch',
      layer: 'reach',
      prop: { kind: 'basket' },
    });
    expect(look('pan')).toMatchObject({
      clip: 'Crouch',
      layer: 'swirl',
      prop: { kind: 'pan' },
    });
    expect(look('eat').prop?.kind).toBe('food');
    expect(look('drink').prop?.kind).toBe('cup');
    expect(look('trade')).toMatchObject({
      clip: 'Interact',
      prop: { kind: 'coin_pouch', at: 'left' },
    });
    expect(look('carry_walk')).toMatchObject({
      prop: { kind: 'sack', at: 'back' },
      layer: 'laden',
    });
    // the town fishes with a rod, the bands with a spear
    expect(look('fish')).toMatchObject({
      clip: 'Holding torch',
      prop: { kind: 'rod' },
    });
    expect(look('fish', { region: 'band_b' }).prop?.kind).toBe('spear');
    expect(look('fish', { region: 'band_a', spear: true }).prop).toBeNull();
    // crafting: the smith hammers fast, a toolmaker knaps crouching, a weaver works standing
    expect(look('craft', { look: 'town-smith' })).toMatchObject({
      clip: 'Chopping wood',
      pace: 1.2,
      prop: { kind: 'hammer' },
    });
    expect(
      look('craft', { look: 'band-a-toolmaker', region: 'band_a' }),
    ).toMatchObject({ clip: 'Crouch', prop: { kind: 'stone' } });
    expect(look('craft', { look: 'town-weaver' })).toMatchObject({
      clip: 'Fixing',
      prop: null,
    });
  });

  test('guards, merchants, hunters and fighters differ', () => {
    const guard = { ...FARMER, look: 'town-ashigaru' };
    expect(motionLook('idle', FARMER).clip).toBe('Idle');
    expect(motionLook('idle', guard)).toMatchObject({
      clip: 'Arms folded',
      prop: null,
    });
    expect(motionLook('idle', { ...guard, dark: true })).toMatchObject({
      clip: 'Holding torch',
      prop: { kind: 'torch', at: 'right' },
    });
    expect(
      motionLook('trade', { ...FARMER, look: 'town-merchant' }),
    ).toMatchObject({ clip: 'Talking', prop: null });
    expect(motionLook('attack', FARMER).clip).toBe('Punch');
    expect(motionLook('attack', { ...FARMER, spear: true }).clip).toBe(
      'Pushing',
    );
    expect(motionLook('stalk', FARMER)).toMatchObject({
      clip: 'Crouch',
      layer: 'stalk',
      prop: { kind: 'spear' },
    });
    // a hunter keeps the spear it carries instead of being handed a second one
    expect(motionLook('stalk', { ...FARMER, spear: true }).prop).toBeNull();
  });

  test('bodies rest, sleep, die, go inside and gesture', () => {
    expect(motionLook('sit', FARMER)).toMatchObject({
      clip: 'Sitting',
      pose: 'seated',
    });
    expect(motionLook('sit_ground', FARMER).pose).toBe('sitting');
    expect(motionLook('lie', FARMER)).toMatchObject({
      pose: 'sleeping',
      still: true,
    });
    expect(motionLook('lie', FARMER, { dead: true }).pose).toBe('lying');
    expect(motionLook('inside', FARMER)).toMatchObject({
      clip: 'Opening',
      pose: 'inside',
    });
    expect(motionLook('pray', FARMER)).toMatchObject({
      pose: 'sitting',
      layer: 'pray',
    });
    expect(motionLook('ring_bell', FARMER).clip).toBe('Pushing');
    expect(motionLook('talk', FARMER).clip).toBe('Talking');
    expect(motionLook('gesture', FARMER).layer).toBe('wave');
    for (const gesture of GESTURES)
      expect(motionLook('gesture', FARMER, { gesture }).layer).toBe(gesture);
    // the moving motions stand idle once the drawn body stopped
    for (const motion of ['walk', 'jog', 'run', 'carry_walk'] as const)
      expect(motionLook(motion, FARMER).clip).toBe('Idle');
  });

  test('a feed without motions falls back to the activity and its label', () => {
    const cases: [Parameters<typeof fallbackMotion>, Motion][] = [
      [['idle', ''], 'idle'],
      [['walking', 'the well'], 'walk'],
      [['running', ''], 'run'],
      [['hunting', 'a deer'], 'stalk'],
      [['resting', 'the fire pit'], 'sit_ground'],
      [['sleeping', ''], 'lie'],
      [['dead', ''], 'lie'],
      [['eating', 'rice'], 'eat'],
      [['drinking', 'the well'], 'drink'],
      [['talking', 'Aiko'], 'talk'],
      [['fishing', ''], 'fish'],
      [['tending_fire', 'the fire pit'], 'tend'],
      [['gathering', 'berries'], 'gather_high'],
      [['gathering', 'nuts'], 'gather_high'],
      [['gathering', 'flint'], 'mine'],
      [['gathering', 'iron sand'], 'mine'],
      [['gathering', 'gold'], 'pan'],
      [['gathering', 'roots'], 'gather_low'],
      [['gathering', 'reeds'], 'gather_low'],
      [['working', 'keeping watch'], 'idle'],
      [['working', 'trading at the market'], 'trade'],
      [['working', 'holding court'], 'talk'],
      [['working', 'praying at the temple'], 'pray'],
      [['working', 'ringing the bell'], 'ring_bell'],
      [['working', 'chopping firewood'], 'chop'],
      [['working', 'digging iron sand'], 'mine'],
      [['working', 'tending the rice paddies'], 'farm'],
      [['working', 'planting the seed beds'], 'farm'],
      [['working', 'filling the storehouse'], 'pick_up'],
      [['working', 'weaving at the loom'], 'craft'],
      [['working', 'knapping a spear point'], 'craft'],
      [['working', 'mending the drying rack'], 'craft'],
    ];
    for (const [[activity, label], motion] of cases)
      expect(fallbackMotion(activity, label), `${activity} ${label}`).toBe(
        motion,
      );
    // the feed's motion wins over the fallback
    expect(
      motionOf({
        activity: 'working',
        action_label: 'tending the rice paddies',
        motion: 'chop',
      }),
    ).toBe('chop');
    expect(motionOf({ activity: 'working', action_label: 'trading' })).toBe(
      'trade',
    );
  });
});

test.describe('gaits', () => {
  test('the gait follows the drawn ground speed and the load', () => {
    const at = (motion: Motion, speed: number, look = 'town-farmer') =>
      gaitOf(motion, speed, BAKED_HIP, look)?.clip ?? null;
    expect(at('walk', 0.1)).toBeNull();
    expect(at('walk', 1.4)).toBe('Walk');
    expect(at('walk', JOG_FROM - 0.01)).toBe('Walk');
    expect(at('jog', JOG_FROM)).toBe('Run');
    expect(at('run', RUN_FROM)).toBe('Run');
    expect(at('carry_walk', 1.2)).toBe('Walk');
    expect(at('walk', 1.2, 'town-lord')).toBe('Walk formal');
    expect(at('carry_walk', 1.2, 'town-lord')).toBe('Walk');
    expect(at('stalk', 0.8, 'town-samurai')).toBe('Walk');
    // a gait still loading walks meanwhile, paced for the walk
    const loading = gaitOf(
      'walk',
      1.2,
      BAKED_HIP,
      'town-lord',
      (clip) => clip === 'Walk',
    );
    expect(loading).toEqual({
      clip: 'Walk',
      timeScale: 1.2 / CAPTURED_SPEED.Walk,
    });
    // a child's shorter legs step faster for the same speed
    const child = gaitOf('walk', 1, 0.5, 'town-child')!;
    expect(child.timeScale).toBeCloseTo(1 / (1.45 * (0.5 / BAKED_HIP)), 5);
  });

  /**
   * How far a planted ankle slides on the ground (m) while the body is carried ahead at `speed` (game m/s) at the
   * clock's `rate`: in stance (the ankle within 1.5 cm of its lowest, scaled to the body), how far it moves before
   * it lifts.
   */
  async function footSlip(
    lookId: string,
    motion: Motion,
    speed: number,
    rate: number,
    /** Plays the clip this many times its gait's pace (1: as drawn). */
    misPace = 1,
  ) {
    const character = createCharacter(lookOf(lookId).config);
    const rest = restOf(character);
    const gait = gaitOf(motion, speed, rest.hipsAt.y, lookId)!;
    const animation = await animateHumanoid(character, {
      clips: [gait.clip],
      planted: new Set(),
    });
    animation.play(gait.clip, {
      fade: 0,
      timeScale: gait.timeScale * misPace,
    });
    const feet = ['LeftFoot', 'RightFoot'].map((name) =>
      character.getObjectByName(name)!,
    );
    const frame = 1 / 60;
    const samples: { z: number; y: number }[][] = [];
    for (let t = 0, body = 0; t < 4; t += frame) {
      animation.update(frame * visualRate(rate));
      body += speed * rate * frame; // the body is carried ahead (+z) at the drawn speed
      character.updateMatrixWorld(true);
      samples.push(
        feet.map((foot) => {
          const at = character.worldToLocal(
            foot.getWorldPosition(new Vector3()),
          );
          return { z: at.z + body, y: at.y };
        }),
      );
    }
    const planted = (0.015 * rest.hipsAt.y) / BAKED_HIP;
    let worst = 0;
    for (const side of [0, 1]) {
      const low = Math.min(...samples.map((sample) => sample[side].y));
      let start: number | null = null;
      for (const sample of samples) {
        const { z, y } = sample[side];
        if (y < low + planted) {
          start ??= z;
          worst = Math.max(worst, Math.abs(z - start));
        } else start = null;
      }
    }
    return worst;
  }

  const SLIP = 0.04;
  for (const [lookId, motion, speed] of [
    ['town-farmer', 'walk', 1.4],
    ['town-farmer', 'carry_walk', 1.19],
    ['town-lord', 'walk', 1.26],
    ['town-elder-farmer', 'walk', 0.84],
    ['band-a-hunter', 'stalk', 0.8],
    ['band-a-hunter', 'jog', 2.5],
    ['band-a-hunter', 'run', 3.5],
    ['town-child', 'walk', 0.98],
  ] as const)
    for (const rate of [1, 10])
      test(`${lookId} ${motion} at ${speed} m/s keeps its feet planted at ×${rate}`, async () => {
        const slip = await footSlip(lookId, motion, speed, rate);
        expect(slip, `slip ${slip.toFixed(3)} m`).toBeLessThan(SLIP);
      });

  test('the slip check catches a gait paced wrong', async () => {
    // the same walk with its clip played half again too fast slides its feet
    const slip = await footSlip('town-farmer', 'walk', 1.4, 1, 1.5);
    expect(slip).toBeGreaterThan(SLIP);
  });
});

const skinnedPoints = (character: Object3D, frame: Object3D) => {
  frame.updateMatrixWorld(true);
  const points: { at: Vector3; bones: string[]; weights: number[] }[] = [];
  character.traverse((object) => {
    const mesh = object as SkinnedMesh;
    if (!mesh.isSkinnedMesh || !mesh.visible) return;
    mesh.skeleton.update();
    const index = mesh.geometry.attributes.skinIndex;
    const weight = mesh.geometry.attributes.skinWeight;
    for (let i = 0; i < mesh.geometry.attributes.position.count; i++) {
      const at = frame.worldToLocal(
        mesh.localToWorld(mesh.getVertexPosition(i, new Vector3())),
      );
      const bones = [0, 1, 2, 3].map(
        (k) => mesh.skeleton.bones[index.getComponent(i, k)].name,
      );
      const weights = [0, 1, 2, 3].map((k) => weight.getComponent(i, k));
      points.push({ at, bones, weights });
    }
  });
  return points;
};

test.describe('seats', () => {
  // looks without a long robe or coat hanging under the seat
  for (const id of ['town-smith', 'band-a-hunter', 'town-child', 'town-digger'])
    test(`${id} sits with the hips on the seat`, async () => {
      const character = createCharacter(lookOf(id).config);
      const rest = restOf(character);
      const animation = await animateHumanoid(character, {
        clips: ['Sitting'],
        planted: new Set(['Sitting']),
      });
      animation.play('Sitting', { fade: 0 });
      animation.update(0.5);
      const world = new Group();
      const posed = new Group();
      world.add(posed);
      posed.add(character);
      const print = settle(posed, character, rest, 'seated');
      holdPosture(rest, 'seated', null, print.lift);
      const seat = new Set(['Hips']);
      const hips = skinnedPoints(character, world).filter(
        ({ bones, weights }) =>
          bones.reduce(
            (sum, bone, k) => sum + (seat.has(bone) ? weights[k] : 0),
            0,
          ) > 0.5,
      );
      const under = Math.min(...hips.map(({ at }) => at.y));
      expect(Math.abs(under - SEAT_HEIGHT), `hips ${under}`).toBeLessThan(0.05);
      // seated bodies are lifted, never tilted, and hold nothing
      showWorn(character, 'seated');
      for (const side of ['left', 'right'] as const)
        expect(holderOf(character, side).visible).toBe(false);
    });
});

test.describe('layers', () => {
  async function posedRig(id = 'town-smith', clip = 'Idle') {
    const character = createCharacter(lookOf(id).config);
    const animation = await animateHumanoid(character, {
      clips: [clip],
      planted: new Set([clip]),
    });
    animation.play(clip, { fade: 0 });
    const rig = rigOf(character);
    const at = (bone: Object3D) => {
      character.updateMatrixWorld(true);
      return character.worldToLocal(bone.getWorldPosition(new Vector3()));
    };
    /** Plays the clip to `t` and lays `kind` over it (as each frame does: unlayer, mixer, keep, layer). */
    const pose = (
      kind: Parameters<typeof layer>[1],
      t: number,
      moving = false,
    ) => {
      unlayer(rig);
      animation.mixer.setTime(t);
      keepClipPose(rig);
      return layer(rig, kind, t, moving);
    };
    return { character, rig, at, pose };
  }

  test('a jump hops 0.4 m in 0.6 s with the knees tucked', async () => {
    expect(hopHeight(0)).toBe(0);
    expect(hopHeight(0.35)).toBeCloseTo(JUMP_HEIGHT, 5);
    expect(hopHeight(0.6)).toBe(0);
    const { rig, at, pose } = await posedRig();
    const standing = at(rig.legs.left.leg).z;
    expect(pose('jump', 0.35)).toBeCloseTo(JUMP_HEIGHT, 5);
    // knees forward of where they stand
    expect(at(rig.legs.left.leg).z).toBeGreaterThan(standing + 0.1);
  });

  test('a wave raises the right hand above the head, a point reaches ahead', async () => {
    const { rig, at, pose } = await posedRig();
    pose('wave', 0);
    const head = at(rig.head).y;
    expect(at(rig.arms.right.hand).y).toBeLessThan(head);
    pose('wave', 1.1);
    expect(at(rig.arms.right.hand).y).toBeGreaterThan(head);
    pose('point', 0.8);
    const hand = at(rig.arms.right.hand);
    const shoulder = at(rig.arms.right.arm);
    expect(hand.z - shoulder.z).toBeGreaterThan(0.45);
  });

  test('bows, prayer and the creep lean ahead; the creep keeps the feet down', async () => {
    const { rig, at, pose } = await posedRig();
    pose(null, 0.9);
    const head = at(rig.head);
    const foot = at(rig.legs.left.foot).y;
    pose('bow', 0.9);
    expect(at(rig.head).z).toBeGreaterThan(head.z + 0.15);
    pose('stalk', 0.9, false);
    expect(at(rig.head).z, 'standing still: no creep').toBeCloseTo(head.z, 3);
    pose('stalk', 0.9, true);
    expect(at(rig.head).y).toBeLessThan(head.y - 0.1);
    expect(Math.abs(at(rig.legs.left.foot).y - foot)).toBeLessThan(0.01);
    // applied every frame, a layer never adds up
    pose('bow', 0.9);
    const once = at(rig.head).clone();
    pose('bow', 0.9);
    expect(at(rig.head).distanceTo(once)).toBeLessThan(1e-6);
  });

  test('a reach puts the right hand out to the ground ahead', async () => {
    const { rig, at, pose } = await posedRig('town-smith', 'Crouch');
    pose(null, 0.85);
    const hand = at(rig.arms.right.hand);
    pose('reach', 0.85);
    const reached = at(rig.arms.right.hand);
    // crouched, the hand is low already: it reaches out ahead and down towards the ground
    expect(reached.z).toBeGreaterThan(hand.z + 0.2);
    expect(reached.y).toBeLessThan(hand.y);
  });
});

test.describe('moving between postures', () => {
  test('lying down rolls over 1.2 s, a death falls in 0.8 s', () => {
    expect(easeSeconds('standing', 'sleeping', false)).toBe(1.2);
    expect(easeSeconds('sleeping', 'standing', false)).toBe(1.2);
    expect(easeSeconds('standing', 'lying', true)).toBe(0.8);
    expect(easeSeconds('standing', 'sitting', false)).toBe(0.8);
    expect(easeSeconds('sitting', 'sitting', false)).toBe(0);
  });

  test('a fall eases from standing to lying, never under the ground', async () => {
    const character = createCharacter(lookOf('town-smith').config);
    const rest = restOf(character);
    const rig = rigOf(character);
    const animation = await animateHumanoid(character, { clips: ['Idle'] });
    animation.play('Idle').paused = true;
    animation.update(0);
    const world = new Group();
    const posed = new Group();
    world.add(posed);
    posed.add(character);
    const standing = placementOf(posed, character, newPlacement());
    holdPosture(rest, 'lying');
    settle(posed, character, rest, 'lying');
    const lying = placementOf(posed, character, newPlacement());
    const easing = startEasing(standing, 0.8, true)!;
    const heights: number[] = [];
    let going = true;
    for (let frame = 0; going; frame++) {
      going = ease(easing, rig, posed, lying, 1 / 60);
      world.updateMatrixWorld(true);
      for (const bone of [rig.head, rig.legs.left.foot, rig.hips])
        heights.push(
          world.worldToLocal(bone.getWorldPosition(new Vector3())).y,
        );
      expect(frame).toBeLessThan(60);
    }
    expect(Math.min(...heights)).toBeGreaterThan(-0.001);
    // it ends where the posture laid it
    expect(posed.position.distanceTo(lying.posed)).toBeLessThan(0.01);
    expect(posed.quaternion.angleTo(lying.turn)).toBeLessThan(1e-3);
  });
});

test.describe('props', () => {
  test('a held thing hangs under the hand, hidden at rest with it', () => {
    const character = createCharacter(lookOf('band-a-hunter').config);
    const hand = holderOf(character, 'right');
    expect((hand.parent as Bone).isBone).toBe(true);
    const prop = propModel('pick', null);
    hand.add(prop);
    const shown = (object: Object3D) => {
      for (let at: Object3D | null = object; at; at = at.parent)
        if (!at.visible) return false;
      return true;
    };
    showWorn(character, 'standing');
    expect(shown(prop)).toBe(true);
    showWorn(character, 'sitting');
    expect(shown(prop)).toBe(false);
    showWorn(character, 'sleeping');
    expect(shown(prop)).toBe(false);
    // the hunter's own spear is put away while the hand holds something else
    showWorn(character, 'standing');
    const spear = character
      .getObjectsByProperty('name', 'attach-righthand')
      .find((object) => !(object.parent as Bone).isBone)!;
    expect(shown(spear)).toBe(true);
    freeHand(character, { kind: 'pick', at: 'right' });
    expect(shown(spear)).toBe(false);
    showWorn(character, 'standing');
    freeHand(character, { kind: 'basket', at: 'left' });
    expect(shown(spear)).toBe(true);
    // a load rides on the chest bone
    expect(holderOf(character, 'back').name).toBe('Spine2');
  });

  test('the torch stake is held at about 0.6 m', () => {
    // a stand-in of the stake's real size (1.5 m tall, on y = 0)
    const stake = new Mesh(
      new BoxGeometry(0.3, 1.5, 0.3).translate(0, 0.75, 0),
    );
    const model = propModel('torch', stake);
    const size = new Box3().setFromObject(model).getSize(new Vector3());
    expect(Math.max(size.x, size.y, size.z)).toBeCloseTo(0.6, 1);
  });
});

test.describe('cues', () => {
  const event = (
    type: string,
    payload: Record<string, unknown>,
    id = `e-${type}`,
    run = 'run-1',
  ): LiveMessage =>
    ({
      type: 'event',
      run_id: run,
      tick: 1,
      event: { id, type, actor_id: 'pip', payload },
    }) as LiveMessage;
  const started = { ...EMPTY_LIVE, runId: 'run-1' };

  test('gestures and blows become cues on the actor', () => {
    let state = applyMessage(started, event('gestured', { kind: 'jump' }), 5);
    expect(state.cues).toEqual([
      { id: 'e-gestured', actorId: 'pip', kind: 'jump', at: 5 },
    ]);
    state = applyMessage(
      state,
      event('injured', { amount: 5, cause: 'violence' }),
      6,
    );
    expect(state.cues.map((cue) => cue.kind)).toEqual(['jump', 'hit']);
    // the same event twice, an unknown gesture, another run, other events: no cue
    expect(applyMessage(state, event('gestured', { kind: 'jump' }), 7)).toBe(
      state,
    );
    expect(
      applyMessage(state, event('gestured', { kind: 'cartwheel' }, 'e-2'), 7)
        .cues,
    ).toHaveLength(2);
    expect(
      applyMessage(
        state,
        event('gestured', { kind: 'wave' }, 'e-3', 'run-2'),
        7,
      ).cues,
    ).toHaveLength(2);
    expect(
      applyMessage(state, event('action_started', {}, 'e-4'), 7).cues,
    ).toHaveLength(2);
  });
});

type Performer = {
  __pebbleMockLive: {
    perform(actor: string, doing: Record<string, unknown> | null): void;
    sendNow(
      type: string,
      actor: string,
      payload: Record<string, unknown>,
    ): void;
    setClock(change: { paused: boolean }): void;
  };
};

/** What the page's hidden hooks say of a drawn citizen. */
async function drawn(page: Page, id: string) {
  const data = await page.locator(`[data-npc="${id}"]`).evaluate((node) => ({
    ...(node as unknown as { dataset: Record<string, string | undefined> })
      .dataset,
  }));
  return {
    motion: data.npcMotion ?? '',
    clip: data.npcClip ?? '',
    prop: data.npcProp ?? '',
    layer: data.npcLayer ?? '',
    posture: data.npcPosture ?? '',
    hidden: data.npcHidden === 'true',
  };
}

test.describe('on the globe', () => {
  test.describe.configure({ timeout: 180_000 });

  // the smith, followed (so his model is near), does every motion the mock asks of him
  test('every motion plays its clip, with its prop and layer', async ({
    page,
  }) => {
    const errors: string[] = [];
    await openGlobe(page, errors, '?mockLive=1&follow=tetsu');
    await expect(page.getByTestId('npcs')).toHaveAttribute(
      'data-npcs-ready',
      '22',
    );
    const perform = (doing: Record<string, unknown>) =>
      page.evaluate(
        (next) =>
          (globalThis as unknown as Performer).__pebbleMockLive.perform(
            'tetsu',
            next,
          ),
        doing,
      );
    const cases: [
      Record<string, unknown>,
      Partial<Awaited<ReturnType<typeof drawn>>>,
    ][] = [
      [
        { activity: 'working', motion: 'chop' },
        { clip: 'Chopping wood', prop: 'axe' },
      ],
      [
        { activity: 'gathering', motion: 'mine' },
        { clip: 'Chopping wood', prop: 'pick' },
      ],
      [
        { activity: 'working', motion: 'farm' },
        { clip: 'Planting', prop: 'hoe' },
      ],
      [
        { activity: 'gathering', motion: 'gather_high' },
        { clip: 'Harvesting', prop: 'basket' },
      ],
      [
        { activity: 'gathering', motion: 'gather_low' },
        { clip: 'Crouch', prop: 'basket', layer: 'reach' },
      ],
      [
        { activity: 'gathering', motion: 'pan' },
        { clip: 'Crouch', prop: 'pan', layer: 'swirl' },
      ],
      [
        { activity: 'fishing', motion: 'fish' },
        { clip: 'Holding torch', prop: 'rod' },
      ],
      [
        { activity: 'working', motion: 'craft' },
        { clip: 'Chopping wood', prop: 'hammer' },
      ],
      [
        { activity: 'eating', motion: 'eat' },
        { clip: 'Eating', prop: 'food' },
      ],
      [
        { activity: 'drinking', motion: 'drink' },
        { clip: 'Drinking', prop: 'cup' },
      ],
      [
        { activity: 'talking', motion: 'talk' },
        { clip: 'Talking', prop: '' },
      ],
      [
        { activity: 'working', motion: 'trade' },
        { clip: 'Interact', prop: 'coin_pouch' },
      ],
      [{ activity: 'working', motion: 'pick_up' }, { clip: 'Pick up' }],
      [{ activity: 'idle', motion: 'attack' }, { clip: 'Punch' }],
      [
        { activity: 'tending_fire', motion: 'tend' },
        { clip: 'Crouch', layer: 'reach' },
      ],
      [{ activity: 'working', motion: 'ring_bell' }, { clip: 'Pushing' }],
      [
        { activity: 'idle', motion: 'carry_walk' },
        { clip: 'Idle', prop: 'sack', layer: 'laden' },
      ],
      [
        { activity: 'hunting', motion: 'stalk' },
        { clip: 'Crouch', prop: 'spear', layer: 'stalk' },
      ],
      [
        { activity: 'idle', motion: 'gesture' },
        { clip: 'Idle', layer: 'wave' },
      ],
      [
        { activity: 'working', motion: 'pray' },
        { clip: 'Sitting', posture: 'sitting', layer: 'pray' },
      ],
      [
        { activity: 'resting', motion: 'sit_ground' },
        { clip: 'Sitting', posture: 'sitting', prop: '' },
      ],
      [
        { activity: 'resting', motion: 'sit' },
        { clip: 'Sitting', posture: 'seated' },
      ],
      [
        { activity: 'sleeping', motion: 'lie' },
        { clip: 'Idle', posture: 'sleeping' },
      ],
      [
        { activity: 'idle', motion: 'idle' },
        { clip: 'Idle', posture: 'standing' },
      ],
      [{ activity: 'dead', motion: 'lie', alive: false }, { posture: 'lying' }],
      [
        { activity: 'sleeping', motion: 'inside' },
        { posture: 'inside', hidden: true },
      ],
    ];
    for (const [doing, shown] of cases) {
      await perform(doing);
      await expect
        .poll(() => drawn(page, 'tetsu'), {
          message: `${String(doing.motion)}`,
          timeout: 20_000,
        })
        .toMatchObject({ motion: doing.motion, ...shown });
    }
    // gone inside, the smith has no label; back out, it is there again
    await expect(page.locator(`[data-label="npc-tetsu"]`)).toBeHidden();
    await perform({ activity: 'idle', motion: 'idle' });
    await expect
      .poll(() => drawn(page, 'tetsu'))
      .toMatchObject({ hidden: false, clip: 'Idle' });
    expect(errors).toEqual([]);
  });

  test('a gesture and a blow from the feed show once', async ({ page }) => {
    const errors: string[] = [];
    await openGlobe(page, errors, '?mockLive=1&follow=tetsu');
    await expect(page.getByTestId('npcs')).toHaveAttribute(
      'data-npcs-ready',
      '22',
    );
    await page.evaluate(() =>
      (globalThis as unknown as Performer).__pebbleMockLive.perform('tetsu', {
        activity: 'idle',
        motion: 'idle',
      }),
    );
    const clock = (change: { paused: boolean }) =>
      page.evaluate(
        (next) =>
          (globalThis as unknown as Performer).__pebbleMockLive.setClock(next),
        change,
      );
    /**
     * The feed sends `type` at once with the clock stopped: a paused body holds what it shows (clips and cues stand
     * still), however slowly a busy machine samples it.
     */
    const send = async (type: string, payload: Record<string, unknown>) => {
      await clock({ paused: true });
      await page.evaluate(
        ({ type, payload }) =>
          (globalThis as unknown as Performer).__pebbleMockLive.sendNow(
            type,
            'tetsu',
            payload,
          ),
        { type, payload },
      );
    };
    await send('gestured', { kind: 'nod' });
    await expect
      .poll(() => drawn(page, 'tetsu'), { timeout: 10_000 })
      .toMatchObject({ layer: 'nod', clip: 'Agree' });
    // played once (1.2 s at ×1), then back to standing about
    await clock({ paused: false });
    await expect
      .poll(() => drawn(page, 'tetsu'), { timeout: 10_000 })
      .toMatchObject({ layer: '', clip: 'Idle' });
    await send('injured', { amount: 5, cause: 'violence' });
    await expect
      .poll(() => drawn(page, 'tetsu'), { timeout: 10_000 })
      .toMatchObject({ clip: 'Hard landing' });
    await clock({ paused: false });
    await expect
      .poll(() => drawn(page, 'tetsu'), { timeout: 10_000 })
      .toMatchObject({ clip: 'Idle' });
    expect(errors).toEqual([]);
  });
});
