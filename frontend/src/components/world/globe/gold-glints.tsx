import { useFrame } from '@react-three/fiber';
import { useEffect, useMemo } from 'react';
import { CanvasTexture, Sprite, SpriteMaterial, Vector3 } from 'three';

import type { Feature } from '@/lib/client/types.gen';
import type { GlobeTerrain } from '@/lib/world/globe';
import { glintCount, glintSpots } from '@/lib/world/gold-glints';
import type { NodeStages } from '@/lib/world/node-stages';

/*
 * The gold pools' glints (gold-glints.ts): each glint a small gold sprite twinkling on its own beat, as many
 * showing as the pool's stage from the feed says.
 */

/** A glint's size (metres) at its brightest, and how fast it twinkles (per second). */
const GLINT_SIZE = 1;
const TWINKLE_HZ = 0.9;

declare global {
  interface Window {
    /** Test hook: the glints showing at each gold pool. */
    __pebbleGlints?: () => Record<string, number>;
  }
}

/** A four-pointed gold spark on a transparent canvas. */
function sparkTexture() {
  const size = 64;
  const canvas = document.createElement('canvas');
  canvas.width = canvas.height = size;
  const context = canvas.getContext('2d')!;
  const glow = context.createRadialGradient(32, 32, 0, 32, 32, 32);
  glow.addColorStop(0, 'rgba(255, 236, 150, 1)');
  glow.addColorStop(0.3, 'rgba(240, 180, 30, 0.85)');
  glow.addColorStop(1, 'rgba(200, 140, 0, 0)');
  context.fillStyle = glow;
  context.fillRect(0, 0, size, size);
  context.fillStyle = 'rgba(255, 240, 170, 1)';
  for (const [w, h] of [
    [3, 30],
    [30, 3],
  ]) {
    context.beginPath();
    context.ellipse(32, 32, w, h, 0, 0, Math.PI * 2);
    context.fill();
  }
  return new CanvasTexture(canvas);
}

export function GoldGlints({
  features,
  terrain,
  stages,
}: {
  features: readonly Pick<Feature, 'id' | 'kind' | 'position'>[];
  terrain: GlobeTerrain;
  stages: NodeStages;
}) {
  const { texture, pools } = useMemo(() => {
    const texture = sparkTexture();
    const pools = features
      .filter((feature) => feature.kind === 'gold_pool')
      .map((feature) => ({
        id: feature.id,
        sprites: glintSpots(new Vector3(...feature.position), terrain).map(
          (spot) => {
            const sprite = new Sprite(
              new SpriteMaterial({
                map: texture,
                depthWrite: false,
                transparent: true,
              }),
            );
            sprite.position.copy(spot);
            return sprite;
          },
        ),
      }));
    return { texture, pools };
  }, [features, terrain]);
  useEffect(
    () => () => {
      texture.dispose();
      for (const { sprites } of pools)
        for (const sprite of sprites) sprite.material.dispose();
    },
    [texture, pools],
  );
  useEffect(() => {
    window.__pebbleGlints = () =>
      Object.fromEntries(
        pools.map(({ id, sprites }) => [
          id,
          sprites.filter((sprite) => sprite.visible).length,
        ]),
      );
    return () => {
      delete window.__pebbleGlints;
    };
  }, [pools]);

  useFrame(({ clock }) => {
    const time = clock.elapsedTime;
    for (const { id, sprites } of pools) {
      const showing = glintCount(stages.state(id));
      sprites.forEach((sprite, k) => {
        sprite.visible = k < showing;
        // each glint flares and fades on its own beat
        const beat = Math.sin((time * TWINKLE_HZ + k * 0.37) * Math.PI * 2);
        const flare = Math.max(0, beat) ** 3;
        sprite.scale.setScalar(GLINT_SIZE * (0.35 + 0.65 * flare));
        sprite.material.opacity = 0.35 + 0.65 * flare;
      });
    }
  });

  return (
    <>
      {pools.flatMap(({ sprites }) =>
        sprites.map((sprite) => (
          <primitive key={sprite.uuid} object={sprite} />
        )),
      )}
    </>
  );
}
