/*
 * Keeps screen labels from covering each other: a greedy pass that leaves the nearest label where it is and
 * nudges each farther one straight up until it clears every label already placed. Speech bubbles are placed
 * after every name tag, so they always end up above the tags they would cover.
 */

/** A label on screen, in CSS pixels: anchored at its bottom centre. */
export interface LabelBox {
  x: number;
  bottom: number;
  width: number;
  height: number;
  /** From the camera (metres): nearer labels keep their spot. */
  distance: number;
  kind: 'name' | 'speech';
}

/** Space kept between stacked labels (px). */
const GAP = 2;

const overlaps = (box: LabelBox, bottom: number, other: Placed) =>
  Math.abs(box.x - other.x) < (box.width + other.width) / 2 &&
  bottom > other.top &&
  bottom - box.height < other.bottom;

interface Placed {
  x: number;
  width: number;
  top: number;
  bottom: number;
}

/** The bottom (px) each label is drawn at, in the order given. */
export function stackLabels(boxes: readonly LabelBox[]): number[] {
  const order = boxes
    .map((box, index) => ({ box, index }))
    .sort(
      (a, b) =>
        Number(a.box.kind === 'speech') - Number(b.box.kind === 'speech') ||
        a.box.distance - b.box.distance,
    );
  const placed: Placed[] = [];
  const bottoms = boxes.map((box) => box.bottom);
  for (const { box, index } of order) {
    let bottom = box.bottom;
    // moving up only, so this ends once the label is above everything it met
    for (
      let hit = placed.find((other) => overlaps(box, bottom, other));
      hit;
      hit = placed.find((other) => overlaps(box, bottom, other))
    )
      bottom = hit.top - GAP;
    bottoms[index] = bottom;
    placed.push({
      x: box.x,
      width: box.width,
      top: bottom - box.height,
      bottom,
    });
  }
  return bottoms;
}
