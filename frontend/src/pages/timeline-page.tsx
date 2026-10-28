import { useState } from 'react';
import { Link, useSearchParams } from 'react-router';

import { PageShell, QueryState } from '@/components/spectator/page-shell';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Slider } from '@/components/ui/slider';
import {
  useCitizens,
  useClock,
  useConversations,
  useStats,
} from '@/hooks/use-spectator';
import { worldAt, withAt } from '@/lib/spectator/links';
import { DAY_MINUTES, tickLabel } from '@/lib/spectator/time';
import { doingWords } from '@/lib/spectator/words';
import { useReplayTick } from '@/hooks/use-replay-tick';

const STEPS = [
  { label: '−1 day', ticks: -DAY_MINUTES },
  { label: '−1 h', ticks: -60 },
  { label: '−10 min', ticks: -10 },
  { label: '+10 min', ticks: 10 },
  { label: '+1 h', ticks: 60 },
  { label: '+1 day', ticks: DAY_MINUTES },
];
const SPEECH_WINDOW = 60; // conversations shown: the game hour up to the moment

function Moment({ tick }: { tick: number }) {
  const citizens = useCitizens(tick);
  const stats = useStats(tick);
  const talk = useConversations({
    fromTick: Math.max(0, tick - SPEECH_WINDOW),
    toTick: tick,
    live: false,
  });
  const store = stats.data?.food.find((stock) => stock.kind === 'storehouse');
  return (
    <div className="grid gap-4 md:grid-cols-3">
      <Card size="sm" className="md:col-span-2">
        <CardHeader>
          <CardTitle>Who was where</CardTitle>
        </CardHeader>
        <CardContent>
          <QueryState isPending={citizens.isPending} error={citizens.error} />
          <ul className="divide-y text-sm" data-testid="moment-citizens">
            {citizens.data?.citizens.map((citizen) => (
              <li key={citizen.id} className="flex gap-2 py-1">
                <Link
                  to={withAt(`/people/${citizen.id}`, tick)}
                  className="w-20 shrink-0 font-medium"
                >
                  {citizen.name}
                </Link>
                <span className="min-w-0 truncate">
                  {doingWords(citizen)}
                  {citizen.place && (
                    <span className="text-muted-foreground">
                      {' '}
                      · {citizen.place.name}
                    </span>
                  )}
                </span>
              </li>
            ))}
          </ul>
        </CardContent>
      </Card>
      <div className="flex flex-col gap-4">
        <Card size="sm">
          <CardHeader>
            <CardTitle>The world then</CardTitle>
          </CardHeader>
          <CardContent className="flex flex-col gap-1 text-sm">
            {stats.data && (
              <>
                <span>
                  {stats.data.population.alive} alive,{' '}
                  {stats.data.population.dead} dead
                </span>
                {store && (
                  <span>
                    Storehouse: {store.items.rice ?? 0} measures of rice
                  </span>
                )}
              </>
            )}
          </CardContent>
        </Card>
        <Card size="sm">
          <CardHeader>
            <CardTitle>Said in the hour before</CardTitle>
          </CardHeader>
          <CardContent>
            <ul
              className="flex flex-col gap-1 text-sm"
              data-testid="moment-speech"
            >
              {talk.data?.threads
                .flatMap((thread) => thread.lines)
                .sort((a, b) => b.seq - a.seq)
                .slice(0, 12)
                .map((line) => (
                  <li key={line.id}>
                    <span className="text-muted-foreground mr-1 tabular-nums">
                      {line.time}
                    </span>
                    <span className="font-medium">{line.speaker.name}</span>: “
                    {line.words}”
                  </li>
                ))}
              {talk.data?.threads.length === 0 && (
                <li className="text-muted-foreground">Silence.</li>
              )}
            </ul>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}

/**
 * Replay: scrub through game time (`?at=N`); the page shows who was where, what was said and the world's stocks
 * at that moment, and opens the World there (`/?tick=N`).
 */
export function TimelinePage() {
  const clock = useClock();
  const [, setParams] = useSearchParams();
  const at = useReplayTick();
  const now = clock.data?.tick ?? 0;
  const tick = Math.min(at ?? now, now);
  const [dragging, setDragging] = useState<number | null>(null);
  const shown = dragging ?? tick;
  const commit = (next: number) => {
    setDragging(null);
    const clamped = Math.min(Math.max(Math.round(next), 0), now);
    setParams(clamped >= now ? {} : { at: String(clamped) });
  };
  return (
    <PageShell
      title="Timeline"
      testId="timeline-page"
      subtitle={
        at === null
          ? 'Live: drag back through game time to replay any moment'
          : 'Replaying the past'
      }
    >
      <QueryState isPending={clock.isPending} error={clock.error} />
      {clock.data && (
        <Card>
          <CardContent className="flex flex-col gap-3">
            <div className="flex flex-wrap items-baseline justify-between gap-2">
              <span
                className="text-2xl font-semibold tabular-nums"
                data-testid="replay-tick"
                data-tick={shown}
              >
                {tickLabel(shown)}
              </span>
              <span className="text-muted-foreground text-sm">
                tick {shown} of {now}
              </span>
            </div>
            <Slider
              min={0}
              max={Math.max(now, 1)}
              step={1}
              value={[shown]}
              onValueChange={([value]) => setDragging(value)}
              onValueCommit={([value]) => commit(value)}
              aria-label="game time"
              data-testid="scrubber"
            />
            <div className="flex flex-wrap items-center gap-1">
              {STEPS.map((step) => (
                <Button
                  key={step.label}
                  size="xs"
                  variant="outline"
                  onClick={() => commit(tick + step.ticks)}
                >
                  {step.label}
                </Button>
              ))}
              <Button size="xs" variant="ghost" onClick={() => commit(now)}>
                Now
              </Button>
              <span className="flex-1" />
              <Button asChild size="sm">
                <Link to={worldAt(tick)} data-testid="open-world">
                  Open the world at this moment
                </Link>
              </Button>
            </div>
          </CardContent>
        </Card>
      )}
      {clock.data && <Moment tick={tick} />}
    </PageShell>
  );
}
