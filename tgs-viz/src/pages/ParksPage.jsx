import React, { useState, useMemo } from 'react';

// League rules stated by the user (2026-09-12): a park can be used by at most three
// clubs, and switching costs $50M. Rules, not estimates.
const MAX_TEAMS_PER_PARK = 3;
const SWITCH_COST = 50_000_000;

export const factorClass = (v) => {
  if (!Number.isFinite(v)) return 'text-slate-500';
  if (v >= 1.10) return 'text-red-400 font-semibold';
  if (v >= 1.03) return 'text-orange-300';
  if (v <= 0.90) return 'text-blue-400 font-semibold';
  if (v <= 0.97) return 'text-sky-300';
  return 'text-slate-300';
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
          <th key={key} title={title || undefined} onClick={() => clickSort(key, numeric)}>
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
      <div className="p-6 text-slate-400 text-sm">
        No park data for {league}. Run <span className="font-mono text-slate-200">python tgs-viz/ingest/parks.py --write</span> after
        checking in the league&apos;s park-factor export.
      </div>
    );
  }

  return (
    <div className="h-full flex flex-col overflow-auto">
      <div className="px-4 pt-3 pb-1">
        <h1 className="text-xl font-bold text-white">Parks</h1>
        <p className="text-xs text-slate-500 mt-0.5">
          A park can be used by at most {MAX_TEAMS_PER_PARK} clubs, each on its own version · switching costs {fmtMoney(SWITCH_COST)} ·
          factors: 1.00 = neutral, batter-hand splits are the batter&apos;s side
          {hasList && <> · {parkRows.length} parks, {openParks} with an open slot · sources: <span className="font-mono">calib/{league}/park_list.csv</span> + <span className="font-mono">park_assignments.csv</span></>}
        </p>
      </div>

      {home && (
        <div className="mx-4 my-2 px-3 py-2 rounded-lg bg-blue-900/20 border border-blue-800/50 text-xs text-slate-300 flex flex-wrap gap-x-5 gap-y-1">
          <span className="font-bold text-blue-300">Your park</span>
          <span>{home.park || home.stadium}</span>
          {homePark && <span className="text-slate-400">used by {homePark.occupants_text}</span>}
          <span>HR <b className={factorClass(home.hr)}>{f3(home.hr)}</b> (vRHB {f3(home.hr_rhb)} · vLHB {f3(home.hr_lhb)})</span>
          <span>Avg <b className={factorClass(home.avg)}>{f3(home.avg)}</b></span>
          <span>2B {f3(home.doubles)} · 3B {f3(home.triples)}</span>
          {homePark && <span className="text-slate-500">{homePark.copies} of {MAX_TEAMS_PER_PARK} slots used</span>}
        </div>
      )}

      {hasList && (
        <div className="px-4 pb-2">
          <h2 className="text-sm font-bold text-slate-200 mb-1">Parks <span className="font-normal text-slate-500 text-xs">— the league&apos;s list and who is in each (factors are per club, in the table below)</span></h2>
          <div className="table-container compact-table" style={{ maxHeight: 300 }}>
            <table className="data-table">
              <Head cols={PARK_COLS} sort={pSort} clickSort={pClick} />
              <tbody>
                {sortedParks.map(p => (
                  <tr key={p.Name} className={homePark && p.Name === homePark.Name ? 'bg-blue-900/20' : ''}>
                    <td className={`whitespace-nowrap ${homePark && p.Name === homePark.Name ? 'text-blue-300 font-semibold' : 'text-white'}`}>{p.Name}</td>
                    <td>{p.copies}</td>
                    <td className={p.open > 0 ? 'text-green-400 font-semibold' : 'text-slate-600'}>{p.open > 0 ? `${p.open} open` : 'full'}</td>
                    <td className="text-slate-400 text-xs">{p.occupants_text || <span className="text-slate-600">empty</span>}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      <div className="flex-1 px-4 pb-3">
        <h2 className="text-sm font-bold text-slate-200 mb-1">Clubs <span className="font-normal text-slate-500 text-xs">— each club&apos;s own factors (its version of the park)</span></h2>
        <div className="table-container compact-table" style={{ maxHeight: hasList ? 'calc(100vh - 560px)' : 'calc(100vh - 170px)', minHeight: 200 }}>
          <table className="data-table">
            <Head cols={CLUB_COLS} sort={cSort} clickSort={cClick} />
            <tbody>
              {sortedClubs.map(p => (
                <tr key={p.Name} className={p.is_home ? 'bg-blue-900/20' : ''}>
                  <td className={`whitespace-nowrap ${p.is_home ? 'text-blue-300 font-semibold' : 'text-white'}`}>{p.Name}</td>
                  <td className="whitespace-nowrap text-slate-300">{p.park || p.stadium}</td>
                  <td className={factorClass(p.hr)}>{f3(p.hr)}</td>
                  <td className={factorClass(p.hr_rhb)}>{f3(p.hr_rhb)}</td>
                  <td className={factorClass(p.hr_lhb)}>{f3(p.hr_lhb)}</td>
                  <td className={factorClass(p.avg)}>{f3(p.avg)}</td>
                  <td className={factorClass(p.avg_rhb)}>{f3(p.avg_rhb)}</td>
                  <td className={factorClass(p.avg_lhb)}>{f3(p.avg_lhb)}</td>
                  <td className={factorClass(p.doubles)}>{f3(p.doubles)}</td>
                  <td className={factorClass(p.triples)}>{f3(p.triples)}</td>
                  <td className="text-slate-400">{Number.isFinite(p.capacity) ? p.capacity.toLocaleString() : ''}</td>
                  <td className="text-slate-400 whitespace-nowrap">{p.type}</td>
                  <td className="text-slate-400">{p.surface}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
