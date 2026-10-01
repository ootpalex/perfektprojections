import React, { useState, useMemo, useEffect } from 'react';
import { useSeriesPlannerData } from '../hooks/usePlayerData';
import { planSeries, presetPattern, changedParkFactors, PATTERN_PRESETS } from '../lib/seriesPlanner';
import {
  isInjured, leagueHasInjuryData, leagueHasPositionRatings, leagueGames,
  canPlaySS, canPlayOF, canPlayAllIF, canPlayCFAndCornerOF,
} from '../lib/rosterOptimizer';
import { getCellColorClass } from '../lib/columns';
import { factorClass, f3 } from './ParksPage';
import { Swords, Trophy, Cross, Users, Target, Lock, AlertTriangle, Loader2 } from 'lucide-react';

// The series on the user's desk when this page shipped (2026-09, BLM: Tampa Bay
// against Pittsburgh). It only fills the opponent box on a first visit; the
// page remembers the last series per league after that.
const FIRST_VISIT_OPPONENT = { BLM: 'Pittsburgh Pirates' };

const BEST_OF = [3, 5, 7];
const presetsFor = (bestOf) => Object.keys(PATTERN_PRESETS).filter(id => PATTERN_PRESETS[id].bestOf === bestOf);
const storeKey = (league) => `tgs-series-${league || 'default'}`;
const pctText = (c) => `${Number((c * 100).toFixed(2))}%`;
const seg = (active, tone = 'bg-blue-600') =>
  `px-3 py-1 text-xs font-medium rounded-md transition-colors ${active ? `${tone} text-white` : 'text-slate-400 hover:text-slate-200'}`;
const selectClass = 'py-1.5 px-3 bg-slate-800 border border-slate-600 rounded-lg text-sm text-slate-200';

function readSaved(league) {
  try { return JSON.parse(localStorage.getItem(storeKey(league)) || 'null') || {}; } catch { return {}; }
}

function Label({ children }) {
  return <span className="text-[10px] text-slate-500 uppercase tracking-widest">{children}</span>;
}

function benchRole(h) {
  const e = h['C Eligible'];
  if (e === true || e === 'True' || e === 'TRUE') return 'Backup C';
  if (canPlayAllIF(h)) return 'Utility IF';
  if (canPlaySS(h)) return 'Backup IF';
  if (canPlayCFAndCornerOF(h)) return 'Utility OF';
  if (canPlayOF(h)) return 'Backup OF';
  return 'Bench bat';
}

function LineupCard({ title, tone, lineup, otherLineup, otherLabel }) {
  const otherSpot = new Map((otherLineup?.order || []).map(e => [String(e.player.ID), e.position]));
  const split = lineup.split;
  return (
    <div className="bg-slate-800/30 rounded-lg border border-slate-700/50">
      <div className="p-3 border-b border-slate-700/50 flex items-center gap-2">
        <Lock className={tone} size={16} />
        <h2 className="text-sm font-bold text-white">{title}</h2>
        <span className="text-xs text-slate-500">locked for every game</span>
        <span className="ml-auto text-xs text-slate-500">
          Lineup WAA <span className={`${tone} font-semibold`}>{lineup.totalWAA.toFixed(2)}</span>
        </span>
      </div>
      <table className="data-table">
        <thead>
          <tr>
            <th>#</th><th>POS</th><th>Name</th><th title="Bats">B</th>
            <th title="wOBA against this hand, parks weighted by their games">wOBA</th>
            <th title="WAA at this position against this hand, parks weighted by their games">WAA</th>
          </tr>
        </thead>
        <tbody>
          {lineup.order.map(e => (
            <tr key={e.slot}>
              <td className="font-bold text-blue-400">{e.slot}</td>
              <td className="font-bold text-amber-400">{e.position}</td>
              <td className="font-medium text-white">{e.player.Name}</td>
              <td className="text-slate-400">{e.player.B}</td>
              <td className={getCellColorClass(e.woba, 'wOBA wtd')}>{e.woba ? e.woba.toFixed(3) : '-'}</td>
              <td className={getCellColorClass(e.waa, `Max WAA ${split}`)}>{e.waa.toFixed(2)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <div className="px-3 pt-2 pb-1 flex items-center gap-2 border-t border-slate-700/50">
        <Users className="text-green-400" size={14} />
        <span className="text-xs font-semibold text-slate-300">Bench</span>
        <span className="text-[11px] text-slate-500">the 13 minus this nine</span>
      </div>
      <table className="data-table">
        <tbody>
          {lineup.bench.length ? lineup.bench.map(h => {
            const covers = (h._positions || []).filter(p => p !== 'DH').join(' / ');
            const other = otherSpot.has(String(h.ID)) ? `starts ${otherLabel} at ${otherSpot.get(String(h.ID))}` : `bench ${otherLabel} too`;
            return (
              <tr key={h.ID}>
                <td className="font-bold text-green-400">{benchRole(h)}</td>
                <td className="font-medium text-white">{h.Name}</td>
                <td className="text-slate-400">{h.B}</td>
                <td className="text-xs text-slate-500">{other}{covers ? ` · covers ${covers}` : ''}</td>
              </tr>
            );
          }) : <tr><td className="text-xs text-slate-500 italic">No bench players</td></tr>}
        </tbody>
      </table>
    </div>
  );
}

export default function SeriesPlannerPage({ hitters, pitchers, parks, metadata, league, parkMode }) {
  const { status, parkValues, neutralHitters, error } = useSeriesPlannerData(league, parkMode, hitters);

  const clubs = useMemo(() => (parkValues?.parks || []).map(p => p.club).sort(), [parkValues]);
  const homeClub = useMemo(() => {
    const live = (parks || []).find(p => p.is_home)?.Name;
    if (live && clubs.includes(live)) return live;
    return (parkValues?.parks || []).find(p => p.is_home)?.club || clubs[0] || '';
  }, [parks, parkValues, clubs]);

  const saved = useMemo(() => readSaved(league), [league]);
  const [team, setTeam] = useState(saved.team || '');
  const [opponent, setOpponent] = useState(saved.opponent || '');
  const [bestOf, setBestOf] = useState(BEST_OF.includes(saved.bestOf) ? saved.bestOf : 7);
  const [presetId, setPresetId] = useState(saved.presetId || '2-3-2');
  const [firstHost, setFirstHost] = useState(saved.firstHost === 'me' ? 'me' : 'opp');   // who hosts game 1
  const [customHosts, setCustomHosts] = useState(Array.isArray(saved.customHosts) ? saved.customHosts : []);
  const [weightMode, setWeightMode] = useState(saved.weightMode === 'scheduled' ? 'scheduled' : 'expected');
  const [level, setLevel] = useState('MLB');
  const [winNow, setWinNow] = useState(true);
  const [excludeInjured, setExcludeInjured] = useState(false);

  // A league switch starts from that league's own saved series.
  useEffect(() => {
    const s = readSaved(league);
    setTeam(s.team || ''); setOpponent(s.opponent || '');
    setBestOf(BEST_OF.includes(s.bestOf) ? s.bestOf : 7);
    setPresetId(s.presetId || '2-3-2');
    setFirstHost(s.firstHost === 'me' ? 'me' : 'opp');
    setCustomHosts(Array.isArray(s.customHosts) ? s.customHosts : []);
    setWeightMode(s.weightMode === 'scheduled' ? 'scheduled' : 'expected');
    setLevel('MLB');
  }, [league]);

  // Effective picks: a saved club that is not in this league's file falls back to the defaults.
  const myTeam = clubs.includes(team) ? team : homeClub;
  const others = clubs.filter(c => c !== myTeam);
  const firstVisit = FIRST_VISIT_OPPONENT[league];
  const opp = others.includes(opponent) ? opponent : (others.includes(firstVisit) ? firstVisit : others[0] || '');
  const presetOk = presetId === 'custom' || PATTERN_PRESETS[presetId]?.bestOf === bestOf;
  const preset = presetOk ? presetId : presetsFor(bestOf)[0];

  const pattern = useMemo(() => {
    if (!myTeam || !opp) return [];
    const first = firstHost === 'me' ? myTeam : opp;
    const second = firstHost === 'me' ? opp : myTeam;
    if (preset !== 'custom') return presetPattern(preset, first, second);
    return Array.from({ length: bestOf }, (_, i) => (customHosts[i] === 'me' ? myTeam : opp));
  }, [preset, bestOf, firstHost, customHosts, myTeam, opp]);

  useEffect(() => {
    if (status !== 'ready' || parkValues?.league !== league) return;   // never save one league's clubs under another
    try {
      localStorage.setItem(storeKey(league), JSON.stringify({
        team: myTeam, opponent: opp, bestOf, presetId: preset, firstHost, customHosts, weightMode,
      }));
    } catch { /* storage is optional */ }
  }, [status, parkValues, league, myTeam, opp, bestOf, preset, firstHost, customHosts, weightMode]);

  const pickBestOf = (n) => { setBestOf(n); setPresetId(presetsFor(n)[0]); };
  const pickPreset = (id) => {
    if (id === 'custom') setCustomHosts(pattern.map(c => (c === myTeam ? 'me' : 'opp')));   // start from what is on screen
    setPresetId(id);
  };
  const flipGame = (i) => setCustomHosts(prev => {
    const next = Array.from({ length: bestOf }, (_, k) => (prev[k] === 'me' ? 'me' : 'opp'));
    next[i] = next[i] === 'me' ? 'opp' : 'me';
    return next;
  });

  const vrShare = metadata?.matchups?.['OVR vR'];
  const injuryDataAvailable = useMemo(() => leagueHasInjuryData(neutralHitters, pitchers), [neutralHitters, pitchers]);
  const injuredOn = excludeInjured && injuryDataAvailable;
  const posRatingsAvailable = useMemo(() => leagueHasPositionRatings(neutralHitters), [neutralHitters]);
  const winNowOn = winNow && posRatingsAvailable;

  const result = useMemo(() => {
    if (status !== 'ready' || !myTeam || !opp || pattern.length !== bestOf) return null;
    try {
      return { plan: planSeries({
        hitters: neutralHitters, pitchers, parkValues, team: myTeam, pattern, bestOf,
        weightMode, level, winNow: winNowOn, excludeInjured: injuredOn, vrShare, league,
      }) };
    } catch (e) {
      return { error: e.message };
    }
  }, [status, neutralHitters, pitchers, parkValues, myTeam, opp, pattern, bestOf, weightMode, level, winNowOn, injuredOn, vrShare, league]);

  // Opponent's MLB starters by throwing hand (names only: the basis of the pitcher file does not matter here).
  const oppStarters = useMemo(() => {
    const sp = (pitchers || []).filter(p => p.ORG === opp && p.Lev === 'MLB' && String(p.POS || '').toUpperCase() === 'SP');
    const byHand = { R: [], L: [] };
    for (const p of sp) (byHand[p.T] || (byHand[p.T] = [])).push(p);
    return { total: sp.length, byHand };
  }, [pitchers, opp]);

  const factorRows = useMemo(() => {
    const seen = [];
    for (const c of pattern) if (!seen.includes(c)) seen.push(c);
    return seen.map(c => (parkValues?.parks || []).find(p => p.club === c)).filter(Boolean);
  }, [pattern, parkValues]);
  const factorsMoved = useMemo(
    () => (parkValues ? changedParkFactors(parkValues, parks, factorRows.map(p => p.club)) : []),
    [parkValues, parks, factorRows]
  );

  const header = (
    <div className="p-4">
      <h1 className="text-2xl font-bold text-white flex items-center gap-2">
        <Swords className="text-amber-400" size={24} />
        Series Planner
      </h1>
      <p className="text-sm text-slate-400 mt-1">
        One lineup vs RHP and one vs LHP for the whole series &bull; each park counts by its games &bull;
        hitter values are the engine&apos;s, in each club&apos;s park at full weight &bull; always built from the Neutral files
      </p>
    </div>
  );

  if (status === 'loading') {
    return (
      <div className="h-full overflow-auto">{header}
        <div className="px-4 text-sm text-slate-400 flex items-center gap-2"><Loader2 size={16} className="animate-spin text-blue-400" /> Loading park values for {league}...</div>
      </div>
    );
  }
  if (status === 'missing') {
    return (
      <div className="h-full overflow-auto">{header}
        <div className="mx-4 px-3 py-3 rounded-lg bg-amber-900/20 border border-amber-700/40 text-sm text-slate-300">
          The park values file for {league} is missing. Run a ratings pull for {league}: the pull builds it.
          You can also build it alone with{' '}
          <span className="font-mono text-slate-100">python tgs-viz/ingest/park_values.py --league {league} --write</span>.
        </div>
      </div>
    );
  }
  if (status === 'error') {
    return (
      <div className="h-full overflow-auto">{header}
        <div className="mx-4 px-3 py-3 rounded-lg bg-red-900/20 border border-red-700/40 text-sm text-red-300">{error || 'The series data did not load.'}</div>
      </div>
    );
  }

  const plan = result?.plan;
  const games = leagueGames(league);

  return (
    <div className="h-full overflow-auto">
      {header}

      {/* Controls */}
      <div className="flex flex-wrap items-end gap-x-4 gap-y-3 px-4 pb-3">
        <div className="flex flex-col gap-1"><Label>My team</Label>
          <select value={myTeam} onChange={e => setTeam(e.target.value)} className={selectClass}>
            {clubs.map(c => <option key={c} value={c}>{c}</option>)}
          </select>
        </div>
        <div className="flex flex-col gap-1"><Label>Opponent</Label>
          <select value={opp} onChange={e => setOpponent(e.target.value)} className={selectClass}>
            {others.map(c => <option key={c} value={c}>{c}</option>)}
          </select>
        </div>
        <div className="flex flex-col gap-1"><Label>Best of</Label>
          <div className="flex gap-1 bg-slate-900 rounded-lg p-0.5">
            {BEST_OF.map(n => <button key={n} onClick={() => pickBestOf(n)} className={seg(bestOf === n)}>{n}</button>)}
          </div>
        </div>
        <div className="flex flex-col gap-1"><Label>Home pattern</Label>
          <div className="flex gap-1 bg-slate-900 rounded-lg p-0.5">
            {[...presetsFor(bestOf), 'custom'].map(id => (
              <button key={id} onClick={() => pickPreset(id)} className={seg(preset === id)}>{id === 'custom' ? 'Custom' : id}</button>
            ))}
          </div>
        </div>
        {preset !== 'custom' && (
          <div className="flex flex-col gap-1"><Label>Hosts game 1</Label>
            <div className="flex gap-1 bg-slate-900 rounded-lg p-0.5">
              <button onClick={() => setFirstHost('opp')} className={seg(firstHost === 'opp')}>{opp}</button>
              <button onClick={() => setFirstHost('me')} className={seg(firstHost === 'me')}>{myTeam}</button>
            </div>
          </div>
        )}
        <div className="flex flex-col gap-1"><Label>Park weights</Label>
          <div className="flex gap-1 bg-slate-900 rounded-lg p-0.5">
            <button onClick={() => setWeightMode('expected')} className={seg(weightMode === 'expected')}
              title="Each game counts by the chance it is played, with every game an even coin flip.">Chance played</button>
            <button onClick={() => setWeightMode('scheduled')} className={seg(weightMode === 'scheduled')}
              title="Every scheduled game counts 1, as if the series goes the distance.">Full schedule</button>
          </div>
        </div>
        <div className="flex flex-col gap-1"><Label>Level</Label>
          <select value={level} onChange={e => setLevel(e.target.value)} className={selectClass}>
            {(parkValues.levels || ['MLB']).map(l => <option key={l} value={l}>{l}</option>)}
          </select>
        </div>
        <button
          onClick={() => posRatingsAvailable && setWinNow(v => !v)}
          disabled={!posRatingsAvailable}
          title={posRatingsAvailable
            ? 'Win now: a player can only start at a position where his OOTP position rating has reached his potential there. DH is always allowed.'
            : 'No position ratings in this league\'s files.'}
          className={`flex items-center gap-1.5 px-3 py-1.5 text-sm font-medium rounded-lg border transition-colors ${
            !posRatingsAvailable ? 'bg-slate-800/50 border-slate-700 text-slate-600 cursor-not-allowed'
              : winNowOn ? 'bg-amber-600 border-amber-500 text-white'
              : 'bg-slate-800 border-slate-600 text-slate-300 hover:text-white hover:border-amber-500/60'}`}>
          <Trophy size={14} className={winNowOn ? 'text-white' : 'text-amber-400'} /> Win now
        </button>
        <button
          onClick={() => injuryDataAvailable && setExcludeInjured(v => !v)}
          disabled={!injuryDataAvailable}
          title={injuryDataAvailable ? 'Pick the 13 from healthy players only (not on the DL).' : 'No injury data in this league\'s files.'}
          className={`flex items-center gap-1.5 px-3 py-1.5 text-sm font-medium rounded-lg border transition-colors ${
            !injuryDataAvailable ? 'bg-slate-800/50 border-slate-700 text-slate-600 cursor-not-allowed'
              : injuredOn ? 'bg-rose-600 border-rose-500 text-white'
              : 'bg-slate-800 border-slate-600 text-slate-300 hover:text-white hover:border-rose-500/60'}`}>
          <Cross size={14} className={injuredOn ? 'text-white' : 'text-rose-400'} fill={injuredOn ? 'currentColor' : 'none'} /> Exclude injured (DL)
        </button>
      </div>

      {/* Game strip */}
      <div className="px-4 pb-3">
        <div className="flex flex-wrap items-stretch gap-2">
          {(plan?.games || pattern.map((host, i) => ({ game: i + 1, host, chance: null }))).map((g, i) => {
            const mine = g.host === myTeam;
            const body = (
              <>
                <div className="text-[10px] uppercase tracking-widest text-slate-500">Game {g.game}</div>
                <div className={`text-xs font-semibold ${mine ? 'text-blue-300' : 'text-amber-300'}`}>@ {g.host}</div>
                {g.chance !== null && (
                  <div className="text-[11px] text-slate-400">{g.chance >= 1 ? 'always played' : `played ${pctText(g.chance)}`}</div>
                )}
              </>
            );
            const cls = `text-left rounded-lg border px-2.5 py-1.5 ${mine ? 'bg-blue-900/20 border-blue-800/50' : 'bg-amber-900/10 border-amber-800/40'}`;
            return preset === 'custom'
              ? <button key={i} onClick={() => flipGame(i)} title="Click to change the host of this game" className={`${cls} hover:border-slate-400 cursor-pointer`}>{body}</button>
              : <div key={i} className={cls}>{body}</div>;
          })}
        </div>
        {preset === 'custom' && <p className="text-[11px] text-slate-500 mt-1">Click a game to change its host.</p>}
        {plan && (
          <p className="text-xs text-slate-400 mt-2">
            {weightMode === 'expected' ? 'Expected games' : 'Scheduled games'}:{' '}
            {plan.weights.map((w, i) => (
              <span key={w.club}>{i > 0 && ' / '}<b className="text-slate-200">{w.games.toFixed(2)}</b> {w.club}</span>
            ))}
            {weightMode === 'expected' && <span className="text-slate-500"> &middot; every game an even coin flip, the series stops when one club has {(bestOf + 1) / 2} wins</span>}
          </p>
        )}
        <p className="text-xs text-slate-400 mt-1">
          <span className="text-slate-500">{opp} MLB starters:</span>{' '}
          {oppStarters.total === 0 ? <span className="text-slate-500 italic">none listed at POS SP</span> : (
            <>
              {[['R', 'RHP'], ['L', 'LHP']].map(([hand, label]) => (
                <span key={hand} className="mr-3">
                  <b className={hand === 'R' ? 'text-cyan-400' : 'text-emerald-400'}>{(oppStarters.byHand[hand] || []).length} {label}</b>
                  {(oppStarters.byHand[hand] || []).length > 0 && (
                    <span className="text-slate-300"> {(oppStarters.byHand[hand]).map(p => p.Name + (isInjured(p) ? ' (DL)' : '')).join(', ')}</span>
                  )}
                </span>
              ))}
            </>
          )}
        </p>
      </div>

      {/* Warnings */}
      {result?.error && (
        <div className="mx-4 mb-3 px-3 py-2 rounded-lg bg-red-900/20 border border-red-700/40 text-sm text-red-300">{result.error}</div>
      )}
      {plan && (plan.missing.length > 0 || plan.stale.length > 0 || factorsMoved.length > 0) && (
        <div className="mx-4 mb-3 px-3 py-2 rounded-lg bg-amber-900/20 border border-amber-700/40 text-xs text-amber-200 space-y-1">
          <div className="flex items-center gap-1.5 font-semibold"><AlertTriangle size={13} /> The park values file does not cover everything. Run a ratings pull for {league}.</div>
          {plan.missing.length > 0 && (
            <div>Not in the file, kept on neutral values: {plan.missing.map(h => h.Name).join(', ')}.</div>
          )}
          {plan.stale.length > 0 && (
            <div>Projection changed after the file was built, kept on neutral values: {plan.stale.map(h => h.Name).join(', ')}.</div>
          )}
          {factorsMoved.length > 0 && (
            <div>Park factors changed after the file was built: {factorsMoved.join(', ')}. Run <span className="font-mono">python tgs-viz/ingest/park_values.py --league {league} --write</span>.</div>
          )}
        </div>
      )}

      {plan && (
        <>
          {/* Locked lineups */}
          <div className="grid grid-cols-1 xl:grid-cols-2 gap-4 px-4 pb-4">
            {[['vs RHP', plan.locked.vR], ['vs LHP', plan.locked.vL]].map(([lab, lu]) => {
              const filled = new Set((lu.order || []).map(e => e.position));
              const empty = ['C', '1B', '2B', '3B', 'SS', 'LF', 'CF', 'RF', 'DH'].filter(x => !filled.has(x));
              return empty.length ? (
                <div key={lab} className="col-span-full bg-rose-900/30 border border-rose-700/50 rounded-lg px-3 py-2 text-sm text-rose-200">
                  No one can start at {empty.join(', ')} {lab}{winNow ? ' with Win now on: nobody on this roster has reached his potential there. Turn Win now off, or widen the Level.' : '.'}
                </div>
              ) : null;
            })}
            <LineupCard title="Lineup vs RHP" tone="text-cyan-400" lineup={plan.locked.vR} otherLineup={plan.locked.vL} otherLabel="vs LHP" />
            <LineupCard title="Lineup vs LHP" tone="text-emerald-400" lineup={plan.locked.vL} otherLineup={plan.locked.vR} otherLabel="vs RHP" />
          </div>

          <div className="grid grid-cols-1 xl:grid-cols-2 gap-4 px-4 pb-6">
            {/* What locking costs */}
            <div className="bg-slate-800/30 rounded-lg border border-slate-700/50">
              <div className="p-3 border-b border-slate-700/50 flex items-center gap-2">
                <Target className="text-blue-400" size={16} />
                <h2 className="text-sm font-bold text-white">What locking costs</h2>
                <span className="text-xs text-slate-500">against each park&apos;s own best nine from the same 13</span>
              </div>
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Park</th><th>Split</th>
                    <th title="The locked nine, valued in this park alone">Locked</th>
                    <th title="This park's own best nine">Park best</th>
                    <th>Cost</th><th>What this park alone would change</th>
                  </tr>
                </thead>
                <tbody>
                  {plan.parks.flatMap(pk => [['vR', 'vs RHP'], ['vL', 'vs LHP']].map(([sp, label]) => {
                    const r = pk[sp];
                    return (
                      <tr key={`${pk.club}-${sp}`}>
                        <td className={pk.club === myTeam ? 'text-blue-300 font-semibold' : 'text-amber-300 font-semibold'}>{pk.club}</td>
                        <td className={sp === 'vR' ? 'text-cyan-400' : 'text-emerald-400'}>{label}</td>
                        <td>{r.lockedValue.toFixed(2)}</td>
                        <td>{r.bestValue.toFixed(2)}</td>
                        <td className={r.cost >= 0.005 ? 'text-orange-400 font-semibold' : 'text-slate-500'}>{r.cost.toFixed(2)}</td>
                        <td className="text-xs text-slate-300" style={{ whiteSpace: 'normal' }}>
                          {r.swaps.length === 0 ? <span className="text-slate-500">same nine, same positions</span> : r.swaps.map((s, i) => (
                            <div key={i}>
                              <span className="font-bold text-amber-400">{s.position}</span>{' '}
                              <span className="text-white">{s.parkPlayer.Name}</span>
                              {s.parkWAA !== null && <span className="text-slate-400"> ({s.parkWAA.toFixed(2)})</span>}
                              {s.lockedPlayer && (
                                <> instead of {s.lockedPlayer.Name}{s.lockedWAA !== null && <span className="text-slate-400"> ({s.lockedWAA.toFixed(2)})</span>}</>
                              )}
                            </div>
                          ))}
                        </td>
                      </tr>
                    );
                  }))}
                </tbody>
              </table>
              <p className="text-xs text-slate-500 px-3 py-2">
                WAA is on a full-season scale: a cost of 0.30 means the park&apos;s own nine would be worth 0.30 more wins
                than the locked nine over {games} games played in that park against that hand.
              </p>
            </div>

            {/* Park factors */}
            <div className="bg-slate-800/30 rounded-lg border border-slate-700/50 self-start">
              <div className="p-3 border-b border-slate-700/50 flex items-center gap-2">
                <h2 className="text-sm font-bold text-white">The two parks</h2>
                <span className="text-xs text-slate-500">1.00 = neutral &middot; splits are the batter&apos;s side &middot; the factors the values were built from</span>
              </div>
              <table className="data-table">
                <thead>
                  <tr><th>Club</th><th>Park</th><th>HR vRHB</th><th>HR vLHB</th><th>Avg vRHB</th><th>Avg vLHB</th><th>2B</th><th>3B</th></tr>
                </thead>
                <tbody>
                  {factorRows.map(p => (
                    <tr key={p.club}>
                      <td className={p.club === myTeam ? 'text-blue-300 font-semibold' : 'text-amber-300 font-semibold'}>{p.club}</td>
                      <td className="text-slate-300">{p.park}</td>
                      <td className={factorClass(p.hr_rhb)}>{f3(p.hr_rhb)}</td>
                      <td className={factorClass(p.hr_lhb)}>{f3(p.hr_lhb)}</td>
                      <td className={factorClass(p.avg_rhb)}>{f3(p.avg_rhb)}</td>
                      <td className={factorClass(p.avg_lhb)}>{f3(p.avg_lhb)}</td>
                      <td className={factorClass(p.doubles)}>{f3(p.doubles)}</td>
                      <td className={factorClass(p.triples)}>{f3(p.triples)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <p className="text-xs text-slate-500 px-3 py-2">
                Park values built {String(parkValues.generated || '').replace('T', ' ')} &middot; {plan.poolSize} {level} hitters in the pool
                {winNowOn ? ' · Win now on' : ''}{injuredOn ? ' · injured excluded' : ''}
              </p>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
