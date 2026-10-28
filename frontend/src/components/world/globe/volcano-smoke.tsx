import { useFrame } from '@react-three/fiber';
import { useEffect, useMemo, useRef } from 'react';
import {
  IcosahedronGeometry,
  type InstancedMesh,
  Matrix4,
  Quaternion,
  Vector3,
} from 'three';

import type { TangentFrame } from '@/lib/world/globe';

/* A plume of grey puffs rising from the summit and drifting east, big enough to read from orbit. */

const PUFFS = 16;
const RISE = 260;
const DRIFT = 120;
/** Seconds for a puff to rise all the way. */
const LIFETIME = 40;

const matrix = new Matrix4();
const position = new Vector3();
const scale = new Vector3();
const turn = new Quaternion();

export function VolcanoSmoke({
  frame,
  summit,
}: {
  frame: TangentFrame;
  /** Radius of the crater (R + h0). */
  summit: number;
}) {
  const puffs = useRef<InstancedMesh>(null);
  const geometry = useMemo(() => new IcosahedronGeometry(1, 1), []);
  useEffect(() => () => geometry.dispose(), [geometry]);

  useFrame(({ clock }) => {
    const mesh = puffs.current;
    if (!mesh) return;
    for (let i = 0; i < PUFFS; i++) {
      const age = (clock.elapsedTime / LIFETIME + i / PUFFS) % 1;
      position
        .copy(frame.up)
        .multiplyScalar(summit + 10 + age * RISE)
        .addScaledVector(frame.east, age * age * DRIFT)
        .addScaledVector(frame.north, Math.sin(i * 2.4) * 12 * age);
      scale.setScalar(10 + age * 45);
      turn.setFromAxisAngle(frame.up, i * 1.7);
      mesh.setMatrixAt(i, matrix.compose(position, turn, scale));
    }
    mesh.instanceMatrix.needsUpdate = true;
  });

  return (
    <instancedMesh
      ref={puffs}
      args={[geometry, undefined, PUFFS]}
      frustumCulled={false}
    >
      <meshLambertMaterial
        color="#8d8a86"
        transparent
        opacity={0.6}
        depthWrite={false}
        flatShading
      />
    </instancedMesh>
  );
}
