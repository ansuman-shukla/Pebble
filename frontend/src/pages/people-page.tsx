import { Link } from 'react-router';

import { PageShell, QueryState } from '@/components/spectator/page-shell';
import { Portrait } from '@/components/spectator/portrait';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent } from '@/components/ui/card';
import { useCitizens } from '@/hooks/use-spectator';
import type { CitizenSummary } from '@/lib/client/types.gen';
import { tickLabel } from '@/lib/spectator/time';
import { doingWords, REGION_NAMES, REGION_ORDER } from '@/lib/spectator/words';
import { useReplayTick } from '@/hooks/use-replay-tick';
import { withAt } from '@/lib/spectator/links';

function PersonCard({
  citizen,
  at,
}: {
  citizen: CitizenSummary;
  at: number | null;
}) {
  return (
    <Link
      to={withAt(`/people/${citizen.id}`, at)}
      data-testid="person"
      data-citizen={citizen.id}
    >
      <Card size="sm" className="hover:ring-foreground/30 h-full">
        <CardContent className="flex gap-3">
          <Portrait
            look={citizen.look}
            name={citizen.name}
            dead={!citizen.alive}
            className="size-14"
          />
          <div className="flex min-w-0 flex-col gap-0.5">
            <span className="font-medium">
              {citizen.name}{' '}
              <span className="text-muted-foreground font-normal">
                {citizen.age}
              </span>
            </span>
            <span className="text-muted-foreground truncate text-xs">
              {citizen.role}
            </span>
            <span className="truncate text-xs" data-testid="doing">
              {doingWords(citizen)}
              {citizen.place && (
                <span className="text-muted-foreground">
                  {' '}
                  · {citizen.place.name}
                </span>
              )}
            </span>
            {citizen.state.length > 0 && (
              <span className="flex flex-wrap gap-1">
                {citizen.state.map((word) => (
                  <Badge key={word} variant="secondary">
                    {word}
                  </Badge>
                ))}
              </span>
            )}
          </div>
        </CardContent>
      </Card>
    </Link>
  );
}

/** Everyone, by region, with what they are doing now (or at `?at=`). */
export function PeoplePage() {
  const at = useReplayTick();
  const { data, isPending, error } = useCitizens(at);
  const alive = data?.citizens.filter((citizen) => citizen.alive).length;
  return (
    <PageShell
      title="People"
      testId="people-page"
      subtitle={
        data &&
        `${alive} of ${data.citizens.length} alive · ${tickLabel(data.tick)}`
      }
    >
      <QueryState isPending={isPending} error={error} />
      {REGION_ORDER.map((region) => {
        const people = data?.citizens.filter(
          (citizen) => citizen.region === region,
        );
        if (!people?.length) return null;
        return (
          <section key={region} className="flex flex-col gap-2">
            <h2 className="text-muted-foreground text-sm font-medium">
              {REGION_NAMES[region]}
            </h2>
            <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
              {people.map((citizen) => (
                <PersonCard key={citizen.id} citizen={citizen} at={at} />
              ))}
            </div>
          </section>
        );
      })}
    </PageShell>
  );
}
