import { useFrame } from '@react-three/fiber';
import { useEffect, useRef, useSyncExternalStore } from 'react';
import { type Group, Vector3 } from 'three';

import type { LabelStore } from '@/lib/world/label-store';

/*
 * Name labels over 3D objects: anchors live in the scene, the text lives in one DOM overlay, and a projector
 * moves each label to its anchor's screen position every frame. (drei's <Html> creates a React root per label
 * and dropped one of them reliably in this app.)
 */

type LabelProps = {
  store: LabelStore;
  id: string;
  text: string;
  height: number;
};

/** An anchor inside the scene; place it as a child of the object it names. */
export function Label({ store, id, text, height }: LabelProps) {
  const anchor = useRef<Group>(null);
  useEffect(
    () => store.add({ id, text, anchor: anchor.current! }),
    [store, id, text],
  );
  return <group ref={anchor} position={[0, height, 0]} />;
}

const projected = new Vector3();

/** Inside the Canvas: moves every label to its anchor's screen position. */
export function LabelProjector({ store }: { store: LabelStore }) {
  useFrame(({ camera, size }) => {
    for (const { id, anchor } of store.getSnapshot()) {
      const element = store.elements.get(id);
      if (!element) continue;
      anchor.getWorldPosition(projected).project(camera);
      const onScreen =
        projected.z < 1 &&
        Math.abs(projected.x) < 1.1 &&
        Math.abs(projected.y) < 1.1;
      element.style.display = onScreen ? '' : 'none';
      if (!onScreen) continue;
      const x = ((projected.x + 1) / 2) * size.width;
      const y = ((1 - projected.y) / 2) * size.height;
      element.style.transform = `translate(${x}px, ${y}px) translate(-50%, -100%)`;
    }
  });
  return null;
}

/** Outside the Canvas, layered over it: the label text. */
export function LabelOverlay({ store }: { store: LabelStore }) {
  const entries = useSyncExternalStore(store.subscribe, store.getSnapshot);
  return (
    <div className="pointer-events-none absolute inset-0 overflow-hidden">
      {entries.map(({ id, text }) => (
        <span
          key={id}
          data-label={id}
          ref={(element) => {
            if (!element) return;
            store.elements.set(id, element);
            return () => {
              store.elements.delete(id);
            };
          }}
          className="absolute top-0 left-0 rounded bg-black/60 px-1.5 py-0.5 text-[11px] whitespace-nowrap text-white"
        >
          {text}
        </span>
      ))}
    </div>
  );
}
