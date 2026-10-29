import { useState } from 'react';

import { LabelStore, type UpAt } from '@/lib/world/label-store';

/** One label store for the page's lifetime; `up` is read once (flat scenes: +y). */
export function useLabelStore(up?: UpAt) {
  return useState(() => new LabelStore(up))[0];
}
