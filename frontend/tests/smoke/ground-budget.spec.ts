import { expect, test } from '@playwright/test';

import { openGlobe } from './globe-helpers';

/*
 * The ground shader's frame cost against the flat ground (bible §5.1: at most 1.5 ms a frame), at street level
 * outside the town walls where the ground fills most of the view.
 */

// South of the town, outside its walls and ground disc: open grassland at street level, facing the town.
const OUTSIDE_THE_WALLS = '?at=31.2,12,0&time=12:00';

/** Mean frame time (ms) over 2 s of animation frames. */
const FRAME_TIME = `new Promise((resolve) => {
  const stamps = [];
  const step = (now) => {
    stamps.push(now);
    if (now - stamps[0] < 2000) requestAnimationFrame(step);
    else resolve((now - stamps[0]) / (stamps.length - 1));
  };
  requestAnimationFrame(step);
})`;

// uncapped frames, so the shader's cost shows in the frame time instead of hiding under vsync
test.use({
  viewport: { width: 1920, height: 1080 },
  launchOptions: {
    args: [
      ...(process.platform === 'darwin'
        ? ['--use-angle=metal', '--ignore-gpu-blocklist']
        : []),
      '--disable-frame-rate-limit',
      '--disable-gpu-vsync',
    ],
  },
});

test('the detailed ground costs at most 1.5 ms a frame more than the flat one', async ({
  page,
}) => {
  test.setTimeout(240_000);
  const errors: string[] = [];
  const frameTime = () => page.evaluate<number>(FRAME_TIME);
  // alternate the two looks and keep each one's best run: other work on the machine only ever slows a run down
  const best: Record<string, number> = { flat: Infinity, full: Infinity };
  for (let round = 0; round < 3; round++)
    for (const quality of ['flat', 'full']) {
      await openGlobe(page, errors, `${OUTSIDE_THE_WALLS}&ground=${quality}`);
      await page.waitForTimeout(1500);
      best[quality] = Math.min(best[quality], await frameTime());
    }
  expect(best.full - best.flat).toBeLessThanOrEqual(1.5);
  expect(errors).toEqual([]);
});
