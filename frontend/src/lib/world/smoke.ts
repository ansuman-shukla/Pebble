import {
  AdditiveBlending,
  BufferAttribute,
  BufferGeometry,
  Color,
  IcosahedronGeometry,
  InstancedBufferAttribute,
  InstancedMesh,
  Matrix4,
  MeshLambertMaterial,
  Points,
  PointsMaterial,
  Quaternion,
  Vector3,
} from 'three';

import { clipPhase, propViews, propWorld } from './prop-motion';
import { windUniforms } from './wind';

/*
 * Smoke and sparks over the live fires (10 §5.3; components/world/globe/fire-smoke.tsx draws them): one instanced
 * mesh of puffs for every fire within SMOKE_REACH that burns or went out less than SMOULDER game minutes ago
 * (thinning as it cools), and one cloud of sparks over the burning ones. Both rise along the local up, the smoke
 * drifting with the wind, at natural speed × visualRate (the prop clock), so two draw calls carry every fire.
 */

/** Fires within this distance of the camera smoke. */
const SMOKE_REACH = 300;
/** Game minutes a fire smokes after it goes out. */
export const SMOULDER = 20;
const PUFFS_PER_FIRE = 10;
const SPARKS_PER_FIRE = 8;
const MAX_FIRES = 12;
/** Seconds a puff takes to rise (natural speed). */
const PUFF_LIFE = 6;
const PUFF_RISE = 4;
const PUFF_DRIFT = 1.6;
const SPARK_LIFE = 1.4;
const SPARK_RISE = 1.8;
const PUFF_LIFT = 0.4;
/** Metres a puff strays sideways by the time it is gone. */
const PUFF_WANDER = 0.6;

/** A fixed pseudo-random number in [0, 1) for `n`. */
const noiseOf = (n: number) => {
  const s = Math.sin(n * 12.9898) * 43758.5453;
  return s - Math.floor(s);
};

const PUFF_VERTEX = /* glsl */ `
attribute float puffAlpha;
varying float vPuffAlpha;
`;

function smokeMaterial() {
  const material = new MeshLambertMaterial({
    color: '#9a9590',
    transparent: true,
    opacity: 0.4,
    depthWrite: false,
  });
  material.onBeforeCompile = (shader) => {
    shader.vertexShader = shader.vertexShader
      .replace('#include <common>', `#include <common>\n${PUFF_VERTEX}`)
      .replace(
        '#include <begin_vertex>',
        '#include <begin_vertex>\nvPuffAlpha = puffAlpha;',
      );
    shader.fragmentShader = shader.fragmentShader
      .replace(
        '#include <common>',
        '#include <common>\nvarying float vPuffAlpha;',
      )
      .replace(
        '#include <opaque_fragment>',
        '#include <opaque_fragment>\ngl_FragColor.a *= vPuffAlpha;',
      );
  };
  material.customProgramCacheKey = () => 'fire-smoke';
  return material;
}

/** How thick a fire's smoke is: 1 while it burns (by strength), thinning to 0 SMOULDER minutes after it went out. */
export function smokiness(
  lit: boolean,
  strength: number,
  outAt: number,
  minutes: number,
) {
  if (lit) return 0.5 + 0.5 * Math.min(Math.max(strength, 0), 1);
  const since = minutes - outAt;
  return since >= 0 && since < SMOULDER ? 0.5 * (1 - since / SMOULDER) : 0;
}

/** A puff's look at `age` (0 born … 1 gone): how high it has risen (0-1), its size (m) and opacity. */
export function puffAt(age: number) {
  const rise = age;
  return {
    rise,
    size: 0.25 + 1.1 * age,
    alpha: Math.min(age / 0.15, 1) * (1 - age),
  };
}

export interface SmokingFire {
  lit: boolean;
  strength: number;
  position: Vector3;
}

const matrix = new Matrix4();
const at = new Vector3();
const up = new Vector3();
const across = new Vector3();
const size = new Vector3();
const spin = new Quaternion();
const swirl = new Vector3();

/** An offset `radius` metres out from the fire at `angle`, across the ground (`up` holds the fire's up). */
const swirlAt = (angle: number, radius: number) => {
  swirl.set(Math.cos(angle), 0, Math.sin(angle));
  return swirl.addScaledVector(up, -swirl.dot(up)).multiplyScalar(radius);
};

/** The puffs and sparks of every fire, as two objects to add to the scene; `frame` moves them every frame. */
export class SmokeCloud {
  readonly puffs: InstancedMesh;
  readonly sparks: Points;
  private readonly alpha: InstancedBufferAttribute;
  private readonly sparkPositions: BufferAttribute;
  /** Each fire as last seen: lit or not, and when it went out (game minutes). */
  private readonly seen = new Map<string, { lit: boolean; outAt: number }>();

  constructor() {
    this.alpha = new InstancedBufferAttribute(
      new Float32Array(MAX_FIRES * PUFFS_PER_FIRE),
      1,
    );
    const puffGeometry = new IcosahedronGeometry(1, 2);
    puffGeometry.setAttribute('puffAlpha', this.alpha);
    this.puffs = new InstancedMesh(
      puffGeometry,
      smokeMaterial(),
      MAX_FIRES * PUFFS_PER_FIRE,
    );
    this.puffs.frustumCulled = false;
    this.puffs.count = 0;
    this.puffs.visible = false;
    this.sparkPositions = new BufferAttribute(
      new Float32Array(MAX_FIRES * SPARKS_PER_FIRE * 3),
      3,
    );
    const sparkGeometry = new BufferGeometry();
    sparkGeometry.setAttribute('position', this.sparkPositions);
    this.sparks = new Points(
      sparkGeometry,
      new PointsMaterial({
        color: new Color('#ffb347'),
        size: 0.07,
        blending: AdditiveBlending,
        transparent: true,
        depthWrite: false,
      }),
    );
    this.sparks.frustumCulled = false;
    this.sparks.visible = false;
  }

  /** Moves the smoke of `fires` (by id) as seen from `camera` to the prop clock's time. */
  frame(camera: Vector3, fires: ReadonlyMap<string, SmokingFire>) {
    const { puffs, alpha, sparks, sparkPositions } = this;
    const time = propWorld.clipTime;
    const wind = windUniforms.windDirection.value;
    const strength = windUniforms.windStrength.value;
    const smoking: { fire: SmokingFire; thick: number; seed: number }[] = [];
    for (const [id, fire] of fires) {
      let seen = this.seen.get(id);
      if (!seen) {
        seen = { lit: fire.lit, outAt: -Infinity };
        this.seen.set(id, seen);
      } else if (seen.lit !== fire.lit) {
        seen.lit = fire.lit;
        if (!fire.lit) seen.outAt = propWorld.minutes;
      }
      const thick = smokiness(
        fire.lit,
        fire.strength,
        seen.outAt,
        propWorld.minutes,
      );
      if (thick > 0 && camera.distanceTo(fire.position) < SMOKE_REACH)
        smoking.push({ fire, thick, seed: clipPhase(id, 1) });
    }
    smoking.sort(
      (a, b) =>
        camera.distanceTo(a.fire.position) - camera.distanceTo(b.fire.position),
    );

    let puffCount = 0;
    let sparkCount = 0;
    for (const { fire, thick, seed } of smoking.slice(0, MAX_FIRES)) {
      up.copy(fire.position).normalize();
      across.copy(wind).addScaledVector(up, -wind.dot(up));
      for (let i = 0; i < PUFFS_PER_FIRE; i++) {
        const cycle = time / PUFF_LIFE + i / PUFFS_PER_FIRE + seed;
        const puff = puffAt(cycle % 1);
        // each puff wanders its own way and has its own size, new every time it is born
        const born = Math.floor(cycle) * 7.31 + i * 3.17 + seed * 11.3;
        const wander = noiseOf(born);
        at.copy(fire.position)
          .addScaledVector(up, PUFF_LIFT + puff.rise * PUFF_RISE * thick)
          .addScaledVector(
            across,
            puff.rise * puff.rise * PUFF_DRIFT * (0.3 + strength),
          )
          .add(swirlAt(wander * 6.28, PUFF_WANDER * puff.rise));
        size.setScalar(
          puff.size * (0.6 + 0.4 * thick) * (0.7 + 0.6 * noiseOf(born + 1)),
        );
        spin.setFromAxisAngle(up, noiseOf(born + 2) * 6.28);
        puffs.setMatrixAt(puffCount, matrix.compose(at, spin, size));
        alpha.setX(puffCount, puff.alpha * thick);
        puffCount++;
      }
      if (!fire.lit) continue;
      for (let i = 0; i < SPARKS_PER_FIRE; i++) {
        const age = (time / SPARK_LIFE + i / SPARKS_PER_FIRE + seed) % 1;
        const turn = i * 2.39 + seed * 6.28;
        at.copy(fire.position)
          .addScaledVector(up, 0.2 + age * SPARK_RISE)
          .add(swirlAt(turn + age * 3, 0.25 * age));
        sparkPositions.setXYZ(sparkCount, at.x, at.y, at.z);
        sparkCount++;
      }
    }
    puffs.count = puffCount;
    puffs.visible = puffCount > 0;
    puffs.instanceMatrix.needsUpdate = true;
    alpha.needsUpdate = true;
    sparks.geometry.setDrawRange(0, sparkCount);
    sparks.visible = sparkCount > 0;
    sparkPositions.needsUpdate = true;
    propViews.puffs = puffCount;
    propViews.sparks = sparkCount;
  }

  dispose() {
    this.puffs.geometry.dispose();
    (this.puffs.material as MeshLambertMaterial).dispose();
    this.puffs.dispose();
    this.sparks.geometry.dispose();
    (this.sparks.material as PointsMaterial).dispose();
    propViews.puffs = 0;
    propViews.sparks = 0;
  }
}
