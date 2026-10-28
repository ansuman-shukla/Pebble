import { useFrame } from '@react-three/fiber';
import { useRef } from 'react';

/** Frames rendered after everything is ready before the renderer's counters are sampled. */
const STATS_AFTER_FRAMES = 30;

export interface RenderStats {
  calls: number;
  triangles: number;
}

/** Samples the renderer's draw calls and triangles once, after `active` has held for a few frames. */
export function RenderStatsProbe({
  active,
  onSample,
}: {
  active: boolean;
  onSample: (stats: RenderStats) => void;
}) {
  const frames = useRef(0);
  // useFrame runs before the frame renders, so gl.info still holds the previous frame's counts
  useFrame(({ gl }) => {
    if (!active || frames.current < 0) return;
    frames.current += 1;
    if (frames.current < STATS_AFTER_FRAMES) return;
    frames.current = -1;
    const { calls, triangles } = gl.info.render;
    onSample({ calls, triangles });
  });
  return null;
}
