import { useThree } from '@react-three/fiber';
import { type RefObject, useEffect } from 'react';
import { Vector3 } from 'three';

import type { NpcViews } from './globe-npcs';
import { Bar } from '@/components/spectator/charts';
import { Button } from '@/components/ui/button';
import { useCitizen } from '@/hooks/use-spectator';
import type { LiveCitizen } from '@/lib/live/live-contract';
import { activityWords } from '@/lib/live/npc-activity';
import { NEED_COLORS, REGION_NAMES } from '@/lib/spectator/words';

/*
 * The inspector (10-world-v1 §5.4): who the selected citizen is and what they are doing now, from the live feed,
 * plus their needs, what they carry, home, people they know and their last events from the citizen profile.
 * Why (goal, driver), coins, standing and ambition join as the feed and the scoreboard carry them. Also the
 * scene-side picker that turns a click on a body into a selection.
 */

/** How many of the citizen's own events show. */
const LAST_EVENTS = 6;
/** How many known people show (the bonds, once they are tracked). */
const KNOWN = 3;
/** A click this close (px) to a citizen's drawn chest picks them. */
const PICK_PX = 28;
/** The picked point: this far above the feet (m). */
const CHEST_M = 1.2;

export type PickAt = (clientX: number, clientY: number) => string | null;

const point = new Vector3();

/**
 * Inside the Canvas: fills `pickRef` with a function that names the citizen drawn nearest a click (within
 * PICK_PX of their chest on screen, in front of the camera), or null.
 */
export function CitizenPicker({
  views,
  pickRef,
}: {
  views: NpcViews;
  pickRef: RefObject<PickAt | null>;
}) {
  const camera = useThree((state) => state.camera);
  const canvas = useThree((state) => state.gl.domElement);
  useEffect(() => {
    pickRef.current = (clientX, clientY) => {
      const rect = canvas.getBoundingClientRect();
      let best: string | null = null;
      let bestPx = PICK_PX;
      for (const [id, view] of views) {
        const { position } = view.pose;
        point.copy(position).normalize().multiplyScalar(CHEST_M).add(position);
        point.project(camera);
        if (point.z >= 1) continue;
        const px = Math.hypot(
          rect.left + ((point.x + 1) / 2) * rect.width - clientX,
          rect.top + ((1 - point.y) / 2) * rect.height - clientY,
        );
        if (px < bestPx) {
          bestPx = px;
          best = id;
        }
      }
      return best;
    };
    return () => {
      pickRef.current = null;
    };
  }, [camera, canvas, views, pickRef]);
  return null;
}

function Section({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <section className="flex flex-col gap-1">
      <h3 className="text-muted-foreground text-[11px] font-medium tracking-wide uppercase">
        {title}
      </h3>
      {children}
    </section>
  );
}

/** The profile half: needs, carrying, home, people known, last events (the backend's citizen profile). */
function Details({ id, at }: { id: string; at: number | null }) {
  const { data: profile, error } = useCitizen(id, at);
  if (error)
    return (
      <p className="text-muted-foreground text-xs">
        No details: {error.message}
      </p>
    );
  if (!profile)
    return <p className="text-muted-foreground text-xs">Loading details…</p>;
  const events = profile.recent
    .filter((entry) => entry.type !== 'tick_summary')
    .slice(0, LAST_EVENTS);
  return (
    <>
      {profile.alive && (
        <Section title="Needs">
          <div className="flex flex-col gap-1" data-testid="inspector-needs">
            {profile.needs.map((need) => (
              <Bar
                key={need.need}
                label={`${need.need}: ${need.word}`}
                value={need.value.toFixed(0)}
                fraction={need.value / 100}
                color={NEED_COLORS[need.need]}
              />
            ))}
          </div>
        </Section>
      )}
      <Section title="Carrying">
        <p data-testid="inspector-carrying">
          {profile.inventory.length
            ? profile.inventory.map((holding) => holding.words).join(', ')
            : 'nothing'}
        </p>
      </Section>
      <Section title="Home">
        <p>{profile.home?.name ?? 'none'}</p>
      </Section>
      {profile.known_people.length > 0 && (
        <Section title="Knows">
          <p>
            {profile.known_people
              .slice(0, KNOWN)
              .map((person) => person.name)
              .join(', ')}
            {profile.known_people.length > KNOWN &&
              ` +${profile.known_people.length - KNOWN}`}
          </p>
        </Section>
      )}
      <Section title="Lately">
        <ol className="flex flex-col gap-0.5" data-testid="inspector-events">
          {events.map((entry) => (
            <li key={entry.id} className="truncate" title={entry.summary}>
              <span className="text-muted-foreground font-mono">
                {entry.time}
              </span>{' '}
              {entry.summary}
            </li>
          ))}
          {events.length === 0 && (
            <li className="text-muted-foreground">nothing yet</li>
          )}
        </ol>
      </Section>
    </>
  );
}

/** The selected citizen's panel; `details` loads their profile (off for the mock feed, which the backend lacks). */
export function Inspector({
  citizen,
  details,
  at,
  following,
  onFollow,
  onGoTo,
  onClose,
}: {
  citizen: LiveCitizen;
  details: boolean;
  at: number | null;
  following: boolean;
  onFollow: () => void;
  onGoTo: () => void;
  onClose: () => void;
}) {
  const blurred =
    (action: () => void) => (event: React.MouseEvent<HTMLElement>) => {
      action();
      // hand the keyboard back to the scene (key presses on buttons are ignored)
      event.currentTarget.blur();
    };
  return (
    <aside
      role="region"
      aria-label="Inspector"
      data-inspect={citizen.id}
      className="absolute top-(--toolbar-bottom) left-3 flex max-h-[calc(65%-var(--toolbar-bottom)-4rem)] w-80 flex-col gap-3 overflow-y-auto rounded-lg bg-white/90 p-3 text-xs shadow-lg"
    >
      <header className="flex items-start gap-2">
        <div className="min-w-0 flex-1">
          <h2 className="text-sm font-semibold">{citizen.name}</h2>
          <p className="text-muted-foreground">
            {citizen.role} · {REGION_NAMES[citizen.region]}
          </p>
        </div>
        <Button
          size="xs"
          variant="ghost"
          aria-label="close inspector"
          onClick={blurred(onClose)}
        >
          ✕
        </Button>
      </header>
      <Section title="Now">
        <p data-testid="inspector-now">
          {activityWords(citizen)}
          {citizen.alive && citizen.state.length > 0 && (
            <span className="text-muted-foreground">
              {' '}
              · {citizen.state.join(', ')}
            </span>
          )}
        </p>
      </Section>
      {details && <Details id={citizen.id} at={at} />}
      <footer className="flex gap-2">
        <Button
          size="sm"
          variant={following ? 'default' : 'outline'}
          aria-pressed={following}
          onClick={blurred(onFollow)}
        >
          follow
        </Button>
        <Button size="sm" variant="outline" onClick={blurred(onGoTo)}>
          go to
        </Button>
      </footer>
    </aside>
  );
}
