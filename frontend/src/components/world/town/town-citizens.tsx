import { useFrame } from '@react-three/fiber';
import { useRef } from 'react';
import type { Group } from 'three';

import { CitizenModel } from '@/components/world/citizen-model';
import { Label } from '@/components/world/labels';
import type { TownCitizen } from '@/lib/client/types.gen';
import { CITIZEN_LOOKS, type CitizenLook } from '@/lib/world/citizen-looks';
import type { Point } from '@/lib/world/collision';
import type { LabelStore } from '@/lib/world/label-store';

/*
 * The town's people until the simulation arrives (M5): a citizen with a route walks it in a loop (back to the
 * first point after the last), facing where it goes; the others stand facing heading_deg.
 */

const WALK_SPEED = 1.2;
const LABEL_HEIGHT = 2.1;
const MAX_FRAME = 0.1;

const LOOKS = new Map(CITIZEN_LOOKS.map((look) => [look.id, look]));

function lookFor(id: string): CitizenLook {
  const look = LOOKS.get(id);
  if (!look) throw new Error(`unknown citizen look ${id}`);
  return look;
}

/** Moves a group along a closed route at WALK_SPEED. */
function useRouteWalk(route: Point[]) {
  const group = useRef<Group>(null);
  const progress = useRef({ leg: 0, along: 0 });

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
        body.position.set(x1 + (x2 - x1) * share, 0, z1 + (z2 - z1) * share);
        body.rotation.y = Math.atan2(x2 - x1, z2 - z1);
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
  labels,
  onReady,
}: {
  citizen: TownCitizen;
  labels: LabelStore;
  onReady: (id: string) => void;
}) {
  const look = lookFor(citizen.look);
  const route = citizen.route ?? [];
  const walking = route.length >= 2;
  const group = useRouteWalk(route);

  return (
    <group
      ref={group}
      position={[citizen.x, 0, citizen.z]}
      rotation-y={(citizen.heading_deg * Math.PI) / 180}
    >
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
  labels,
  onReady,
}: {
  citizens: TownCitizen[];
  labels: LabelStore;
  onReady: (id: string) => void;
}) {
  return (
    <>
      {citizens.map((citizen) => (
        <Townsperson
          key={citizen.look}
          citizen={citizen}
          labels={labels}
          onReady={onReady}
        />
      ))}
    </>
  );
}
