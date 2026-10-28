import { useEffect, useMemo } from 'react';
import { BufferGeometry, DoubleSide, Float32BufferAttribute } from 'three';
import { mergeGeometries } from 'three/examples/jsm/utils/BufferGeometryUtils.js';

import type { TownArea, TownWater } from '@/lib/client/types.gen';
import type { Point } from '@/lib/world/collision';
import { groundShape } from '@/lib/world/ground-shape';

/*
 * The flat town ground: grass with holes where water is (an island inside a moat ring is land again), water
 * surfaces a little below it with bank walls around every edge so the sky never shows through, and the areas
 * (streets, plazas, courtyards, fields) as coloured polygons just above the grass.
 */

// far enough out that the fog (town-sky.tsx) hides the edge even from the orbit camera
const GROUND_HALF = 1000;
const WATER_Y = -0.4;
const BANK_BOTTOM = -0.8;
const AREA_Y = 0.005;

const GRASS = '#9fb37a';
const WATER = '#4f86a8';
const BANK = '#7d6c50';
const AREA_COLORS: Record<TownArea['kind'], string> = {
  street: '#b8a07a',
  road: '#b09670',
  plaza: '#d2c9b4',
  courtyard: '#c7bda8',
  field: '#86a05c',
};

/** Vertical quads from y = 0 down to the bank bottom along every edge of a closed ring. */
function bankWalls(rings: Point[][]) {
  const positions: number[] = [];
  for (const ring of rings) {
    ring.forEach(([x1, z1], index) => {
      const [x2, z2] = ring[(index + 1) % ring.length];
      positions.push(
        ...[x1, 0, z1, x1, BANK_BOTTOM, z1, x2, 0, z2],
        ...[x2, 0, z2, x1, BANK_BOTTOM, z1, x2, BANK_BOTTOM, z2],
      );
    });
  }
  const geometry = new BufferGeometry();
  geometry.setAttribute('position', new Float32BufferAttribute(positions, 3));
  geometry.computeVertexNormals();
  return geometry;
}

function useDisposed<T extends { dispose(): void }>(items: T[]) {
  useEffect(() => () => items.forEach((item) => item.dispose()), [items]);
  return items;
}

export function TownGround({
  areas,
  water,
}: {
  areas: TownArea[];
  water: TownWater[];
}) {
  const [grass, surface, banks] = useDisposed(
    useMemo(() => {
      const holes = water.flatMap((area) => area.holes ?? []);
      const outline: Point[] = [
        [-GROUND_HALF, -GROUND_HALF],
        [GROUND_HALF, -GROUND_HALF],
        [GROUND_HALF, GROUND_HALF],
        [-GROUND_HALF, GROUND_HALF],
      ];
      return [
        mergeGeometries([
          groundShape(
            outline,
            water.map((area) => area.polygon),
          ),
          ...holes.map((hole) => groundShape(hole)),
        ]),
        mergeGeometries(
          water.map((area) => groundShape(area.polygon, area.holes)),
        ),
        bankWalls(
          water.flatMap((area) => [area.polygon, ...(area.holes ?? [])]),
        ),
      ];
    }, [water]),
  );

  const areaKinds = useMemo(
    () => [...new Set(areas.map((area) => area.kind))],
    [areas],
  );
  const areaGeometries = useDisposed(
    useMemo(
      () =>
        areaKinds.map((kind) =>
          mergeGeometries(
            areas
              .filter((area) => area.kind === kind)
              .map((area) => groundShape(area.polygon)),
          ),
        ),
      [areas, areaKinds],
    ),
  );

  return (
    <>
      <mesh geometry={grass} rotation-x={-Math.PI / 2} receiveShadow>
        <meshStandardMaterial color={GRASS} />
      </mesh>
      <mesh geometry={surface} rotation-x={-Math.PI / 2} position-y={WATER_Y}>
        <meshStandardMaterial color={WATER} />
      </mesh>
      <mesh geometry={banks} receiveShadow>
        <meshStandardMaterial color={BANK} side={DoubleSide} />
      </mesh>
      {areaGeometries.map((geometry, index) => (
        <mesh
          key={areaKinds[index]}
          geometry={geometry}
          rotation-x={-Math.PI / 2}
          position-y={AREA_Y}
          receiveShadow
        >
          <meshStandardMaterial
            color={AREA_COLORS[areaKinds[index]]}
            polygonOffset
            polygonOffsetFactor={-1}
            polygonOffsetUnits={-1}
          />
        </mesh>
      ))}
    </>
  );
}
