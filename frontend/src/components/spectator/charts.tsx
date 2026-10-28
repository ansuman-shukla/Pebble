import type { NeedPoint } from '@/lib/client/types.gen';
import { tickLabel } from '@/lib/spectator/time';
import { type Need, NEED_COLORS } from '@/lib/spectator/words';

/*
 * Small SVG charts for the spectator pages (no chart library): needs over time as lines, and labelled bars.
 */

const NEEDS = Object.keys(NEED_COLORS) as Need[];

const WIDTH = 600;
const HEIGHT = 140;

function path(points: NeedPoint[], need: Need, x: (tick: number) => number) {
  return points
    .map(
      (point, index) =>
        `${index === 0 ? 'M' : 'L'}${x(point.tick).toFixed(1)},${(HEIGHT - (point[need] / 100) * HEIGHT).toFixed(1)}`,
    )
    .join(' ');
}

/** Hunger and thirst (rising is bad), energy and health (falling is bad), 0-100 over the series' ticks. */
export function NeedsChart({
  points,
  fromTick,
  toTick,
}: {
  points: NeedPoint[];
  fromTick: number;
  toTick: number;
}) {
  const span = Math.max(toTick - fromTick, 1);
  const x = (tick: number) => ((tick - fromTick) / span) * WIDTH;
  return (
    <figure className="flex flex-col gap-1" data-testid="needs-chart">
      <svg
        viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
        preserveAspectRatio="none"
        className="bg-muted/40 h-36 w-full rounded"
        role="img"
        aria-label="needs over time"
      >
        {[60, 90].map((level) => (
          <line
            key={level}
            x1={0}
            x2={WIDTH}
            y1={HEIGHT - (level / 100) * HEIGHT}
            y2={HEIGHT - (level / 100) * HEIGHT}
            stroke="currentColor"
            strokeOpacity={0.15}
            strokeDasharray="4 4"
            vectorEffect="non-scaling-stroke"
          />
        ))}
        {points.length > 1 &&
          NEEDS.map((need) => (
            <path
              key={need}
              d={path(points, need, x)}
              fill="none"
              stroke={NEED_COLORS[need]}
              strokeWidth={2}
              vectorEffect="non-scaling-stroke"
              data-need={need}
            />
          ))}
      </svg>
      <figcaption className="text-muted-foreground flex justify-between text-xs">
        <span>{tickLabel(fromTick)}</span>
        <span className="flex gap-3">
          {NEEDS.map((need) => (
            <span key={need} className="flex items-center gap-1">
              <span
                className="inline-block size-2 rounded-full"
                style={{ background: NEED_COLORS[need] }}
              />
              {need}
            </span>
          ))}
        </span>
        <span>{tickLabel(toTick)}</span>
      </figcaption>
    </figure>
  );
}

/** One horizontal bar: a label, a value and how full it is (0-1). */
export function Bar({
  label,
  value,
  fraction,
  color = 'var(--color-primary)',
}: {
  label: string;
  value: string;
  fraction: number;
  color?: string;
}) {
  return (
    <div className="flex flex-col gap-1">
      <div className="flex justify-between text-sm">
        <span>{label}</span>
        <span className="text-muted-foreground tabular-nums">{value}</span>
      </div>
      <div className="bg-muted h-2 overflow-hidden rounded-full">
        <div
          className="h-full rounded-full"
          style={{
            width: `${Math.min(Math.max(fraction, 0), 1) * 100}%`,
            background: color,
          }}
        />
      </div>
    </div>
  );
}

/** Vertical bars, one per entry, scaled to the largest. */
export function Columns({
  entries,
  label,
}: {
  entries: { key: string; label: string; value: number }[];
  label: string;
}) {
  const top = Math.max(1, ...entries.map((entry) => entry.value));
  return (
    <div
      className="flex h-32 items-end gap-1"
      role="img"
      aria-label={label}
      data-testid="columns"
    >
      {entries.map((entry) => (
        <div
          key={entry.key}
          className="flex h-full min-w-0 flex-1 flex-col items-center justify-end gap-1"
          title={`${entry.label}: ${entry.value}`}
        >
          <span className="text-muted-foreground text-[10px] tabular-nums">
            {entry.value}
          </span>
          <div
            className="bg-primary/70 w-full rounded-t"
            style={{ height: `${(entry.value / top) * 80}%` }}
          />
          <span className="text-muted-foreground truncate text-[10px]">
            {entry.label}
          </span>
        </div>
      ))}
    </div>
  );
}
