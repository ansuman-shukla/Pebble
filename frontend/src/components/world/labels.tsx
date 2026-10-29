import { useFrame } from '@react-three/fiber';
import { useEffect, useRef, useSyncExternalStore } from 'react';
import { type Group, Vector3 } from 'three';

import { type LabelBox, stackLabels } from '@/lib/world/label-layout';
import type { LabelStore } from '@/lib/world/label-store';

/*
 * Labels over 3D objects: anchors live in the scene, the text lives in one DOM overlay (both go through the
 * label store, lib/world/label-store.ts), and a projector moves each label to its subject's anchor on screen every
 * frame, stacking labels that would overlap. (drei's <Html> creates a React root per label and dropped one of them
 * reliably in this app.)
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
