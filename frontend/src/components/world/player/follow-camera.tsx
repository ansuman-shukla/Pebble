import { useFrame, useThree } from '@react-three/fiber';
import { type RefObject, useCallback, useEffect } from 'react';

import { PLAYER_EYE_HEIGHT, type PlayerState } from './player-state';
import { useDrag } from './use-drag';

/** Orbit around the player, kept by the walker so it survives camera mode switches. */
export interface FollowRig {
  yaw: number;
  pitch: number;
  distance: number;
}

const DRAG_SPEED = 0.005;
const PITCH_RANGE: [number, number] = [0.05, 1.45];
const DISTANCE_RANGE: [number, number] = [3, 25];

const clamp = (value: number, [min, max]: [number, number]) =>
  Math.min(max, Math.max(min, value));

/** Third person: behind and above the player; drag orbits around it, the wheel zooms. */
export function FollowCamera({
  playerRef,
  rigRef,
}: {
  playerRef: RefObject<PlayerState>;
  rigRef: RefObject<FollowRig>;
}) {
  const canvas = useThree((state) => state.gl.domElement);

  useDrag(
    useCallback(
      (dx: number, dy: number) => {
        const rig = rigRef.current;
        rig.yaw -= dx * DRAG_SPEED;
        rig.pitch = clamp(rig.pitch + dy * DRAG_SPEED, PITCH_RANGE);
      },
      [rigRef],
    ),
  );

  useEffect(() => {
    const zoom = (event: WheelEvent) => {
      event.preventDefault();
      const rig = rigRef.current;
      rig.distance = clamp(
        rig.distance * Math.exp(event.deltaY * 0.001),
        DISTANCE_RANGE,
      );
    };
    canvas.addEventListener('wheel', zoom, { passive: false });
    return () => canvas.removeEventListener('wheel', zoom);
  }, [canvas, rigRef]);

  useFrame(({ camera }) => {
    const rig = rigRef.current;
    const { x, y, z } = playerRef.current.position;
    const flat = Math.cos(rig.pitch) * rig.distance;
    camera.position.set(
      x + Math.sin(rig.yaw) * flat,
      y + PLAYER_EYE_HEIGHT + Math.sin(rig.pitch) * rig.distance,
      z + Math.cos(rig.yaw) * flat,
    );
    camera.lookAt(x, y + PLAYER_EYE_HEIGHT, z);
  });

  return null;
}
