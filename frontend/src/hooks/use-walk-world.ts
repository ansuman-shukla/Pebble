import { useEffect, useState } from 'react';

import { collidersUrl } from '@/lib/world/assets';
import {
  assetIdForKind,
  buildWalkWorld,
  type ColliderFile,
  type WalkPlacement,
  type WalkWater,
  type WalkWorld,
} from '@/lib/world/collision';

const colliderFiles = new Map<string, Promise<ColliderFile>>();

function loadColliders(id: string) {
  let file = colliderFiles.get(id);
  if (!file) {
    file = fetch(collidersUrl(id)).then((response) => {
      if (!response.ok)
        throw new Error(`colliders for ${id}: HTTP ${response.status}`);
      return response.json() as Promise<ColliderFile>;
    });
    colliderFiles.set(id, file);
  }
  return file;
}

interface Built {
  placements: WalkPlacement[];
  water: WalkWater[];
  world: WalkWorld;
}

/** The collision world for a placement set (null while colliders load); rebuilt only when the arrays change. */
export function useWalkWorld(
  placements: WalkPlacement[],
  water: WalkWater[],
): WalkWorld | null {
  const [built, setBuilt] = useState<Built | null>(null);
  const [error, setError] = useState<Error | null>(null);

  useEffect(() => {
    let live = true;
    const ids = [
      ...new Set(
        placements
          .filter((placement) => placement.walk !== 'none')
          .map((placement) => assetIdForKind(placement.kind)),
      ),
    ];
    Promise.all(ids.map(loadColliders))
      .then((files) => {
        if (!live) return;
        const byId = new Map(files.map((file, index) => [ids[index], file]));
        const world = buildWalkWorld(placements, water, byId);
        setBuilt({ placements, water, world });
      })
      .catch((reason: Error) => live && setError(reason));
    return () => {
      live = false;
    };
  }, [placements, water]);

  if (error) throw error;
  return built?.placements === placements && built.water === water
    ? built.world
    : null;
}
