import React, { useState, useMemo } from 'react';
import { optimizeRoster, getMaxWAA, leagueWinOffset, isInjured, leagueHasInjuryData, leagueHasPositionRatings, playerKey, canPlaySS, canPlayOF, canPlayAllIF, canPlayCFAndCornerOF } from '../lib/rosterOptimizer';
import { LEAGUE_TEAMS } from './TeamStandingsPage';
import { resolveLeagueClubs } from '../lib/leagueClubs';
import { formatCellValue, getCellColorClass } from '../lib/columns';
import PlayerDetail from '../components/PlayerDetail';
import { useSelectedById } from '../hooks/useSelectedById';
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Cell, ReferenceLine } from 'recharts';
import { Trophy, Users, Zap, Shield, Target, ArrowLeftRight, Calculator, Sigma, Dices, HeartPulse, TrendingUp, Cross } from 'lucide-react';

// Win-model lenses for the selector. Linear + Pythagorean re-score the same roster;
// Monte Carlo adds a season distribution; Durability re-picks on playing time; Levers
// shows where the next win is cheapest.
const WIN_MODELS = [
  { id: 'linear', label: 'Linear', icon: Calculator, blurb: 'G/2 + WAA' },
  { id: 'pythagorean', label: 'Pythagorean', icon: Sigma, blurb: 'runs → wins' },
  { id: 'montecarlo', label: 'Monte Carlo', icon: Dices, blurb: 'odds + range' },
  { id: 'durability', label: 'Durability', icon: HeartPulse, blurb: 'playing time' },
  { id: 'levers', label: 'Levers', icon: TrendingUp, blurb: 'next win' },
];

const pct = (x) => `${Math.round((x || 0) * 100)}%`;

// Small surface metric for the model panels.
function Metric({ label, value, sub, tone = 'text-white' }) {
  return (
    <div className="bg-slate-800/50 rounded-lg p-3 border border-slate-700/50">
      <div className={`text-xl font-bold ${tone}`}>{value}</div>
      <div className="text-xs text-slate-500">{label}</div>
      {sub && <div className="text-[11px] text-slate-600 mt-0.5">{sub}</div>}
    </div>
  );
}

export default function RosterOptimizerPage({ hitters, pitchers, metadata, league }) {
  // The open card is kept by player ID and found again in the page's current
  // rows, so a data refresh shows the new numbers in the card.
  const rowsByKind = useMemo(() => ({ hitter: hitters, pitcher: pitchers }), [hitters, pitchers]);
  const { selected: selectedPlayer, kind: playerType, select, clear } = useSelectedById(rowsByKind);
  const [orgFilter, setOrgFilter] = useState('ALL');
  const [levelFilter, setLevelFilter] = useState('ALL');
  const [activeLineup, setActiveLineup] = useState('vR'); // 'vR' or 'vL'
  const [winModel, setWinModel] = useState('linear'); // linear | pythagorean | montecarlo | durability | levers
  const [excludeInjured, setExcludeInjured] = useState(false); // re-pick from healthy players only
  const [winNow, setWinNow] = useState(false); // only play a man where his position rating has reached his potential
  const [clearedIds, setClearedIds] = useState([]); // DL players manually marked "back this sim" (playerKey list)

  const organizations = useMemo(() => {
    const orgs = new Set([
      ...hitters.map(h => h.ORG).filter(Boolean),
      ...pitchers.map(p => p.ORG).filter(Boolean),
    ]);
    return ['ALL', ...Array.from(orgs).sort()];
  }, [hitters, pitchers]);

  const levels = useMemo(() => {
    const lvls = new Set([
      ...hitters.map(h => h.Lev).filter(Boolean),
      ...pitchers.map(p => p.Lev).filter(Boolean),
    ]);
    return ['ALL', ...Array.from(lvls).sort()];
  }, [hitters, pitchers]);

  // Season vs-RHP share from the league metadata (TGS "OVR vR" = 0.7368) — weights
  // the two platoon lineups. Falls back inside optimizeRoster if absent.
  const vrShare = metadata?.matchups?.['OVR vR'];

  // League win baseline — mean optimized winBasis across the league's teams. Subtracting it
  // makes the optimizer's wins zero-sum and ALIGNED with the League Projections screen (which
  // normalizes the same way). Memoized on the data/league, not the per-team filters.
  const knownTeams = useMemo(
    () => resolveLeagueClubs(metadata, LEAGUE_TEAMS[league]).known,
    [metadata, league]
  );
  const leagueOffset = useMemo(
    () => leagueWinOffset(hitters, pitchers, knownTeams, league, vrShare),
    [hitters, pitchers, knownTeams, league, vrShare]
  );

  // Injury toggle guard: offline leagues carry no injury fields at all — the toggle
  // disables itself there. `injuredOn` is the effective flag used everywhere below,
  // so a stale ON state can't leak across a league switch.
  const injuryDataAvailable = useMemo(() => leagueHasInjuryData(hitters, pitchers), [hitters, pitchers]);
  const injuredOn = excludeInjured && injuryDataAvailable;
  const posRatingsAvailable = useMemo(() => leagueHasPositionRatings(hitters), [hitters]);
  const winNowOn = winNow && posRatingsAvailable;

  // Manual "he's back this sim" overrides: DL players the user has clicked to treat as
  // healthy (OOTP shows them active before StatsPlus refreshes). Only meaningful while the
  // injury filter is ON. Stored as a key list for stable useMemo deps; a Set is derived for
  // O(1) lookups in the optimizer. Toggling rebuilds the list immutably so the roster memo
  // recomputes.
  const clearedSet = useMemo(() => new Set(clearedIds), [clearedIds]);
  const toggleCleared = (key) => {
    if (!key) return;
    setClearedIds(prev => prev.includes(key) ? prev.filter(k => k !== key) : [...prev, key]);
  };

  // Build the best 13 for the two platoon lineups (cut maximizes the blended
  // vR/vL lineup objective; coverage bench reserved).
  const roster = useMemo(() => {
    return optimizeRoster(hitters, pitchers, {
      teamOrg: orgFilter !== 'ALL' ? orgFilter : null,
      levelFilter: levelFilter !== 'ALL' ? levelFilter : null,
      vrShare,
      excludeInjured: injuredOn,
      clearedInjured: clearedSet,
      winNow: winNowOn,
      leagueOffset,
      league,   // B3: selects the league's real season length (measured: 162)
    });
  }, [hitters, pitchers, orgFilter, levelFilter, vrShare, injuredOn, clearedSet, winNowOn, leagueOffset, league]);

  // Durability lens re-picks the roster on playing time — only compute when selected.
  // Composes on top of the injury filter: proneness haircuts apply to the healthy pool.
  const durabilityRoster = useMemo(() => {
    if (winModel !== 'durability') return null;
    return optimizeRoster(hitters, pitchers, {
      teamOrg: orgFilter !== 'ALL' ? orgFilter : null,
      levelFilter: levelFilter !== 'ALL' ? levelFilter : null,
      vrShare,
      durabilityWeighted: true,
      excludeInjured: injuredOn,
      clearedInjured: clearedSet,
      winNow: winNowOn,
      leagueOffset,
      league,   // B3
    });
  }, [winModel, hitters, pitchers, orgFilter, levelFilter, vrShare, injuredOn, clearedSet, winNowOn, leagueOffset, league]);

  // "Out injured" strip: the DL players who WOULD have made the roster if we ignored
  // health — i.e. why the lineup differs. Needs the injury-blind roster to diff against.
  const injuredOut = useMemo(() => {
    if (!injuredOn) return null;
    const blind = optimizeRoster(hitters, pitchers, {
      teamOrg: orgFilter !== 'ALL' ? orgFilter : null,
      levelFilter: levelFilter !== 'ALL' ? levelFilter : null,
      vrShare,
      winNow: winNowOn,
      leagueOffset,
      league,   // B3
    });
    const members = [
      ...(blind.rosteredHitters || []).map(p => ({ p, slot: p.POS || 'Bat' })),
      ...(blind.startingPitchers || []).map(p => ({ p, slot: 'SP' })),
      ...(blind.reliefPitchers || []).map(p => ({ p, slot: 'RP' })),
    ];
    return members.filter(m => isInjured(m.p)).map(({ p, slot }) => {
      const dlDays = parseFloat(p.DLDays) || 0;
      const is60 = p.OnDL60 === true || p.OnDL60 === 'Yes';
      const key = playerKey(p);
      return {
        key, name: p.Name, slot,
        status: (is60 ? '60-day' : 'DL') + (dlDays > 0 ? ` · ${Math.round(dlDays)}d` : ''),
        cleared: clearedSet.has(key),
      };
    });
  }, [injuredOn, hitters, pitchers, orgFilter, levelFilter, vrShare, leagueOffset, clearedSet, league]);

  const models = roster.models;

  // The headline "Projected Wins" number for the selected lens, plus a delta vs Linear.
  const winView = useMemo(() => {
    const lin = models.linearWins;
    switch (winModel) {
      case 'pythagorean':
        return { wins: models.pythWins, label: 'Pythagorean wins', delta: models.pythWins - lin };
      case 'montecarlo':
        return { wins: models.monteCarlo.median, label: 'Median wins (sim)', delta: models.monteCarlo.median - lin };
      case 'durability': {
        const w = durabilityRoster ? durabilityRoster.totals.estimatedWinsPyth : models.pythWins;
        return { wins: w, label: 'Realistic wins', delta: w - models.pythWins, deltaLabel: 'vs full-strength' };
      }
      case 'levers':
        return { wins: models.pythWins, label: 'Pythagorean wins', delta: models.pythWins - lin };
      default:
        return { wins: lin, label: 'Projected wins', delta: 0 };
    }
  }, [winModel, models, durabilityRoster]);

  // Active lineup data based on tab
  const activeLineupData = useMemo(() => {
    return activeLineup === 'vR' ? roster.lineupVsRHP : roster.lineupVsLHP;
  }, [roster, activeLineup]);

  // Position WAA chart data (from active split lineup)
  const positionWAAData = useMemo(() => {
    if (!activeLineupData?.battingOrder) return [];
    return activeLineupData.battingOrder.map(entry => ({
      pos: entry.position,
      waa: entry.waa || 0,
      name: entry.player.Name,
    }));
  }, [activeLineupData]);

  // Pitching WAA data
  const pitchingWAAData = useMemo(() => {
    const data = [];
    roster.startingPitchers?.forEach((p, i) => {
      data.push({ name: `SP${i + 1}`, waa: p._spWAA || p._bestWAA || 0, player: p.Name, role: 'SP' });
    });
    roster.reliefPitchers?.forEach((p, i) => {
      data.push({ name: `RP${i + 1}`, waa: p._rpWAA || p._bestWAA || 0, player: p.Name, role: 'RP' });
    });
    return data;
  }, [roster]);

  const splitLabel = activeLineup === 'vR' ? 'vs RHP' : 'vs LHP';
  const splitWAACol = activeLineup === 'vR' ? 'Max WAA vR' : 'Max WAA vL';

  // The REAL bench for the lineup on screen: the 13 minus that lineup's nine.
  // (The optimizer's role labels come from an "everyday nine by overall value"
  // step that never looks at the two lineups, so it could tag a man who starts
  // both ways as the flex bat.) Each man gets the job he can cover, and a note
  // when he starts in the other lineup.
  const activeBench = useMemo(() => {
    const idOf = (h) => h.ID || h.Name;
    const cur = (activeLineup === 'vR' ? roster.lineupVsRHP : roster.lineupVsLHP)?.battingOrder || [];
    const other = (activeLineup === 'vR' ? roster.lineupVsLHP : roster.lineupVsRHP)?.battingOrder || [];
    const starting = new Set(cur.map(e => idOf(e.player)));
    const otherSpot = new Map(other.map(e => [idOf(e.player), e.position]));
    const otherLabel = activeLineup === 'vR' ? 'vs LHP' : 'vs RHP';
    const isC = (h) => { const e = h['C Eligible']; return e === true || e === 'True' || e === 'TRUE'; };
    return (roster.rosteredHitters || []).filter(h => !starting.has(idOf(h))).map(h => {
      const role = isC(h) ? 'Backup C'
        : canPlayAllIF(h) ? 'Utility IF'
        : canPlaySS(h) ? 'Backup IF'
        : canPlayCFAndCornerOF(h) ? 'Utility OF'
        : canPlayOF(h) ? 'Backup OF'
        : 'Bench bat';
      const covers = (h._positions || []).filter(x => x !== 'DH').join(' / ');
      const alsoStarts = otherSpot.has(idOf(h)) ? `starts ${otherLabel} at ${otherSpot.get(idOf(h))}` : `bench ${otherLabel} too`;
      return { player: h, role, note: `${alsoStarts}${covers ? ` · covers ${covers}` : ''}` };
    });
  }, [roster, activeLineup]);

  // Helper for bench rows
  const BenchRow = ({ player, role, note }) => {
    if (!player) return (
      <tr><td colSpan={7} className="text-xs text-orange-400/70 italic">No {role} available</td></tr>
    );
    const waa = player._maxWAA || 0;
    return (
      <tr className="cursor-pointer hover:bg-slate-800/50"
        onClick={() => select(player, 'hitter')}>
        <td className="font-bold text-green-400">{role}</td>
        <td className="font-medium text-white">{player.Name}</td>
        <td className="text-slate-400">{player.POS}</td>
        <td>{Math.round(parseFloat(player.Age) || 0)}</td>
        <td className={getCellColorClass(waa, 'Max WAA wtd')}>{waa.toFixed(1)}</td>
        <td className="text-xs text-slate-500 max-w-[240px] truncate">{note}</td>
        <td className="text-slate-400">{player.ORG}</td>
      </tr>
    );
  };

  return (
    <div className="h-full overflow-auto">
      <div className="p-4">
        <h1 className="text-2xl font-bold text-white flex items-center gap-2">
          <Trophy className="text-amber-400" size={24} />
          Roster Optimizer
        </h1>
        <p className="text-sm text-slate-400 mt-1">
          Best 13 for the two platoon lineups &bull; weighted {vrShare ? `${(vrShare * 100).toFixed(1)}%` : '~74%'} vs RHP (from league metadata) &bull; cut maximizes blended vR/vL lineup value &bull; bench contract: backup C / utility IF / utility OF / flex
        </p>
      </div>

      {/* Controls */}
      <div className="flex flex-wrap items-center gap-3 px-4 pb-4">
        <select value={orgFilter} onChange={e => setOrgFilter(e.target.value)}
          className="py-1.5 px-3 bg-slate-800 border border-slate-600 rounded-lg text-sm text-slate-200">
          {organizations.map(o => <option key={o} value={o}>{o === 'ALL' ? 'All Organizations' : o}</option>)}
        </select>

        <select value={levelFilter} onChange={e => setLevelFilter(e.target.value)}
          className="py-1.5 px-3 bg-slate-800 border border-slate-600 rounded-lg text-sm text-slate-200">
          {levels.map(l => <option key={l} value={l}>{l === 'ALL' ? 'All Levels' : l}</option>)}
        </select>

        {/* Injury toggle: re-pick everything from healthy players only */}
        <button
          onClick={() => injuryDataAvailable && setExcludeInjured(v => !v)}
          disabled={!injuryDataAvailable}
          title={injuryDataAvailable
            ? 'Re-pick the entire roster (13 bats + rotation + bullpen) from healthy players only. Injured = on DL, 60-day DL, or DL days remaining.'
            : 'No injury data in this league\'s files — nothing to exclude.'}
          className={`flex items-center gap-1.5 px-3 py-1.5 text-sm font-medium rounded-lg border transition-colors ${
            !injuryDataAvailable
              ? 'bg-slate-800/50 border-slate-700 text-slate-600 cursor-not-allowed'
              : injuredOn
                ? 'bg-rose-600 border-rose-500 text-white'
                : 'bg-slate-800 border-slate-600 text-slate-300 hover:text-white hover:border-rose-500/60'
          }`}>
          <Cross size={14} className={injuredOn ? 'text-white' : 'text-rose-400'} fill={injuredOn ? 'currentColor' : 'none'} />
          Exclude injured (DL)
        </button>

        {/* Win now: only play a man where his position rating has reached his potential */}
        <button
          onClick={() => posRatingsAvailable && setWinNow(v => !v)}
          disabled={!posRatingsAvailable}
          title={posRatingsAvailable
            ? 'Win now: in the starting lineups a player can only be placed at a position where his OOTP position rating has reached his potential there. Nobody starts at a spot he is still learning or has never played. Bench roles use the normal rules. DH is always allowed.'
            : 'No position ratings in this league\'s files.'}
          className={`flex items-center gap-1.5 px-3 py-1.5 text-sm font-medium rounded-lg border transition-colors ${
            !posRatingsAvailable
              ? 'bg-slate-800/50 border-slate-700 text-slate-600 cursor-not-allowed'
              : winNowOn
                ? 'bg-amber-600 border-amber-500 text-white'
                : 'bg-slate-800 border-slate-600 text-slate-300 hover:text-white hover:border-amber-500/60'
          }`}>
          <Trophy size={14} className={winNowOn ? 'text-white' : 'text-amber-400'} />
          Win now
        </button>

        {/* Win-model selector */}
        <div className="flex gap-1 bg-slate-900 rounded-lg p-0.5 ml-auto">
          {WIN_MODELS.map(m => {
            const Icon = m.icon;
            const active = winModel === m.id;
            return (
              <button key={m.id} onClick={() => setWinModel(m.id)} title={m.blurb}
                className={`flex items-center gap-1.5 px-2.5 py-1 text-xs font-medium rounded-md transition-colors ${
                  active ? 'bg-blue-600 text-white' : 'text-slate-400 hover:text-slate-200'
                }`}>
                <Icon size={13} /> {m.label}
              </button>
            );
          })}
        </div>
      </div>

      {/* Out-injured strip: who got benched by the injury filter and why. Each chip is a
          toggle — click a DL player to mark him "back this sim" (activated) and the roster
          re-picks with him included, before StatsPlus catches up to OOTP. Click again to
          send him back to the DL. */}
      {injuredOn && injuredOut && (
        <div className="px-4 pb-4">
          <div className="bg-rose-900/20 border border-rose-700/40 rounded-lg px-3 py-2 flex flex-wrap items-center gap-x-2 gap-y-1.5">
            <Cross size={13} className="text-rose-400 shrink-0" />
            <span className="text-xs font-semibold text-rose-300 uppercase tracking-wide">Out injured</span>
            {injuredOut.length > 0 ? (
              <>
                {injuredOut.map((e) => (
                  <button
                    key={e.key}
                    onClick={() => toggleCleared(e.key)}
                    title={e.cleared
                      ? `${e.name} is being counted as HEALTHY (back this sim). Click to send back to the DL.`
                      : `${e.name} is on the ${e.status}. Click to mark him back this sim and re-pick the roster with him in.`}
                    className={`text-xs rounded-md px-2 py-0.5 border transition-colors cursor-pointer ${
                      e.cleared
                        ? 'bg-emerald-900/50 border-emerald-600/60 text-emerald-100 hover:border-emerald-400'
                        : 'bg-rose-950/60 border-rose-800/50 text-slate-200 hover:border-rose-400'
                    }`}>
                    {e.cleared
                      ? <TrendingUp size={11} className="inline -mt-0.5 mr-1 text-emerald-400" />
                      : <Cross size={11} className="inline -mt-0.5 mr-1 text-rose-400" />}
                    <span className="font-medium text-white">{e.name}</span>
                    <span className={e.cleared ? 'text-emerald-300/80' : 'text-rose-300/80'}> {e.slot}</span>
                    <span className={e.cleared ? 'text-emerald-300/90' : 'text-rose-400/90'}> · {e.cleared ? 'back this sim' : e.status}</span>
                  </button>
                ))}
                {clearedIds.length > 0 && (
                  <button
                    onClick={() => setClearedIds([])}
                    title="Send everyone back to the DL — respect StatsPlus injury status again."
                    className="text-xs text-slate-400 hover:text-white underline decoration-dotted ml-1">
                    reset ({clearedIds.length} back)
                  </button>
                )}
                <span className="text-[11px] text-slate-500 italic ml-1 basis-full sm:basis-auto">
                  click a name to count him healthy this sim
                </span>
              </>
            ) : (
              <span className="text-xs text-slate-400 italic">no roster-caliber players on the DL — lineup unchanged</span>
            )}
          </div>
        </div>
      )}

      {/* Summary Cards */}
      {roster.totals && (
        <div className="grid grid-cols-2 md:grid-cols-3 xl:grid-cols-6 gap-3 px-4 pb-4">
          <div title={`Every team also fields its best 26, so the average optimized roster is about +${leagueOffset.toFixed(1)} WAA above the league-average player. That league average is subtracted so this projects your real FINISH and matches the Team Projections standings (a zero-sum league). Raw roster strength is the Total WAA card.`}
               className="bg-gradient-to-br from-blue-900/50 to-blue-800/30 rounded-lg p-3 border border-blue-700/30">
            <div className="flex items-baseline gap-2">
              <div className="text-2xl font-black text-blue-400">{winView.wins}</div>
              {winView.delta !== 0 && (
                <span className={`text-xs font-semibold ${winView.delta > 0 ? 'text-green-400' : 'text-orange-400'}`}>
                  {winView.delta > 0 ? '+' : ''}{winView.delta} {winView.deltaLabel || 'vs Linear'}
                </span>
              )}
            </div>
            <div className="text-xs text-blue-300/70">{winView.label}</div>
            <div className="text-[10px] text-blue-300/50 mt-0.5">league-normalized · matches standings</div>
          </div>
          <div title={`Raw roster strength: best-26 WAA with NO league normalization. Projected wins subtract the ~+${leagueOffset.toFixed(1)} league-average optimized roster, which is why ${Math.round((roster.totals.games || 162) / 2)} + this ≠ the win total.`}
               className="bg-slate-800/50 rounded-lg p-3 border border-slate-700/50">
            <div className="text-xl font-bold text-green-400">{roster.totals.totalRosterWAA}</div>
            <div className="text-xs text-slate-500">Total WAA (raw strength)</div>
          </div>
          <div className="bg-slate-800/50 rounded-lg p-3 border border-slate-700/50">
            <div className="text-xl font-bold text-cyan-400">{roster.totals.lineupWAA_vR}</div>
            <div className="text-xs text-slate-500">vs RHP Lineup WAA</div>
          </div>
          <div className="bg-slate-800/50 rounded-lg p-3 border border-slate-700/50">
            <div className="text-xl font-bold text-emerald-400">{roster.totals.lineupWAA_vL}</div>
            <div className="text-xs text-slate-500">vs LHP Lineup WAA</div>
          </div>
          <div className="bg-slate-800/50 rounded-lg p-3 border border-slate-700/50">
            <div className="text-xl font-bold text-amber-400">{roster.totals.totalSPWAA}</div>
            <div className="text-xs text-slate-500">SP WAA</div>
          </div>
          <div className="bg-slate-800/50 rounded-lg p-3 border border-slate-700/50">
            <div className="text-xl font-bold text-purple-400">{roster.totals.totalRPWAA}</div>
            <div className="text-xs text-slate-500">RP WAA</div>
          </div>
        </div>
      )}

      {/* ===== Win-model panel ===== */}
      {winModel === 'pythagorean' && (
        <div className="px-4 pb-4">
          <div className="bg-slate-800/30 rounded-lg border border-slate-700/50 p-3">
            <div className="flex items-center gap-2 mb-1"><Sigma size={15} className="text-cyan-400" />
              <h2 className="text-sm font-bold text-white">Pythagorean — runs → wins</h2></div>
            <p className="text-xs text-slate-400 mb-3 max-w-3xl">
              Reconstructs Runs Scored / Allowed from the lineup's batting + baserunning runs and the staff,
              then applies the PythagenPat win curve. The run differential is pinned to your WAA model, so this
              agrees with Linear in the normal range and only bends at the extremes (where it correctly refuses
              to overstate a great roster).
            </p>
            <div className="grid grid-cols-2 md:grid-cols-3 xl:grid-cols-6 gap-3">
              <Metric label="Runs Scored" value={models.runs.RS} tone="text-green-400" />
              <Metric label="Runs Allowed" value={models.runs.RA} tone="text-red-400" />
              <Metric label="Run Differential" value={`${models.runs.runDiff > 0 ? '+' : ''}${models.runs.runDiff}`} tone="text-cyan-400" />
              <Metric label="Pythagorean Wins" value={models.pythWins} sub={`Linear ${models.linearWins} (${models.pythWins - models.linearWins >= 0 ? '+' : ''}${models.pythWins - models.linearWins})`} tone="text-blue-400" />
              <Metric label="Runs / Win" value={models.runs.RPW} tone="text-amber-400" />
              <Metric label="Run Env (R/G)" value={models.runs.lgRG} sub="league baseline" tone="text-slate-300" />
            </div>
          </div>
        </div>
      )}

      {winModel === 'montecarlo' && (() => {
        const mc = models.monteCarlo;
        const histData = mc.hist.map(h => ({ wins: h.wins, count: h.count }));
        // B3: thresholds are win%-equivalents of the 162-game milestones at the
        // league's real season length (at the measured G=162 they coincide).
        const th = mc.thresholds || { pGE90: 90, pGE95: 95, pGE100: 100 };
        const G = mc.games || 162;
        return (
          <div className="px-4 pb-4">
            <div className="bg-slate-800/30 rounded-lg border border-slate-700/50 p-3">
              <div className="flex items-center gap-2 mb-1"><Dices size={15} className="text-purple-400" />
                <h2 className="text-sm font-bold text-white">Monte Carlo — {mc.N.toLocaleString()} simulated seasons</h2></div>
              <p className="text-xs text-slate-400 mb-3 max-w-3xl">
                Each season perturbs the projection, draws a true-talent win% off the Pythagorean curve, and plays
                {' '}{G} games. The spread is your real range of outcomes — luck plus projection uncertainty.
                <span className="text-slate-500"> Playoff line is a {th.pGE90}-win proxy (90-win pace over 162), not a full league sim.</span>
              </p>
              <div className="grid grid-cols-2 md:grid-cols-3 xl:grid-cols-6 gap-3 mb-3">
                <Metric label="Median" value={mc.median} tone="text-blue-400" />
                <Metric label="Floor (5th %)" value={mc.floor} tone="text-orange-400" />
                <Metric label="Ceiling (95th %)" value={mc.ceiling} tone="text-green-400" />
                <Metric label={`P(${th.pGE90}+ wins)`} value={pct(mc.pGE90)} tone="text-cyan-400" />
                <Metric label={`P(${th.pGE95}+ wins)`} value={pct(mc.pGE95)} tone="text-cyan-400" />
                <Metric label={`P(${th.pGE100}+ wins)`} value={pct(mc.pGE100)} tone="text-purple-400" />
              </div>
              <ResponsiveContainer width="100%" height={180}>
                <BarChart data={histData} margin={{ top: 4, right: 8, bottom: 4, left: -8 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
                  <XAxis dataKey="wins" tick={{ fill: '#94a3b8', fontSize: 10 }} interval={4} />
                  <YAxis tick={{ fill: '#94a3b8', fontSize: 10 }} />
                  <Tooltip contentStyle={{ background: '#1e293b', border: '1px solid #475569', borderRadius: 8 }}
                    formatter={(v) => [`${v} of ${mc.N} sims`, 'count']} labelFormatter={(l) => `${l} wins`} />
                  <ReferenceLine x={th.pGE90} stroke="#22d3ee" strokeDasharray="4 3" label={{ value: String(th.pGE90), fill: '#22d3ee', fontSize: 10, position: 'top' }} />
                  <ReferenceLine x={mc.median} stroke="#f59e0b" strokeDasharray="4 3" label={{ value: 'med', fill: '#f59e0b', fontSize: 10, position: 'top' }} />
                  <Bar dataKey="count" radius={[3, 3, 0, 0]}>
                    {histData.map((d, i) => (
                      <Cell key={i} fill={d.wins >= th.pGE90 ? '#34d399' : '#475569'} />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </div>
          </div>
        );
      })()}

      {winModel === 'durability' && (() => {
        if (!durabilityRoster) return null;
        const dm = durabilityRoster.models;
        const lostWins = models.pythWins - durabilityRoster.totals.estimatedWinsPyth;
        const normIds = new Set(roster.rosteredHitters.map(h => h.ID || h.Name));
        const durIds = new Set(durabilityRoster.rosteredHitters.map(h => h.ID || h.Name));
        const added = durabilityRoster.rosteredHitters.filter(h => !normIds.has(h.ID || h.Name));
        const dropped = roster.rosteredHitters.filter(h => !durIds.has(h.ID || h.Name));
        return (
          <div className="px-4 pb-4">
            <div className="bg-slate-800/30 rounded-lg border border-slate-700/50 p-3">
              <div className="flex items-center gap-2 mb-1"><HeartPulse size={15} className="text-rose-400" />
                <h2 className="text-sm font-bold text-white">Durability — value at realistic playing time</h2></div>
              <p className="text-xs text-slate-400 mb-3 max-w-3xl">
                Each player's value is discounted by expected games (injury proneness + current DL), then the
                roster is re-picked — a durable solid bat can beat a fragile star. This is the win total you'd
                actually expect once the injury bug bites.
              </p>
              <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-3">
                <Metric label="Realistic Wins" value={durabilityRoster.totals.estimatedWinsPyth} tone="text-rose-400" />
                <Metric label="Full-strength Wins" value={models.pythWins} tone="text-blue-400" />
                <Metric label="Cost of Injuries" value={`-${lostWins} W`} tone="text-orange-400" />
                <Metric label="Avg Playing Time" value={pct(dm.durability.avg)} tone="text-slate-300" />
              </div>
              {(added.length > 0 || dropped.length > 0) && (
                <div className="text-xs text-slate-300 mb-3">
                  <span className="text-rose-400 font-semibold">Roster changes once durability is priced in:</span>{' '}
                  {added.map(h => `+${h.Name}`).join(', ')}
                  {dropped.length > 0 && <> &nbsp;|&nbsp; {dropped.map(h => `−${h.Name}`).join(', ')}</>}
                </div>
              )}
              <div className="text-xs font-semibold text-slate-400 uppercase mb-1">Biggest injury risks</div>
              <table className="data-table">
                <thead><tr><th>Player</th><th>Slot</th><th>Proneness</th><th>Playing Time</th><th>Status</th></tr></thead>
                <tbody>
                  {dm.durability.risks.map((d, i) => (
                    <tr key={i}>
                      <td className="font-medium text-white">{d.name}</td>
                      <td className="text-slate-400">{d.pos}</td>
                      <td className={getCellColorClass(d.prone, 'Prone')}>{d.prone || '—'}</td>
                      <td className={d.f < 0.8 ? 'text-orange-400' : 'text-slate-300'}>{pct(d.f)}</td>
                      <td className="text-xs text-slate-500">{d.onDL ? `On DL (${d.dlDays}d)` : '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        );
      })()}

      {winModel === 'levers' && (() => {
        const lev = models.levers;
        const weakBats = [...(roster.lineupVsRHP.battingOrder || [])].sort((a, b) => (a.waa || 0) - (b.waa || 0)).slice(0, 3);
        const weakArms = [
          ...(roster.startingPitchers || []).map(p => ({ name: p.Name, role: 'SP', waa: p._spWAA || 0 })),
          ...(roster.reliefPitchers || []).map(p => ({ name: p.Name, role: 'RP', waa: p._rpWAA || 0 })),
        ].sort((a, b) => a.waa - b.waa).slice(0, 3);
        return (
          <div className="px-4 pb-4">
            <div className="bg-slate-800/30 rounded-lg border border-slate-700/50 p-3">
              <div className="flex items-center gap-2 mb-1"><TrendingUp size={15} className="text-emerald-400" />
                <h2 className="text-sm font-bold text-white">Levers — where the next win is cheapest</h2></div>
              <p className="text-xs text-slate-400 mb-3 max-w-3xl">
                On the Pythagorean curve the marginal value of a run depends on your run balance. This is which
                kind of upgrade buys you more wins right now, plus your weakest rostered spots.
              </p>
              <div className="grid grid-cols-2 md:grid-cols-3 gap-3 mb-3">
                <Metric label="+10 runs of offense" value={`+${lev.offPer10.toFixed(2)} W`}
                  tone={lev.lean === 'offense' ? 'text-green-400' : 'text-slate-300'} />
                <Metric label="+10 runs of prevention" value={`+${lev.prevPer10.toFixed(2)} W`}
                  tone={lev.lean === 'run prevention' ? 'text-green-400' : 'text-slate-300'} />
                <Metric label="Better lever" value={lev.lean === 'offense' ? 'Offense' : 'Pitch / Defense'}
                  sub={`+${lev.edge.toFixed(2)} W per 10 runs`} tone="text-emerald-400" />
              </div>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div>
                  <div className="text-xs font-semibold text-slate-400 uppercase mb-1">Weakest rostered spots</div>
                  <table className="data-table">
                    <thead><tr><th>Slot</th><th>Player</th><th>WAA</th></tr></thead>
                    <tbody>
                      {weakBats.map((e, i) => (
                        <tr key={`b${i}`}><td className="text-amber-400">{e.position}</td>
                          <td className="text-white">{e.player.Name}</td>
                          <td className={getCellColorClass(e.waa, 'Max WAA wtd')}>{(e.waa || 0).toFixed(1)}</td></tr>
                      ))}
                      {weakArms.map((e, i) => (
                        <tr key={`p${i}`}><td className="text-purple-400">{e.role}</td>
                          <td className="text-white">{e.name}</td>
                          <td className={getCellColorClass(e.waa, 'WAA wtd')}>{e.waa.toFixed(1)}</td></tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                <div>
                  <div className="text-xs font-semibold text-slate-400 uppercase mb-1">Internal call-up upgrades</div>
                  {models.callups.length > 0 ? (
                    <table className="data-table">
                      <thead><tr><th>Spot</th><th>Call up</th><th>Over</th><th>+Wins</th></tr></thead>
                      <tbody>
                        {models.callups.map((u, i) => (
                          <tr key={i}><td className="text-amber-400">{u.pos}</td>
                            <td className="text-green-400">{u.name}</td>
                            <td className="text-slate-400">{u.over}</td>
                            <td className="text-cyan-400">+{u.dWins.toFixed(1)}</td></tr>
                        ))}
                      </tbody>
                    </table>
                  ) : (
                    <p className="text-xs text-slate-500 italic mt-2">
                      No internal upgrade — at this level your roster is already your org's best at every spot.
                      Gains have to come from trades or free agency.
                    </p>
                  )}
                </div>
              </div>
            </div>
          </div>
        );
      })()}

      <div className="grid grid-cols-1 xl:grid-cols-2 gap-4 px-4 pb-4">
        {/* Batting Order with Split Tabs */}
        <div className="bg-slate-800/30 rounded-lg border border-slate-700/50">
          <div className="p-3 border-b border-slate-700/50 flex items-center gap-2">
            <Target className="text-blue-400" size={16} />
            <h2 className="text-sm font-bold text-white">Batting Order</h2>
            <span className="text-xs text-slate-500">(The Book &bull; wOBA + OBP)</span>
            <div className="flex gap-1 bg-slate-900 rounded-lg p-0.5 ml-auto">
              <button onClick={() => setActiveLineup('vR')}
                className={`px-3 py-1 text-xs font-medium rounded-md transition-colors ${
                  activeLineup === 'vR' ? 'bg-blue-600 text-white' : 'text-slate-400 hover:text-slate-200'
                }`}>
                vs RHP
              </button>
              <button onClick={() => setActiveLineup('vL')}
                className={`px-3 py-1 text-xs font-medium rounded-md transition-colors ${
                  activeLineup === 'vL' ? 'bg-green-600 text-white' : 'text-slate-400 hover:text-slate-200'
                }`}>
                vs LHP
              </button>
            </div>
          </div>
          <div className="text-xs text-slate-500 px-3 pt-1">
            Lineup WAA ({splitLabel}): <span className={activeLineup === 'vR' ? 'text-cyan-400 font-semibold' : 'text-emerald-400 font-semibold'}>
              {activeLineupData?.totalLineupWAA || 0}
            </span>
          </div>
          <table className="data-table">
            <thead>
              <tr>
                <th>#</th>
                <th>POS</th>
                <th>Name</th>
                <th>Role</th>
                <th>Age</th>
                <th>wOBA</th>
                <th>WAA</th>
                <th>ORG</th>
              </tr>
            </thead>
            <tbody>
              {activeLineupData?.battingOrder?.map((entry, idx) => {
                if (!entry) return null;
                return (
                  <tr key={idx} className="cursor-pointer hover:bg-slate-800/50"
                    onClick={() => select(entry.player, 'hitter')}>
                    <td className="font-bold text-blue-400">{entry.slot}</td>
                    <td className="font-bold text-amber-400">{entry.position}</td>
                    <td className="font-medium text-white">{entry.player.Name}</td>
                    <td className="text-xs text-slate-500">{entry.role}</td>
                    <td>{Math.round(parseFloat(entry.player.Age) || 0)}</td>
                    <td className={getCellColorClass(entry.woba, 'wOBA wtd')}>
                      {entry.woba ? entry.woba.toFixed(3) : '-'}
                    </td>
                    <td className={getCellColorClass(entry.waa, splitWAACol)}>
                      {entry.waa.toFixed(1)}
                    </td>
                    <td className="text-slate-400">{entry.player.ORG}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>

        {/* Bench */}
        <div className="bg-slate-800/30 rounded-lg border border-slate-700/50">
          <div className="p-3 border-b border-slate-700/50 flex items-center gap-2">
            <Users className="text-green-400" size={16} />
            <h2 className="text-sm font-bold text-white">Bench {splitLabel}</h2>
            <span className="text-xs text-slate-500">the 13 minus this lineup's nine</span>
          </div>
          <table className="data-table">
            <thead>
              <tr>
                <th>Role</th>
                <th>Name</th>
                <th>POS</th>
                <th>Age</th>
                <th>WAA</th>
                <th>Note</th>
                <th>ORG</th>
              </tr>
            </thead>
            <tbody>
              {activeBench.length ? activeBench.map((b, i) => (
                <BenchRow key={i} player={b.player} role={b.role} note={b.note} />
              )) : (
                <tr><td colSpan={7} className="text-xs text-slate-500 italic">No bench players</td></tr>
              )}
              {(roster.bench?.roleNotes?.backupC || roster.bench?.roleNotes?.utilityIF || roster.bench?.roleNotes?.utilityOF) && (
                <tr><td colSpan={7} className="text-xs text-orange-400/80 italic">
                  {[roster.bench.roleNotes.backupC, roster.bench.roleNotes.utilityIF, roster.bench.roleNotes.utilityOF].filter(Boolean).join(' · ')}
                </td></tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      {/* Pitching Staff */}
      <div className="grid grid-cols-1 xl:grid-cols-2 gap-4 px-4 pb-4">
        <div className="bg-slate-800/30 rounded-lg border border-slate-700/50">
          <div className="p-3 border-b border-slate-700/50 flex items-center gap-2">
            <Zap className="text-amber-400" size={16} />
            <h2 className="text-sm font-bold text-white">Starting Rotation (5 SP)</h2>
          </div>
          <table className="data-table">
            <thead>
              <tr>
                <th>#</th>
                <th>Name</th>
                <th>Age</th>
                <th>SP WAA</th>
                <th>RA/9</th>
                <th>STM</th>
                <th>ORG</th>
              </tr>
            </thead>
            <tbody>
              {roster.startingPitchers?.map((p, i) => (
                <tr key={i} className="cursor-pointer hover:bg-slate-800/50"
                  onClick={() => select(p, 'pitcher')}>
                  <td className="font-bold text-amber-400">SP{i + 1}</td>
                  <td className="font-medium text-white">{p.Name}</td>
                  <td>{Math.round(parseFloat(p.Age) || 0)}</td>
                  <td className={getCellColorClass(p._spWAA, 'WAA wtd')}>{(p._spWAA || 0).toFixed(1)}</td>
                  <td className={getCellColorClass(p['RA/9 wtd'], 'RA/9 wtd')}>
                    {formatCellValue(p['RA/9 wtd'], 'RA/9 wtd')}
                  </td>
                  <td>{p.STM}</td>
                  <td className="text-slate-400">{p.ORG}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <div className="bg-slate-800/30 rounded-lg border border-slate-700/50">
          <div className="p-3 border-b border-slate-700/50 flex items-center gap-2">
            <Shield className="text-purple-400" size={16} />
            <h2 className="text-sm font-bold text-white">Bullpen (8 RP)</h2>
          </div>
          <table className="data-table">
            <thead>
              <tr>
                <th>#</th>
                <th>Name</th>
                <th>Age</th>
                <th>RP WAA</th>
                <th>RA/9</th>
                <th>HLD</th>
                <th>ORG</th>
              </tr>
            </thead>
            <tbody>
              {roster.reliefPitchers?.map((p, i) => (
                <tr key={i} className="cursor-pointer hover:bg-slate-800/50"
                  onClick={() => select(p, 'pitcher')}>
                  <td className="font-bold text-purple-400">RP{i + 1}</td>
                  <td className="font-medium text-white">{p.Name}</td>
                  <td>{Math.round(parseFloat(p.Age) || 0)}</td>
                  <td className={getCellColorClass(p._rpWAA, 'WAA wtd RP')}>{(p._rpWAA || 0).toFixed(1)}</td>
                  <td className={getCellColorClass(p['RA/9 wtd RP'], 'RA/9 wtd RP')}>
                    {formatCellValue(p['RA/9 wtd RP'], 'RA/9 wtd RP')}
                  </td>
                  <td>{p.HLD}</td>
                  <td className="text-slate-400">{p.ORG}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* Charts */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 px-4 pb-6">
        <div className="bg-slate-800/50 rounded-lg p-3">
          <h3 className="text-xs font-semibold text-slate-400 uppercase mb-2">
            Position Player WAA ({splitLabel})
          </h3>
          <ResponsiveContainer width="100%" height={200}>
            <BarChart data={positionWAAData}>
              <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
              <XAxis dataKey="pos" tick={{ fill: '#94a3b8', fontSize: 11 }} />
              <YAxis tick={{ fill: '#94a3b8', fontSize: 10 }} />
              <Tooltip
                contentStyle={{ background: '#1e293b', border: '1px solid #475569', borderRadius: 8 }}
                formatter={(val, name, props) => [`${val.toFixed(1)} WAA - ${props.payload.name}`, 'WAA']}
              />
              <Bar dataKey="waa" radius={[4, 4, 0, 0]}>
                {positionWAAData.map((entry, i) => (
                  <Cell key={i} fill={entry.waa >= 2 ? '#3b82f6' : entry.waa >= 0 ? '#60a5fa' : '#ef4444'} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>

        <div className="bg-slate-800/50 rounded-lg p-3">
          <h3 className="text-xs font-semibold text-slate-400 uppercase mb-2">Pitching Staff WAA</h3>
          <ResponsiveContainer width="100%" height={200}>
            <BarChart data={pitchingWAAData}>
              <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
              <XAxis dataKey="name" tick={{ fill: '#94a3b8', fontSize: 10 }} />
              <YAxis tick={{ fill: '#94a3b8', fontSize: 10 }} />
              <Tooltip
                contentStyle={{ background: '#1e293b', border: '1px solid #475569', borderRadius: 8 }}
                formatter={(val, name, props) => [`${val.toFixed(1)} WAA - ${props.payload.player}`, 'WAA']}
              />
              <Bar dataKey="waa" radius={[4, 4, 0, 0]}>
                {pitchingWAAData.map((entry, i) => (
                  <Cell key={i} fill={entry.role === 'SP' ? '#f59e0b' : '#8b5cf6'} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
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
