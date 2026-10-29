/*
 * Keeps screen labels from covering each other.
 * - Name tags (town and gallery pages): a greedy pass that leaves the nearest label where it is and nudges each
 *   farther one straight up until it clears every label already placed. Speech bubbles are placed after every
 *   name tag, so they always end up above the tags they would cover.
 * - Chips (the globe, 10-world-v1 §5.4): full chips near the camera, icon chips farther, none beyond. Chips that
 *   would overlap merge into one cluster chip ("3 · asleep") instead of stacking into towers; selected and
 *   followed chips stay whole (others cluster above them). At most MAX_CHIPS chips and MAX_BUBBLES speech bubbles,
 *   nearest first.
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

/** Full chips (icon, name, what they do) nearer than this (m); icon chips up to ICON_M; none beyond. */
export const FULL_M = 30;
export const ICON_M = 150;
export const MAX_CHIPS = 14;
export const MAX_BUBBLES = 3;

/** How a chip is drawn: whole, icon only, or a cluster of several (with names near, a count farther). */
export type ChipView = 'full' | 'icon' | 'cluster' | 'cluster-icon';

/** A subject's anchor on screen (CSS px, the chip's bottom centre). */
export interface ChipAnchor {
  id: string;
  x: number;
  y: number;
  /** From the camera (m). */
  distance: number;
  /** Selected or followed: always a full chip of its own. */
  pinned: boolean;
}

export interface ChipSize {
  width: number;
  height: number;
}

/** The size a subject's chip takes in a view (measured, or estimated before its first draw). */
export type ChipSizer = (id: string, view: ChipView) => ChipSize;

export interface PlacedChip {
  /** The subject drawn: the nearest of the cluster (or the pinned one). */
  leader: string;
  /** Every subject the chip stands for, the leader first. */
  members: string[];
  pinned: boolean;
  near: boolean;
  view: ChipView;
  x: number;
  bottom: number;
  width: number;
  height: number;
}

const viewOf = (chip: Pick<PlacedChip, 'near' | 'members'>): ChipView =>
  chip.members.length > 1
    ? chip.near
      ? 'cluster'
      : 'cluster-icon'
    : chip.near
      ? 'full'
      : 'icon';

const placedBox = (chip: PlacedChip): Placed => ({
  x: chip.x,
  width: chip.width,
  top: chip.bottom - chip.height,
  bottom: chip.bottom,
});

const meets = (a: Placed, b: Placed) =>
  Math.abs(a.x - b.x) < (a.width + b.width) / 2 &&
  a.top < b.bottom &&
  b.top < a.bottom;

/**
 * The chips to draw for anchors on screen: pinned ones first (stacked if they meet), then the rest nearest first,
 * each joining the cluster it would overlap (a cluster that grows into others swallows them; one that meets a
 * pinned chip moves up above it). Anchors beyond ICON_M and new chips past MAX_CHIPS are left out (pinned ones
 * always show).
 */
export function layoutChips(
  anchors: readonly ChipAnchor[],
  sizeOf: ChipSizer,
): PlacedChip[] {
  const order = anchors
    .filter((anchor) => anchor.pinned || anchor.distance <= ICON_M)
    .sort(
      (a, b) => Number(b.pinned) - Number(a.pinned) || a.distance - b.distance,
    );
  const chips: PlacedChip[] = [];
  const resize = (chip: PlacedChip) => {
    chip.view = viewOf(chip);
    Object.assign(chip, sizeOf(chip.leader, chip.view));
  };
  const liftPastPinned = (chip: PlacedChip) => {
    for (
      let hit = chips.find(
        (other) =>
          other.pinned &&
          other !== chip &&
          meets(placedBox(chip), placedBox(other)),
      );
      hit;
      hit = chips.find(
        (other) =>
          other.pinned &&
          other !== chip &&
          meets(placedBox(chip), placedBox(other)),
      )
    )
      chip.bottom = hit.bottom - hit.height - GAP;
  };
  for (const anchor of order) {
    let chip: PlacedChip = {
      leader: anchor.id,
      members: [anchor.id],
      pinned: anchor.pinned,
      near: anchor.pinned || anchor.distance < FULL_M,
      view: 'full',
      x: anchor.x,
      bottom: anchor.y,
      width: 0,
      height: 0,
    };
    resize(chip);
    if (chip.pinned) {
      liftPastPinned(chip);
      chips.push(chip);
      continue;
    }
    let placed = false;
    // ends: each pass either moves the chip up past a pinned chip (finitely many) or removes a chip by merging
    for (;;) {
      liftPastPinned(chip);
      const box = placedBox(chip);
      const hit = chips.find(
        (other) =>
          !other.pinned && other !== chip && meets(box, placedBox(other)),
      );
      if (!hit) break;
      if (!placed) {
        hit.members.push(...chip.members);
        chip = hit;
        placed = true;
      } else {
        chip.members.push(...hit.members);
        chips.splice(chips.indexOf(hit), 1);
      }
      resize(chip);
    }
    if (!placed && chips.length < MAX_CHIPS) chips.push(chip);
  }
  return chips;
}

/** A speech bubble's anchor on screen and its measured size. */
export interface BubbleAnchor extends ChipAnchor, ChipSize {}

export interface PlacedBubble {
  id: string;
  x: number;
  bottom: number;
}

/**
 * Up to MAX_BUBBLES speech bubbles (pinned speakers first, then the nearest, none beyond ICON_M), each nudged up
 * above every chip and bubble it would cover.
 */
export function layoutBubbles(
  bubbles: readonly BubbleAnchor[],
  chips: readonly PlacedChip[],
): PlacedBubble[] {
  const taken = chips.map(placedBox);
  return bubbles
    .filter((bubble) => bubble.pinned || bubble.distance <= ICON_M)
    .sort(
      (a, b) => Number(b.pinned) - Number(a.pinned) || a.distance - b.distance,
    )
    .slice(0, MAX_BUBBLES)
    .map((bubble) => {
      const box = {
        x: bubble.x,
        width: bubble.width,
        top: bubble.y - bubble.height,
        bottom: bubble.y,
      };
      for (
        let hit = taken.find((other) => meets(box, other));
        hit;
        hit = taken.find((other) => meets(box, other))
      ) {
        box.bottom = hit.top - GAP;
        box.top = box.bottom - bubble.height;
      }
      taken.push(box);
      return { id: bubble.id, x: bubble.x, bottom: box.bottom };
    });
}
