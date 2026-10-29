/** The clock's speeds in button order (keys 1-4): game seconds per real second (D65). */
export const CLOCK_SPEEDS: {
  label: string;
  title: string;
  change: { speed: number; paused: false };
}[] = [
  {
    label: '×1',
    title: 'real time: citizens walk at your pace',
    change: { speed: 1, paused: false },
  },
  {
    label: '×10',
    title: 'ten times faster: a tick every 6 s',
    change: { speed: 10, paused: false },
  },
  {
    label: '×60',
    title: 'a game hour per real minute',
    change: { speed: 60, paused: false },
  },
  {
    label: '×600',
    title: 'time-lapse: a game day in 2.4 minutes',
    change: { speed: 600, paused: false },
  },
];
