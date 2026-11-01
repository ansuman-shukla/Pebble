import { useFrame } from '@react-three/fiber';
import { type RefObject, useEffect, useRef } from 'react';
import { Vector3 } from 'three';

import type { NpcViews } from '@/components/world/globe/globe-npcs';
import type { GameClock } from '@/lib/world/game-clock';
import { propViews, propWorld } from '@/lib/world/prop-motion';
import { windUniforms } from '@/lib/world/wind';

/*
 * The page's side of living props (10 §5.3): inside the Canvas, `LivingProps` tells them the clock (rate and town
 * time), where the citizens are drawn and who of them is shown crafting (a hearth burns while someone works at it),
 * the live fires, and which way is up where the camera is (the wind blows across it). Outside it, `PropHooks` shows the tests what moves. Without them (the flat town page) props run at ×1.
 */

const SECONDS_PER_MINUTE = 60;

export function LivingProps({
  clockRef,
  peopleRef,
  views,
  fires,
}: {
  clockRef: RefObject<GameClock>;
  /** Where each citizen's feet are drawn (world metres). */
  peopleRef: RefObject<Map<string, Vector3>>;
  /** What is drawn of each citizen (the motion shown). */
  views: NpcViews;
  fires: ReadonlyMap<string, { lit: boolean; position: Vector3 }>;
}) {
  const up = useRef(new Vector3());
  const crafters = useRef(new Set<string>());
  useEffect(() => {
    propWorld.people = peopleRef.current;
    propWorld.crafters = crafters.current;
    propWorld.fires = fires;
    return () => {
      propWorld.people = new Map();
      propWorld.crafters = new Set();
      propWorld.fires = new Map();
      propWorld.up = null;
      propWorld.rate = 1;
    };
  }, [peopleRef, fires]);

  useFrame(({ camera }) => {
    const clock = clockRef.current;
    propWorld.rate = clock.rate * SECONDS_PER_MINUTE;
    propWorld.minutes = clock.minutes;
    propWorld.up = up.current.copy(camera.position).normalize();
    const crafting = crafters.current;
    crafting.clear();
    for (const [id, view] of views)
      if (view.motion === 'craft') crafting.add(id);
  });
  return null;
}

/** Hidden DOM hooks for tests: what living props do, refreshed every 0.1 s. */
export function PropHooks() {
  const root = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const timer = window.setInterval(() => {
      const element = root.current;
      if (!element) return;
      const playing = [...propViews.playing.values()].filter(
        ({ count }) => count > 0,
      );
      element.dataset.playing = String(
        playing.reduce((sum, { count }) => sum + count, 0),
      );
      element.dataset.playingKinds = [
        ...new Set(playing.map(({ kind }) => kind)),
      ]
        .sort()
        .join(',');
      element.dataset.turns = [...propViews.turns]
        .map(([id, angle]) => `${id}:${angle.toFixed(4)}`)
        .sort()
        .join(' ');
      element.dataset.openDoors = [...propViews.openDoors].sort().join(',');
      element.dataset.hidden = [...propViews.hidden].sort().join(',');
      element.dataset.hearths = [...propViews.hearths]
        .map(([id, heat]) => `${id}:${heat.toFixed(2)}`)
        .sort()
        .join(' ');
      element.dataset.puffs = String(propViews.puffs);
      element.dataset.sparks = String(propViews.sparks);
      element.dataset.wind = windUniforms.windStrength.value.toFixed(3);
      element.dataset.windTime = windUniforms.windTime.value.toFixed(3);
      element.dataset.clipTime = propWorld.clipTime.toFixed(3);
    }, 100);
    return () => window.clearInterval(timer);
  }, []);
  return <div ref={root} hidden data-testid="props" />;
}
