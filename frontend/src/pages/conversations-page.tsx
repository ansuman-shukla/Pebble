import { Link, useSearchParams } from 'react-router';

import { PageShell, QueryState } from '@/components/spectator/page-shell';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { useClock, useConversations } from '@/hooks/use-spectator';
import type { Thread } from '@/lib/client/types.gen';
import { mapLink } from '@/lib/spectator/links';
import { dayStartTick, parseTick, townClock } from '@/lib/spectator/time';

function ThreadCard({ thread }: { thread: Thread }) {
  const first = thread.lines[0];
  const end = thread.lines[thread.lines.length - 1];
  return (
    <Card size="sm" data-testid="thread" data-start-tick={thread.start_tick}>
      <CardHeader>
        <CardTitle className="flex flex-wrap items-baseline justify-between gap-2">
          <span>
            {thread.place?.name ?? 'out in the wild'}
            {thread.area && thread.area.id !== thread.place?.id && (
              <span className="text-muted-foreground font-normal">
                {' '}
                · {thread.area.name}
              </span>
            )}
          </span>
          <span className="text-muted-foreground text-xs font-normal">
            day {thread.day}, {thread.time}
            {end.tick !== first.tick && `–${end.time}`}
          </span>
        </CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col gap-2">
        <ol className="flex flex-col gap-1.5">
          {thread.lines.map((line) => (
            <li key={line.id} className="text-sm" data-testid="line">
              <span className="text-muted-foreground mr-2 tabular-nums">
                {line.time}
              </span>
              <Link to={`/people/${line.speaker.id}`} className="font-medium">
                {line.speaker.name}
              </Link>
              {line.volume !== 'normal' && (
                <span className="text-muted-foreground"> ({line.volume}s)</span>
              )}
              : “{line.words}”
              <span className="text-muted-foreground block pl-12 text-xs">
                {line.heard_by.length
                  ? `heard by ${line.heard_by.map((p) => p.name).join(', ')}`
                  : 'nobody heard'}
              </span>
            </li>
          ))}
        </ol>
        <div className="flex flex-wrap items-center justify-between gap-2">
          <span className="flex flex-wrap gap-1">
            {thread.listeners.map((person) => (
              <Badge key={person.id} variant="outline">
                {person.name} listened
              </Badge>
            ))}
          </span>
          <Button asChild size="sm" variant="outline">
            <Link
              to={mapLink(first.speaker.id, thread.start_tick)}
              data-testid="jump"
            >
              See it in the world
            </Link>
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}

/**
 * Speech grouped into conversations: the last game day live, or one town day (`?day=N`); `?place=` keeps the
 * threads at one place or area.
 */
export function ConversationsPage() {
  const [params, setParams] = useSearchParams();
  const day = parseTick(params.get('day'));
  const place = params.get('place') ?? undefined;
  const clock = useClock();
  const today = clock.data ? townClock(clock.data.tick).day : null;
  const { data, isPending, error } = useConversations(
    day === null
      ? { place, live: true }
      : {
          fromTick: dayStartTick(day),
          toTick: dayStartTick(day + 1) - 1,
          place,
          live: day === today,
        },
  );
  const shown = day ?? today;
  const goTo = (next: number | null) =>
    setParams((current) => {
      const updated = new URLSearchParams(current);
      if (next === null) updated.delete('day');
      else updated.set('day', String(next));
      return updated;
    });
  const places = new Map(
    (data?.threads ?? [])
      .flatMap((thread) => [thread.place, thread.area])
      .filter((ref) => ref !== null)
      .map((ref) => [ref.id, ref.name]),
  );
  return (
    <PageShell
      title="Conversations"
      testId="conversations-page"
      subtitle={
        day === null
          ? 'The last game day, newest first'
          : `Day ${day}, newest first`
      }
      actions={
        <div className="flex items-center gap-2">
          <Button
            size="sm"
            variant="outline"
            disabled={shown === null || shown <= 0}
            onClick={() => shown !== null && goTo(shown - 1)}
          >
            Earlier day
          </Button>
          <Button
            size="sm"
            variant="outline"
            disabled={day === null}
            onClick={() =>
              goTo(
                day !== null && today !== null && day + 1 < today
                  ? day + 1
                  : null,
              )
            }
          >
            Later day
          </Button>
        </div>
      }
    >
      <div className="flex flex-wrap gap-1">
        <Button
          size="xs"
          variant={place ? 'ghost' : 'secondary'}
          onClick={() =>
            setParams((current) => {
              const updated = new URLSearchParams(current);
              updated.delete('place');
              return updated;
            })
          }
        >
          Everywhere
        </Button>
        {[...places].map(([id, name]) => (
          <Button
            key={id}
            size="xs"
            variant={place === id ? 'secondary' : 'ghost'}
            onClick={() =>
              setParams((current) => {
                const updated = new URLSearchParams(current);
                updated.set('place', id);
                return updated;
              })
            }
          >
            {name}
          </Button>
        ))}
      </div>
      <QueryState isPending={isPending} error={error} />
      {data && data.threads.length === 0 && (
        <p className="text-muted-foreground text-sm">Nobody said anything.</p>
      )}
      <div className="flex flex-col gap-3">
        {data?.threads.map((thread) => (
          <ThreadCard key={thread.id} thread={thread} />
        ))}
      </div>
    </PageShell>
  );
}
