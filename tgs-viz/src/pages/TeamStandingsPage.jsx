import React, { useMemo, useState } from 'react';
import { optimizeRoster, leagueGames } from '../lib/rosterOptimizer';
import { PositionalStrengthGrid } from '../components/PositionalStrength';
import { Download, ArrowUpDown, Loader2 } from 'lucide-react';

// ─── League assignments, per league ──────────────────────────────
// OOTP's export carries no AL/NL field, and team names differ between leagues
// (e.g. BLM disambiguates same-city clubs as "Chicago (N) Cubs"). The two
// leagues also disagree on some clubs — Milwaukee is AL in TGS but NL in BLM —
// so the mapping MUST be keyed by league rather than shared.
// TODO(contraction): TGS is contracting to 28 clubs; the dispersal lands when
// the league file updates. Do NOT pre-edit these sets or any zero-sum org
// counts — refresh them from the updated league file when it arrives.
export const LEAGUE_TEAMS = {
  TGS: {
    AL: new Set([
      'New York Yankees', 'Boston Red Sox', 'Baltimore Orioles',
      'Kansas City Royals', 'Chicago White Sox', 'Minnesota Twins',
      'Detroit Tigers', 'Oakland Athletics', 'Texas Rangers',
      'Tampa Bay Devil Rays', 'Toronto Blue Jays', 'Cleveland Guardians',
      'Anaheim Angels', 'Seattle Mariners', 'Milwaukee Brewers',
      'Houston Astros',
    ]),
    NL: new Set([
      'Atlanta Hammers', 'Cincinnati Reds', 'Chicago Cubs',
      'Arizona Diamondbacks', 'Kansas City Monarchs', 'Philadelphia Phillies',
      'Florida Marlins', 'New York Mets', 'Colorado Rockies',
      'Los Angeles Dodgers', 'Pittsburgh Pirates', 'San Diego Padres',
      'San Francisco Giants', 'Washington Nationals', 'St. Louis Cardinals',
      'Montreal Expos',
    ]),
  },
  BLM: {
    AL: new Set([
      'Baltimore Orioles', 'Boston Red Sox', 'Chicago (A) White Sox',
      'Cleveland Guardians', 'Detroit Tigers', 'Houston Astros',
      'Kansas City Royals', 'Los Angeles (A) Angels', 'Minnesota Twins',
      'New York (A) Yankees', 'Oakland Athletics', 'Seattle Mariners',
      'Tampa Bay Rays', 'Texas Rangers', 'Toronto Blue Jays',
    ]),
    NL: new Set([
      'Arizona Diamondbacks', 'Atlanta Braves', 'Chicago (N) Cubs',
      'Cincinnati Reds', 'Colorado Rockies', 'Los Angeles (N) Dodgers',
      'Miami Marlins', 'Milwaukee Brewers', 'New York (N) Mets',
      'Philadelphia Phillies', 'Pittsburgh Pirates', 'San Diego Padres',
      'San Francisco Giants', 'St. Louis Cardinals', 'Washington Nationals',
    ]),
  },
};

// Fallback for an unmapped league: include any org with a real roster
// (filters out cameo foreign clubs that have 1-3 players on loan).
const FALLBACK_MIN_ROSTER = 20;

// ─── Build team projections using the roster optimizer ───────────
// Step 1: Run optimizer per team to get raw WAA
// Step 2: Normalize so total league wins = total league losses
//         (optimizer cherry-picks best 26, leaving negative-WAA guys
//          off rosters, inflating the sum — normalization fixes this)
function buildTeamProjections(hitters, pitchers, knownTeams, league = null, vrShare = null) {
  // B3 (audit, corrected): base wins are G/2 for the league's REAL season
  // length — MEASURED at 162 for both real leagues (see LEAGUE_GAMES).
  const G = leagueGames(league);
  // Tally roster sizes per org. When we have a known team set for the league,
  // include exactly those orgs; otherwise (unmapped league) fall back to any
  // org with a real roster so nothing is silently dropped.
  const orgCount = {};
  const tally = (p) => {
    if (!p.ORG || p.ORG === '-') return;
    if (knownTeams && !knownTeams.has(p.ORG)) return;
    orgCount[p.ORG] = (orgCount[p.ORG] || 0) + 1;
  };
  hitters.forEach(tally);
  pitchers.forEach(tally);

  let orgList = Object.keys(orgCount);
  if (!knownTeams) orgList = orgList.filter(o => orgCount[o] >= FALLBACK_MIN_ROSTER);
  const orgs = new Set(orgList);

  // ── Pass 1: raw optimizer results ──
  const raw = [];
  for (const org of orgs) {
    // vrShare = the league's REAL season vs-RHP share from metadata (same value the
    // Roster Optimizer uses) — without it every row silently used the optimizer's
    // hardcoded TGS fallback, so the two screens computed on different bases.
    const roster = optimizeRoster(hitters, pitchers, { teamOrg: org, league, vrShare });
    const t = roster.totals;
    raw.push({
      team: org,
      rawWAAwtd: t.weightedLineupWAA + t.totalPitcherWAA,  // win-relevant WAA: platoon lineups (PA-weighted) + pitching, NOT the 13-bat sum (which over-counts rest-day bench). Matches the Roster Optimizer basis.
      rawOffWtd: t.weightedLineupWAA,
      rawWAAvR: t.lineupWAA_vR,
      rawWAAvL: t.lineupWAA_vL,
      // workload-scaled rotation/pen — the values that actually feed the total,
      // so Off wtd + SP + RP = Total WAA wtd holds exactly in the table
      rawSPWAA: t.totalSPWAAeff ?? t.totalSPWAA,
      rawRPWAA: t.totalRPWAAeff ?? t.totalRPWAA,
      rawHitterWAA: t.totalHitterWAA,
    });
  }

  const numTeams = raw.length;
  if (numTeams === 0) return [];

  // ── Pass 2: normalize ──
  // WAA should be zero-sum: total wins across league = numTeams × G/2
  // Raw sum is inflated → compute per-team offset to bring average WAA to 0
  const rawTotalWAA = raw.reduce((s, t) => s + t.rawWAAwtd, 0);
  const waaOffset = rawTotalWAA / numTeams; // subtract this from each team

  // Also normalize the split WAAs (vR / vL) and component WAAs proportionally
  const rawTotalvR = raw.reduce((s, t) => s + t.rawWAAvR, 0);
  const rawTotalvL = raw.reduce((s, t) => s + t.rawWAAvL, 0);
  const rawTotalOff = raw.reduce((s, t) => s + t.rawOffWtd, 0);
  const vROffset = rawTotalvR / numTeams;
  const vLOffset = rawTotalvL / numTeams;
  const offOffset = rawTotalOff / numTeams;

  // Center SP and RP each on its OWN league mean — zero-sum per component, exactly like
  // offense vR/vL above. (Previously they took a proportional share of the TOTAL offset,
  // which mis-centers once the total uses the platoon-weighted lineup basis: it pushed the
  // SP/RP columns negative so most teams read below average. Own-mean centering fixes that
  // and stays consistent: total = vr-weighted offense + SP + RP.)
  const rawTotalSP = raw.reduce((s, t) => s + t.rawSPWAA, 0);
  const rawTotalRP = raw.reduce((s, t) => s + t.rawRPWAA, 0);
  const spOffset = rawTotalSP / numTeams;
  const rpOffset = rawTotalRP / numTeams;

  return raw.map(t => {
    const adjWAA = t.rawWAAwtd - waaOffset;
    const adjOff = t.rawOffWtd - offOffset;
    const adjSP = t.rawSPWAA - spOffset;
    const adjRP = t.rawRPWAA - rpOffset;
    const adjvR = t.rawWAAvR - vROffset;
    const adjvL = t.rawWAAvL - vLOffset;
    const projW = Math.round(G / 2 + adjWAA);

    return {
      team: t.team,
      projW,
      projL: G - projW,
      offWAAwtd: Math.round(adjOff * 100) / 100,
      totalWAAvR: Math.round(adjvR * 100) / 100,
      totalWAAvL: Math.round(adjvL * 100) / 100,
      spWAA: Math.round(adjSP * 100) / 100,
      rpWAA: Math.round(adjRP * 100) / 100,
      totalWAAwtd: Math.round(adjWAA * 100) / 100,
    };
  });
}

// ─── CSV export ──────────────────────────────────────────────────
function toCSV(rows, columns) {
  const header = columns.map(c => c.label).join(',');
  const body = rows.map(r =>
    columns.map(c => {
      const v = c.accessor(r);
      if (typeof v === 'string' && v.includes(',')) return `"${v}"`;
      return v;
    }).join(',')
  );
  return [header, ...body].join('\n');
}

function downloadCSV(filename, csvText) {
  const blob = new Blob([csvText], { type: 'text/csv;charset=utf-8;' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

// ─── Column definitions ──────────────────────────────────────────
// Every WAA column is re-centered to the league average (see buildTeamProjections):
// the optimizer keeps each team's best 26 and drops the rest, which inflates raw
// WAA above zero-sum, so we subtract the league mean to keep standings honest
// (total W = total L). Net effect: each WAA column reads "vs the average team,"
// NOT raw/above-replacement — a solid-but-below-average unit shows negative. The
// tooltips say so, since the org page shows the raw values and the two would
// otherwise look contradictory.
const COLUMNS = [
  { key: 'team',       label: 'Team',       accessor: r => r.team,         fmt: v => v,            align: 'left',  tip: 'Organization' },
  { key: 'projW',      label: 'Proj W',     accessor: r => r.projW,        fmt: v => v,            align: 'right', tip: 'Projected wins = G/2 + total WAA vs league average (G = league games/season, 162 here)' },
  { key: 'projL',      label: 'Proj L',     accessor: r => r.projL,        fmt: v => v,            align: 'right', tip: 'Projected losses = G − Proj W' },
  { key: 'offWAAwtd',  label: 'Off WAA wtd', accessor: r => r.offWAAwtd,  fmt: v => v.toFixed(1), align: 'right', tip: 'Lineup (offense) WAA, platoon-weighted by the league’s real vs-RHP share, vs the league-average lineup. Off wtd + SP + RP = Total WAA wtd exactly.' },
  { key: 'totalWAAvR', label: 'Off WAA vR', accessor: r => r.totalWAAvR,   fmt: v => v.toFixed(1), align: 'right', tip: 'Lineup (offense) WAA vs right-handed pitching, as a team total relative to the league-average lineup. Not the platoon-weighted value — this is the vR split.' },
  { key: 'totalWAAvL', label: 'Off WAA vL', accessor: r => r.totalWAAvL,   fmt: v => v.toFixed(1), align: 'right', tip: 'Lineup (offense) WAA vs left-handed pitching, as a team total relative to the league-average lineup. Not the platoon-weighted value — this is the vL split.' },
  { key: 'spWAA',      label: 'SP WAA wtd', accessor: r => r.spWAA,        fmt: v => v.toFixed(1), align: 'right', tip: 'Rotation: the 5 starters’ weighted WAA scaled to the innings the sim actually gives a rotation (~94%), vs the league-average rotation. Above average = positive. (The org page shows each pitcher’s raw WAA, which runs higher.)' },
  { key: 'rpWAA',      label: 'RP WAA wtd', accessor: r => r.rpWAA,        fmt: v => v.toFixed(1), align: 'right', tip: 'Bullpen: the 8 relievers’ weighted WAA scaled to the innings the sim actually gives a pen, vs the league-average bullpen. Every team stacks its 8 best arms, so a pen of small-positive raw WAA can still land below average and read negative here.' },
  { key: 'totalWAAwtd',label: 'Total WAA wtd', accessor: r => r.totalWAAwtd, fmt: v => v.toFixed(1), align: 'right', tip: 'Whole-team weighted WAA vs the league-average team. Proj W = G/2 + this. Equals Off wtd + SP + RP exactly.' },
];

// ─── Sortable table component ────────────────────────────────────
function StandingsTable({ title, rows, onExport, halfWins = 81 }) {
  const [sortKey, setSortKey] = useState('projW');
  const [sortDir, setSortDir] = useState('desc');

  const sorted = useMemo(() => {
    const col = COLUMNS.find(c => c.key === sortKey);
    if (!col) return rows;
    return [...rows].sort((a, b) => {
      const av = col.accessor(a);
      const bv = col.accessor(b);
      if (typeof av === 'number' && typeof bv === 'number') {
        return sortDir === 'asc' ? av - bv : bv - av;
      }
      return sortDir === 'asc'
        ? String(av).localeCompare(String(bv))
        : String(bv).localeCompare(String(av));
    });
  }, [rows, sortKey, sortDir]);

  const handleSort = (key) => {
    if (sortKey === key) {
      setSortDir(d => d === 'desc' ? 'asc' : 'desc');
    } else {
      setSortKey(key);
      setSortDir('desc');
    }
  };

  return (
    <div className="bg-slate-900 rounded-xl border border-slate-800 overflow-hidden">
      <div className="flex items-center justify-between px-4 py-3 border-b border-slate-800">
        <h2 className="text-lg font-bold text-white">{title}</h2>
        <button
          onClick={onExport}
          className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-slate-300 bg-slate-800 hover:bg-slate-700 rounded-lg transition-colors"
        >
          <Download size={14} /> Export CSV
        </button>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-slate-800">
              {COLUMNS.map(col => (
                <th
                  key={col.key}
                  onClick={() => handleSort(col.key)}
                  title={col.tip}
                  className={`px-4 py-2.5 font-semibold text-slate-400 cursor-pointer hover:text-white transition-colors select-none whitespace-nowrap ${
                    col.align === 'left' ? 'text-left' : 'text-right'
                  }`}
                >
                  <span className="inline-flex items-center gap-1">
                    {col.label}
                    {sortKey === col.key && (
                      <ArrowUpDown size={12} className="text-blue-400" />
                    )}
                  </span>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {sorted.map((row, i) => (
              <tr
                key={row.team}
                className={`border-b border-slate-800/50 hover:bg-slate-800/40 transition-colors ${
                  i % 2 === 0 ? '' : 'bg-slate-900/50'
                }`}
              >
                {COLUMNS.map(col => {
                  const raw = col.accessor(row);
                  const display = col.fmt(raw);
                  let colorClass = 'text-slate-300';

                  if (col.key === 'projW') {
                    // Scale: G/2 = neutral (81 at 162 games — B3), ±14 = bright
                    const diff = raw - halfWins;
                    if (diff >= 14) colorClass = 'text-green-400 font-semibold';
                    else if (diff >= 9) colorClass = 'text-green-400';
                    else if (diff >= 4) colorClass = 'text-green-400/70';
                    else if (diff > 0) colorClass = 'text-green-400/50';
                    else if (diff === 0) colorClass = 'text-slate-400';
                    else if (diff > -4) colorClass = 'text-red-400/50';
                    else if (diff > -9) colorClass = 'text-red-400/70';
                    else if (diff > -14) colorClass = 'text-red-400';
                    else colorClass = 'text-red-400 font-semibold';
                  } else if (col.key === 'projL') {
                    // Inverse: high losses = red, low losses = green
                    const diff = raw - halfWins;
                    if (diff >= 14) colorClass = 'text-red-400 font-semibold';
                    else if (diff >= 9) colorClass = 'text-red-400';
                    else if (diff >= 4) colorClass = 'text-red-400/70';
                    else if (diff > 0) colorClass = 'text-red-400/50';
                    else if (diff === 0) colorClass = 'text-slate-400';
                    else if (diff > -4) colorClass = 'text-green-400/50';
                    else if (diff > -9) colorClass = 'text-green-400/70';
                    else if (diff > -14) colorClass = 'text-green-400';
                    else colorClass = 'text-green-400 font-semibold';
                  } else if (col.key !== 'team' && typeof raw === 'number') {
                    if (raw > 5) colorClass = 'text-green-400';
                    else if (raw > 0) colorClass = 'text-green-400/70';
                    else if (raw < -5) colorClass = 'text-red-400';
                    else if (raw < 0) colorClass = 'text-red-400/70';
                  }

                  return (
                    <td
                      key={col.key}
                      className={`px-4 py-2 whitespace-nowrap ${col.align === 'left' ? 'text-left' : 'text-right'} ${colorClass}`}
                    >
                      {display}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// ─── Main page ───────────────────────────────────────────────────
export default function TeamStandingsPage({ hitters, pitchers, metadata, league }) {
  // Resolve the per-league AL/NL map. Unknown leagues fall back to a single
  // combined table (no sub-league split) so teams are never silently dropped.
  const map = LEAGUE_TEAMS[league] || null;
  const halfWins = Math.round(leagueGames(league) / 2);   // neutral win total (B3: 81 at 162 games)

  const knownTeams = useMemo(
    () => map ? new Set([...map.AL, ...map.NL]) : null,
    [map]
  );

  // Same platoon-weight basis as the Roster Optimizer (real season vs-RHP share
  // from the league metadata) so the two screens agree on every team's WAA.
  const vrShare = metadata?.matchups?.['OVR vR'];

  const allTeams = useMemo(
    () => buildTeamProjections(hitters, pitchers, knownTeams, league, vrShare),
    [hitters, pitchers, knownTeams, league, vrShare]
  );

  const alTeams = useMemo(
    () => map ? allTeams.filter(t => map.AL.has(t.team)) : [],
    [allTeams, map]
  );
  const nlTeams = useMemo(
    () => map ? allTeams.filter(t => map.NL.has(t.team)) : [],
    [allTeams, map]
  );

  const exportLeague = (teams, filename) => {
    const csv = toCSV(teams, COLUMNS);
    downloadCSV(filename, csv);
  };

  const exportAll = () => {
    const allCols = [
      { label: 'League', accessor: r => map && map.AL.has(r.team) ? 'AL' : (map && map.NL.has(r.team) ? 'NL' : '-') },
      ...COLUMNS,
    ];
    const rows = map ? [...alTeams, ...nlTeams] : allTeams;
    const csv = toCSV(rows, allCols);
    downloadCSV('team_projections.csv', csv);
  };

  if (allTeams.length === 0) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="text-center space-y-3">
          <Loader2 size={36} className="animate-spin text-blue-500 mx-auto" />
          <p className="text-slate-400 text-sm">Building optimal rosters for all teams...</p>
        </div>
      </div>
    );
  }

  return (
    <div className="h-full overflow-y-auto">
      <div className="p-4 pb-2">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-bold text-white">Team Projections</h1>
            <p className="text-sm text-slate-400 mt-1">
              Optimized 26-man rosters. Every column is a{' '}
              <span className="text-slate-200 font-medium">team total shown vs the league-average team</span>{' '}
              (0 = average, + better, − worse) so the standings stay zero-sum (total W = total L).
              The org page shows raw per-player WAA, which runs higher.
            </p>
            <p className="text-xs text-slate-500 mt-1">
              <span className="text-slate-400">wtd</span> = platoon-weighted WAA ·{' '}
              <span className="text-slate-400">Off vR / vL</span> = lineup vs right / left-handed pitching ·{' '}
              <span className="text-slate-400">Proj W</span> = {halfWins} + Total WAA wtd ({leagueGames(league)}-game season) · hover any header for detail
            </p>
          </div>
          <button
            onClick={exportAll}
            className="flex items-center gap-1.5 px-4 py-2 text-sm font-medium text-white bg-blue-600 hover:bg-blue-500 rounded-lg transition-colors"
          >
            <Download size={16} /> Export All Teams
          </button>
        </div>
      </div>

      <div className="p-4 space-y-6">
        {map ? (
          <>
            <StandingsTable
              title="American League"
              rows={alTeams}
              halfWins={halfWins}
              onExport={() => exportLeague(alTeams, 'al_projections.csv')}
            />
            <StandingsTable
              title="National League"
              rows={nlTeams}
              halfWins={halfWins}
              onExport={() => exportLeague(nlTeams, 'nl_projections.csv')}
            />
          </>
        ) : (
          <StandingsTable
            title="All Teams"
            rows={allTeams}
            halfWins={halfWins}
            onExport={() => exportLeague(allTeams, 'team_projections.csv')}
          />
        )}

        {/* Where the wins above actually come from, position by position. Ranked
            inside this league only — never against the other league. */}
        <PositionalStrengthGrid
          hitters={hitters} pitchers={pitchers}
          league={league} knownTeams={knownTeams}
          title="Positional Strength"
        />
      </div>
    </div>
  );
}
