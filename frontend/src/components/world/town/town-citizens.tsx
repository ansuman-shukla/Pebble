import { useFrame } from '@react-three/fiber';
import { useLayoutEffect, useRef } from 'react';
import { type Group, Matrix4 } from 'three';

import { CitizenModel } from '@/components/world/citizen-model';
import { Label } from '@/components/world/labels';
import type { TownCitizen } from '@/lib/client/types.gen';
import { CITIZEN_LOOKS, type CitizenLook } from '@/lib/world/citizen-looks';
import type { LabelStore } from '@/lib/world/label-store';
import { FLAT_MAPPING, type LocalMapping } from '@/lib/world/local-mapping';

/*
 * The town's people until the simulation arrives (M5): a citizen with a route walks it in a loop (back to the
 * first point after the last), facing where it goes; the others stand facing heading_deg.
 */

const WALK_SPEED = 1.2;
const LABEL_HEIGHT = 2.1;
const MAX_FRAME = 0.1;

const LOOKS = new Map(CITIZEN_LOOKS.map((look) => [look.id, look]));
const pose = new Matrix4();

function lookFor(id: string): CitizenLook {
  const look = LOOKS.get(id);
  if (!look) throw new Error(`unknown citizen look ${id}`);
  return look;
}

/** Stands a group at local (x, z) facing `heading` (radians, rotation.y) through the mapping. */
function place(
  group: Group,
  mapping: LocalMapping,
  x: number,
  z: number,
  heading: number,
) {
  mapping
    .matrix(x, 0, z, heading, pose)
    .decompose(group.position, group.quaternion, group.scale);
}

/** Stands a group at its spot, then moves it along a closed route at WALK_SPEED. */
function useRouteWalk(citizen: TownCitizen, mapping: LocalMapping) {
  const route = citizen.route ?? [];
  const group = useRef<Group>(null);
  const progress = useRef({ leg: 0, along: 0 });

  useLayoutEffect(() => {
    if (group.current)
      place(
        group.current,
        mapping,
        citizen.x,
        citizen.z,
        (citizen.heading_deg * Math.PI) / 180,
      );
  }, [citizen, mapping]);

  useFrame((_, frameDelta) => {
    const body = group.current;
    if (!body || route.length < 2) return;
    const current = progress.current;
    current.along += WALK_SPEED * Math.min(frameDelta, MAX_FRAME);
    for (;;) {
      const [x1, z1] = route[current.leg];
      const [x2, z2] = route[(current.leg + 1) % route.length];
      const length = Math.hypot(x2 - x1, z2 - z1);
      if (current.along < length) {
        const share = current.along / length;
        place(
          body,
          mapping,
          x1 + (x2 - x1) * share,
          z1 + (z2 - z1) * share,
          Math.atan2(x2 - x1, z2 - z1),
        );
        return;
      }
      current.along -= length;
      current.leg = (current.leg + 1) % route.length;
    }
  });

  return group;
}

function Townsperson({
  citizen,
  mapping,
  labels,
  onReady,
}: {
  citizen: TownCitizen;
  mapping: LocalMapping;
  labels: LabelStore;
  onReady: (id: string) => void;
}) {
  const look = lookFor(citizen.look);
  const walking = (citizen.route ?? []).length >= 2;
  const group = useRouteWalk(citizen, mapping);

  return (
    <group ref={group}>
      <CitizenModel
        look={look}
        motion={walking ? 'Walk' : 'Idle'}
        speed={walking ? WALK_SPEED : undefined}
        onReady={onReady}
      />
      <Label
        store={labels}
        id={look.id}
        text={look.role}
        height={LABEL_HEIGHT}
      />
    </group>
  );
}

export function TownCitizens({
  citizens,
  mapping = FLAT_MAPPING,
  labels,
  onReady,
}: {
  citizens: TownCitizen[];
  mapping?: LocalMapping;
  labels: LabelStore;
  onReady: (id: string) => void;
}) {
  return (
    <>
      {citizens.map((citizen) => (
        <Townsperson
          key={citizen.look}
          citizen={citizen}
          mapping={mapping}
          labels={labels}
          onReady={onReady}
        />
      ))}
    </>
  );
}
