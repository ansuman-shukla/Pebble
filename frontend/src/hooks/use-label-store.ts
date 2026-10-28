import { useState } from 'react';

import { LabelStore } from '@/lib/world/label-store';

export function useLabelStore() {
  return useState(() => new LabelStore())[0];
}
