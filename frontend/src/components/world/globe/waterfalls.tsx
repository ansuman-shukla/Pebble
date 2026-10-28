import { useFrame } from '@react-three/fiber';
import { useEffect, useMemo, useRef } from 'react';
import {
  BufferAttribute,
  BufferGeometry,
  DataTexture,
  DoubleSide,
  type Points,
  Vector3,
} from 'three';

import type { GlobeTerrain } from '@/lib/world/globe';
import type { Waterfall } from '@/lib/world/river-courses';
import {
  fallFoamGeometry,
  fallFrame,
  fallLanding,
  fallSheetGeometry,
} from '@/lib/world/water-mesh';
import { waterMaterial } from '@/lib/world/water-material';

/*
 * Waterfalls: where a river drops off a cliff (river-courses.ts finds them; the great falls is the big one) a
 * sheet of water curves down from the lip, mist rises where it lands and, when it lands in a lake or the sea, a
 * disc of foam churns on the surface.
 */

/** Mist puffs per fall, their lifetime (s), how high (m) they rise and how far they drift out. */
const MIST_PUFFS = 70;
const MIST_LIFETIME = 6;
const MIST_RISE = 14;
const MIST_DRIFT = 9;
const MIST_SPREAD = 5;
const MIST_SIZE = 7;
const MIST_TEXTURE_SIZE = 32;

/** A soft round puff (white, alpha falling off from the middle). */
function puffTexture() {
  const size = MIST_TEXTURE_SIZE;
  const data = new Uint8Array(size * size * 4);
  for (let y = 0; y < size; y++)
    for (let x = 0; x < size; x++) {
      const r = Math.hypot(x + 0.5 - size / 2, y + 0.5 - size / 2) / (size / 2);
      const alpha = Math.max(0, 1 - r) ** 2;
      data.set([255, 255, 255, Math.round(alpha * 255)], (y * size + x) * 4);
    }
  const texture = new DataTexture(data, size, size);
  texture.needsUpdate = true;
  return texture;
}

/** Deterministic pseudo-random numbers in [0, 1) per puff. */
const random = (i: number, salt: number) => {
  const h = Math.sin(i * 127.1 + salt * 311.7) * 43758.5453;
  return h - Math.floor(h);
};

const spot = new Vector3();

function Mist({ terrain, fall }: { terrain: GlobeTerrain; fall: Waterfall }) {
  const points = useRef<Points>(null);
  const { radius } = terrain.globe;
  const { out, across } = useMemo(() => fallFrame(fall), [fall]);
  const landing = useMemo(() => fallLanding(terrain, fall), [terrain, fall]);
  const geometry = useMemo(() => {
    const result = new BufferGeometry();
    result.setAttribute(
      'position',
      new BufferAttribute(new Float32Array(MIST_PUFFS * 3), 3),
    );
    result.setAttribute(
      'color',
      new BufferAttribute(new Float32Array(MIST_PUFFS * 4).fill(1), 4),
    );
    return result;
  }, []);
  const texture = useMemo(() => puffTexture(), []);
  useEffect(() => () => geometry.dispose(), [geometry]);
  useEffect(() => () => texture.dispose(), [texture]);

  useFrame(({ clock }) => {
    const mesh = points.current;
    if (!mesh) return;
    const position = mesh.geometry.getAttribute('position') as BufferAttribute;
    const color = mesh.geometry.getAttribute('color') as BufferAttribute;
    for (let i = 0; i < MIST_PUFFS; i++) {
      const age = (clock.elapsedTime / MIST_LIFETIME + random(i, 1)) % 1;
      const angle = random(i, 2) * Math.PI * 2;
      const spread = MIST_SPREAD * Math.sqrt(random(i, 3));
      const drift = MIST_DRIFT * age;
      const x = Math.cos(angle) * (spread + drift * 0.5) + drift * 0.6;
      const z = Math.sin(angle) * (spread + drift * 0.5);
      spot
        .copy(landing)
        .addScaledVector(out, x / radius)
        .addScaledVector(across, z / radius)
        .normalize()
        .multiplyScalar(
          radius + fall.footHeight + 0.5 + MIST_RISE * Math.sqrt(age),
        );
      position.setXYZ(i, spot.x, spot.y, spot.z);
      color.setW(i, Math.sin(Math.PI * age) * 0.55);
    }
    position.needsUpdate = true;
    color.needsUpdate = true;
  });

  // the puffs move every frame: their bounds are never computed, so keep them out of frustum culling
  return (
    <points
      ref={points}
      geometry={geometry}
      frustumCulled={false}
      renderOrder={4}
    >
      <pointsMaterial
        map={texture}
        size={MIST_SIZE}
        sizeAttenuation
        transparent
        depthWrite={false}
        vertexColors
        color="#f4f8fb"
      />
    </points>
  );
}

function Fall({ terrain, fall }: { terrain: GlobeTerrain; fall: Waterfall }) {
  const sheet = useMemo(
    () => fallSheetGeometry(terrain, fall),
    [terrain, fall],
  );
  const foam = useMemo(
    () => (fall.intoWater ? fallFoamGeometry(terrain, fall) : null),
    [terrain, fall],
  );
  const sheetMaterial = useMemo(() => {
    const material = waterMaterial('falling');
    material.side = DoubleSide;
    return material;
  }, []);
  const foamMaterial = useMemo(() => waterMaterial('foam'), []);
  useEffect(() => () => sheet.dispose(), [sheet]);
  useEffect(() => () => foam?.dispose(), [foam]);
  useEffect(() => () => sheetMaterial.dispose(), [sheetMaterial]);
  useEffect(() => () => foamMaterial.dispose(), [foamMaterial]);
  return (
    <>
      <mesh geometry={sheet} material={sheetMaterial} renderOrder={3} />
      {foam && <mesh geometry={foam} material={foamMaterial} renderOrder={2} />}
      <Mist terrain={terrain} fall={fall} />
    </>
  );
}

export function Waterfalls({
  terrain,
  falls,
  onMounted,
}: {
  terrain: GlobeTerrain;
  falls: Waterfall[];
  /** Called once the falls are in the scene. */
  onMounted?: () => void;
}) {
  useEffect(() => onMounted?.(), [onMounted]);
  return (
    <>
      {falls.map((fall, index) => (
        <Fall key={index} terrain={terrain} fall={fall} />
      ))}
    </>
  );
}
