import { useFrame } from '@react-three/fiber';
import { useRef } from 'react';

/** Frames rendered after everything is ready before the renderer's counters are first sampled... */
const STATS_AFTER_FRAMES = 30;
/** ...and between later samples, so the counters follow the view as it moves. */
const STATS_EVERY_FRAMES = 60;

export interface RenderStats {
  calls: number;
  triangles: number;
}

/** Samples the renderer's draw calls and triangles once `active` has held for a few frames, then every second. */
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
    if (!active) return;
    frames.current += 1;
    if (frames.current < STATS_AFTER_FRAMES) return;
    frames.current = STATS_AFTER_FRAMES - STATS_EVERY_FRAMES;
    const { calls, triangles } = gl.info.render;
    onSample({ calls, triangles });
  });
  return null;
}
