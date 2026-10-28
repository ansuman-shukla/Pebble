import { useThree } from '@react-three/fiber';
import { useEffect, useRef } from 'react';

/** Calls back with pointer movement (pixels) while the user drags on the canvas. */
export function useDrag(onDrag: (dx: number, dy: number) => void) {
  const canvas = useThree((state) => state.gl.domElement);
  const drag = useRef(onDrag);

  useEffect(() => {
    drag.current = onDrag;
  }, [onDrag]);

  useEffect(() => {
    let last: { x: number; y: number } | null = null;
    const down = (event: PointerEvent) => {
      last = { x: event.clientX, y: event.clientY };
      canvas.setPointerCapture(event.pointerId);
    };
    const move = (event: PointerEvent) => {
      if (!last) return;
      drag.current(event.clientX - last.x, event.clientY - last.y);
      last = { x: event.clientX, y: event.clientY };
    };
    const up = (event: PointerEvent) => {
      last = null;
      if (canvas.hasPointerCapture(event.pointerId))
        canvas.releasePointerCapture(event.pointerId);
    };
    canvas.addEventListener('pointerdown', down);
    canvas.addEventListener('pointermove', move);
    canvas.addEventListener('pointerup', up);
    canvas.addEventListener('pointercancel', up);
    return () => {
      canvas.removeEventListener('pointerdown', down);
      canvas.removeEventListener('pointermove', move);
      canvas.removeEventListener('pointerup', up);
      canvas.removeEventListener('pointercancel', up);
    };
  }, [canvas]);
}
