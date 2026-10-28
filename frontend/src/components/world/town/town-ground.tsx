import { useEffect, useMemo } from 'react';
import { BufferGeometry, DoubleSide, Float32BufferAttribute } from 'three';
import { mergeGeometries } from 'three/examples/jsm/utils/BufferGeometryUtils.js';

import type { TownArea, TownWater } from '@/lib/client/types.gen';
import type { Point } from '@/lib/world/collision';
import { groundShape } from '@/lib/world/ground-shape';
import { FLAT_MAPPING, type LocalMapping } from '@/lib/world/local-mapping';
import { mapGeometry } from '@/lib/world/map-geometry';

/*
 * The town ground: grass with holes where water is (an island inside a moat ring is land again), water
 * surfaces a little below it with bank walls around every edge so the sky never shows through, and the areas
 * (streets, plazas, courtyards, fields) as coloured polygons just above the grass. Built in local metres and
 * carried through the mapping (flat on the town page, wrapped onto the planet on the globe).
 */

// far enough out that the fog (town-sky.tsx) hides the edge even from the orbit camera
const GROUND_HALF = 1000;
const FLAT_OUTLINE: Point[] = [
  [-GROUND_HALF, -GROUND_HALF],
  [GROUND_HALF, -GROUND_HALF],
  [GROUND_HALF, GROUND_HALF],
  [-GROUND_HALF, GROUND_HALF],
];
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

/** Vertical quads from y = 0 down to `bottom` along every edge of a closed ring. */
function bankWalls(rings: Point[][], bottom: number) {
  const positions: number[] = [];
  for (const ring of rings) {
    ring.forEach(([x1, z1], index) => {
      const [x2, z2] = ring[(index + 1) % ring.length];
      positions.push(
        ...[x1, 0, z1, x1, bottom, z1, x2, 0, z2],
        ...[x2, 0, z2, x1, bottom, z1, x2, bottom, z2],
      );
    });
  }
  const geometry = new BufferGeometry();
  geometry.setAttribute('position', new Float32BufferAttribute(positions, 3));
  return geometry;
}

/** A flat shape lying at local height y. */
const shapeAt = (outline: Point[], holes: Point[][] | undefined, y: number) =>
  groundShape(outline, holes)
    .rotateX(-Math.PI / 2)
    .translate(0, y, 0);

function mapAll(geometries: BufferGeometry[], mapping: LocalMapping) {
  const mapped = geometries.map((geometry) => mapGeometry(geometry, mapping));
  geometries.forEach((geometry) => geometry.dispose());
  const merged = mergeGeometries(mapped);
  mapped.forEach((geometry) => geometry.dispose());
  return merged;
}

function useDisposed<T extends { dispose(): void }>(items: T[]) {
  useEffect(() => () => items.forEach((item) => item.dispose()), [items]);
  return items;
}

type TownGroundProps = {
  areas: TownArea[];
  water: TownWater[];
  mapping?: LocalMapping;
  /** The grass's outer edge in local metres. */
  outline?: Point[];
  /** Depth of a wall hanging from the outline, hiding the gap to terrain below it (0 = none). */
  skirt?: number;
  grass?: string;
};

export function TownGround({
  areas,
  water,
  mapping = FLAT_MAPPING,
  outline = FLAT_OUTLINE,
  skirt = 0,
  grass: grassColor = GRASS,
}: TownGroundProps) {
  const [grass, surface, banks] = useDisposed(
    useMemo(() => {
      const holes = water.flatMap((area) => area.holes ?? []);
      const rings = water.flatMap((area) => [
        area.polygon,
        ...(area.holes ?? []),
      ]);
      return [
        mapAll(
          [
            shapeAt(
              outline,
              water.map((area) => area.polygon),
              0,
            ),
            ...holes.map((hole) => shapeAt(hole, [], 0)),
          ],
          mapping,
        ),
        mapAll(
          water.map((area) => shapeAt(area.polygon, area.holes, WATER_Y)),
          mapping,
        ),
        mapAll(
          [
            bankWalls(rings, BANK_BOTTOM),
            ...(skirt > 0 ? [bankWalls([outline], -skirt)] : []),
          ],
          mapping,
        ),
      ];
    }, [water, mapping, outline, skirt]),
  );

  const areaKinds = useMemo(
    () => [...new Set(areas.map((area) => area.kind))],
    [areas],
  );
  const areaGeometries = useDisposed(
    useMemo(
      () =>
        areaKinds.map((kind) =>
          mapAll(
            areas
              .filter((area) => area.kind === kind)
              .map((area) => shapeAt(area.polygon, [], AREA_Y)),
            mapping,
          ),
        ),
      [areas, areaKinds, mapping],
    ),
  );

  return (
    <>
      <mesh geometry={grass} receiveShadow>
        <meshStandardMaterial color={grassColor} />
      </mesh>
      <mesh geometry={surface}>
        <meshStandardMaterial color={WATER} />
      </mesh>
      <mesh geometry={banks} receiveShadow>
        <meshStandardMaterial color={BANK} side={DoubleSide} />
      </mesh>
      {areaGeometries.map((geometry, index) => (
        <mesh key={areaKinds[index]} geometry={geometry} receiveShadow>
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
