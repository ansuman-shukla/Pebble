import { useEffect, useRef, useState } from 'react';

import { Button } from '@/components/ui/button';
import type { LiveFeed } from '@/hooks/use-live-citizens';
import {
  addEntry,
  FEED_FILTERS,
  type FeedEntry,
  type FeedFilter,
  feedEntry,
  type FeedSubjects,
  foldDetail,
  shows,
} from '@/lib/live/event-feed';

/*
 * The event feed over the globe (10-world-v1 §5.4): what just happened, newest first, one line per event with its
 * importance, repeats merged, filters All/People/Danger/Economy, and ▶ to fly there. Collapsible (key L).
 */

const IMPORTANCE_CLASS: Record<number, string> = {
  1: 'text-muted-foreground',
  2: '',
  3: 'font-semibold text-red-700',
};

export function EventFeed({
  listen,
  subjects,
  open,
  onToggle,
  canFly,
  onFly,
}: {
  listen: LiveFeed['listen'];
  /** Citizen names and animal kinds by id, for events that carry no line of their own yet. */
  subjects: FeedSubjects;
  open: boolean;
  onToggle: () => void;
  /** Whether there is somewhere to fly for an entry (its place, or its actor drawn). */
  canFly: (entry: FeedEntry) => boolean;
  /** Fly to where an entry happened (or to its actor). */
  onFly: (entry: FeedEntry) => void;
}) {
  const [entries, setEntries] = useState<FeedEntry[]>([]);
  const [filter, setFilter] = useState<FeedFilter>('all');
  const subjectsRef = useRef(subjects);
  useEffect(() => {
    subjectsRef.current = subjects;
  }, [subjects]);
  useEffect(
    () =>
      listen((message) => {
        if (message.type !== 'event') return;
        const entry = feedEntry(message, subjectsRef.current);
        if (entry) setEntries((current) => addEntry(current, entry));
      }),
    [listen],
  );
  const shown = entries.filter((entry) => shows(entry, filter));
  return (
    <section
      role="region"
      aria-label="Events"
      className="absolute bottom-12 left-3 flex max-h-[35%] w-96 flex-col gap-1 rounded-lg bg-white/90 p-1 text-xs shadow-lg"
    >
      <header className="flex items-center gap-1">
        <Button
          size="xs"
          variant={open ? 'default' : 'outline'}
          aria-expanded={open}
          onClick={(event) => {
            onToggle();
            event.currentTarget.blur();
          }}
        >
          events
        </Button>
        {open &&
          FEED_FILTERS.map(({ filter: kind, label }) => (
            <Button
              key={kind}
              size="xs"
              variant={kind === filter ? 'secondary' : 'ghost'}
              aria-pressed={kind === filter}
              onClick={(event) => {
                setFilter(kind);
                event.currentTarget.blur();
              }}
            >
              {label}
            </Button>
          ))}
      </header>
      {open && (
        <ol className="overflow-y-auto" data-testid="event-feed">
          {shown.map((entry) => (
            <li
              key={entry.id}
              data-event-type={entry.type}
              data-importance={entry.importance}
              className="flex items-center gap-1 rounded px-1 hover:bg-black/5"
            >
              <span className="text-muted-foreground font-mono">
                {entry.time}
              </span>
              <span
                className={`min-w-0 flex-1 truncate ${IMPORTANCE_CLASS[entry.importance] ?? ''}`}
                title={
                  entry.folded.length > 0
                    ? entry.folded.map(({ line }) => line).join('\n')
                    : entry.line
                }
              >
                {entry.line}
                {entry.count > 1 && ` ×${entry.count}`}
                {entry.folded.length > 0 && (
                  <span data-testid="fold-detail" className="italic">
                    {' '}
                    · {foldDetail(entry)}
                  </span>
                )}
              </span>
              {canFly(entry) && (
                <Button
                  size="xs"
                  variant="ghost"
                  aria-label={`fly to: ${entry.line}`}
                  onClick={(event) => {
                    onFly(entry);
                    event.currentTarget.blur();
                  }}
                >
                  ▶
                </Button>
              )}
            </li>
          ))}
          {shown.length === 0 && (
            <li className="text-muted-foreground px-1">nothing yet</li>
          )}
        </ol>
      )}
    </section>
  );
}
