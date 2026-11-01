import { useState } from 'react';

import { Button } from '@/components/ui/button';
import { useScoreboard } from '@/hooks/use-spectator';
import type {
  CitizenScore,
  GroupScore,
  StallView,
} from '@/lib/client/types.gen';
import { REGION_NAMES, titled } from '@/lib/spectator/words';

/*
 * The scoreboard tab (10-world-v1 §5.4, §7): every citizen's wealth, flow, health, duty, status, ambition and ties
 * in one sortable table, each group's spread of wealth and deeds, the money supply check and the stall's stocks and
 * prices, now or at the replayed tick. For spectators only: minds are never shown it (D95).
 */

type Column = {
  key: string;
  label: string;
  title: string;
  /** What the column sorts by: a number, words, or numbers compared in order (the first that differs). */
  value: (row: CitizenScore) => number | string | number[];
  shown?: (row: CitizenScore) => string;
  /** A longer reading of the cell, on hover. */
  hint?: (row: CitizenScore) => string;
};

/** Groups in a narrow column. */
const GROUP_SHORT: Record<CitizenScore['region'], string> = {
  town: 'Town',
  band_a: 'Band A',
  band_b: 'Band B',
};

const COLUMNS: Column[] = [
  {
    key: 'name',
    label: 'Name',
    title: 'name and title',
    value: (row) => row.name,
    shown: titled,
  },
  {
    key: 'group',
    label: 'Group',
    title: 'their group',
    value: (row) => row.region,
    shown: (row) => GROUP_SHORT[row.region],
  },
  {
    key: 'coins',
    label: 'Coins',
    title: 'coins carried',
    value: (row) => row.coins,
  },
  {
    key: 'wealth',
    label: 'Wealth',
    title: 'coins + goods carried + a share of the household chest (mon)',
    value: (row) => row.wealth_mon,
  },
  {
    key: 'in',
    label: 'In',
    title: 'coins received over the last game day',
    value: (row) => row.income_24h,
  },
  {
    key: 'out',
    label: 'Out',
    title: 'coins paid out over the last game day',
    value: (row) => row.spent_24h,
  },
  {
    key: 'health',
    label: 'HP',
    title: 'health now (0-100)',
    value: (row) => row.health,
    shown: (row) => (row.alive ? row.health.toFixed(0) : 'dead'),
  },
  {
    key: 'well',
    label: 'Well',
    title: 'share of the last day neither hungry, thirsty nor exhausted',
    value: (row) => row.wellbeing_24h ?? -1,
    shown: (row) =>
      row.wellbeing_24h === null ? '–' : `${row.wellbeing_24h}%`,
  },
  {
    key: 'tax',
    label: 'Owes',
    title:
      "the household's tax owed: rice measures / coins (sorted by coins, then rice)",
    value: (row) => [row.tax_owed.coins, row.tax_owed.rice],
    shown: (row) =>
      row.tax_owed.rice || row.tax_owed.coins
        ? `${row.tax_owed.rice} / ${row.tax_owed.coins}`
        : '–',
  },
  {
    key: 'rank',
    label: 'Rank',
    title: 'rank: 1 child .. 5 lord',
    value: (row) => row.rank ?? 0,
  },
  {
    key: 'standing',
    label: 'Stand.',
    title: 'standing with their own group (-100..100)',
    value: (row) => row.standing ?? -101,
    shown: (row) => (row.standing === null ? '–' : String(row.standing)),
    hint: (row) => row.standing_word,
  },
  {
    key: 'ambition',
    label: 'Aim',
    title: 'how far the world says their ambition is',
    value: (row) => row.ambition?.progress ?? -1,
    shown: (row) =>
      row.ambition
        ? row.ambition.done
          ? 'done'
          : `${row.ambition.progress}%`
        : '–',
  },
  {
    key: 'partners',
    label: 'Trad.',
    title: 'distinct people they traded with at a stall this week',
    value: (row) => row.trade_partners_7d,
  },
  {
    key: 'known',
    label: 'Knows',
    title: 'people / places they know',
    value: (row) => row.people_known,
    shown: (row) => `${row.people_known} / ${row.places_known}`,
  },
  {
    key: 'skill',
    label: 'Skill',
    title: 'the skill they practised most over the run (hours)',
    value: (row) => topSkill(row)?.[1] ?? 0,
    shown: (row) => {
      const top = topSkill(row);
      return top ? `${top[0]} ${top[1].toFixed(0)}h` : '–';
    },
  },
];

function topSkill(row: CitizenScore): [string, number] | undefined {
  return Object.entries(row.skill_hours).sort((a, b) => b[1] - a[1])[0];
}

function compare(
  x: number | string | number[],
  y: number | string | number[],
): number {
  if (Array.isArray(x) && Array.isArray(y))
    return x.reduce((order, value, at) => order || value - y[at], 0);
  if (typeof x === 'number' && typeof y === 'number') return x - y;
  return String(x).localeCompare(String(y));
}

function sortRows(rows: CitizenScore[], column: Column, descending: boolean) {
  return [...rows].sort((a, b) => {
    const order = compare(column.value(a), column.value(b));
    return (descending ? -order : order) || a.name.localeCompare(b.name);
  });
}

function Groups({ groups }: { groups: GroupScore[] }) {
  return (
    <div className="grid grid-cols-3 gap-2" data-testid="scoreboard-groups">
      {groups.map((group) => (
        <div
          key={group.group}
          className="bg-muted/50 rounded p-2"
          data-group={group.group}
        >
          <p className="font-medium">{REGION_NAMES[group.group]}</p>
          <p className="text-muted-foreground">
            {group.alive} alive · {group.wealth_mon} mon · gini{' '}
            {group.gini_wealth.toFixed(2)}
          </p>
          <p className="text-muted-foreground">
            deeds this week {group.deeds_7d} · judged {group.caught_7d}
          </p>
        </div>
      ))}
    </div>
  );
}

function Stall({ stall }: { stall: StallView }) {
  return (
    <section className="flex flex-col gap-1" data-testid="scoreboard-stall">
      <h3 className="text-muted-foreground text-[11px] font-medium tracking-wide uppercase">
        Stall · {stall.keeper ?? 'nobody'} {stall.trading ? '(open)' : '(shut)'}
      </h3>
      <div className="flex flex-wrap gap-1">
        {stall.goods.map((good) => (
          <span
            key={good.item}
            className="bg-muted/50 rounded px-1.5 py-0.5"
            data-good={good.item}
            title={`${good.lot} a lot: sells for ${good.sell}, pays ${good.buy}`}
          >
            {good.item} {good.stock} · {good.sell}/{good.buy}{' '}
            <span
              className={
                good.word === 'dear'
                  ? 'text-red-700'
                  : good.word === 'cheap'
                    ? 'text-green-700'
                    : 'text-muted-foreground'
              }
            >
              {good.word}
            </span>
          </span>
        ))}
      </div>
    </section>
  );
}

/** The scoreboard panel, between the inspector (left, 20rem) and the minimap, above the clock: a click on a row
 * selects that citizen. */
export function Scoreboard({
  at,
  selectedId,
  onSelect,
  onClose,
}: {
  at: number | null;
  selectedId: string | null;
  onSelect: (id: string) => void;
  onClose: () => void;
}) {
  const { data, error } = useScoreboard(at);
  const [sort, setSort] = useState({ key: 'wealth', descending: true });
  const column = COLUMNS.find((entry) => entry.key === sort.key) ?? COLUMNS[0];
  return (
    <aside
      role="region"
      aria-label="Scoreboard"
      className="absolute right-60 bottom-12 left-[21.5rem] flex max-h-[55%] flex-col gap-2 overflow-auto rounded-lg bg-white/95 p-2 text-[11px] shadow-lg"
    >
      <header className="flex items-center gap-2">
        <h2 className="text-sm font-semibold">Scoreboard</h2>
        {data && (
          <span className="text-muted-foreground">
            day {data.day} {data.time} · money{' '}
            <span
              data-testid="scoreboard-money"
              className={
                data.money_supply_ok ? '' : 'font-semibold text-red-700'
              }
            >
              {data.money_supply} {data.money_supply_ok ? '✓' : '✗'}
            </span>{' '}
            · for spectators only
          </span>
        )}
        <Button
          size="xs"
          variant="ghost"
          className="ml-auto"
          aria-label="close scoreboard"
          onClick={(event) => {
            onClose();
            event.currentTarget.blur();
          }}
        >
          ✕
        </Button>
      </header>
      {error && (
        <p className="text-muted-foreground">No scoreboard: {error.message}</p>
      )}
      {!data && !error && (
        <p className="text-muted-foreground">Loading the scoreboard…</p>
      )}
      {data && (
        <>
          <Groups groups={data.groups} />
          <table className="w-full border-collapse" data-testid="scoreboard">
            <thead>
              <tr>
                {COLUMNS.map((entry) => (
                  <th
                    key={entry.key}
                    title={entry.title}
                    aria-sort={
                      entry.key === sort.key
                        ? sort.descending
                          ? 'descending'
                          : 'ascending'
                        : undefined
                    }
                    className="border-b px-0.5 py-px text-left font-medium whitespace-nowrap"
                  >
                    <button
                      type="button"
                      className="hover:underline"
                      onClick={(event) => {
                        setSort((now) => ({
                          key: entry.key,
                          descending:
                            now.key === entry.key ? !now.descending : true,
                        }));
                        event.currentTarget.blur();
                      }}
                    >
                      {entry.label}
                      {entry.key === sort.key &&
                        (sort.descending ? ' ▾' : ' ▴')}
                    </button>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {sortRows(data.citizens, column, sort.descending).map((row) => (
                <tr
                  key={row.id}
                  data-row={row.id}
                  aria-selected={row.id === selectedId}
                  onClick={() => onSelect(row.id)}
                  className={`cursor-pointer hover:bg-sky-50 ${row.id === selectedId ? 'bg-sky-100' : ''} ${row.alive ? '' : 'text-muted-foreground line-through'}`}
                  title={row.ambition?.text}
                >
                  {COLUMNS.map((entry) => (
                    <td
                      key={entry.key}
                      data-col={entry.key}
                      className="px-0.5 py-px whitespace-nowrap tabular-nums"
                      title={entry.hint?.(row)}
                    >
                      {entry.shown ? entry.shown(row) : entry.value(row)}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
          {data.stalls.map((stall) => (
            <Stall key={stall.id} stall={stall} />
          ))}
        </>
      )}
    </aside>
  );
}
