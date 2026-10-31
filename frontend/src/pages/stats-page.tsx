import { Bar, Columns } from '@/components/spectator/charts';
import { PageShell, QueryState } from '@/components/spectator/page-shell';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { useStats } from '@/hooks/use-spectator';
import { tickLabel } from '@/lib/spectator/time';
import { useReplayTick } from '@/hooks/use-replay-tick';

const MEAL = 30; // hunger one meal takes away, to read food stocks as meals

function Stat({
  label,
  value,
  testId,
}: {
  label: string;
  value: string | number;
  testId: string;
}) {
  return (
    <Card size="sm">
      <CardContent className="flex flex-col">
        <span className="text-muted-foreground text-xs">{label}</span>
        <span
          className="text-2xl font-semibold tabular-nums"
          data-testid={testId}
        >
          {value}
        </span>
      </CardContent>
    </Card>
  );
}

/** Population, deaths, food, wild resources and how busy each day was (now or at `?at=`). */
export function StatsPage() {
  const at = useReplayTick();
  const { data, isPending, error } = useStats(at);
  const meals = data
    ? data.food.reduce((sum, stock) => sum + stock.hunger, 0) / MEAL
    : 0;
  const topFood = Math.max(
    1,
    ...(data?.food.map((stock) => stock.hunger) ?? []),
  );
  return (
    <PageShell
      title="Stats"
      testId="stats-page"
      subtitle={data && tickLabel(data.tick)}
    >
      <QueryState isPending={isPending} error={error} />
      {data && (
        <>
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
            <Stat label="Alive" value={data.population.alive} testId="alive" />
            <Stat label="Dead" value={data.population.dead} testId="dead" />
            <Stat
              label="Meals of food in stock"
              value={Math.floor(meals)}
              testId="meals"
            />
            <Stat label="Game day" value={data.day} testId="day" />
          </div>
          <div className="grid gap-4 md:grid-cols-2">
            <Card size="sm">
              <CardHeader>
                <CardTitle>Food</CardTitle>
              </CardHeader>
              <CardContent className="flex flex-col gap-3" data-testid="food">
                {data.food.map((stock) => (
                  <Bar
                    key={stock.id}
                    label={stock.name}
                    value={
                      Object.entries(stock.items)
                        .map(([item, count]) => `${count} ${item}`)
                        .join(', ') || 'none'
                    }
                    fraction={stock.hunger / topFood}
                  />
                ))}
              </CardContent>
            </Card>
            <Card size="sm">
              <CardHeader>
                <CardTitle>Wild plants (now / at the start)</CardTitle>
              </CardHeader>
              <CardContent
                className="flex flex-col gap-3"
                data-testid="resources"
              >
                {data.resources.map((resource) => (
                  <Bar
                    key={resource.resource}
                    label={`${resource.resource}${resource.emptied_nodes ? ` · ${resource.emptied_nodes} picked bare` : ''}`}
                    value={`${resource.now.toLocaleString()} / ${resource.start.toLocaleString()}`}
                    fraction={
                      resource.start ? resource.now / resource.start : 0
                    }
                    color="#65a30d"
                  />
                ))}
              </CardContent>
            </Card>
          </div>
          <Card size="sm">
            <CardHeader>
              <CardTitle>Deaths</CardTitle>
            </CardHeader>
            <CardContent className="text-sm" data-testid="deaths">
              {data.deaths.length === 0 ? (
                <span className="text-muted-foreground">Nobody has died.</span>
              ) : (
                <ul className="flex flex-col gap-1">
                  {Object.entries(data.deaths_by_cause).map(
                    ([cause, count]) => (
                      <li key={cause} className="font-medium">
                        {cause}: {count}
                      </li>
                    ),
                  )}
                  {data.deaths.map((death) => (
                    <li
                      key={death.citizen.id}
                      className="text-muted-foreground"
                    >
                      {death.citizen.name} ({death.cause}), day {death.day},{' '}
                      {death.time}
                    </li>
                  ))}
                </ul>
              )}
            </CardContent>
          </Card>
          <div className="grid gap-4 md:grid-cols-2">
            <Card size="sm">
              <CardHeader>
                <CardTitle>Things done per day</CardTitle>
              </CardHeader>
              <CardContent>
                <Columns
                  label="actions per day"
                  entries={data.days.map((day) => ({
                    key: String(day.day),
                    label: `d${day.day}`,
                    value: day.actions,
                  }))}
                />
              </CardContent>
            </Card>
            <Card size="sm">
              <CardHeader>
                <CardTitle>Lines said per day</CardTitle>
              </CardHeader>
              <CardContent>
                <Columns
                  label="lines said per day"
                  entries={data.days.map((day) => ({
                    key: String(day.day),
                    label: `d${day.day}`,
                    value: day.said,
                  }))}
                />
              </CardContent>
            </Card>
          </div>
        </>
      )}
    </PageShell>
  );
}
