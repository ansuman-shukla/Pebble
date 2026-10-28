import { useFrame, useThree } from '@react-three/fiber';
import { useCallback, useEffect, useMemo, useRef } from 'react';
import { Vector3 } from 'three';

import { useDrag } from './use-drag';
import {
  axis,
  BACK,
  FORWARD,
  isRunning,
  LEFT,
  RIGHT,
  useKeys,
} from './use-keys';

const FLY_SPEED = 8;
const FAST_FLY_SPEED = 24;
const LOOK_SPEED = 0.004;
const MAX_PITCH = 1.5;
const MAX_FRAME = 0.1;
const UP = new Vector3(0, 1, 0);

const clampPitch = (pitch: number) =>
  Math.min(MAX_PITCH, Math.max(-MAX_PITCH, pitch));

/** Free flight from wherever the camera is: WASD fly, Q/E down/up, Shift faster, drag to look. */
export function FlyCamera() {
  const camera = useThree((state) => state.camera);
  const keys = useKeys();
  const look = useRef({ yaw: 0, pitch: 0 });
  const vectors = useMemo(
    () => ({
      forward: new Vector3(),
      right: new Vector3(),
      move: new Vector3(),
    }),
    [],
  );

  useEffect(() => {
    const direction = camera.getWorldDirection(new Vector3());
    look.current = {
      yaw: Math.atan2(direction.x, direction.z),
      pitch: clampPitch(Math.asin(direction.y)),
    };
  }, [camera]);

  useDrag(
    useCallback((dx: number, dy: number) => {
      look.current.yaw -= dx * LOOK_SPEED;
      look.current.pitch = clampPitch(look.current.pitch - dy * LOOK_SPEED);
    }, []),
  );

  useFrame((state, frameDelta) => {
    const { forward, right, move } = vectors;
    const { yaw, pitch } = look.current;
    forward.set(
      Math.sin(yaw) * Math.cos(pitch),
      Math.sin(pitch),
      Math.cos(yaw) * Math.cos(pitch),
    );
    right.crossVectors(forward, UP).normalize();
    move
      .set(0, 0, 0)
      .addScaledVector(forward, axis(keys.current, BACK, FORWARD))
      .addScaledVector(right, axis(keys.current, LEFT, RIGHT))
      .addScaledVector(UP, axis(keys.current, ['KeyQ'], ['KeyE']));
    if (move.lengthSq() > 0) {
      const speed = isRunning(keys.current) ? FAST_FLY_SPEED : FLY_SPEED;
      state.camera.position.addScaledVector(
        move.normalize(),
        speed * Math.min(frameDelta, MAX_FRAME),
      );
    }
    state.camera.lookAt(
      state.camera.position.x + forward.x,
      state.camera.position.y + forward.y,
      state.camera.position.z + forward.z,
    );
  });

  return null;
}
