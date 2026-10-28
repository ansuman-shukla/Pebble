import { useEffect, useMemo, useState } from 'react';

import { collidersUrl } from '@/lib/world/assets';
import {
  buildWalkWorld,
  colliderIdsOf,
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

interface Loaded {
  key: string;
  files: ReadonlyMap<string, ColliderFile>;
}

/** The colliders files of a set of assets by id (null while they load). */
export function useColliders(
  ids: readonly string[],
): ReadonlyMap<string, ColliderFile> | null {
  const unique = useMemo(() => [...new Set(ids)].sort(), [ids]);
  const key = unique.join(',');
  const [loaded, setLoaded] = useState<Loaded | null>(null);
  const [error, setError] = useState<Error | null>(null);

  useEffect(() => {
    let live = true;
    Promise.all(unique.map(loadColliders))
      .then((files) => {
        if (!live) return;
        setLoaded({
          key,
          files: new Map(files.map((file, index) => [unique[index], file])),
        });
      })
      .catch((reason: Error) => live && setError(reason));
    return () => {
      live = false;
    };
  }, [unique, key]);

  if (error) throw error;
  return loaded?.key === key ? loaded.files : null;
}

/** The collision world for a placement set (null while colliders load); rebuilt only when the arrays change. */
export function useWalkWorld(
  placements: WalkPlacement[],
  water: WalkWater[],
): WalkWorld | null {
  const ids = useMemo(() => colliderIdsOf(placements), [placements]);
  const colliders = useColliders(ids);
  return useMemo(
    () => colliders && buildWalkWorld(placements, water, colliders),
    [colliders, placements, water],
  );
}
