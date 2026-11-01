import {
  type RefObject,
  useEffect,
  useMemo,
  useRef,
  useSyncExternalStore,
} from 'react';
import type { Vector3 } from 'three';

import type { NpcViews } from './globe-npcs';
import { Button } from '@/components/ui/button';
import type { ClockChange, LiveStatus } from '@/hooks/use-live-citizens';
import { CLOCK_SPEEDS } from '@/lib/live/clock-speeds';
import type { LiveCitizen } from '@/lib/live/live-contract';
import { type LiveState, type Speech, speedWords } from '@/lib/live/live-state';
import { activityWords } from '@/lib/live/npc-activity';
import type { ShownDoings } from '@/lib/live/shown-doings';
import type { Region } from '@/lib/world/citizen-looks';
import { citizenLabels } from '@/lib/world/citizen-labels';
import type { LabelStore } from '@/lib/world/label-store';
import { clockRate, timeLapseBadge } from '@/lib/world/visual-rate';

/*
 * The live feed's controls over the globe: the clock with its speed buttons (the local time where the camera is,
 * and a time-lapse badge past ×10), the People panel (select, follow, go to),
 * the citizens' labels and, hidden, the per-citizen data attributes the browser tests read.
 */

const REGIONS: Record<Region, string> = {
  town: 'town',
  band_a: 'Band A',
  band_b: 'Band B',
};

/** Coarse body state in words ("hungry, tired"), "fine" when none (the activity already says asleep or dead). */
function stateWords(citizen: LiveCitizen) {
  return citizen.state.length ? citizen.state.join(', ') : 'fine';
}

const STATUS_WORDS: Record<LiveStatus, string> = {
  connecting: 'connecting…',
  live: 'live',
  reconnecting: 'reconnecting…',
  'no-run': 'no run yet',
  off: 'no feed',
};

export function LiveClock({
  state,
  status,
  onChange,
  site,
}: {
  state: LiveState;
  status: LiveStatus;
  onChange: (change: ClockChange) => void;
  /** The local time where the camera is, when that's not the town ("Band B camp", "04:10"). */
  site: { name: string; time: string } | null;
}) {
  const badge = timeLapseBadge(clockRate(state.speed, state.paused));
  return (
    <div
      className="flex items-center gap-1 rounded-lg bg-white/80 p-1 text-sm shadow"
      data-testid="live-clock"
    >
      <span className="px-1 font-mono" data-testid="live-time">
        day {state.day} · {state.time}
        {site && <span className="text-muted-foreground"> town</span>}
      </span>
      {site && (
        <span className="px-1 font-mono" data-testid="site-time">
          {site.name} {site.time}
        </span>
      )}
      <span className="text-muted-foreground px-1" data-testid="live-speed">
        {speedWords(state)}
      </span>
      {badge && (
        <span
          className="rounded bg-amber-200 px-1.5 text-xs font-medium text-amber-900"
          data-testid="time-lapse-badge"
        >
          {badge}
        </span>
      )}
      <Button
        size="sm"
        variant={state.paused ? 'default' : 'ghost'}
        aria-pressed={state.paused}
        onClick={(event) => {
          onChange({ paused: true });
          event.currentTarget.blur();
        }}
      >
        pause
      </Button>
      {CLOCK_SPEEDS.map(({ label, title, change }) => {
        const active = !state.paused && state.speed === change.speed;
        return (
          <Button
            key={label}
            title={title}
            size="sm"
            variant={active ? 'default' : 'ghost'}
            aria-pressed={active}
            onClick={(event) => {
              onChange(change);
              event.currentTarget.blur();
            }}
          >
            {label}
          </Button>
        );
      })}
      <span className="text-muted-foreground px-1 text-xs">
        {STATUS_WORDS[status]}
      </span>
    </div>
  );
}

export function PeoplePanel({
  citizens,
  followId,
  selectedId,
  onSelect,
  onFollow,
  onGoTo,
}: {
  citizens: LiveCitizen[];
  followId: string | null;
  selectedId: string | null;
  onSelect: (id: string) => void;
  onFollow: (id: string) => void;
  onGoTo: (id: string) => void;
}) {
  return (
    <div
      role="region"
      aria-label="People"
      className="w-96 overflow-y-auto rounded-lg bg-white/90 p-1 text-xs shadow-lg"
    >
      <ul>
        {citizens.map((citizen) => (
          <li
            key={citizen.id}
            data-person={citizen.id}
            aria-current={citizen.id === followId}
            aria-selected={citizen.id === selectedId}
            className="flex items-center gap-2 rounded-md px-2 py-0.5 hover:bg-black/5 aria-[current=true]:bg-black/10 aria-[selected=true]:ring-1 aria-[selected=true]:ring-black/30"
          >
            <button
              type="button"
              className="min-w-0 flex-1 text-left"
              onClick={(event) => {
                onSelect(citizen.id);
                event.currentTarget.blur();
              }}
            >
              <span className="font-medium">{citizen.name}</span>
              <span className="text-muted-foreground">
                {' '}
                · {citizen.role} · {REGIONS[citizen.region]}
              </span>
              <span className="block truncate">
                {activityWords(citizen)}
                {citizen.alive && (
                  <span className="text-muted-foreground">
                    {' '}
                    · {stateWords(citizen)}
                  </span>
                )}
              </span>
            </button>
            <Button
              size="xs"
              variant="outline"
              onClick={(event) => {
                onFollow(citizen.id);
                event.currentTarget.blur();
              }}
            >
              follow
            </Button>
            <Button
              size="xs"
              variant="outline"
              onClick={(event) => {
                onGoTo(citizen.id);
                event.currentTarget.blur();
              }}
            >
              go to
            </Button>
          </li>
        ))}
      </ul>
    </div>
  );
}

/**
 * What the citizens' labels say: a chip each (icon, name, what the drawn body is shown doing, need ring) and the
 * latest speech.
 */
export function CitizenLabels({
  store,
  citizens,
  doings,
  speech,
}: {
  store: LabelStore;
  citizens: LiveCitizen[];
  doings: ShownDoings;
  speech: Speech[];
}) {
  const shown = useSyncExternalStore(doings.subscribe, doings.getSnapshot);
  const contents = useMemo(
    () => citizenLabels(citizens, shown, speech),
    [citizens, shown, speech],
  );
  useEffect(() => store.describe('citizens', contents), [store, contents]);
  return null;
}

const fixed = (value: number) => value.toFixed(2);

/** Hidden: the drawn citizens as data attributes for the browser tests, refreshed ten times a second. */
export function NpcHooks({
  citizens,
  views,
  focusRef,
}: {
  citizens: LiveCitizen[];
  views: NpcViews;
  focusRef: RefObject<Vector3>;
}) {
  const root = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const timer = window.setInterval(() => {
      const element = root.current;
      if (!element) return;
      element.dataset.npcsReady = String(views.size);
      element.dataset.focus = focusRef.current.toArray().map(fixed).join(',');
      for (const item of element.children) {
        const node = item as HTMLElement;
        const view = node.dataset.npc && views.get(node.dataset.npc);
        if (!view) continue;
        const { position, ground } = view.pose;
        node.dataset.npcX = fixed(position.x);
        node.dataset.npcY = fixed(position.y);
        node.dataset.npcZ = fixed(position.z);
        node.dataset.npcGround = fixed(ground);
        node.dataset.npcActivity = view.activity;
        node.dataset.npcPosture = view.posture;
        node.dataset.npcMotion = view.motion;
        node.dataset.npcProp = view.prop;
        node.dataset.npcLayer = view.layer;
        node.dataset.npcStowed = String(view.stowed);
        node.dataset.npcHidden = String(view.hidden);
        node.dataset.npcClip = view.clip;
        node.dataset.npcLoaded = String(view.loaded);
        node.dataset.npcClipClock = view.clipClock.toFixed(3);
        node.dataset.npcFacing = view.pose.facing
          .toArray()
          .map((value) => value.toFixed(4))
          .join(',');
        node.dataset.npcFeet = view.feet
          .map((value) => value.toFixed(4))
          .join(',');
        node.dataset.npcHead = fixed(view.heights.head);
        node.dataset.npcLabelHeight = fixed(view.heights.label);
      }
    }, 100);
    return () => window.clearInterval(timer);
  }, [views, focusRef]);
  return (
    <div ref={root} hidden data-testid="npcs" data-npcs-ready={0}>
      {citizens.map((citizen) => (
        <span
          key={citizen.id}
          data-npc={citizen.id}
          data-npc-label={citizen.action_label}
        />
      ))}
    </div>
  );
}
