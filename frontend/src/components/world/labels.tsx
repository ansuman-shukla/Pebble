import { useFrame } from '@react-three/fiber';
import {
  Armchair,
  Crosshair,
  Droplet,
  Fish,
  Flame,
  Footprints,
  Hammer,
  type LucideIcon,
  MessageCircle,
  Moon,
  PersonStanding,
  Skull,
  Sprout,
  Utensils,
  Wind,
} from 'lucide-react';
import { useEffect, useRef, useSyncExternalStore } from 'react';
import { type Camera, type Group, Vector3 } from 'three';

import {
  type BubbleAnchor,
  type ChipAnchor,
  type ChipSize,
  type ChipView,
  type LabelBox,
  layoutBubbles,
  layoutChips,
  type PlacedChip,
  stackLabels,
} from '@/lib/world/label-layout';
import type {
  ChipIcon,
  LabelContent,
  LabelStore,
} from '@/lib/world/label-store';

/*
 * Labels over 3D objects: anchors live in the scene, the text lives in one DOM overlay (both go through the
 * label store, lib/world/label-store.ts), and a projector moves each label to its subject's anchor on screen every
 * frame: the town and gallery stack name tags that would overlap, the globe draws chips that cluster instead
 * (lib/world/label-layout.ts). (drei's <Html> creates a React root per label and dropped one of them reliably in
 * this app.)
 */

/**
 * An anchor inside the scene: `subject`'s labels hang `lift` metres above wherever this is placed, unless an anchor
 * with a higher `priority` (or a newer one with the same) is live for the subject.
 */
export function LabelAnchor({
  store,
  subject,
  lift = 0,
  priority = 0,
}: {
  store: LabelStore;
  subject: string;
  lift?: number;
  priority?: number;
}) {
  const anchor = useRef<Group>(null);
  useEffect(
    () => store.anchor(subject, anchor.current!, lift, priority),
    [store, subject, lift, priority],
  );
  return <group ref={anchor} />;
}

/** A name tag `height` metres above its parent object: its anchor and its text in one. */
export function Label({
  store,
  id,
  text,
  height,
}: {
  store: LabelStore;
  id: string;
  text: string;
  height: number;
}) {
  useEffect(
    () => store.describe(id, [{ id, subject: id, kind: 'name', text }]),
    [store, id, text],
  );
  return <LabelAnchor store={store} subject={id} lift={height} />;
}

const projected = new Vector3();

/**
 * Inside the Canvas: moves every label to its anchor's screen position, hiding those beyond maxDistance and
 * nudging farther ones up out of nearer ones (speech bubbles stay on top).
 */
export function LabelProjector({
  store,
  maxDistance = Infinity,
}: {
  store: LabelStore;
  maxDistance?: number;
}) {
  useFrame(({ camera, size }) => {
    const shown: { element: HTMLElement; box: LabelBox }[] = [];
    for (const { id, subject, kind } of store.getSnapshot()) {
      const element = store.elements.get(id);
      if (!element) continue;
      const anchored = store.anchorPosition(subject, projected) !== null;
      const distance = projected.distanceTo(camera.position);
      const near = anchored && distance <= maxDistance;
      projected.project(camera);
      const onScreen =
        near &&
        projected.z < 1 &&
        Math.abs(projected.x) < 1.1 &&
        Math.abs(projected.y) < 1.1;
      element.style.display = onScreen ? '' : 'none';
      if (!onScreen) continue;
      const x = ((projected.x + 1) / 2) * size.width;
      const bottom = ((1 - projected.y) / 2) * size.height;
      shown.push({
        element,
        box: { x, bottom, width: 0, height: 0, distance, kind },
      });
    }
    // sizes are read after every display change: one layout per frame
    for (const { element, box } of shown) {
      box.width = element.offsetWidth;
      box.height = element.offsetHeight;
    }
    const bottoms = stackLabels(shown.map(({ box }) => box));
    shown.forEach(({ element, box }, index) => {
      element.style.transform = `translate(${box.x}px, ${bottoms[index]}px) translate(-50%, -100%)`;
    });
  });
  return null;
}

/** Outside the Canvas, layered over it: the label text. */
export function LabelOverlay({ store }: { store: LabelStore }) {
  const entries = useSyncExternalStore(store.subscribe, store.getSnapshot);
  return (
    <div className="pointer-events-none absolute inset-0 overflow-hidden">
      {entries.map(({ id, text, kind }) => (
        <span
          key={id}
          data-label={id}
          data-label-kind={kind}
          ref={(element) => {
            if (!element) return;
            store.elements.set(id, element);
            return () => {
              store.elements.delete(id);
            };
          }}
          className={
            kind === 'speech'
              ? 'absolute top-0 left-0 z-10 w-max max-w-56 rounded-lg bg-white/95 px-2 py-1 text-xs text-black shadow'
              : 'absolute top-0 left-0 rounded bg-black/60 px-1.5 py-0.5 text-[11px] whitespace-nowrap text-white'
          }
        >
          {text}
        </span>
      ))}
    </div>
  );
}

const CHIP_ICONS: Record<ChipIcon, LucideIcon> = {
  stand: PersonStanding,
  walk: Footprints,
  run: Wind,
  sleep: Moon,
  rest: Armchair,
  gather: Sprout,
  eat: Utensils,
  drink: Droplet,
  work: Hammer,
  hunt: Crosshair,
  fish: Fish,
  fire: Flame,
  talk: MessageCircle,
  dead: Skull,
};

/** Rough sizes (px) before a chip or bubble is first drawn in a view; measured sizes replace them. */
const CHAR_PX = 6.5;
const CHIP_PX = 24;
const BUBBLE_WIDTH_PX = 224;
const BUBBLE_LINE_PX = 16;

function estimate(content: LabelContent, view: ChipView | 'speech'): ChipSize {
  const words = content.text.length + (content.detail?.length ?? 0) + 3;
  switch (view) {
    case 'icon':
      return { width: CHIP_PX, height: CHIP_PX };
    case 'cluster-icon':
      return { width: CHIP_PX * 2, height: CHIP_PX };
    case 'full':
    case 'cluster':
      return { width: words * CHAR_PX + CHIP_PX + 12, height: CHIP_PX };
    case 'speech': {
      const width = Math.min(BUBBLE_WIDTH_PX, words * CHAR_PX + 16);
      const lines = Math.ceil((words * CHAR_PX) / (BUBBLE_WIDTH_PX - 16));
      return { width, height: lines * BUBBLE_LINE_PX + 8 };
    }
  }
}

/** What a cluster chip says: "3 · asleep" when all do the same, else "3 people"; farther, just the count. */
function clusterWords(chip: PlacedChip, chips: Map<string, LabelContent>) {
  const count = chip.members.length;
  if (chip.view === 'cluster-icon') return String(count);
  const doing = new Set(chip.members.map((id) => chips.get(id)?.detail));
  const [detail] = doing;
  return doing.size === 1 && detail
    ? `${count} · ${detail}`
    : `${count} people`;
}

/** Projects `subject`'s anchor: its screen spot (CSS px) and distance, or null when it has none or is off screen. */
function onScreen(
  store: LabelStore,
  subject: string,
  camera: Camera,
  size: { width: number; height: number },
) {
  if (!store.anchorPosition(subject, projected)) return null;
  const distance = projected.distanceTo(camera.position);
  projected.project(camera);
  if (
    projected.z >= 1 ||
    Math.abs(projected.x) >= 1.1 ||
    Math.abs(projected.y) >= 1.1
  )
    return null;
  return {
    x: ((projected.x + 1) / 2) * size.width,
    y: ((1 - projected.y) / 2) * size.height,
    distance,
  };
}

const place = (element: HTMLElement, x: number, bottom: number) => {
  element.style.transform = `translate(${x}px, ${bottom}px) translate(-50%, -100%)`;
};

const setText = (element: Element | null, text: string) => {
  if (element && element.textContent !== text) element.textContent = text;
};

/**
 * Inside the Canvas: lays out the chips and speech bubbles every frame (full near, icons farther, overlapping
 * chips clustered, `pinned` subjects always whole) and moves their elements there. Sizes are measured as each
 * element is drawn, for the next frame's layout.
 */
export function ChipProjector({
  store,
  pinned,
}: {
  store: LabelStore;
  pinned: readonly string[];
}) {
  const sizes = useRef(new Map<string, ChipSize>());
  useFrame(({ camera, size }) => {
    const chipOf = new Map<string, LabelContent>();
    const speech: LabelContent[] = [];
    for (const content of store.getSnapshot())
      if (content.kind === 'speech') speech.push(content);
      else chipOf.set(content.subject, content);
    const spots = new Map<string, ChipAnchor>();
    const spotOf = (subject: string) => {
      if (!spots.has(subject)) {
        const spot = onScreen(store, subject, camera, size);
        if (spot)
          spots.set(subject, {
            id: subject,
            ...spot,
            pinned: pinned.includes(subject),
          });
      }
      return spots.get(subject);
    };
    const measured = (content: LabelContent, view: ChipView | 'speech') =>
      sizes.current.get(`${content.id}:${view}`) ?? estimate(content, view);

    const anchors = [...chipOf.keys()]
      .map(spotOf)
      .filter((spot) => spot !== undefined);
    const chips = layoutChips(anchors, (subject, view) =>
      measured(chipOf.get(subject)!, view),
    );
    const leading = new Map(chips.map((chip) => [chip.leader, chip]));
    const bubbles = layoutBubbles(
      speech.flatMap((content): BubbleAnchor[] => {
        const spot = spotOf(content.subject);
        return spot
          ? [{ ...spot, id: content.id, ...measured(content, 'speech') }]
          : [];
      }),
      chips,
    );
    const shownBubbles = new Map(bubbles.map((bubble) => [bubble.id, bubble]));

    const drawn: { element: HTMLElement; key: string }[] = [];
    for (const [subject, content] of chipOf) {
      const element = store.elements.get(content.id);
      if (!element) continue;
      const chip = leading.get(subject);
      element.style.display = chip ? '' : 'none';
      if (!chip) continue;
      element.dataset.view = chip.view;
      element.dataset.members = chip.members.join(' ');
      setText(
        element.querySelector('[data-chip-count]'),
        chip.members.length > 1 ? clusterWords(chip, chipOf) : '',
      );
      place(element, chip.x, chip.bottom);
      drawn.push({ element, key: `${content.id}:${chip.view}` });
    }
    for (const content of speech) {
      const element = store.elements.get(content.id);
      if (!element) continue;
      const bubble = shownBubbles.get(content.id);
      element.style.display = bubble ? '' : 'none';
      if (!bubble) continue;
      place(element, bubble.x, bubble.bottom);
      drawn.push({ element, key: `${content.id}:speech` });
    }
    // read after every change above: one layout per frame
    for (const { element, key } of drawn)
      sizes.current.set(key, {
        width: element.offsetWidth,
        height: element.offsetHeight,
      });
  });
  return null;
}

const RING_CLASS = {
  need: 'ring-2 ring-orange-400',
  hurt: 'ring-2 ring-red-500',
};

function Chip({ content }: { content: LabelContent }) {
  const Icon = content.icon && CHIP_ICONS[content.icon];
  return (
    <>
      {Icon && (
        <span
          data-chip-icon={content.icon}
          data-chip-ring={content.ring}
          className={`flex size-5 shrink-0 items-center justify-center rounded-full bg-black/40 ${content.ring ? RING_CLASS[content.ring] : ''}`}
        >
          <Icon className="size-3.5" aria-hidden />
        </span>
      )}
      <span className="block max-w-56 truncate group-data-[view=cluster]:hidden group-data-[view=cluster-icon]:hidden group-data-[view=icon]:hidden">
        <span className="font-medium">{content.text}</span>
        {content.detail && ` · ${content.detail}`}
      </span>
      <span
        data-chip-count
        className="hidden max-w-56 truncate group-data-[view=cluster]:block group-data-[view=cluster-icon]:block"
      />
    </>
  );
}

/** Outside the Canvas, layered over it: the chips and speech bubbles (ChipProjector places them). */
export function ChipOverlay({ store }: { store: LabelStore }) {
  const entries = useSyncExternalStore(store.subscribe, store.getSnapshot);
  return (
    <div className="pointer-events-none absolute inset-0 overflow-hidden">
      {entries.map((content) => (
        <div
          key={content.id}
          data-label={content.id}
          data-label-kind={content.kind}
          data-view="full"
          style={{ display: 'none' }}
          ref={(element) => {
            if (!element) return;
            store.elements.set(content.id, element);
            return () => {
              store.elements.delete(content.id);
            };
          }}
          className={
            content.kind === 'speech'
              ? 'absolute top-0 left-0 z-10 w-max max-w-56 rounded-lg bg-white/95 px-2 py-1 text-xs text-black shadow'
              : 'group absolute top-0 left-0 flex h-6 items-center gap-1 rounded-full bg-black/60 p-0.5 pr-2 text-[11px] whitespace-nowrap text-white data-[view=icon]:pr-0.5'
          }
        >
          {content.kind === 'speech' ? (
            content.text
          ) : (
            <Chip content={content} />
          )}
        </div>
      ))}
    </div>
  );
}
