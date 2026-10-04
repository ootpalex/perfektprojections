import React, { useMemo, useState } from 'react';
import { buildPositionalStrength, teamPositionalStrength, LENSES, DEFAULT_LENS } from '../lib/positionalStrength';
import { posClass } from '../lib/columns';

// Every number below is WAA (value vs average) — see positionalStrength.js.
const fmt = (v) => (v === null || v === undefined || !Number.isFinite(v) ? '—' : (v > 0 ? '+' : '') + Number(v).toFixed(2));
const fmtZ = (v) => (Number.isFinite(v) ? (v > 0 ? '+' : '') + v.toFixed(2) : '—');

// Night Scorecard z-heat (ootp-dashboard theme.js zHeat), one encoding for the
// card and the grid so a colour means one thing: the cell fills from the panel
// toward red (weak) or blue (strong) by |z| / 2.5, and its ink flips to the
// desk colour at 80 % fill. Returns the custom properties .ns-heat reads
// (index.css); no colour literals here. --z-label is the secondary line's ink:
// muted cream while the fill is dark, the heat ink from 40 %.
function heatVars(z) {
  if (!Number.isFinite(z)) return undefined;
  const mix = Math.min(Math.abs(z), 2.5) / 2.5;
  const ink = mix >= 0.8 ? 'var(--bg)' : 'var(--text)';
  return {
    '--z-end': z < 0 ? 'var(--zneg)' : 'var(--zpos)',
    '--z-mix': `${(mix * 100).toFixed(1)}%`,
    '--z-ink': ink,
    '--z-label': mix >= 0.4 ? ink : 'var(--text-2)',
  };
}

function LensPicker({ lens, onChange }) {
  return (
    <select value={lens} onChange={(e) => onChange(e.target.value)} className="ns-select" aria-label="Value lens">
      {Object.values(LENSES).map((l) => <option key={l.key} value={l.key}>{l.label}</option>)}
    </select>
  );
}

/** Shared hook: build the league board once per (data, league, lens). */
function useStrength(hitters, pitchers, league, knownTeams, lens) {
  return useMemo(
    () => buildPositionalStrength(hitters, pitchers, { league, knownTeams, lens }),
    [hitters, pitchers, league, knownTeams, lens]
  );
}

/**
 * One org against its own league: rank and z at every position, the man who
 * scores the slot, the next man up (shown, never blended into the score), and
 * the league's best / worst club at that position.
 */
export function PositionalStrengthCard({ hitters, pitchers, league, knownTeams = null, team }) {
  const [lens, setLens] = useState(DEFAULT_LENS);
  const build = useStrength(hitters, pitchers, league, knownTeams, lens);
  const rows = useMemo(() => teamPositionalStrength(build, team), [build, team]);
  const n = build.teams.length;
  // The org dropdown also lists affiliates and loan clubs that aren't league
  // members; those have nothing to be ranked against, so say so rather than
  // vanishing.
  if (!rows.length) {
    return (
      <div className="ns-box px-3 py-2.5 text-xs ns-muted">
        <span className="font-narrow text-[13.5px] font-bold ns-text">Positional Strength</span> — {team || 'this club'} is not one of the {n} {league} clubs, so there is no league to rank it inside.
      </div>
    );
  }

  return (
    <div className="ns-box">
      <div className="ns-strip">
        <h2>Positional Strength</h2>
        <span className="ns-strip-right">
          <span className="truncate">{team} vs the other {n - 1} {league} clubs · {build.lens.note}</span>
          <LensPicker lens={lens} onChange={setLens} />
        </span>
      </div>
      <div className="overflow-x-auto">
        <table className="ns-table">
          <thead>
            <tr>
              <th>Pos</th>
              <th className="num col-group-start" title="Rank among this league's clubs at this position (1 = best)">Rank</th>
              <th className="num" title="Starter's WAA at this slot (SP = top 5 summed, RP = top 8). Empty slots are charged at the league's measured org replacement level.">WAA</th>
              <th className="num" title="Standard deviations from this league's mean at this position">z</th>
              <th className="col-group-start">Scores the slot</th>
              <th title="Next man up — shown for depth, NOT folded into the score (no measurable playing-time weights ship with the data)">Next up</th>
              <th className="col-group-start">League best</th>
              <th>League worst</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.key}>
                <td className={`whitespace-nowrap ${posClass(r.key) || 'font-semibold ns-text'}`}>
                  {r.key}{r.slots > 1 && <span className="ns-muted font-normal"> ×{r.slots}</span>}
                </td>
                <td className="num col-group-start ns-heat" style={heatVars(r.z)}>{r.rank}<span className="ns-heat-sub">/{n}</span></td>
                <td className="num ns-heat" style={heatVars(r.z)}>{fmt(r.waa)}</td>
                <td className="num ns-muted">{fmtZ(r.z)}</td>
                <td className="col-group-start ns-text whitespace-nowrap">
                  {r.top ? <>{r.top.name} <span className="ns-muted tabular-nums">{fmt(r.top.waa)}</span></>
                         : <span className="ns-bad">nobody — charged at replacement</span>}
                  {r.kind === 'arm' && r.count < r.slots && <span className="ns-bad"> · {r.slots - r.count} slot{r.slots - r.count > 1 ? 's' : ''} empty</span>}
                </td>
                <td className="ns-text-2 whitespace-nowrap">
                  {r.depth ? <>{r.depth.name} <span className="ns-muted tabular-nums">{fmt(r.depth.waa)}</span></> : <span className="ns-dim">—</span>}
                </td>
                <td className="col-group-start ns-text-2 whitespace-nowrap">{r.league.best.team} <span className="ns-good tabular-nums">{fmt(r.league.best.waa)}</span></td>
                <td className="ns-text-2 whitespace-nowrap">{r.league.worst.team} <span className="ns-bad tabular-nums">{fmt(r.league.worst.waa)}</span></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="ns-foot">
        WAA = wins vs average. Score = the starter only ({'SP ×5 / RP ×8'} summed) — the shipped rows carry no playing-time
        column, so no starter/backup depth weights can be measured and none are invented. Below-average slots stay negative.
      </div>
    </div>
  );
}

/**
 * The whole league at a glance: one row per club, one column per position,
 * cell = rank (WAA underneath), shaded by z within that position's column.
 */
export function PositionalStrengthGrid({ hitters, pitchers, league, knownTeams = null, teams = null, highlight = null, title = 'Positional Strength' }) {
  const [lens, setLens] = useState(DEFAULT_LENS);
  const build = useStrength(hitters, pitchers, league, knownTeams, lens);
  const shown = useMemo(() => {
    const set = teams ? new Set(teams) : null;
    return build.teams.filter((t) => !set || set.has(t));
  }, [build, teams]);
  if (!shown.length) return null;

  return (
    <div className="ns-box">
      <div className="ns-strip">
        <h2>{title}</h2>
        <span className="ns-strip-right"><LensPicker lens={lens} onChange={setLens} /></span>
      </div>
      <p className="ns-sub pb-2.5">
        Rank (of {build.teams.length}) and WAA at each position, ranked within {league} only · {build.lens.note} ·
        starter only for bats, top 5 SP / top 8 RP for the staff
      </p>
      <div className="overflow-x-auto ns-rule-t">
        <table className="ns-table">
          <thead>
            <tr>
              <th>Team</th>
              {build.positions.map((p, i) => (
                <th key={p.key} className={`text-center ${i === 0 ? 'col-group-start' : ''}`} title={p.slots > 1 ? `${p.key} — top ${p.slots} summed` : p.key}>
                  <span className={posClass(p.key)}>{p.key}</span>{p.slots > 1 && <span className="ns-muted"> ×{p.slots}</span>}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {shown.map((t) => (
              <tr key={t} className={t === highlight ? 'selected' : undefined}>
                <td className={`whitespace-nowrap ns-text ${t === highlight ? 'font-bold' : ''}`}>{t}</td>
                {build.positions.map((p, i) => {
                  const c = build.cells[t][p.key];
                  return (
                    <td key={p.key} className={`py-1 text-center ns-heat ${i === 0 ? 'col-group-start' : ''}`} style={heatVars(c.z)}
                        title={`${t} ${p.key}: WAA ${fmt(c.waa)}, z ${fmtZ(c.z)}${c.top ? ` — ${c.top.name}` : ' — no eligible player, charged at replacement'}`}>
                      <div>{c.rank}</div>
                      <div className="ns-heat-sub">{fmt(c.waa)}</div>
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
