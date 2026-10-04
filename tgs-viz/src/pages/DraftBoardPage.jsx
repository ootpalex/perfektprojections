import React, { useState, useMemo } from 'react';
import { usePlayersWithFV, usePlayersWithDraftFV, usePlayersWithG5FV, usePlayersWithHybridFV } from '../hooks/usePlayerData';
import PlayerDetail from '../components/PlayerDetail';
import { useSelectedById } from '../hooks/useSelectedById';
import { formatCellValue, getCellColorClass, posClass } from '../lib/columns';
import { useAppConfig } from '../lib/controlApi';
import {
  MARK_MINE, MARK_TAKEN, loadMarks, saveMarks, toggleMark, livePickIndex,
  draftStatus, pickLabel, hiddenAsTaken, summarizeMarks,
} from '../lib/draftMarks';
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, ScatterChart, Scatter, ZAxis } from 'recharts';

// localStorage, or null where it is blocked (draftMarks reads null as no marks).
const store = () => { try { return window.localStorage; } catch { return null; } };

// FV ladder (20-80): same band edges as before the restyle, only the classes changed.
const fvClass = (fv) => {
  if (fv >= 70) return 'ns-g80';
  if (fv >= 60) return 'ns-g70';
  if (fv >= 55) return 'ns-g55';
  if (fv >= 50) return 'ns-text-2';
  if (fv >= 45) return 'ns-g30';
  return 'ns-muted';
};

const PRONE_CLASS = {
  'Iron Man': 'ns-prone-iron-man', Durable: 'ns-prone-durable', Normal: 'ns-prone-normal',
  Fragile: 'ns-prone-fragile', Wrecked: 'ns-prone-wrecked',
};

const TOOLTIP_STYLE = { background: 'var(--chart-tooltip-bg)', border: '1px solid var(--chart-tooltip-border)', borderRadius: 'var(--radius)' };

// The status cell: a live pick (from the pull), or my manual mark.
function PickCell({ status }) {
  if (!status) return <span className="ns-dim">—</span>;
  if (status.source === 'live') {
    return (
      <span className={status.mine ? 'ns-good font-semibold' : 'ns-muted'}
        title={`Drafted ${pickLabel(status.pick) || ''} by ${status.pick.team || 'unknown'} (from the last pull)`}>
        {pickLabel(status.pick) || 'drafted'} {status.mine ? 'mine' : ''}
      </span>
    );
  }
  return status.mine
    ? <span className="ns-good font-semibold" title="You marked him as your pick">mine</span>
    : <span className="ns-muted" title="You marked him as taken by another club">taken</span>;
}

export default function DraftBoardPage({ hitters, pitchers, allHitters, allPitchers, picks = [], league }) {
  const [viewMode, setViewMode] = useState('combined'); // combined, hitters, pitchers
  const [sortBy, setSortBy] = useState('_draftRawFV'); // default to Draft FV Raw
  const [maxAge, setMaxAge] = useState(30);
  const [minFV, setMinFV] = useState(20);
  const [hideWrecked, setHideWrecked] = useState(true);
  const [hideImpossible, setHideImpossible] = useState(true);
  const [hideTaken, setHideTaken] = useState(true);

  // Draft tracking: my manual marks (per league, in localStorage) merged with the
  // live picks from the pull. A league switch reloads that league's marks.
  const myOrg = useAppConfig()?.leagues?.[league]?.my_org || null;
  const [marks, setMarks] = useState(() => loadMarks(store(), league));
  const [marksLeague, setMarksLeague] = useState(league);
  if (marksLeague !== league) {
    setMarksLeague(league);
    setMarks(loadMarks(store(), league));
  }
  const updateMarks = (fn) => setMarks((prev) => {
    const next = fn(prev);
    saveMarks(store(), league, next);
    return next;
  });
  const liveIndex = useMemo(() => livePickIndex(picks), [picks]);
  const statusOf = (p) => draftStatus(p.ID, marks, liveIndex, myOrg);
  const markSummary = useMemo(() => summarizeMarks(marks, liveIndex, myOrg), [marks, liveIndex, myOrg]);

  // Chain: raw data → FV → Draft FV → G5 → Hybrid
  const hittersWithFV = usePlayersWithFV(hitters);
  const pitchersWithFV = usePlayersWithFV(pitchers);
  const hittersWithDraftFV = usePlayersWithDraftFV(hittersWithFV, allHitters || [], 'hitter');
  const pitchersWithDraftFV = usePlayersWithDraftFV(pitchersWithFV, allPitchers || [], 'pitcher');
  const hittersWithG5 = usePlayersWithG5FV(hittersWithDraftFV, allHitters || [], 'hitter');
  const pitchersWithG5 = usePlayersWithG5FV(pitchersWithDraftFV, allPitchers || [], 'pitcher');
  const hittersWithHybrid = usePlayersWithHybridFV(hittersWithG5);
  const pitchersWithHybrid = usePlayersWithHybridFV(pitchersWithG5);
  // The open card is kept by player ID and found again in the current rows.
  const rowsByKind = useMemo(() => ({ hitter: hittersWithHybrid, pitcher: pitchersWithHybrid }), [hittersWithHybrid, pitchersWithHybrid]);
  const { selected: selectedPlayer, kind: playerType, select, clear } = useSelectedById(rowsByKind);

  // Combined and sorted draft board (all that pass the filters; the table shows the top 200)
  const rankedBoard = useMemo(() => {
    let players = [];

    if (viewMode !== 'pitchers') {
      players.push(...hittersWithHybrid.map(p => ({ ...p, _type: 'H' })));
    }
    if (viewMode !== 'hitters') {
      players.push(...pitchersWithHybrid.map(p => ({ ...p, _type: 'P' })));
    }

    // Filter (draft files are already pre-filtered to draftable players by extract_data.py)
    players = players.filter(p => {
      if (!p.Name) return false;
      const age = parseFloat(p.Age) || 99;
      const fv = p._fvScale || 0;
      if (age > maxAge || fv < minFV) return false;
      if (hideWrecked && p._wrecked) return false;
      if (hideImpossible && p.DEM === 'Impossible' && (p._draftFV || 0) < 60) return false;
      if (p._draftCeiling === null) return false; // no projection data at all
      if (hideTaken && hiddenAsTaken(draftStatus(p.ID, marks, liveIndex, myOrg))) return false;
      return true;
    });

    // Sort — players with raw ceiling > 0 always rank above players with ceiling <= 0
    players.sort((a, b) => {
      const aAbove = (a._draftCeiling ?? -Infinity) > 0;
      const bAbove = (b._draftCeiling ?? -Infinity) > 0;
      if (aAbove !== bAbove) return aAbove ? -1 : 1;
      const aVal = parseFloat(a[sortBy]) || 0;
      const bVal = parseFloat(b[sortBy]) || 0;
      return bVal - aVal;
    });

    return players;
  }, [hittersWithHybrid, pitchersWithHybrid, viewMode, sortBy, maxAge, minFV, hideWrecked, hideImpossible, hideTaken, marks, liveIndex, myOrg]);
  const draftBoard = useMemo(() => rankedBoard.slice(0, 200), [rankedBoard]);

  // My picks: live picks by my org (pick order), then manual 'mine' marks the pull has not caught up on.
  const myPicks = useMemo(() => {
    const byId = new Map([...(hitters || []), ...(pitchers || [])].map(p => [String(p.ID), p]));
    const out = [];
    for (const [id, pk] of liveIndex) {
      if (myOrg && pk.team === myOrg) out.push({ id, name: pk.name || byId.get(id)?.Name || `#${id}`, pos: byId.get(id)?.POS, label: pickLabel(pk), live: true, overall: pk.overall });
    }
    out.sort((a, b) => (a.overall || 0) - (b.overall || 0));
    for (const [id, m] of Object.entries(marks)) {
      if (m !== MARK_MINE || liveIndex.has(id)) continue;
      const p = byId.get(id);
      out.push({ id, name: p?.Name || `#${id}`, pos: p?.POS, label: null, live: false });
    }
    return out;
  }, [hitters, pitchers, liveIndex, marks, myOrg]);

  // Age distribution chart
  const ageDistribution = useMemo(() => {
    const buckets = {};
    draftBoard.forEach(p => {
      const age = Math.round(parseFloat(p.Age) || 0);
      if (!buckets[age]) buckets[age] = { age, hitters: 0, pitchers: 0 };
      if (p._type === 'H') buckets[age].hitters++;
      else buckets[age].pitchers++;
    });
    return Object.values(buckets).sort((a, b) => a.age - b.age);
  }, [draftBoard]);

  // Draft FV vs Age scatter
  const scatterData = useMemo(() => {
    return draftBoard.slice(0, 100).map(p => ({
      age: parseFloat(p.Age) || 0,
      fv: p._draftRawFV || 0,
      name: p.Name,
      type: p._type,
      pos: p.POS,
    }));
  }, [draftBoard]);

  // StatsPlus draft list: an ID header, then up to 500 IDs in board order (the format ours'
  // dashboard exported). Players already taken or mine are left out, whatever the Hide taken toggle.
  const exportDraftList = () => {
    const ids = [];
    const seen = new Set();
    for (const p of rankedBoard) {
      const id = String(p.ID || '');
      const st = draftStatus(id, marks, liveIndex, myOrg);
      if (!id || seen.has(id) || (st && (st.taken || st.mine))) continue;
      seen.add(id);
      ids.push(id);
      if (ids.length >= 500) break;
    }
    const csv = 'ID\n' + ids.join('\n');
    const blob = new Blob([csv], { type: 'text/csv' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `draft_list_${league}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  };

  // Drop manual marks the live picks now cover (the pull caught up).
  const clearRedundant = () => updateMarks((prev) => {
    const next = { ...prev };
    for (const id of Object.keys(next)) if (liveIndex.has(id)) delete next[id];
    return next;
  });
  const clearAll = () => {
    const n = Object.keys(marks).length;
    if (n && window.confirm(`Clear all ${n} draft marks for ${league}? Live picks from the pull are not affected.`)) updateMarks(() => ({}));
  };

  const markBtn = (p, kind, label, title) => {
    const on = marks[String(p.ID)] === kind;
    return (
      <button type="button" className="ns-btn ns-btn-sm px-1.5 py-0" aria-pressed={on} title={title}
        onClick={(ev) => { ev.stopPropagation(); updateMarks((prev) => toggleMark(prev, p.ID, kind)); }}>
        {label}
      </button>
    );
  };

  return (
    <div className="ns-page overflow-auto">
      <header className="ns-page-head">
        <div>
          <h1>Draft Board</h1>
          <p className="ns-page-sub">
            Draft FV: age percentile 30% + ceiling 60% + projected peak 10%, all in WAA · Fragile, work ethic and intelligence adjust it
          </p>
          <p className="text-[11px] ns-muted mt-0.5 max-w-5xl">
            Value columns display WAA (vs average). <b className="ns-text-2">Ceiling</b> = best case, no haircut. <b className="ns-text-2">Proj Peak</b> = where we project him to top out (Proj Potential): from the ML model when the row has it (his WAA today + the ML median gain, washouts counted), else his WAA today + the DEV cell gain or the measured curve. Ceiling is the payoff, Age Pctl is the probability.
          </p>
        </div>
        <div className="ns-head-actions">
          <button type="button" onClick={exportDraftList} className="ns-btn ns-btn-primary ns-btn-sm"
            title="Export the top 500 still available, in board order, as a StatsPlus draft list (ID column)">
            Export CSV
          </button>
        </div>
      </header>

      {/* Draft tracking + charts */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4 mb-4">
        <div className="ns-card">
          <h3 className="ns-strip">
            <span>My picks <span className="ns-count">({markSummary.mine})</span></span>
            <span className="ns-strip-right">{markSummary.taken} taken by others</span>
          </h3>
          {!myOrg && (
            <p className="text-[11px] ns-warn mb-1">No org set for {league}: live picks cannot be told apart as yours. Set "My org" in Setup.</p>
          )}
          {myPicks.length === 0 ? (
            <p className="text-[12.5px] ns-muted">None yet. Mark a player with <b className="ns-text-2">Mine</b> as you draft him; the next pull replaces the mark with the real pick.</p>
          ) : (
            <ul className="text-[12.5px] space-y-0.5 max-h-[150px] overflow-auto">
              {myPicks.map(p => (
                <li key={p.id} className="flex items-center gap-2">
                  <span className="w-10 tabular-nums ns-muted">{p.label || 'mark'}</span>
                  <span className="ns-text font-semibold truncate">{p.name}</span>
                  {p.pos && <span className={posClass(p.pos) || 'ns-text-2'}>{p.pos}</span>}
                  {!p.live && (
                    <button type="button" className="ns-link ml-auto text-[11px]" title="Remove this mark"
                      onClick={() => updateMarks((prev) => toggleMark(prev, p.id, MARK_MINE))}>unmark</button>
                  )}
                </li>
              ))}
            </ul>
          )}
          <div className="mt-2 pt-1.5 ns-rule-t text-[11px] ns-muted flex flex-wrap items-center gap-x-3 gap-y-1">
            <span>{markSummary.live} live picks in the pull · {markSummary.manual} manual marks</span>
            {markSummary.redundant > 0 && (
              <button type="button" className="ns-link text-[11px]" onClick={clearRedundant}
                title="These marks are now covered by the live picks">
                clear {markSummary.redundant} the pull caught up on
              </button>
            )}
            {Object.keys(marks).length > 0 && (
              <button type="button" className="ns-link text-[11px]" onClick={clearAll}>clear all marks</button>
            )}
          </div>
        </div>

        <div className="ns-card">
          <h3 className="ns-strip">Draft FV vs Age</h3>
          <ResponsiveContainer width="100%" height={170}>
            <ScatterChart margin={{ top: 5, right: 10, bottom: 5, left: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="var(--chart-grid)" />
              <XAxis dataKey="age" type="number" domain={['dataMin - 1', 'dataMax + 1']}
                tick={{ fill: 'var(--chart-axis)', fontSize: 11 }} name="Age" />
              <YAxis dataKey="fv" tick={{ fill: 'var(--chart-axis)', fontSize: 11 }} name="Draft FV (Raw)" />
              <ZAxis range={[30, 30]} />
              <Tooltip
                contentStyle={TOOLTIP_STYLE}
                labelStyle={{ color: 'var(--chart-tooltip-text)' }}
                formatter={(value, name) => [typeof value === 'number' ? value.toFixed(1) : value, name]}
                labelFormatter={(label) => `Age: ${label}`}
              />
              <Scatter data={scatterData.filter(d => d.type === 'H')} fill="var(--chart-series-1)" name="Hitters" />
              <Scatter data={scatterData.filter(d => d.type === 'P')} fill="var(--chart-series-2)" name="Pitchers" />
            </ScatterChart>
          </ResponsiveContainer>
          <div className="flex justify-center gap-4 text-[11px] mt-1">
            <span className="ns-series-1">Hitters</span>
            <span className="text-[var(--chart-series-2)]">Pitchers</span>
          </div>
        </div>

        <div className="ns-card">
          <h3 className="ns-strip">Age Distribution</h3>
          <ResponsiveContainer width="100%" height={190}>
            <BarChart data={ageDistribution}>
              <CartesianGrid strokeDasharray="3 3" stroke="var(--chart-grid)" />
              <XAxis dataKey="age" tick={{ fill: 'var(--chart-axis)', fontSize: 11 }} />
              <YAxis tick={{ fill: 'var(--chart-axis)', fontSize: 11 }} />
              <Tooltip contentStyle={TOOLTIP_STYLE} labelStyle={{ color: 'var(--chart-tooltip-text)' }} />
              <Bar dataKey="hitters" stackId="a" fill="var(--chart-series-1)" name="Hitters" />
              <Bar dataKey="pitchers" stackId="a" fill="var(--chart-series-2)" name="Pitchers" />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>

      {/* Draft Board Table */}
      <section className="ns-box flex flex-col min-h-[360px]">
        <div className="ns-strip">
          <h2>Board <span className="ns-count">({draftBoard.length} prospects)</span></h2>
          <span className="ns-strip-right">top 200 shown</span>
        </div>
        <div className="ns-toolbar">
          {['combined', 'hitters', 'pitchers'].map(mode => (
            <button key={mode} type="button" onClick={() => setViewMode(mode)}
              className="ns-btn ns-btn-sm" aria-pressed={viewMode === mode}>
              {mode.charAt(0).toUpperCase() + mode.slice(1)}
            </button>
          ))}

          <select value={sortBy} onChange={e => setSortBy(e.target.value)} className="ns-select">
            <option value="_draftRawFV">Sort by Draft FV</option>
            <option value="_draftCeilingWAA">Sort by Ceiling (WAA)</option>
            <option value="_agePercentile">Sort by Age Percentile</option>
            <option value="_futureValue">Sort by Future Value</option>
            <option value="_fvScale">Sort by FV (20-80)</option>
            <option value="_g5FV">Sort by G5 FV (Peak)</option>
            <option value="_hybridFV">Sort by Hybrid FV</option>
            <option value="_potentialWAA">Sort by Proj Peak (WAA)</option>
            <option value="_peakWAA">Sort by Peak WAA</option>
          </select>

          <div className="flex items-center gap-2">
            <label className="ns-label" htmlFor="db-max-age">Max Age</label>
            <input id="db-max-age" type="range" min="16" max="35" value={maxAge} onChange={e => setMaxAge(parseInt(e.target.value))}
              className="w-24 accent-[var(--accent)]" />
            <span className="text-[12.5px] ns-text w-6 tabular-nums">{maxAge}</span>
          </div>

          <div className="flex items-center gap-2">
            <label className="ns-label" htmlFor="db-min-fv">Min FV</label>
            <input id="db-min-fv" type="range" min="20" max="70" step="5" value={minFV} onChange={e => setMinFV(parseInt(e.target.value))}
              className="w-24 accent-[var(--accent)]" />
            <span className="text-[12.5px] ns-text w-6 tabular-nums">{minFV}</span>
          </div>

          <button type="button" className="ns-btn ns-btn-sm" aria-pressed={hideWrecked} onClick={() => setHideWrecked(!hideWrecked)}>
            Hide Wrecked
          </button>
          <button type="button" className="ns-btn ns-btn-sm" aria-pressed={hideImpossible} onClick={() => setHideImpossible(!hideImpossible)}>
            Hide Impossible (&lt;60)
          </button>
          <button type="button" className="ns-btn ns-btn-sm" aria-pressed={hideTaken} onClick={() => setHideTaken(!hideTaken)}
            title="Hide players drafted by another club: the live picks from the pull, and your Taken marks. Your own picks stay.">
            Hide taken
          </button>
        </div>

        <div className="overflow-auto" style={{ maxHeight: 'calc(100vh - 260px)' }}>
          <table className="data-table">
            <thead>
              <tr>
                <th className="w-16">ID</th>
                <th className="w-10">#</th>
                <th title="Mark a pick between pulls: Mine = you drafted him, Taken = another club did">Mark</th>
                <th title="Live pick from the pull (round.pick), or your manual mark">Pick</th>
                <th>Type</th>
                <th>Name</th>
                <th>POS</th>
                <th>ORG</th>
                <th>Age</th>
                <th title="Age percentile x 0.30 + ceiling x 0.60 + projected peak x 0.10 (ceiling x 0.70 when there is no projected peak), then the durability, work ethic and intelligence modifiers.">Draft FV</th>
                <th title="Percentile vs the whole league at this age, on current performance. The PROBABILITY half of Draft FV.">Age Pctl</th>
                <th title="Best-case peak, WAA (vs average): the sheet's own MAX WAA P / WAP. No risk haircut. The PAYOFF half of Draft FV.">Ceiling</th>
                <th>Durability</th>
                <th>INT</th>
                <th className="col-group-start">FV</th>
                <th>Future$</th>
                <th>G5 FV</th>
                <th>G5 Peak</th>
                <th>Dev%</th>
                <th className="col-group-start">Hybrid</th>
                <th title="Proj Potential, WAA: where we project him to top out. From the ML model when the row has it (his WAA today + the ML median gain, washouts counted), else his WAA today + the DEV cell gain or the measured curve.">Proj Peak</th>
              </tr>
            </thead>
            <tbody>
              {draftBoard.map((player, idx) => {
                const status = statusOf(player);
                const rowCls = [
                  'cursor-pointer',
                  status?.mine ? 'selected' : '',
                  status && !status.mine ? 'opacity-50' : '',
                  player._wrecked ? 'opacity-40 line-through' : '',
                ].filter(Boolean).join(' ');
                return (
                  <tr key={player.ID || player.Name || idx}
                    className={rowCls}
                    onClick={() => select(player, player._type === 'H' ? 'hitter' : 'pitcher')}>
                    <td className="ns-muted text-xs">{player.ID}</td>
                    <td className="ns-muted">{idx + 1}</td>
                    <td className="whitespace-nowrap">
                      <span className="inline-flex gap-1">
                        {markBtn(player, MARK_MINE, 'Mine', 'I drafted him (click again to clear)')}
                        {markBtn(player, MARK_TAKEN, 'Taken', 'Another club drafted him (click again to clear)')}
                      </span>
                    </td>
                    <td><PickCell status={status} /></td>
                    <td>
                      <span className={`ns-chip ${player._type === 'H' ? 'ns-series-1' : 'text-[var(--chart-series-2)]'}`}>
                        {player._type}
                      </span>
                    </td>
                    <td className="col-name">
                      {player.Name}
                      {(player['Bat Peak'] != null || player['Arm Peak'] != null) && (
                        <span className="ml-1.5 ns-chip ns-g80"
                          title={`Genuine two-way threat — ${player['Bat Peak'] != null ? 'bat' : 'arm'} also peaks at +${player['Bat Peak'] ?? player['Arm Peak']} WAA`}>
                          2W
                        </span>
                      )}
                    </td>
                    <td className={posClass(player.POS) || 'ns-text-2'}>{player.POS}</td>
                    <td className="ns-text-2">{player.ORG}</td>
                    <td>{Math.round(parseFloat(player.Age) || 0)}</td>
                    <td className={`text-[13px] ${fvClass(player._draftFV)}`}>
                      {formatCellValue(player._draftRawFV, '_draftRawFV')}
                    </td>
                    <td className={getCellColorClass(player._agePercentile, '_agePercentile')}>
                      {formatCellValue(player._agePercentile, '_agePercentile')}
                    </td>
                    <td className={getCellColorClass(player._draftCeilingWAA, '_draftCeilingWAA')}
                      title="Draft FV scores this same number">
                      {formatCellValue(player._draftCeilingWAA, '_draftCeilingWAA')}
                    </td>
                    <td className={`text-xs ${PRONE_CLASS[player._durability] || 'ns-text'}`}>
                      {player._durability}
                      {player._weBoost && <span className="ml-1 ns-good" title="High work ethic (+1.5% Draft FV)">+WE</span>}
                    </td>
                    <td className={getCellColorClass(player._highINT, '_highINT')}>
                      {formatCellValue(player._highINT, '_highINT')}
                    </td>
                    <td className={`col-group-start text-xs ${fvClass(player._fvScale)}`}>
                      {player._fvScale}
                    </td>
                    <td className={getCellColorClass(player._futureValue, '_futureValue')}>
                      {formatCellValue(player._futureValue, '_futureValue')}
                    </td>
                    <td className={`text-xs ${fvClass(player._g5FV)}`}>
                      {player._g5FV}
                    </td>
                    <td className={getCellColorClass(player._g5Raw, '_g5Raw')}>
                      {formatCellValue(player._g5Raw, '_g5Raw')}
                    </td>
                    <td className={getCellColorClass(player._g5DevPct, '_g5DevPct')}>
                      {formatCellValue(player._g5DevPct, '_g5DevPct')}
                    </td>
                    <td className={`col-group-start text-[13px] ${fvClass(player._hybridFV)}`}>
                      {player._hybridFV}
                    </td>
                    <td className={getCellColorClass(player._potentialWAA, '_potentialWAA')}>
                      {formatCellValue(player._potentialWAA, '_potentialWAA')}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </section>

      {selectedPlayer && (
        <PlayerDetail
          player={selectedPlayer}
          onClose={clear}
          type={playerType}
        />
      )}
    </div>
  );
}
