import { useEffect, useRef } from 'react';

const TYPING_TARGETS = 'input, textarea, select, button, [contenteditable]';

/**
 * Keys held down (KeyboardEvent.code), read every frame. Key presses aimed at form controls are ignored;
 * releases always count so a key can never stick.
 */
export function useKeys(onPress?: (code: string) => void) {
  const held = useRef(new Set<string>());
  const press = useRef(onPress);

  useEffect(() => {
    press.current = onPress;
  }, [onPress]);

  useEffect(() => {
    const keys = held.current;
    const down = (event: KeyboardEvent) => {
      if (event.metaKey || event.ctrlKey || event.altKey) return;
      if (
        event.target instanceof Element &&
        event.target.closest(TYPING_TARGETS)
      )
        return;
      keys.add(event.code);
      if (!event.repeat) press.current?.(event.code);
    };
    const up = (event: KeyboardEvent) => keys.delete(event.code);
    const clear = () => keys.clear();
    window.addEventListener('keydown', down);
    window.addEventListener('keyup', up);
    window.addEventListener('blur', clear);
    return () => {
      window.removeEventListener('keydown', down);
      window.removeEventListener('keyup', up);
      window.removeEventListener('blur', clear);
      keys.clear();
    };
  }, []);

  return held;
}

/** -1, 0 or 1 from a pair of key sets (e.g. back/forward). */
export function axis(
  keys: Set<string>,
  negative: string[],
  positive: string[],
) {
  const pressed = (codes: string[]) => codes.some((code) => keys.has(code));
  return Number(pressed(positive)) - Number(pressed(negative));
}

export const isRunning = (keys: Set<string>) =>
  keys.has('ShiftLeft') || keys.has('ShiftRight');

export const FORWARD = ['KeyW', 'ArrowUp'];
export const BACK = ['KeyS', 'ArrowDown'];
export const LEFT = ['KeyA', 'ArrowLeft'];
export const RIGHT = ['KeyD', 'ArrowRight'];
