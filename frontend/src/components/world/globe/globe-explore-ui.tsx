import { useEffect, useRef, useState } from 'react';

import { Button } from '@/components/ui/button';
import type { DropTarget, GoToSite } from './globe-drop';

/*
 * The exploring controls over the globe: the pegman (click it, then click the planet; or drag it onto the
 * planet) and the "Go to" menu of named sites.
 */

/** Drag data type of the pegman, so the page only accepts drops that carry it. */
export const PEGMAN_DRAG = 'application/x-pebble-pegman';

/** The pin that follows the pointer while dropping: amber over land, grey over water (with a note). */
export function DropPin({
  x,
  y,
  target,
}: {
  x: number;
  y: number;
  target: DropTarget;
}) {
  const land = target === 'land';
  return (
    <div
      aria-hidden="true"
      data-testid="drop-pin"
      data-target={target ?? 'none'}
      className="pointer-events-none fixed z-20 flex items-start gap-1"
      // the pin's tip (12, 31) sits on the pointer
      style={{ left: x - 12, top: y - 31 }}
    >
      <svg width="24" height="32" viewBox="0 0 24 32">
        <path
          d="M12 31s10-11.3 10-19A10 10 0 0 0 2 12c0 7.7 10 19 10 19z"
          fill={land ? '#e8a33a' : '#9aa3ad'}
          stroke={land ? '#5b3a0e' : '#47505a'}
          strokeWidth="1.5"
        />
        <circle cx="12" cy="12" r="4" fill="#fff" />
      </svg>
      {target === 'water' && (
        <span className="rounded bg-white/90 px-1.5 py-0.5 text-xs shadow">
          water
        </span>
      )}
    </div>
  );
}

function PegmanIcon() {
  return (
    <svg
      aria-hidden="true"
      width="14"
      height="18"
      viewBox="0 0 14 18"
      className="shrink-0"
    >
      <circle cx="7" cy="3.2" r="2.7" fill="#e8a33a" />
      <path
        d="M3 7.5a4 4 0 0 1 8 0V12H9.5v5.5h-5V12H3z"
        fill="#e8a33a"
        stroke="#5b3a0e"
        strokeWidth="0.8"
      />
    </svg>
  );
}

/** Toggles drop mode; can also be dragged onto the planet. */
export function Pegman({
  active,
  onToggle,
}: {
  active: boolean;
  onToggle: () => void;
}) {
  return (
    <Button
      size="sm"
      variant={active ? 'default' : 'outline'}
      aria-pressed={active}
      title="Drop yourself anywhere: click, then click the planet (or drag me onto it)"
      draggable
      onDragStart={(event) => {
        event.dataTransfer.setData(PEGMAN_DRAG, 'pegman');
        event.dataTransfer.effectAllowed = 'move';
      }}
      onClick={(event) => {
        onToggle();
        event.currentTarget.blur();
      }}
    >
      <PegmanIcon />
      drop
    </Button>
  );
}

/** A button opening the list of named sites; picking one drops the player there. */
export function GoToMenu({
  sites,
  onPick,
}: {
  sites: GoToSite[];
  onPick: (id: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const menu = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const close = (event: PointerEvent | KeyboardEvent) => {
      if (event instanceof KeyboardEvent && event.key !== 'Escape') return;
      if (
        event instanceof PointerEvent &&
        event.target instanceof Node &&
        menu.current?.contains(event.target)
      )
        return;
      setOpen(false);
    };
    window.addEventListener('pointerdown', close);
    window.addEventListener('keydown', close);
    return () => {
      window.removeEventListener('pointerdown', close);
      window.removeEventListener('keydown', close);
    };
  }, [open]);

  return (
    <div ref={menu} className="relative">
      <Button
        size="sm"
        variant={open ? 'default' : 'outline'}
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={(event) => {
          setOpen((on) => !on);
          event.currentTarget.blur();
        }}
      >
        go to ▾
      </Button>
      {open && (
        <div
          role="menu"
          aria-label="Go to"
          className="absolute top-full left-0 z-10 mt-1 flex min-w-44 flex-col rounded-lg bg-white p-1 shadow-lg"
        >
          {sites.map((site) => (
            <button
              key={site.id}
              type="button"
              role="menuitem"
              className="rounded-md px-2 py-1 text-left text-sm hover:bg-black/5"
              onClick={(event) => {
                setOpen(false);
                event.currentTarget.blur();
                onPick(site.id);
              }}
            >
              {site.name}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
