import React, { useState, useMemo } from 'react';

// League rules stated by the user (2026-09-12): a park can be used by at most three
// clubs, and switching costs $50M. Rules, not estimates.
const MAX_TEAMS_PER_PARK = 3;
const SWITCH_COST = 50_000_000;

export const factorClass = (v) => {
  if (!Number.isFinite(v)) return 'ns-muted';
  if (v >= 1.10) return 'ns-bad font-semibold';
  if (v >= 1.03) return 'ns-warn';
  if (v <= 0.90) return 'ns-series-1 font-semibold';
  if (v <= 0.97) return 'ns-series-1';
  return 'ns-text-2';
};
export const f3 = (v) => (Number.isFinite(v) ? v.toFixed(3) : '');

function useSorted(rows, cols, initial) {
  const [sort, setSort] = useState(initial);
  const clickSort = (key, numeric) => setSort(s => s.key === key
    ? { key, dir: s.dir === 'asc' ? 'desc' : 'asc' }
    : { key, dir: numeric ? 'desc' : 'asc' });
  const sorted = useMemo(() => {
    const { key, dir } = sort;
    const mul = dir === 'asc' ? 1 : -1;
    const numeric = cols.find(c => c[1] === key)?.[3];
    return [...rows].sort((a, b) => {
      const d = numeric
        ? ((parseFloat(a[key]) || 0) - (parseFloat(b[key]) || 0)) * mul
        : String(a[key] ?? '').localeCompare(String(b[key] ?? '')) * mul;
      return d !== 0 ? d : String(a.Name ?? '').localeCompare(String(b.Name ?? ''));
    });
  }, [rows, sort, cols]);
  return [sorted, sort, clickSort];
}

function Head({ cols, sort, clickSort }) {
  return (
    <thead>
      <tr>
        {cols.map(([label, key, title, numeric]) => (
          <th key={key} title={title || undefined} onClick={() => clickSort(key, numeric)}
            aria-sort={sort.key === key ? (sort.dir === 'asc' ? 'ascending' : 'descending') : undefined}
            className={`${numeric ? 'num' : ''} ${sort.key === key ? 'sorted' : ''}`}>
            {label}{sort.key === key ? (sort.dir === 'asc' ? ' ▲' : ' ▼') : ''}
          </th>
        ))}
      </tr>
    </thead>
  );
}

// The league's park list: base factors per park, occupancy counted over clubs still in
// the league (folded clubs drop out), open slots against the cap.
const PARK_COLS = [
  ['Park', 'Name', 'Park name as the league lists it (named for its original club)', false],
  ['Copies', 'copies', `Clubs using this park now (cap ${MAX_TEAMS_PER_PARK}); counted from park_assignments.csv over clubs still in the league`, true],
  ['Open', 'open', 'Slots still available to switch into', true],
  ['Used by', 'occupants_text', null, false],
];

// Each club's OWN factors (a club can run its own version of a park) + the park it is on.
const CLUB_COLS = [
  ['Club', 'Name', null, false],
  ['Park', 'park', 'From park_assignments.csv', false],
  ['HR', 'hr', 'Home run factor, all batters', true],
  ['HR vRHB', 'hr_rhb', null, true],
  ['HR vLHB', 'hr_lhb', null, true],
  ['Avg', 'avg', 'Batting average factor, all batters', true],
  ['Avg vRHB', 'avg_rhb', null, true],
  ['Avg vLHB', 'avg_lhb', null, true],
  ['2B', 'doubles', null, true],
  ['3B', 'triples', null, true],
  ['Capacity', 'capacity', null, true],
  ['Type', 'type', null, false],
  ['Surface', 'surface', null, false],
];

export default function ParksPage({ parks, parkList, league }) {
  const parkRows = useMemo(() => (parkList || []).map(p => ({
    ...p, occupants_text: (p.occupants || []).join(', '),
  })), [parkList]);
  const clubRows = useMemo(() => (parks || []).map(p => ({
    ...p, capacity: parseFloat(String(p.capacity ?? '').replace(/,/g, '')),
  })), [parks]);
  const [sortedParks, pSort, pClick] = useSorted(parkRows, PARK_COLS, { key: 'open', dir: 'desc' });
  const [sortedClubs, cSort, cClick] = useSorted(clubRows, CLUB_COLS, { key: 'hr', dir: 'desc' });

  const hasList = parkRows.length > 0;
  const home = clubRows.find(p => p.is_home);
  const homePark = home && parkRows.find(p => p.Name === home.park);
  const openParks = parkRows.filter(p => p.open > 0 && !(homePark && p.Name === homePark.Name)).length;
  const fmtMoney = (v) => `$${(v / 1e6).toFixed(0)}M`;

  if ((!parks || parks.length === 0) && !hasList) {
    return (
      <div className="p-6 ns-text-2 text-sm">
        No park data for {league}. Run <span className="ns-text">python tgs-viz/ingest/parks.py --write</span> after
        checking in the league&apos;s park-factor export.
      </div>
    );
  }

  return (
    <div className="ns-page block overflow-auto">
      <header className="ns-page-head">
        <div>
        <h1>Parks</h1>
        <p className="ns-page-sub">
          A park can be used by at most {MAX_TEAMS_PER_PARK} clubs, each on its own version · switching costs {fmtMoney(SWITCH_COST)} ·
          factors: 1.00 = neutral, batter-hand splits are the batter&apos;s side
          {hasList && <> · {parkRows.length} parks, {openParks} with an open slot · sources: <span>calib/{league}/park_list.csv</span> + <span>park_assignments.csv</span></>}
        </p>
        </div>
      </header>

      {home && (
        <div className="ns-box mb-4 px-3 py-2 bg-[var(--accent-bg)] text-xs ns-text-2 flex flex-wrap gap-x-5 gap-y-1">
          <span className="font-bold ns-text">Your park</span>
          <span>{home.park || home.stadium}</span>
          {homePark && <span className="ns-text-2">used by {homePark.occupants_text}</span>}
          <span>HR <b className={factorClass(home.hr)}>{f3(home.hr)}</b> (vRHB {f3(home.hr_rhb)} · vLHB {f3(home.hr_lhb)})</span>
          <span>Avg <b className={factorClass(home.avg)}>{f3(home.avg)}</b></span>
          <span>2B {f3(home.doubles)} · 3B {f3(home.triples)}</span>
          {homePark && <span className="ns-muted">{homePark.copies} of {MAX_TEAMS_PER_PARK} slots used</span>}
        </div>
      )}

      {hasList && (
        <div className="ns-box mb-4">
          <h2 className="ns-strip">Parks <span className="ns-count">— the league&apos;s list and who is in each (factors are per club, in the table below)</span></h2>
          <div className="compact-table overflow-auto" style={{ maxHeight: 300 }}>
            <table className="data-table">
              <Head cols={PARK_COLS} sort={pSort} clickSort={pClick} />
              <tbody>
                {sortedParks.map(p => (
                  <tr key={p.Name} className={homePark && p.Name === homePark.Name ? 'selected' : ''}>
                    <td className={`whitespace-nowrap ${homePark && p.Name === homePark.Name ? 'font-semibold' : ''} col-name`}>{p.Name}</td>
                    <td className="num">{p.copies}</td>
                    <td className={`num ${p.open > 0 ? 'ns-good font-semibold' : 'ns-dim'}`}>{p.open > 0 ? `${p.open} open` : 'full'}</td>
                    <td className="ns-text-2 text-xs">{p.occupants_text || <span className="ns-dim">empty</span>}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      <div className="ns-box flex-1">
        <h2 className="ns-strip">Clubs <span className="ns-count">— each club&apos;s own factors (its version of the park)</span></h2>
        <div className="compact-table overflow-auto" style={{ maxHeight: hasList ? 'calc(100vh - 560px)' : 'calc(100vh - 170px)', minHeight: 200 }}>
          <table className="data-table">
            <Head cols={CLUB_COLS} sort={cSort} clickSort={cClick} />
            <tbody>
              {sortedClubs.map(p => (
                <tr key={p.Name} className={p.is_home ? 'selected' : ''}>
                  <td className={`whitespace-nowrap ${p.is_home ? 'font-semibold' : ''} col-name`}>{p.Name}</td>
                  <td className="whitespace-nowrap ns-text-2">{p.park || p.stadium}</td>
                  <td className={`num ${factorClass(p.hr)}`}>{f3(p.hr)}</td>
                  <td className={`num ${factorClass(p.hr_rhb)}`}>{f3(p.hr_rhb)}</td>
                  <td className={`num ${factorClass(p.hr_lhb)}`}>{f3(p.hr_lhb)}</td>
                  <td className={`num ${factorClass(p.avg)}`}>{f3(p.avg)}</td>
                  <td className={`num ${factorClass(p.avg_rhb)}`}>{f3(p.avg_rhb)}</td>
                  <td className={`num ${factorClass(p.avg_lhb)}`}>{f3(p.avg_lhb)}</td>
                  <td className={`num ${factorClass(p.doubles)}`}>{f3(p.doubles)}</td>
                  <td className={`num ${factorClass(p.triples)}`}>{f3(p.triples)}</td>
                  <td className="ns-text-2 num">{Number.isFinite(p.capacity) ? p.capacity.toLocaleString() : ''}</td>
                  <td className="ns-text-2 whitespace-nowrap">{p.type}</td>
                  <td className="ns-text-2">{p.surface}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
