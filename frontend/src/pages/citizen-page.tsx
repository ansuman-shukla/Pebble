import { useEffect, useRef } from 'react';
import { Link, useParams } from 'react-router';

import { Bar, NeedsChart } from '@/components/spectator/charts';
import { PageShell, QueryState } from '@/components/spectator/page-shell';
import { Portrait } from '@/components/spectator/portrait';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import {
  useCitizen,
  useCitizenNeeds,
  useCitizenTimeline,
} from '@/hooks/use-spectator';
import type { CitizenProfile, TimelineEntry } from '@/lib/client/types.gen';
import { mapLink, withAt } from '@/lib/spectator/links';
import { tickLabel } from '@/lib/spectator/time';
import { doingWords, NEED_COLORS, REGION_NAMES } from '@/lib/spectator/words';
import { useReplayTick } from '@/hooks/use-replay-tick';

function Profile({
  citizen,
  at,
}: {
  citizen: CitizenProfile;
  at: number | null;
}) {
  return (
    <Card>
      <CardContent className="flex flex-wrap items-start gap-4">
        <Portrait
          look={citizen.look}
          name={citizen.name}
          dead={!citizen.alive}
          className="size-28"
        />
        <div className="flex min-w-60 flex-1 flex-col gap-1">
          <p className="text-muted-foreground text-sm">
            {citizen.role} · {citizen.age} · {REGION_NAMES[citizen.region]}
          </p>
          <p className="text-sm italic">{citizen.appearance}</p>
          {citizen.personality && (
            <p className="text-sm">{citizen.personality}</p>
          )}
          <p className="text-muted-foreground text-sm">
            Home: {citizen.home?.name ?? 'none'}
          </p>
          {citizen.skills.length > 0 && (
            <div className="flex flex-wrap gap-1">
              {citizen.skills.map((skill) => (
                <Badge key={skill} variant="outline">
                  {skill}
                </Badge>
              ))}
            </div>
          )}
        </div>
        <Button asChild>
          <Link to={mapLink(citizen.id, at)} data-testid="show-on-map">
            Show on map
          </Link>
        </Button>
      </CardContent>
    </Card>
  );
}

function Now({ citizen }: { citizen: CitizenProfile }) {
  return (
    <Card size="sm">
      <CardHeader>
        <CardTitle>{citizen.alive ? 'Now' : 'Dead'}</CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        <p data-testid="activity">
          {doingWords(citizen)}
          {citizen.place && (
            <span className="text-muted-foreground">
              {' '}
              · {citizen.place.name}
            </span>
          )}
        </p>
        {citizen.needs.map((need) => (
          <Bar
            key={need.need}
            label={`${need.need}: ${need.word}`}
            value={need.value.toFixed(0)}
            fraction={need.value / 100}
            color={NEED_COLORS[need.need]}
          />
        ))}
        <div className="text-sm">
          <span className="text-muted-foreground">Carrying: </span>
          {citizen.inventory.length
            ? citizen.inventory.map((holding) => holding.words).join(', ')
            : 'nothing'}
        </div>
      </CardContent>
    </Card>
  );
}

function Knows({
  citizen,
  at,
}: {
  citizen: CitizenProfile;
  at: number | null;
}) {
  return (
    <Card size="sm">
      <CardHeader>
        <CardTitle>Knows</CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col gap-3 text-sm">
        <div className="flex flex-wrap gap-1" data-testid="known-people">
          {citizen.known_people.map((person) => (
            <Link key={person.id} to={withAt(`/people/${person.id}`, at)}>
              <Badge variant="secondary">{person.name}</Badge>
            </Link>
          ))}
          {citizen.known_people.length === 0 && 'nobody yet'}
        </div>
        <div className="flex flex-wrap gap-1" data-testid="known-places">
          {citizen.known_places.map((place) => (
            <Badge
              key={place.id}
              variant={place.level === 'visited' ? 'outline' : 'ghost'}
              title={place.level === 'visited' ? 'been there' : 'heard of it'}
            >
              {place.name}
              {place.level !== 'visited' && ' (heard of)'}
            </Badge>
          ))}
        </div>
      </CardContent>
    </Card>
  );
}

function Needs({ id, at }: { id: string; at: number | null }) {
  const { data } = useCitizenNeeds(id, at);
  return (
    <Card size="sm">
      <CardHeader>
        <CardTitle>Needs over the last day</CardTitle>
      </CardHeader>
      <CardContent>
        {data ? (
          <NeedsChart
            points={data.points}
            fromTick={data.from_tick}
            toTick={data.to_tick}
          />
        ) : (
          <div className="bg-muted/40 h-36 rounded" />
        )}
      </CardContent>
    </Card>
  );
}

function Entry({
  entry,
  id,
  people,
}: {
  entry: TimelineEntry;
  id: string;
  people: Map<string, string>;
}) {
  return (
    <li className="flex gap-3 py-1.5 text-sm" data-testid="timeline-entry">
      <Link
        to={mapLink(id, entry.tick)}
        className="text-muted-foreground w-12 shrink-0 tabular-nums hover:underline"
        title="See this moment in the world"
      >
        {entry.time}
      </Link>
      <div className="flex min-w-0 flex-col">
        <span>
          {entry.summary}
          {entry.visibility === 'private' && (
            <span className="text-muted-foreground"> (private)</span>
          )}
        </span>
        {entry.detail && (
          <span className="text-muted-foreground text-xs italic">
            {entry.detail}
          </span>
        )}
        {entry.related.length > 0 && entry.type === 'said' && (
          <span className="flex gap-1 text-xs">
            {entry.related.map((other) => (
              <Link
                key={other}
                to={`/people/${other}`}
                className="text-muted-foreground underline"
              >
                {people.get(other) ?? other}
              </Link>
            ))}
          </span>
        )}
      </div>
    </li>
  );
}

function Timeline({
  citizen,
  at,
}: {
  citizen: CitizenProfile;
  at: number | null;
}) {
  const { data, error, fetchNextPage, hasNextPage, isFetchingNextPage } =
    useCitizenTimeline(citizen.id, at);
  const sentinel = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const element = sentinel.current;
    if (!element || !hasNextPage) return;
    const observer = new IntersectionObserver((seen) => {
      if (seen.some((entry) => entry.isIntersecting) && !isFetchingNextPage)
        void fetchNextPage();
    });
    observer.observe(element);
    return () => observer.disconnect();
  }, [fetchNextPage, hasNextPage, isFetchingNextPage]);
  const entries = data?.pages.flatMap((page) => page.entries) ?? [];
  const people = new Map(citizen.known_people.map((p) => [p.id, p.name]));
  return (
    <Card size="sm">
      <CardHeader>
        <CardTitle>Life</CardTitle>
      </CardHeader>
      <CardContent>
        <QueryState isPending={!data && !error} error={error} />
        <ol className="divide-y" data-testid="timeline">
          {entries.map((entry, index) => {
            const header = index === 0 || entries[index - 1].day !== entry.day;
            return [
              header && (
                <li
                  key={`day-${entry.day}`}
                  className="text-muted-foreground pt-3 pb-1 text-xs font-medium"
                >
                  Day {entry.day}
                </li>
              ),
              <Entry
                key={entry.id}
                entry={entry}
                id={citizen.id}
                people={people}
              />,
            ];
          })}
        </ol>
        <div ref={sentinel} className="h-6" />
        {isFetchingNextPage && (
          <p className="text-muted-foreground text-sm">Loading more…</p>
        )}
        {data && !hasNextPage && (
          <p className="text-muted-foreground text-sm">The beginning.</p>
        )}
      </CardContent>
    </Card>
  );
}

/** One citizen's life: who they are, how they are, what they know, and everything they did (at `?at=` or now). */
export function CitizenPage() {
  const { id = '' } = useParams();
  const at = useReplayTick();
  const { data: citizen, isPending, error } = useCitizen(id, at);
  return (
    <PageShell
      title={citizen?.name ?? id}
      testId="citizen-page"
      subtitle={citizen && tickLabel(citizen.tick)}
      actions={
        <Link to={withAt('/people', at)} className="text-sm underline">
          Everyone
        </Link>
      }
    >
      <QueryState isPending={isPending} error={error} />
      {citizen && (
        <div
          className="flex flex-col gap-4"
          data-citizen={citizen.id}
          data-tick={citizen.tick}
        >
          <Profile citizen={citizen} at={at} />
          <div className="grid gap-4 md:grid-cols-2">
            <Now citizen={citizen} />
            <Knows citizen={citizen} at={at} />
          </div>
          <Needs id={citizen.id} at={at} />
          <Timeline citizen={citizen} at={at} />
        </div>
      )}
    </PageShell>
  );
}
