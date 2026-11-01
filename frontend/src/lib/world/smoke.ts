import {
  AdditiveBlending,
  BufferAttribute,
  BufferGeometry,
  Color,
  DataTexture,
  IcosahedronGeometry,
  InstancedBufferAttribute,
  InstancedMesh,
  Matrix4,
  MeshLambertMaterial,
  Points,
  PointsMaterial,
  Quaternion,
  RGBAFormat,
  Vector3,
} from 'three';

import { clipPhase, propViews, propWorld } from './prop-motion';
import { windUniforms } from './wind';

/*
 * Smoke and sparks over the live fires (10 §5.3; components/world/globe/fire-smoke.tsx draws them): one instanced
 * mesh of puffs for every fire within SMOKE_REACH that burns or went out less than SMOULDER game minutes ago
 * (thinning as it cools), and one cloud of sparks over the burning ones (round glows that fade as they rise).
 * Both rise along the local up, the smoke drifting with the wind, at natural speed × visualRate (the prop clock),
 * so two draw calls carry every fire. A puff is born thin and narrow over the flame (people round the fire stay in
 * sight through it) and thickens as it rises and spreads; while the fire burns, the flame lights it from below (warm
 * where it is low, fading as it rises), so smoke at night reads as smoke, not a dark column.
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
/** Pixels across the spark sprite. */
const SPARK_SPRITE = 32;
const PUFF_LIFT = 0.4;
/** Metres a puff strays sideways by the time it is gone. */
const PUFF_WANDER = 0.6;
/** A puff thickens over the first this much of its rise (above a sitter's or a sleeper's head by then). */
const PUFF_THIN = 0.35;

/** A fixed pseudo-random number in [0, 1) for `n`. */
const noiseOf = (n: number) => {
  const s = Math.sin(n * 12.9898) * 43758.5453;
  return s - Math.floor(s);
};

const PUFF_VERTEX = /* glsl */ `
attribute float puffAlpha;
attribute float puffGlow;
varying float vPuffAlpha;
varying float vPuffGlow;
`;
/** The flame's light on the smoke over it (added to the puff's colour, by how low and close to the flame it is). */
const FLAME_LIGHT = '0.95, 0.5, 0.18';

function smokeMaterial() {
  const material = new MeshLambertMaterial({
    color: '#a9a49e',
    transparent: true,
    opacity: 0.55,
    depthWrite: false,
  });
  material.onBeforeCompile = (shader) => {
    shader.vertexShader = shader.vertexShader
      .replace('#include <common>', `#include <common>\n${PUFF_VERTEX}`)
      .replace(
        '#include <begin_vertex>',
        '#include <begin_vertex>\nvPuffAlpha = puffAlpha;\nvPuffGlow = puffGlow;',
      );
    shader.fragmentShader = shader.fragmentShader
      .replace(
        '#include <common>',
        '#include <common>\nvarying float vPuffAlpha;\nvarying float vPuffGlow;',
      )
      .replace(
        '#include <opaque_fragment>',
        // soft edges: a puff thins towards its outline
        `#include <opaque_fragment>\nfloat puffFacing = abs(dot(normal, normalize(vViewPosition)));\ngl_FragColor.a *= vPuffAlpha * smoothstep(0.0, 0.6, puffFacing);\ngl_FragColor.rgb += vec3(${FLAME_LIGHT}) * vPuffGlow;`,
      );
  };
  material.customProgramCacheKey = () => 'fire-smoke';
  return material;
}

/** How bright a spark is at `age` (0 born … 1 gone): it flares up at once and dies away as it rises. */
export const sparkGlow = (age: number) => Math.min(age / 0.1, 1) * (1 - age);

/** A round spark: white at the centre fading to nothing at the rim (added light: black is see-through). */
function sparkSprite() {
  const pixels = new Uint8Array(SPARK_SPRITE * SPARK_SPRITE * 4);
  const half = SPARK_SPRITE / 2;
  for (let y = 0; y < SPARK_SPRITE; y++)
    for (let x = 0; x < SPARK_SPRITE; x++) {
      const out = Math.hypot(x + 0.5 - half, y + 0.5 - half) / half;
      const glow = Math.round(255 * Math.max(0, 1 - out) ** 2);
      pixels.set([glow, glow, glow, glow], (y * SPARK_SPRITE + x) * 4);
    }
  const texture = new DataTexture(
    pixels,
    SPARK_SPRITE,
    SPARK_SPRITE,
    RGBAFormat,
  );
  texture.needsUpdate = true;
  return texture;
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

/**
 * A puff's look at `age` (0 born … 1 gone): how high it has risen (0-1), its size (m), its opacity (thin over the
 * flame, thickest a third of the way up, then fading) and how much a burning flame lights it (low puffs most).
 */
export function puffAt(age: number) {
  const rise = age;
  return {
    rise,
    size: 0.2 + 1.2 * age,
    alpha: Math.min(age / PUFF_THIN, 1) * (1 - age),
    glow: (1 - age) ** 3,
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
  private readonly glow: InstancedBufferAttribute;
  private readonly sparkPositions: BufferAttribute;
  private readonly sparkGlows: BufferAttribute;
  /** Each fire as last seen: lit or not, and when it went out (game minutes). */
  private readonly seen = new Map<string, { lit: boolean; outAt: number }>();

  constructor() {
    this.alpha = new InstancedBufferAttribute(
      new Float32Array(MAX_FIRES * PUFFS_PER_FIRE),
      1,
    );
    this.glow = new InstancedBufferAttribute(
      new Float32Array(MAX_FIRES * PUFFS_PER_FIRE),
      1,
    );
    const puffGeometry = new IcosahedronGeometry(1, 2);
    puffGeometry.setAttribute('puffAlpha', this.alpha);
    puffGeometry.setAttribute('puffGlow', this.glow);
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
    this.sparkGlows = new BufferAttribute(
      new Float32Array(MAX_FIRES * SPARKS_PER_FIRE * 3),
      3,
    );
    const sparkGeometry = new BufferGeometry();
    sparkGeometry.setAttribute('position', this.sparkPositions);
    sparkGeometry.setAttribute('color', this.sparkGlows);
    this.sparks = new Points(
      sparkGeometry,
      new PointsMaterial({
        color: new Color('#ffb347'),
        size: 0.12,
        map: sparkSprite(),
        vertexColors: true,
        blending: AdditiveBlending,
        transparent: true,
        depthWrite: false,
      }),
    );
    this.sparks.frustumCulled = false;
    this.sparks.visible = false;
  }

  /**
   * Moves the smoke of every fire of `sources` (each by id: the live fires, the chimneys of lit hearths) as seen from
   * `camera` to the prop clock's time.
   */
  frame(camera: Vector3, ...sources: ReadonlyMap<string, SmokingFire>[]) {
    const { puffs, alpha, glow, sparks, sparkPositions, sparkGlows } = this;
    const time = propWorld.clipTime;
    const wind = windUniforms.windDirection.value;
    const strength = windUniforms.windStrength.value;
    const smoking: { fire: SmokingFire; thick: number; seed: number }[] = [];
    for (const fires of sources)
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
    // a fire gone from the feed is forgotten
    for (const id of this.seen.keys())
      if (!sources.some((fires) => fires.has(id))) this.seen.delete(id);
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
        glow.setX(puffCount, fire.lit ? puff.glow * thick : 0);
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
        const glow = sparkGlow(age);
        sparkGlows.setXYZ(sparkCount, glow, glow, glow);
        sparkCount++;
      }
    }
    puffs.count = puffCount;
    puffs.visible = puffCount > 0;
    puffs.instanceMatrix.needsUpdate = true;
    alpha.needsUpdate = true;
    glow.needsUpdate = true;
    sparks.geometry.setDrawRange(0, sparkCount);
    sparks.visible = sparkCount > 0;
    sparkPositions.needsUpdate = true;
    sparkGlows.needsUpdate = true;
    propViews.puffs = puffCount;
    propViews.sparks = sparkCount;
  }

  dispose() {
    this.puffs.geometry.dispose();
    (this.puffs.material as MeshLambertMaterial).dispose();
    this.puffs.dispose();
    this.sparks.geometry.dispose();
    const sparkLook = this.sparks.material as PointsMaterial;
    sparkLook.map?.dispose();
    sparkLook.dispose();
    propViews.puffs = 0;
    propViews.sparks = 0;
  }
}
