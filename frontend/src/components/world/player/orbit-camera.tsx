import { CameraControls } from '@react-three/drei';
import { useEffect, useRef } from 'react';

/** Ground rectangle the orbit camera frames: centre (x, z) and the longer side in metres. */
export interface PlaceBounds {
  center: [number, number];
  size: number;
}

/** Bird's-eye view over the whole place; drag rotates, right-drag pans, the wheel zooms. */
export function OrbitCamera({ bounds }: { bounds: PlaceBounds }) {
  const controls = useRef<CameraControls>(null);

  useEffect(() => {
    const [x, z] = bounds.center;
    controls.current?.setLookAt(
      x,
      bounds.size * 0.8,
      z + bounds.size * 0.6,
      x,
      0,
      z,
      false,
    );
  }, [bounds]);

  return (
    <CameraControls
      ref={controls}
      maxPolarAngle={Math.PI / 2.05}
      maxDistance={bounds.size * 3}
    />
  );
}
