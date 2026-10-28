import { useQuery } from '@tanstack/react-query';

import { cn } from 'cn';
import { portraitUrl } from '@/lib/world/portraits';

type PortraitProps = {
  look: string;
  name: string;
  className?: string;
  dead?: boolean;
};

/** A citizen's face (their 3D look, rendered once); their initial until it is ready. */
export function Portrait({ look, name, className, dead }: PortraitProps) {
  const { data } = useQuery({
    queryKey: ['portrait', look],
    queryFn: () => portraitUrl(look),
    staleTime: Infinity,
    retry: 1,
  });
  return (
    <div
      className={cn(
        'bg-muted flex shrink-0 items-center justify-center overflow-hidden rounded-full',
        dead && 'grayscale',
        className,
      )}
      data-testid="portrait"
      data-ready={data !== undefined}
    >
      {data ? (
        <img src={data} alt={`${name}'s portrait`} className="size-full" />
      ) : (
        <span className="text-muted-foreground font-medium">{name[0]}</span>
      )}
    </div>
  );
}
