import { Badge } from '@/components/ui/badge';
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card';
import { useHealth } from '@/hooks/use-health';

type StatusRowProps = { label: string; value: string; healthy: boolean };

function StatusRow({ label, value, healthy }: StatusRowProps) {
  return (
    <div className="flex items-center justify-between">
      <span className="text-muted-foreground">{label}</span>
      <Badge
        variant={healthy ? 'default' : 'destructive'}
        aria-label={`${label}: ${value}`}
      >
        {value}
      </Badge>
    </div>
  );
}

export function StatusPage() {
  const { data, isPending, isError } = useHealth();
  const apiStatus = isPending ? 'checking' : isError ? 'unreachable' : 'ok';
  const databaseStatus = data?.database ?? 'unknown';

  return (
    <main className="bg-muted flex h-full items-center justify-center p-6">
      <Card className="w-full max-w-sm">
        <CardHeader>
          <CardTitle>
            <h1>Pebble</h1>
          </CardTitle>
          <CardDescription>A small round world. Coming soon.</CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-3">
          <StatusRow
            label="API"
            value={apiStatus}
            healthy={apiStatus === 'ok'}
          />
          <StatusRow
            label="Database"
            value={databaseStatus}
            healthy={databaseStatus === 'up'}
          />
        </CardContent>
      </Card>
    </main>
  );
}
