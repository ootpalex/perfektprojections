import React, { useState, useMemo } from 'react';
import { usePlayersWithFV, usePlayersWithDraftFV } from '../hooks/usePlayerData';
import PlayerDetail from '../components/PlayerDetail';
import { useSelectedById } from '../hooks/useSelectedById';
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
export default function MockDraftPage({ hitters, pitchers, fullHitters, fullPitchers, picks, allHitters, allPitchers }) {
  const [picksPerRound, setPicksPerRound] = useState(28);
  const [rounds, setRounds] = useState(35);
  const [viewRound, setViewRound] = useState('all'); // 'all' | round number | 'und'
  const [search, setSearch] = useState('');
  const [fromBeginning, setFromBeginning] = useState(true);

  // The REAL draft structure (round / pick / overall / club per pick, supplementals
  // included), shipped by draft.py. When present, the mock slots our board into these
  // picks — a fixed rounds x picks-per-round grid can never match a draft with comp
  // picks (user 2026-09-12). The grid inputs are the fallback when no pick list exists.
  const realPicks = useMemo(() => (picks || [])
    .map(p => ({ overall: parseInt(p.Overall), round: parseInt(p.Round), pick: parseInt(p.Pick), team: p.Team }))
    .filter(p => Number.isFinite(p.overall) && p.overall > 0)
    .sort((a, b) => a.overall - b.overall), [picks]);
  const hasReal = realPicks.length > 0;
  const realRounds = hasReal ? Math.max(...realPicks.map(p => p.round)) : 0;

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
  // The open card is kept by player ID and found again in the current rows.
  const rowsByKind = useMemo(() => ({ hitter: hittersWithDraftFV, pitcher: pitchersWithDraftFV }), [hittersWithDraftFV, pitchersWithDraftFV]);
  const { selected: selectedPlayer, kind: playerType, select, clear } = useSelectedById(rowsByKind);

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

    const base = players.map(p => ({
      ...p,
      // genuine two-way threats only (stamped by draft.py when BOTH sides clear
      // league average at peak): the OFF side's peak + which side it is
      _twPeak: Number.isFinite(parseFloat(p['Bat Peak'] ?? p['Arm Peak']))
        ? parseFloat(p['Bat Peak'] ?? p['Arm Peak']) : null,
      _twSide: p['Bat Peak'] != null ? 'BAT' : (p['Arm Peak'] != null ? 'ARM' : null),
    }));
    if (hasReal) {
      // board player i goes to the club that really held pick i; past the last real
      // pick the class is undrafted
      return base.map((p, i) => {
        const rp = realPicks[i];
        return {
          ...p,
          _overall: i + 1,
          _round: rp ? rp.round : null,
          _pick: rp ? rp.pick : null,
          _slot: rp ? `${rp.round}.${String(rp.pick).padStart(2, '0')}` : 'UND',
          _mockTeam: rp ? rp.team : null,
        };
      });
    }
    const totalSlots = picksPerRound * rounds;
    return base.map((p, i) => ({
      ...p,
      _overall: i + 1,
      _round: i < totalSlots ? Math.floor(i / picksPerRound) + 1 : null,
      _pick: i < totalSlots ? (i % picksPerRound) + 1 : null,
      _slot: i < totalSlots
        ? `${Math.floor(i / picksPerRound) + 1}.${String((i % picksPerRound) + 1).padStart(2, '0')}`
        : 'UND',
      _mockTeam: null,
    }));
  }, [hittersWithDraftFV, pitchersWithDraftFV, picksPerRound, rounds, hasReal, realPicks]);

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

  const slotCount = hasReal ? realPicks.length : picksPerRound * rounds;
  const roundCount = hasReal ? realRounds : rounds;
  const undrafted = slotted.length - Math.min(slotted.length, slotCount);

  // Team draft grades (from-the-beginning view): how each club did, by OUR board.
  // Value = Draft FV of the player taken minus the Draft FV our board had AT that
  // overall pick (the player we would have slotted there). FV points, not slot
  // distance: late slots are hundreds of ranks apart but near-identical in talent,
  // so a round-12 "500-slot steal" is worth ~0 while a 2.07 taken 10th costs real
  // points. Positive = better than our board expected at that pick.
  const [gradeSort, setGradeSort] = useState('fv'); // fv | avg | value
  const [showGrades, setShowGrades] = useState(true);
  // Best value / biggest reach consider IMPACT picks only (user 2026-09-12): late
  // rounds are a lottery, so a pick qualifies only when something impactful was on
  // the table at that slot — the player taken OR the player our board had there
  // projects at or above league average at peak (ceiling >= 0 WAA, the two-way
  // flag's bar). The totals still run over every pick.
  const REACH_MAX_ROUND = 5;
  const teamGrades = useMemo(() => {
    if (!useFull) return [];
    const by = new Map();
    const atSlot = (overall) => slotted[Math.min(Math.max(Math.round(overall), 1), slotted.length) - 1];
    const fvOf = (row) => parseFloat(row?._draftRawFV) || 0;
    const impact = (row) => (parseFloat(row?._draftCeilingWAA) || -Infinity) >= 0;
    for (const p of slotted) {
      const actual = parseFloat(p.DraftedOverall);
      if (!p.DraftedTeam || !Number.isFinite(actual)) continue;
      const boardPick = atSlot(actual);
      const fv = fvOf(p);
      const t = by.get(p.DraftedTeam) || { team: p.DraftedTeam, picks: 0, fv: 0, mock: 0, value: 0, steal: null, reach: null };
      const diff = Math.round((fv - fvOf(boardPick)) * 10) / 10;   // FV points vs our board at that pick
      const pick = { name: p.Name, fv, actual, slot: p._slot, diff };
      t.picks += 1;
      t.fv += fv;
      t.mock += fvOf(boardPick);
      t.value += diff;
      // best pick = best VALUE against our board, not the highest score (a 2.07 taken
      // 10th is a reach, not a best pick); reach = the worst value; impact picks only
      if (impact(p) || impact(boardPick)) {
        if (!t.steal || diff > t.steal.diff) t.steal = pick;
        // reaches only count in the early rounds (user preference, 2026-09-12): late
        // picks are often Winter League roster filler, not a talent judgment
        const rnd = parseInt(p.DraftedRound);
        if (Number.isFinite(rnd) && rnd <= REACH_MAX_ROUND && (!t.reach || diff < t.reach.diff)) t.reach = pick;
      }
      by.set(p.DraftedTeam, t);
    }
    const rows = [...by.values()].map(t => ({ ...t, avg: t.picks ? t.fv / t.picks : 0 }));
    const key = gradeSort === 'avg' ? 'avg' : gradeSort === 'value' ? 'value' : 'fv';
    return rows.sort((a, b) => b[key] - a[key]);
  }, [slotted, useFull, gradeSort]);

  const fvColor = (fv) => {
    if (fv >= 70) return 'var(--g80)';
    if (fv >= 60) return 'var(--g70)';
    if (fv >= 55) return 'var(--g55)';
    if (fv >= 50) return 'var(--text-2)';
    if (fv >= 45) return 'var(--g30)';
    return 'var(--text-2)';
  };

  return (
    <div className="ns-page overflow-auto [&>*]:shrink-0">
      <header className="ns-page-head">
        <div>
        <h1>Mock Draft</h1>
        <p className="ns-page-sub">
          {useFull
            ? 'the whole class from the beginning, in Draft FV order — "Actually" is where each drafted player really went'
            : 'players still on the board, in Draft FV order — re-ranks as picks come in'}
          {' '}· {slotted.length} players · {slotCount} picks{hasReal ? ` (real draft order, ${roundCount} rounds)` : ''}
          {undrafted > 0 && ` · ${undrafted} undrafted`}
          {!hasFull && ' · full-class file not built yet — run a board update for the from-the-beginning view'}
        </p>
        </div>
      </header>

      {/* Controls */}
      <div className="flex flex-wrap items-center gap-3 pb-3">
        <select value={viewRound} onChange={e => setViewRound(e.target.value)}
          className="ns-select">
          <option value="all">All rounds</option>
          {Array.from({ length: roundCount }, (_, i) => (
            <option key={i + 1} value={i + 1}>Round {i + 1}</option>
          ))}
          {undrafted > 0 && <option value="und">Undrafted</option>}
        </select>

        <input
          type="text" placeholder="Find a player…" value={search}
          onChange={e => setSearch(e.target.value)}
          className="ns-input w-48"
        />

        {!hasReal && <div className="flex items-center gap-2">
          <label className="ns-label">Picks/round:</label>
          <input type="number" min="2" max="40" value={picksPerRound}
            onChange={e => setPicksPerRound(Math.max(2, parseInt(e.target.value) || 28))}
            className="ns-input w-16" />
        </div>}

        {!hasReal && <div className="flex items-center gap-2">
          <label className="ns-label">Rounds:</label>
          <input type="number" min="1" max="60" value={rounds}
            onChange={e => setRounds(Math.max(1, parseInt(e.target.value) || 35))}
            className="ns-input w-16" />
        </div>}

        {hasFull && (
          <label className="flex items-center gap-1.5 text-xs ns-text-2 cursor-pointer">
            <input type="checkbox" checked={fromBeginning} onChange={e => setFromBeginning(e.target.checked)}
              className="border-[var(--line-2)]" />
            From the beginning
          </label>
        )}

        <span className="ml-auto text-xs ns-muted">{visible.length} shown</span>
      </div>

      {/* Team draft grades */}
      {useFull && teamGrades.length > 0 && (
        <div className="pb-2">
          <div className="ns-box">
            <div className="ns-strip flex items-center gap-3 text-xs">
              <button type="button" onClick={() => setShowGrades(s => !s)} aria-expanded={showGrades} className="font-bold ns-text flex items-center gap-1.5">
                <span className="ns-muted">{showGrades ? '▾' : '▸'}</span> Team draft grades
              </button>
              <span className="ns-muted">by our board · value = Draft FV taken minus the Draft FV our board had at that pick, summed · + = out-drafted the board</span>

              <label className="ml-auto flex items-center gap-1.5 ns-text-2">
                Rank by
                <select value={gradeSort} onChange={e => setGradeSort(e.target.value)}
                  className="ns-select">
                  <option value="fv">Total Draft FV</option>
                  <option value="avg">Avg Draft FV</option>
                  <option value="value">Value (FV pts)</option>
                </select>
              </label>
            </div>
            {showGrades && (
              <div className="overflow-auto compact-table" style={{ maxHeight: 200 }}>
                <table className="data-table">
                  <thead>
                    <tr>
                      <th className="w-8">#</th><th>Team</th>
                      <th>Picks</th>
                      <th title="Draft FV of the players the club actually took, summed">Actual FV</th>
                      <th title="Draft FV our board had at those same picks, summed">Mock FV</th>
                      <th>Avg FV</th>
                      <th title="Sum over the club's picks of (Draft FV taken − Draft FV our board had at that overall pick), in FV points">Value (FV pts)</th>
                      <th title="Most Draft FV gained over what our board had at that pick — impact picks only (the player taken or our board's player at that slot has a ceiling >= 0 WAA at peak)">Best value</th>
                      <th title="Most Draft FV given up vs what our board had at that pick — impact picks in rounds 1-5 only (later picks are usually roster filler)">Biggest reach</th>
                    </tr>
                  </thead>
                  <tbody>
                    {teamGrades.map((t, i) => (
                      <tr key={t.team}>
                        <td className="ns-muted">{i + 1}</td>
                        <td className="ns-text font-medium">{t.team}</td>
                        <td>{t.picks}</td>
                        <td className="font-bold">{t.fv.toFixed(0)}</td>
                        <td className="ns-text-2">{t.mock.toFixed(0)}</td>
                        <td>{t.avg.toFixed(1)}</td>
                        <td className={t.value >= 0 ? 'ns-good' : 'ns-warn'}>{t.value > 0 ? '+' : ''}{t.value.toFixed(1)}</td>
                        <td className="ns-text whitespace-nowrap">
                          {t.steal && <>{t.steal.name} <span className="ns-muted">(our {t.steal.slot} · went #{t.steal.actual} · {t.steal.diff > 0 ? '+' : ''}{t.steal.diff})</span></>}
                        </td>
                        <td className="ns-text whitespace-nowrap">
                          {t.reach && <>{t.reach.name} <span className="ns-muted">(our {t.reach.slot} · went #{t.reach.actual} · {t.reach.diff > 0 ? '+' : ''}{t.reach.diff})</span></>}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </div>
      )}

      {/* Board */}
      <div className="flex-1 pb-3">
        <div className="table-container compact-table" style={{ maxHeight: 'calc(100vh - 130px)' }}>
          <table className="data-table">
            <thead>
              <tr>
                {[
                  ['Slot', '_overall', 'Round.Pick — click to restore the mock order'],
                  ...(hasReal ? [['Mock team', '_mockTeam', 'The club that really held this pick — who our board would hand this player to']] : []),
                  ['Type', '_type', null],
                  ['Name', 'Name', null],
                  ['POS', 'POS', null],
                  ['Age', 'Age', null],
                  ['Draft FV', '_draftRawFV', 'Age percentile 30% + ceiling 60% + projected peak 10%, red flags multiply'],
                  ['Ceiling', '_draftCeilingWAA', 'Best-case peak, WAA — no risk haircut'],
                  ['Proj Peak', '_potentialWAA', 'Proj Potential: where we project him to top out, from the ML model when the row has it, else the DEV cell gain or the measured curve'],
                  ['DEM', 'DEM', 'Signing demand from the OOTP pool export'],
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
                  className={`cursor-pointer hover:bg-[var(--panel-2)] ${player._wrecked ? 'opacity-40' : ''} ${player._pick === 1 && viewRound === 'all' ? 'border-t-2 border-[var(--line-2)]' : ''}`}
                  onClick={() => select(player, player._type === 'H' ? 'hitter' : 'pitcher')}>
                  <td className="font-bold ns-text">{player._slot}</td>
                  {hasReal && <td className="text-xs ns-text-2 whitespace-nowrap">{player._mockTeam || ''}</td>}
                  <td>
                    <span className="ns-chip" data-pos={player._type === 'H' ? 'DH' : 'SP'}>
                      {player._type}
                    </span>
                  </td>
                  <td className="font-medium ns-text">{player.Name}</td>
                  <td>{player.POS}</td>
                  <td>{Math.round(parseFloat(player.Age) || 0)}</td>
                  <td>
                    <span className="px-1.5 font-bold text-xs"
                      style={{ color: fvColor(player._draftFV), background: `color-mix(in oklab, ${fvColor(player._draftFV)} 10%, var(--panel))` }}>
                      {formatCellValue(player._draftRawFV, '_draftRawFV')}
                    </span>
                  </td>
                  <td className={getCellColorClass(player._draftCeilingWAA, '_draftCeilingWAA')}>
                    {formatCellValue(player._draftCeilingWAA, '_draftCeilingWAA')}
                  </td>
                  <td className={getCellColorClass(player._potentialWAA, '_potentialWAA')}>
                    {formatCellValue(player._potentialWAA, '_potentialWAA')}
                  </td>
                  <td className="text-xs ns-text-2">{player.DEM}</td>
                  {useFull && (
                    <td className="text-xs whitespace-nowrap">
                      {player.DraftedOverall ? (
                        <span className="ns-warn" title={`Round ${player.DraftedRound}, pick ${player.DraftedPick}`}>
                          #{player.DraftedOverall} · {player.DraftedTeam}
                        </span>
                      ) : (
                        <span className="ns-muted">on the board</span>
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
          onClose={clear}
          type={playerType}
        />
      )}
    </div>
  );
}
