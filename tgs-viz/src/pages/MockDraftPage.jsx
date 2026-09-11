import React, { useState, useMemo } from 'react';
import { usePlayersWithFV, usePlayersWithDraftFV } from '../hooks/usePlayerData';
import PlayerDetail from '../components/PlayerDetail';
import { formatCellValue, getCellColorClass } from '../lib/columns';

/**
 * Mock Draft — the FULL class from the beginning (nobody removed), slotted into picks
 * in Draft FV order. A separate entity from the Draft Board: this is "how the draft
 * should have gone", so already-drafted players stay in and each shows where he
 * ACTUALLY went (stamped by ingest/draft.py from the live StatsPlus pick list).
 * No filters and no opinions beyond the score itself: the board's own Draft FV ranking
 * IS the mock (Wrecked players score ~0 and fall to the bottom on their own).
 * Round/pick math is display-only; picks-per-round and rounds are editable so the same
 * page works for any league size or draft format.
 */
export default function MockDraftPage({ hitters, pitchers, fullHitters, fullPitchers, allHitters, allPitchers }) {
  const [selectedPlayer, setSelectedPlayer] = useState(null);
  const [playerType, setPlayerType] = useState(null);
  const [picksPerRound, setPicksPerRound] = useState(28);
  const [rounds, setRounds] = useState(35);
  const [viewRound, setViewRound] = useState('all'); // 'all' | round number | 'und'
  const [search, setSearch] = useState('');
  const [fromBeginning, setFromBeginning] = useState(true);

  // Full class when it exists (drafted players stamped + kept); the live board is the
  // fallback for a league whose pull predates the *_draft_all files.
  const hasFull = (fullHitters?.length || 0) + (fullPitchers?.length || 0) > 0;
  const useFull = fromBeginning && hasFull;
  const srcHitters = useFull ? fullHitters : hitters;
  const srcPitchers = useFull ? fullPitchers : pitchers;

  // Same enrichment chain as the Draft Board, so the order here matches its Draft FV sort
  const hittersWithFV = usePlayersWithFV(srcHitters);
  const pitchersWithFV = usePlayersWithFV(srcPitchers);
  const hittersWithDraftFV = usePlayersWithDraftFV(hittersWithFV, allHitters || [], 'hitter');
  const pitchersWithDraftFV = usePlayersWithDraftFV(pitchersWithFV, allPitchers || [], 'pitcher');

  const slotted = useMemo(() => {
    const players = [
      ...hittersWithDraftFV.map(p => ({ ...p, _type: 'H' })),
      ...pitchersWithDraftFV.map(p => ({ ...p, _type: 'P' })),
    ].filter(p => p.Name);

    players.sort((a, b) => {
      const d = (parseFloat(b._draftRawFV) || 0) - (parseFloat(a._draftRawFV) || 0);
      if (d !== 0) return d;
      const c = (b._draftCeilingWAA ?? -99) - (a._draftCeilingWAA ?? -99);
      if (c !== 0) return c;
      return String(a.Name).localeCompare(String(b.Name));
    });

    const totalSlots = picksPerRound * rounds;
    return players.map((p, i) => ({
      ...p,
      // genuine two-way threats only (stamped by draft.py when BOTH sides clear
      // league average at peak): the OFF side's peak + which side it is
      _twPeak: Number.isFinite(parseFloat(p['Bat Peak'] ?? p['Arm Peak']))
        ? parseFloat(p['Bat Peak'] ?? p['Arm Peak']) : null,
      _twSide: p['Bat Peak'] != null ? 'BAT' : (p['Arm Peak'] != null ? 'ARM' : null),
      _overall: i + 1,
      _round: i < totalSlots ? Math.floor(i / picksPerRound) + 1 : null,
      _pick: i < totalSlots ? (i % picksPerRound) + 1 : null,
      _slot: i < totalSlots
        ? `${Math.floor(i / picksPerRound) + 1}.${String((i % picksPerRound) + 1).padStart(2, '0')}`
        : 'UND',
    }));
  }, [hittersWithDraftFV, pitchersWithDraftFV, picksPerRound, rounds]);

  // Column sort — reorders the VIEW only; every player keeps his mock slot.
  const [sort, setSort] = useState({ key: '_overall', dir: 'asc' });
  const NUMERIC = new Set(['_overall', 'Age', '_draftRawFV', '_draftCeilingWAA', '_potentialWAA', 'DraftedOverall', '_twPeak']);
  const clickSort = (key) => {
    setSort(s => s.key === key
      ? { key, dir: s.dir === 'asc' ? 'desc' : 'asc' }
      : { key, dir: (key === '_overall' || key === 'Age' || !NUMERIC.has(key)) ? 'asc' : 'desc' });
  };

  const visible = useMemo(() => {
    let rows = slotted;
    if (viewRound === 'und') rows = rows.filter(p => p._round === null);
    else if (viewRound !== 'all') rows = rows.filter(p => p._round === Number(viewRound));
    const q = search.trim().toLowerCase();
    if (q) rows = rows.filter(p => String(p.Name).toLowerCase().includes(q));
    const { key, dir } = sort;
    const mul = dir === 'asc' ? 1 : -1;
    rows = [...rows].sort((a, b) => {
      if (NUMERIC.has(key)) {
        const av = parseFloat(a[key]); const bv = parseFloat(b[key]);
        const aOk = Number.isFinite(av); const bOk = Number.isFinite(bv);
        if (aOk !== bOk) return aOk ? -1 : 1;             // blanks always last
        if (!aOk) return 0;
        return (av - bv) * mul;
      }
      return String(a[key] ?? '').localeCompare(String(b[key] ?? '')) * mul;
    });
    return rows;
  }, [slotted, viewRound, search, sort]);

  const undrafted = slotted.length - Math.min(slotted.length, picksPerRound * rounds);

  const fvColor = (fv) => {
    if (fv >= 70) return '#8b5cf6';
    if (fv >= 60) return '#06b6d4';
    if (fv >= 55) return '#22c55e';
    if (fv >= 50) return '#eab308';
    if (fv >= 45) return '#f97316';
    return '#94a3b8';
  };
  const durColor = (prone) => {
    const map = { 'Wrecked': '#f87171', 'Fragile': '#fb923c', 'Normal': '#cbd5e1', 'Durable': '#4ade80', 'Iron Man': '#22d3ee' };
    return map[prone] || '#cbd5e1';
  };

  return (
    <div className="h-full flex flex-col overflow-auto">
      <div className="px-4 pt-3 pb-1 flex items-baseline gap-3 flex-wrap">
        <h1 className="text-xl font-bold text-white">Mock Draft</h1>
        <p className="text-xs text-slate-500">
          {useFull
            ? 'the whole class from the beginning, in Draft FV order — "Actually" is where each drafted player really went'
            : 'players still on the board, in Draft FV order — re-ranks as picks come in'}
          {' '}· {slotted.length} players · {picksPerRound * rounds} slots
          {undrafted > 0 && ` · ${undrafted} undrafted`}
          {!hasFull && ' · full-class file not built yet — run a board update for the from-the-beginning view'}
        </p>
      </div>

      {/* Controls */}
      <div className="flex flex-wrap items-center gap-3 px-4 pb-3">
        <select value={viewRound} onChange={e => setViewRound(e.target.value)}
          className="py-1.5 px-2 bg-slate-800 border border-slate-600 rounded-lg text-sm text-slate-200">
          <option value="all">All rounds</option>
          {Array.from({ length: rounds }, (_, i) => (
            <option key={i + 1} value={i + 1}>Round {i + 1}</option>
          ))}
          {undrafted > 0 && <option value="und">Undrafted</option>}
        </select>

        <input
          type="text" placeholder="Find a player…" value={search}
          onChange={e => setSearch(e.target.value)}
          className="py-1.5 px-3 bg-slate-800 border border-slate-600 rounded-lg text-sm text-slate-200 w-48"
        />

        <div className="flex items-center gap-2">
          <label className="text-xs text-slate-500">Picks/round:</label>
          <input type="number" min="2" max="40" value={picksPerRound}
            onChange={e => setPicksPerRound(Math.max(2, parseInt(e.target.value) || 28))}
            className="w-16 py-1 px-2 bg-slate-800 border border-slate-600 rounded-lg text-sm text-slate-200" />
        </div>

        <div className="flex items-center gap-2">
          <label className="text-xs text-slate-500">Rounds:</label>
          <input type="number" min="1" max="60" value={rounds}
            onChange={e => setRounds(Math.max(1, parseInt(e.target.value) || 35))}
            className="w-16 py-1 px-2 bg-slate-800 border border-slate-600 rounded-lg text-sm text-slate-200" />
        </div>

        {hasFull && (
          <label className="flex items-center gap-1.5 text-xs text-slate-400 cursor-pointer">
            <input type="checkbox" checked={fromBeginning} onChange={e => setFromBeginning(e.target.checked)}
              className="rounded border-slate-600" />
            From the beginning
          </label>
        )}

        <span className="ml-auto text-xs text-slate-500">{visible.length} shown</span>
      </div>

      {/* Board */}
      <div className="flex-1 px-4 pb-3">
        <div className="table-container compact-table" style={{ maxHeight: 'calc(100vh - 130px)' }}>
          <table className="data-table">
            <thead>
              <tr>
                {[
                  ['Slot', '_overall', 'Round.Pick — click to restore the mock order'],
                  ['#', '_overall', 'Overall pick number'],
                  ['Type', '_type', null],
                  ['Name', 'Name', null],
                  ['POS', 'POS', null],
                  ['NAT', 'ORG', null],
                  ['Age', 'Age', null],
                  ['Draft FV', '_draftRawFV', 'Age percentile 30% + ceiling 60% + projected peak 10%, red flags multiply'],
                  ['Ceiling', '_draftCeilingWAA', 'Best-case peak, WAA — no risk haircut'],
                  ['Proj Peak', '_potentialWAA', 'Same ceiling after the gap-factor + risk haircut'],
                  ['Durability', '_durability', null],
                  ['DEM', 'DEM', 'Signing demand from the OOTP pool export'],
                  ['2W', '_twPeak', 'Genuine two-way threat: BOTH sides clear league average at peak. Shows the OFF side’s peak WAA (BAT for arms, ARM for bats).'],
                  ...(useFull ? [['Actually', 'DraftedOverall', 'Where he really went (live StatsPlus pick list)']] : []),
                ].map(([label, key, title]) => (
                  <th key={label} title={title || undefined} onClick={() => clickSort(key)}>
                    {label}{sort.key === key ? (sort.dir === 'asc' ? ' ▲' : ' ▼') : ''}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {visible.map((player) => (
                <tr key={player.ID || `${player.Name}-${player._overall}`}
                  className={`cursor-pointer hover:bg-slate-800 ${player._wrecked ? 'opacity-40' : ''} ${player._pick === 1 && viewRound === 'all' ? 'border-t-2 border-slate-600' : ''}`}
                  onClick={() => { setSelectedPlayer(player); setPlayerType(player._type === 'H' ? 'hitter' : 'pitcher'); }}>
                  <td className="font-mono font-bold text-slate-200">{player._slot}</td>
                  <td className="text-slate-500 font-mono text-xs">{player._overall}</td>
                  <td>
                    <span className={`px-1 rounded text-xs font-bold ${
                      player._type === 'H' ? 'bg-blue-900/50 text-blue-400' : 'bg-amber-900/50 text-amber-400'
                    }`}>
                      {player._type}
                    </span>
                  </td>
                  <td className="font-medium text-white">{player.Name}</td>
                  <td>{player.POS}</td>
                  <td className="text-slate-400">{player.ORG}</td>
                  <td>{Math.round(parseFloat(player.Age) || 0)}</td>
                  <td>
                    <span className="px-1.5 rounded font-bold text-xs"
                      style={{ color: fvColor(player._draftFV), background: `${fvColor(player._draftFV)}15` }}>
                      {formatCellValue(player._draftRawFV, '_draftRawFV')}
                    </span>
                  </td>
                  <td className={getCellColorClass(player._draftCeilingWAA, '_draftCeilingWAA')}>
                    {formatCellValue(player._draftCeilingWAA, '_draftCeilingWAA')}
                  </td>
                  <td className={getCellColorClass(player._potentialWAA, '_potentialWAA')}>
                    {formatCellValue(player._potentialWAA, '_potentialWAA')}
                  </td>
                  <td style={{ color: durColor(player._durability) }} className="text-xs">
                    {player._durability}
                    {player._weBoost && <span className="ml-1 text-green-400" title="High Work Ethic">+WE</span>}
                  </td>
                  <td className="text-xs text-slate-400">{player.DEM}</td>
                  <td>
                    {player._twSide && (
                      <span className="px-1 rounded text-xs font-bold bg-purple-900/50 text-purple-300"
                        title={`Genuine two-way threat — ${player._twSide === 'BAT' ? 'bat' : 'arm'} also peaks at ${player._twPeak >= 0 ? '+' : ''}${player._twPeak} WAA`}>
                        {player._twSide} {player._twPeak >= 0 ? '+' : ''}{player._twPeak}
                      </span>
                    )}
                  </td>
                  {useFull && (
                    <td className="text-xs whitespace-nowrap">
                      {player.DraftedOverall ? (
                        <span className="text-amber-400" title={`Round ${player.DraftedRound}, pick ${player.DraftedPick}`}>
                          #{player.DraftedOverall} · {player.DraftedTeam}
                        </span>
                      ) : (
                        <span className="text-slate-600">on the board</span>
                      )}
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {selectedPlayer && (
        <PlayerDetail
          player={selectedPlayer}
          onClose={() => setSelectedPlayer(null)}
          type={playerType}
        />
      )}
    </div>
  );
}
