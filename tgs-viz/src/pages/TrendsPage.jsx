import React, { useState, useEffect, useMemo } from 'react';
import { BarChart, Bar, LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Cell, ReferenceLine } from 'recharts';
import { loadRatingTrends, ratingScale, DISPLAY_UNIT } from '../lib/ratingTrends';
import { TrendingUp, TrendingDown, Info, Loader2 } from 'lucide-react';

/**
 * TrendsPage — league-wide scouting-rating movement from the ratings-history
 * DB (backtest/ratings_history.db -> rating_trends.json).
 *
 * INFORMATIONAL ONLY: nothing here feeds a projection. Projections stay
 * ratings-only from the current pull.
 */

function MoverTable({ title, rows, icon, accent }) {
  return (
    <div className="bg-slate-900 border border-slate-800 rounded-xl overflow-hidden">
      <div className={`flex items-center gap-2 px-4 py-2.5 border-b border-slate-800 ${accent}`}>
        {icon}
        <h3 className="text-sm font-bold">{title}</h3>
      </div>
      <table className="w-full text-sm">
        <thead>
          <tr className="text-[10px] uppercase tracking-wider text-slate-500 border-b border-slate-800">
            <th className="text-left px-4 py-1.5">Player</th>
            <th className="text-left px-2 py-1.5">Pos</th>
            <th className="text-right px-2 py-1.5">Age</th>
            <th className="text-left px-2 py-1.5">Org</th>
            <th className="text-right px-2 py-1.5">Total Δ</th>
            <th className="text-left px-2 py-1.5">Biggest changes</th>
          </tr>
        </thead>
        <tbody>
          {rows.map(x => (
            <tr key={x.id} className="border-b border-slate-800/50 hover:bg-slate-800/40">
              <td className="px-4 py-1.5 text-slate-200 font-medium whitespace-nowrap">{x.n}</td>
              <td className="px-2 py-1.5 text-slate-400">{x.p || '—'}</td>
              <td className="px-2 py-1.5 text-slate-400 text-right">{x.a != null ? Math.round(x.a) : '—'}</td>
              <td className="px-2 py-1.5 text-slate-500 whitespace-nowrap max-w-[160px] overflow-hidden text-ellipsis">{x.o || '—'}</td>
              <td className={`px-2 py-1.5 text-right font-mono font-bold ${x.t > 0 ? 'text-green-400' : 'text-red-400'}`}>
                {x.t > 0 ? '+' : ''}{x.t}
              </td>
              <td className="px-2 py-1.5">
                <div className="flex flex-wrap gap-1">
                  {Object.entries(x.d || {}).slice(0, 4).map(([c, d]) => (
                    <span key={c} className={`text-[10px] font-mono px-1.5 py-0.5 rounded ${
                      d > 0 ? 'bg-green-900/40 text-green-400' : 'bg-red-900/40 text-red-400'
                    }`}>
                      {c} {d > 0 ? '+' : ''}{d}
                    </span>
                  ))}
                </div>
              </td>
            </tr>
          ))}
          {rows.length === 0 && (
            <tr><td colSpan={6} className="px-4 py-4 text-slate-500 text-xs">No movers in this window.</td></tr>
          )}
        </tbody>
      </table>
    </div>
  );
}

// "Split by" lenses come from age_curves.trait_meta (order, labels, buckets,
// note, basis). This list is only the fallback for an export made before
// trait_meta existed.
const HNL = { buckets: ['H', 'N', 'L'], bucket_labels: { H: 'High', N: 'Normal', L: 'Low' } };
const FALLBACK_TRAIT_META = {
  WE: { label: 'Work Ethic', ...HNL },
  INT: { label: 'Intelligence', ...HNL },
  LEA: { label: 'Leadership', ...HNL },
};
const FALLBACK_PIT_COLS = ['STU', 'HRR', 'PBABIP', 'CON'];
// High / Normal / Low keep the green / slate / orange of the old legend. Normal
// is slate-400 because a thin slate-500 line hides next to the zero line.
const HNL_COLOR = { H: '#22c55e', N: '#94a3b8', L: '#f97316' };
// Every other bucket takes a color by its position in trait_meta.buckets, so a
// bucket the min-sample filter hides never repaints the others. Fixed order,
// checked on the #0f172a surface: every neighbor pair stays apart for
// protan / deutan / tritan readers and every color clears 3:1 contrast.
const BUCKET_COLORS = ['#3987e5', '#d95926', '#199e70', '#c98500', '#d55181', '#008300', '#9085e9', '#e66767'];
const bucketColor = (key, i) => HNL_COLOR[key] || BUCKET_COLORS[i % BUCKET_COLORS.length];
// Card surface (slate-900). A hollow dot fills with it so the line does not show through.
const SURFACE = '#0f172a';
const SIDE_LABEL = { pit: 'pitcher', hit: 'hitter' };
const isCount = v => typeof v === 'number' && Number.isFinite(v);
const fmtInt = v => Math.round(v).toLocaleString();
const fmtPts = v => `${v > 0 ? '+' : ''}${v.toFixed(2)}`;
const fmtYears = v => v.toFixed(v < 10 ? 1 : 0);
// A bare count in a bucket label ("1-25", "Too few (under 50)") takes the unit
// of the chosen rating's side (PA for hitter ratings, BF for pitcher ratings).
// A decimal such as "-.040" is a wOBA gap, not a count, and stays as it is.
const withUnit = (label, unit) => {
  if (!unit) return label;
  if (/^[\d\s+-]+$/.test(label)) return `${label} ${unit}`;
  return label.replace(/(^|[^.\d])(\d+)\)$/, `$1$2 ${unit})`);
};

// Tooltip of the split chart: buckets in trait_meta order (recharts sorts by
// name), a color swatch per row, and every sample size of the point.
// thinNote names the hollow-dot bar ("under 40 players") on a thin point.
// ptsWord is the unit of the chosen rating ("internal pts/yr" or "pts/yr").
function SplitTooltip({ active, payload, label, title, thinNote, ptsWord }) {
  if (!active || !payload?.length) return null;
  const pos = it => Number(String(it.dataKey).slice(1));
  const rows = [...payload].sort((a, b) => pos(a) - pos(b));
  return (
    <div className="bg-slate-800 border border-slate-600 rounded-lg px-3 py-2 text-xs shadow-lg">
      <div className="text-slate-200 mb-1">Age {label} · {title}</div>
      <table className="whitespace-nowrap">
        <tbody>
          {rows.map(it => {
            const k = it.dataKey;
            const p = it.payload || {};
            const bits = [`n=${p[`${k}_n`] != null ? fmtInt(p[`${k}_n`]) : '?'}`];
            if (p[`${k}_p`] != null) bits.push(`${fmtInt(p[`${k}_p`])} players`);
            if (p[`${k}_y`] != null) bits.push(`${fmtYears(p[`${k}_y`])} player-yrs`);
            return (
              <tr key={k}>
                <td className="text-slate-300">
                  <span
                    className="inline-block w-3 h-[3px] rounded-full align-middle mr-2"
                    style={{ background: it.color }}
                  />
                  {it.name}
                </td>
                <td className="pl-4 text-right font-mono text-slate-100">{fmtPts(it.value)} {ptsWord}</td>
                <td className="pl-4 font-mono text-slate-400">
                  {bits.join(' · ')}
                  {p[`${k}_thin`] && thinNote ? <span className="text-amber-400/80"> · {thinNote}</span> : null}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function AgeCurveExplorer({ ageCurves }) {
  // mode 'raw' = every rated player, points/yr (scout drift included);
  // mode 'gap' = ONLY players whose current sat below potential (maxed players
  // never dilute it) — share of the gap closed per year, the drafting number
  const [mode, setMode] = useState('gap');
  const hasGaps = !!ageCurves?.gaps && Object.keys(ageCurves.gaps).length > 0;
  const effMode = hasGaps ? mode : 'raw';
  const colSource = effMode === 'gap' ? ageCurves?.gaps : ageCurves?.cols;
  const cols = useMemo(() => Object.keys(colSource || {}).sort(), [colSource]);
  const [col, setCol] = useState('');
  const [minN, setMinN] = useState(50);       // bar view: pull-pair observations per age
  const [minP, setMinP] = useState(20);       // split view: distinct players per point
  const [split, setSplit] = useState('none'); // none | a lens key from trait_meta
  const [hot, setHot] = useState(null);       // bucket under the pointer in the legend
  useEffect(() => {
    if (cols.length && !cols.includes(col)) {
      setCol(cols.includes('POW vR') ? 'POW vR' : cols.includes('POW P') ? 'POW P' : cols[0]);
    }
  }, [cols]); // eslint-disable-line react-hooks/exhaustive-deps

  // traits are gap-conditioned; split applies in gap mode only
  const hasTraits = effMode === 'gap' && !!ageCurves?.traits && Object.keys(ageCurves.traits).length > 0;

  // cols values: [gain/yr, n, years]; gaps values: [gain/yr, closure/yr, n, years].
  // Gap view shows POINTS per year (user 2026-09-04: %-of-gap is a ratio of two
  // fuzzy quantities — a "5-point gap" at 45 vs 25 is not the same thing).
  const data = useMemo(() => {
    if (!col || !colSource?.[col]) return [];
    // gap_players: distinct players per base gap cell (gap view only)
    const gp = effMode === 'gap' ? ageCurves?.gap_players?.[col] : null;
    return Object.entries(colSource[col])
      .map(([age, v]) => effMode === 'gap'
        ? { age: Number(age), mean: v[0], n: v[2], years: v[3], players: isCount(gp?.[age]) ? gp[age] : null }
        : { age: Number(age), mean: v[0], n: v[1], years: v[2], players: null })
      .filter(d => d.n >= minN && d.age >= 15 && d.age <= 45)
      .sort((a, b) => a.age - b.age);
  }, [ageCurves, colSource, col, minN, effMode]);

  // Lens list for "Split by": order, labels and bucket order come from
  // trait_meta. Only a lens that holds data is offered. A bucket that holds
  // data but is missing from trait_meta.buckets goes last, so no data hides.
  // A lens that holds data but has no trait_meta entry goes last too: its key
  // is the label and its bucket keys are the buckets.
  const lenses = useMemo(() => {
    const isObj = v => !!v && typeof v === 'object' && !Array.isArray(v);
    const traits = isObj(ageCurves?.traits) ? ageCurves.traits : {};
    const tm = ageCurves?.trait_meta;
    const meta = isObj(tm) && Object.keys(tm).length > 0 ? tm : FALLBACK_TRAIT_META;
    const keys = [...Object.keys(meta), ...Object.keys(traits).filter(k => !(k in meta))];
    return keys
      .filter(k => isObj(traits[k]) && Object.keys(traits[k]).length > 0)
      .map(k => {
        const m = isObj(meta[k]) ? meta[k] : {};
        const listed = Array.isArray(m.buckets) ? m.buckets.map(String) : [];
        const extra = Object.keys(traits[k]).filter(b => !listed.includes(b));
        return {
          ...m,
          key: k,
          label: m.label ? String(m.label) : k,
          buckets: [...new Set([...listed, ...extra])],
          bucket_labels: isObj(m.bucket_labels) ? m.bucket_labels : {},
          basis_by_side: isObj(m.basis_by_side) ? m.basis_by_side : null,
        };
      });
  }, [ageCurves]);
  const lens = hasTraits ? (lenses.find(l => l.key === split) || null) : null;

  // Split view gates on DISTINCT PLAYERS when the export carries trait_players
  // for the lens. An export without it gates on n and keeps the old label.
  const lensPlayers = lens ? (ageCurves?.trait_players?.[lens.key] || null) : null;
  const byPlayers = !!lensPlayers;
  const minGate = byPlayers ? minP : minN;
  const minLabel = byPlayers ? 'Min players' : 'Min sample';

  // Hitter rating or pitcher rating: picks PA or BF where the lens has a basis per side.
  const pitCols = ageCurves?.lens_info?.pit_cols || FALLBACK_PIT_COLS;
  const side = pitCols.includes(col) ? 'pit' : 'hit';
  // Unit of the chosen rating: internal points (1-600) or display points.
  const colInternal = ratingUnits(ageCurves).unitOf(col) === UNIT;
  const ptsWord = colInternal ? 'internal pts/yr' : 'pts/yr';
  const unitFor = l => l?.basis_by_side?.[side] || null;
  const unit = unitFor(lens);
  const bucketLabel = b => withUnit(String(lens?.bucket_labels?.[b] ?? b), unit);
  let basisText = typeof lens?.basis === 'string' ? lens.basis : '';
  if (unit) {
    const both = [lens.basis_by_side.hit, lens.basis_by_side.pit].filter(Boolean).join('/');
    basisText = (!basisText || basisText === both) ? unit : `${basisText}, sample in ${unit}`;
    basisText += side === 'pit' ? ' (pitcher rating)' : ' (hitter rating)';
  }

  // One series per bucket, keyed b0, b1, ... by position in lens.buckets (a
  // bucket key such as "251+" is not a safe recharts dataKey). A point shows
  // only when its own distinct players reach the minimum (its n when the cell
  // has no player count). Rows cover every age between the first and the last
  // shown point, so a hidden point breaks the line and the chart never bridges
  // an age it did not measure. A shown point under 2x the minimum is "thin" and
  // draws hollow.
  // stats: n = pull-pair observations over the shown points; players = distinct
  // players per age, added over the same points (trait_players).
  const splitView = useMemo(() => {
    if (!lens || !col) return { rows: [], stats: [], ages: null };
    const t = ageCurves.traits[lens.key] || {};
    const tp = lensPlayers;
    const byAge = new Map();
    let lo = Infinity, hi = -Infinity;
    const stats = lens.buckets.map((b, i) => {
      const s = { key: b, i, n: 0, allN: 0, years: 0, points: 0, thin: 0, players: tp ? 0 : null };
      Object.entries(t[b]?.[col] || {}).forEach(([age, e]) => {
        if (!Array.isArray(e) || !isCount(e[0]) || !isCount(e[2])) return;
        const a = Number(age);
        lo = Math.min(lo, a); hi = Math.max(hi, a);
        s.allN += e[2];
        const cell = tp?.[b]?.[col]?.[age];
        const p = isCount(cell) ? cell : null;
        const size = p != null ? p : e[2];
        if (size < minGate) return;
        const thin = size < 2 * minGate;
        const row = byAge.get(a) || { age: a };
        row[`b${i}`] = e[0];
        row[`b${i}_n`] = e[2];
        row[`b${i}_y`] = e[3];
        row[`b${i}_p`] = p;
        row[`b${i}_thin`] = thin;
        byAge.set(a, row);
        s.n += e[2]; s.years += e[3] || 0; s.points += 1;
        if (thin) s.thin += 1;
        if (tp) s.players += p || 0;
      });
      return s;
    });
    const shown = [...byAge.keys()];
    const rows = [];
    if (shown.length) {
      for (let a = Math.min(...shown); a <= Math.max(...shown); a++) rows.push(byAge.get(a) || { age: a });
    }
    return { rows, stats, ages: lo <= hi ? [lo, hi] : null };
  }, [ageCurves, lens, lensPlayers, col, minGate]);
  // A legend entry with no drawn point has no line to pick out: it dims nothing.
  const hotKey = splitView.stats.some(s => s.key === hot && s.points > 0) ? hot : null;
  const dropped = hasTraits ? Object.entries(ageCurves?.lens_info?.dropped || {}) : [];

  // Pull pairs the export left out as a league-wide rating re-scale. The export
  // lists one entry per side, so the two sides of one pair merge into one item.
  const skippedPairs = useMemo(() => {
    const list = Array.isArray(ageCurves?.skipped_pairs) ? ageCurves.skipped_pairs : [];
    const byPair = new Map();
    list.forEach(sp => {
      if (!sp || typeof sp !== 'object') return;
      const from = sp.game_from || sp.real_from || '?';
      const to = sp.game_to || sp.real_to || '?';
      const id = `${sp.real_from}|${sp.real_to}|${from}|${to}`;
      const item = byPair.get(id) || { id, from, to, sides: [], reasons: [] };
      if (sp.side && !item.sides.includes(sp.side)) item.sides.push(sp.side);
      if (typeof sp.reason === 'string' && sp.reason) item.reasons.push(sp.reason);
      byPair.set(id, item);
    });
    return [...byPair.values()];
  }, [ageCurves]);

  if (!cols.length) return null;
  return (
    <div className="bg-slate-900 border border-slate-800 rounded-xl p-4">
      <div className="flex items-center justify-between flex-wrap gap-2 mb-2">
        <h3 className="text-sm font-bold text-slate-200">
          {effMode === 'gap' ? 'Growth Toward Potential (gap holders only)' : 'Average Gain per Year of Age'}
        </h3>
        <div className="flex flex-wrap items-center gap-x-3 gap-y-2 min-w-0 text-xs text-slate-400">
          {hasGaps && (
            <label className="flex items-center gap-1.5">
              View
              <select
                value={effMode}
                onChange={e => { setMode(e.target.value); setSplit('none'); }}
                className="bg-slate-800 border border-slate-700 rounded px-2 py-1 text-white"
              >
                <option value="gap">Growth (players with room)</option>
                <option value="raw">Raw change (all players)</option>
              </select>
            </label>
          )}
          <label className="flex items-center gap-1.5">
            Rating
            <select
              value={col}
              onChange={e => setCol(e.target.value)}
              className="bg-slate-800 border border-slate-700 rounded px-2 py-1 text-white"
            >
              {cols.map(c => <option key={c} value={c}>{c}</option>)}
            </select>
          </label>
          {hasTraits && lenses.length > 0 && (
            <label className="flex items-center gap-1.5 min-w-0">
              <span className="shrink-0">Split by</span>
              <select
                value={lens ? lens.key : 'none'}
                onChange={e => { setSplit(e.target.value); setHot(null); }}
                className="bg-slate-800 border border-slate-700 rounded px-2 py-1 text-white max-w-[13rem] min-w-0 truncate"
              >
                <option value="none">—</option>
                {lenses.map(l => (
                  <option key={l.key} value={l.key}>
                    {l.label}{unitFor(l) ? ` (${unitFor(l)})` : ''}
                  </option>
                ))}
              </select>
            </label>
          )}
          <label
            className="flex items-center gap-1.5 whitespace-nowrap"
            title={byPlayers
              ? 'Fewest distinct players a point needs before it is drawn'
              : 'Fewest pull-pair observations (n) an age needs before it is drawn'}
          >
            {minLabel}
            <input
              type="number" min={1} step={byPlayers ? 5 : 25} value={minGate}
              onChange={e => (byPlayers ? setMinP : setMinN)(Math.max(1, parseInt(e.target.value, 10) || 1))}
              className="w-16 bg-slate-800 border border-slate-700 rounded px-2 py-1 text-white"
            />
          </label>
        </div>
      </div>
      {lens && splitView.rows.length === 0 ? (
        <div className="h-[240px] flex items-center justify-center text-xs text-slate-500">
          {byPlayers
            ? `No ${lens.label} bucket reaches ${fmtInt(minGate)} players for ${col} at any age. Lower Min players.`
            : `No ${lens.label} bucket reaches a sample of ${fmtInt(minGate)} for ${col} at any age. Lower Min sample.`}
        </div>
      ) : (
      <ResponsiveContainer width="100%" height={240}>
        {!lens ? (
          <BarChart data={data}>
            <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
            <XAxis dataKey="age" tick={{ fill: '#94a3b8', fontSize: 11 }} />
            <YAxis tick={{ fill: '#94a3b8', fontSize: 10 }} tickFormatter={v => (Math.abs(v) >= 10 ? v.toFixed(0) : v.toFixed(1))} />
            <ReferenceLine y={0} stroke="#64748b" />
            <Tooltip
              contentStyle={{ background: '#1e293b', border: '1px solid #475569', borderRadius: 8 }}
              labelStyle={{ color: '#e2e8f0' }}
              formatter={(v, _name, item) => {
                const p = item?.payload || {};
                const sizes = [`n=${p.n}`];
                if (p.players != null) sizes.push(`${fmtInt(p.players)} players`);
                if (p.years != null) sizes.push(`${p.years.toFixed(0)} player-yrs`);
                const what = effMode === 'gap' ? `${ptsWord} toward potential` : 'per year of age';
                return [`${v > 0 ? '+' : ''}${v.toFixed(2)} ${what} (${sizes.join(', ')})`, col];
              }}
              labelFormatter={age => `Age ${age}`}
            />
            <Bar dataKey="mean" radius={[3, 3, 0, 0]}>
              {data.map((d, i) => <Cell key={i} fill={d.mean >= 0 ? '#3b82f6' : '#ef4444'} />)}
            </Bar>
          </BarChart>
        ) : (
          <LineChart data={splitView.rows}>
            <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
            <XAxis dataKey="age" tick={{ fill: '#94a3b8', fontSize: 11 }} />
            <YAxis tick={{ fill: '#94a3b8', fontSize: 10 }} tickFormatter={v => (Math.abs(v) >= 10 ? v.toFixed(0) : v.toFixed(1))} />
            <ReferenceLine y={0} stroke="#64748b" />
            <Tooltip
              content={tp => (
                <SplitTooltip
                  {...tp}
                  title={`${lens.label}${unit ? ` (${unit})` : ''}`}
                  thinNote={`under ${fmtInt(2 * minGate)} ${byPlayers ? 'players' : 'n'}`}
                  ptsWord={ptsWord}
                />
              )}
            />
            {lens.buckets.map((b, i) => {
              const c = bucketColor(b, i);
              const dim = hotKey && hotKey !== b ? 0.15 : 1;
              // colors repeat past the palette length; the repeat goes dashed
              const dash = !HNL_COLOR[b] && i >= BUCKET_COLORS.length ? '5 3' : undefined;
              return (
                <Line
                  key={b} type="linear" dataKey={`b${i}`} name={bucketLabel(b)}
                  stroke={c} strokeWidth={hotKey === b ? 3 : 2} strokeOpacity={dim}
                  strokeDasharray={dash}
                  dot={dp => {
                    // recharts calls this for every row; a row with no point has no cy
                    if (dp.cx == null || dp.cy == null || dp.value == null) return null;
                    // hollow = drawn, but under 2x the minimum players
                    return dp.payload?.[`b${i}_thin`]
                      ? <circle cx={dp.cx} cy={dp.cy} r={3} fill={SURFACE} stroke={c} strokeWidth={1.5} strokeOpacity={dim} />
                      : <circle cx={dp.cx} cy={dp.cy} r={2.5} fill={c} fillOpacity={dim} />;
                  }}
                  activeDot={{ r: 4, fill: c, stroke: SURFACE, strokeWidth: 2 }}
                  connectNulls={false} isAnimationActive={false}
                />
              );
            })}
          </LineChart>
        )}
      </ResponsiveContainer>
      )}
      {lens && (
        <div className="mt-1 space-y-1 text-[11px]">
          <div className="flex flex-wrap gap-x-3 gap-y-0.5 justify-center">
            <span className="text-slate-300 font-semibold">{lens.label}</span>
            {basisText && <span className="text-slate-500">basis: {basisText}</span>}
            {splitView.ages && (
              <span className="text-slate-500">(ages {splitView.ages[0]}–{splitView.ages[1]})</span>
            )}
          </div>
          <div className="flex flex-wrap gap-x-4 gap-y-1 justify-center">
            {splitView.stats.map(s => (
              <span
                key={s.key}
                onMouseEnter={() => setHot(s.key)}
                onMouseLeave={() => setHot(null)}
                className={`inline-flex items-center gap-1.5 cursor-default ${s.points ? '' : 'opacity-50'}`}
              >
                <span
                  className="inline-block w-3.5 h-[3px] rounded-full shrink-0"
                  style={{ background: bucketColor(s.key, s.i) }}
                />
                <span className="text-slate-300">{bucketLabel(s.key)}</span>
                <span className="text-slate-500 font-mono">
                  {s.points
                    ? `n=${fmtInt(s.n)}${s.allN > s.n ? ` of ${fmtInt(s.allN)}` : ''}`
                      + (s.players != null ? ` · ${fmtInt(s.players)} players` : '')
                    : s.allN > 0 ? `n=${fmtInt(s.allN)}, every age under ${minLabel.toLowerCase()}` : 'no data'}
                </span>
              </span>
            ))}
          </div>
          <p className="text-center text-slate-500">
            n = pull-pair observations at the points drawn for {col}
            {byPlayers
              ? '; players = distinct players at each age, added over the same points, so a player who turned a year older inside the archive counts once at each age'
              : ''}
            . A point shows only when its own {byPlayers ? 'distinct players reach' : 'n reaches'} {minLabel}, and a line breaks at a hidden point.{' '}
            <svg width="9" height="9" viewBox="0 0 9 9" className="inline-block align-baseline" aria-hidden="true">
              <circle cx="4.5" cy="4.5" r="3" fill={SURFACE} stroke="#94a3b8" strokeWidth="1.5" />
            </svg>
            {' '}A hollow dot is a drawn point with fewer than {fmtInt(2 * minGate)} {byPlayers ? 'players' : 'observations'} (2x the minimum). Hover a legend entry to pick out its line.
          </p>
        </div>
      )}
      {skippedPairs.length > 0 && (
        <p
          className="mt-2 text-[11px] text-amber-400/80"
          title={skippedPairs.flatMap(sp => sp.reasons).join(' / ') || undefined}
        >
          Left out: {skippedPairs.length} pull pair{skippedPairs.length > 1 ? 's' : ''} with a league-wide rating re-scale (
          {skippedPairs.map(sp => {
            const sides = ['pit', 'hit'].filter(s => sp.sides.includes(s)).map(s => SIDE_LABEL[s]);
            const other = sp.sides.filter(s => !SIDE_LABEL[s]).map(String);
            const who = [...sides, ...other].join(' and ');
            return `${sp.from} to ${sp.to}${who ? `, ${who} ratings` : ''}`;
          }).join('; ')}
          )
        </p>
      )}
      {typeof lens?.note === 'string' && lens.note && (
        <p className="mt-2 text-[11px] text-slate-400">
          <span className="text-slate-300 font-semibold">{lens.label}: </span>{lens.note}
        </p>
      )}
      {dropped.length > 0 && (
        <p className="mt-2 text-[11px] text-amber-400/80">
          Left out of this export: {dropped.map(([k, why]) => `${k} (${why})`).join('; ')}
        </p>
      )}
      <div className="flex items-start gap-2 mt-2 text-[11px] text-slate-500">
        <Info size={13} className="shrink-0 mt-0.5" />
        <p>
          {effMode === 'gap'
            ? `Only players whose CURRENT sat below their POTENTIAL for this rating at each interval — maxed players never dilute the growth of players with room. ${lens ? 'Lines' : 'Bars'} = ${colInternal ? "points on OOTP's internal 1-600 scale" : `display points (${ratingScale(ageCurves)} scale)`} gained per year of age; the gap is re-read every pull pair, so re-scouts and caught-up ratings switch tracking automatically.${lens ? '' : ' Bars past ~29 are scout alignment on veterans, not development.'}`
            : ageCurves.note}
        </p>
      </div>
    </div>
  );
}

// ---- Plain-language development summary (user, 2026-09-22: "what is good vs
// what is bad, what matters, what doesn't" — every age its own column, numbers
// on the page, nothing to hover). Reads the same age_curves export as the
// explorer below; the explorer is kept under a fold for digging.
const RATING_LABEL = {
  'BA vR': 'BABIP vs RHP', 'BA vL': 'BABIP vs LHP', 'GAP vR': 'Gap vs RHP', 'GAP vL': 'Gap vs LHP',
  'POW vR': 'Power vs RHP', 'POW vL': 'Power vs LHP', 'EYE vR': 'Eye vs RHP', 'EYE vL': 'Eye vs LHP',
  'K vR': 'Avoid K vs RHP', 'K vL': 'Avoid K vs LHP',
  'HT P': 'BABIP potential', 'GAP P': 'Gap potential', 'POW P': 'Power potential',
  'EYE P': 'Eye potential', 'K P': 'Avoid K potential',
  STU: 'Stuff', HRR: 'HRR', PBABIP: 'BABIP allowed', CON: 'Control', STM: 'Stamina', HLD: 'Hold runners',
  'STU P': 'Stuff potential', 'HRR P': 'HRR potential', 'PBABIP P': 'BABIP-allowed potential', 'CON P': 'Control potential',
  'IF RNG': 'IF range', 'IF ERR': 'IF error', 'IF ARM': 'IF arm', TDP: 'Turn DP',
  'OF RNG': 'OF range', 'OF ERR': 'OF error', 'OF ARM': 'OF arm',
  'C ABI': 'C ability', 'C FRM': 'C framing', 'C ARM': 'C arm',
  SPE: 'Speed', SR: 'Steal attempts', STE: 'Stealing ability', RUN: 'Baserunning',
  Ovr: 'Overall', Pot: 'Overall potential',
};
const OVR = 'Ovr';   // OOTP's own overall grade: display points (1-pt steps in TGS, 5-pt in BLM), never internal
// vR and vL of one skill are pooled into ONE attribute row (user, 2026-09-22:
// "get rid of the vR and vL stuff and just have it be both tied into one
// attribute"). Cells are player-year-weighted means of the two sides.
const ATTR_POOL = {
  BABIP: ['BA vR', 'BA vL'], Gap: ['GAP vR', 'GAP vL'], Power: ['POW vR', 'POW vL'],
  Eye: ['EYE vR', 'EYE vL'], 'Avoid K': ['K vR', 'K vL'],
};
function pooled(source, shape) {
  const out = {};
  for (const [attr, cols] of Object.entries(ATTR_POOL)) {
    const present = cols.filter(c => source?.[c]);
    if (!present.length) continue;
    out[attr] = {};
    for (const a of SUMMARY_AGES) {
      const cells = present.map(c => source[c][String(a)]).filter(Array.isArray);
      if (!cells.length) continue;
      const g = meanGain(cells);
      const n = cells.reduce((t, c) => t + ((shape === 'gap' ? c[2] : c[1]) || 0), 0);
      out[attr][String(a)] = shape === 'gap' ? [g.mean, null, n, g.years] : [g.mean, n, g.years];
    }
  }
  return out;
}
const POOLED_COLS = new Set(Object.values(ATTR_POOL).flat());
// Units. Two kinds of row:
//   internal points: batting and pitching ratings and their potentials in a
//     20-80 league, measured on OOTP's internal 1-600 scale. One step is
//     UNIT = 30 internal points (about one 20-80 step in the 50s).
//   display points: everything else. One step is one point on the 20-80
//     scale, or 100/60 = 1.67 points on the 1-100 scale (one 20-80 point
//     spans that much of 1-100). See DISPLAY_UNIT in lib/ratingTrends.js.
// The export stamps age_curves.scale ("20-80" | "1-100") and
// age_curves.units_by_col (col -> "internal" | "display"). A 1-100 league has
// no internal columns at all. An export without units_by_col uses the fixed
// split in INTERNAL_FALLBACK; one without scale is 20-80.
const UNIT = 30;
// [group label, ratings]. The unit of each rating comes from ratingUnits().
const RATING_GROUPS = [
  ['Overall', ['Ovr', 'Pot']],
  ['Hitting', ['BABIP', 'Gap', 'Power', 'Eye', 'Avoid K']],
  ['Hitting potential', ['HT P', 'GAP P', 'POW P', 'EYE P', 'K P']],
  ['Pitching', ['STU', 'HRR', 'PBABIP', 'CON']],
  ['Pitching potential', ['STU P', 'HRR P', 'PBABIP P', 'CON P']],
  ['Stamina / hold', ['STM', 'HLD']],
  ['Fielding', ['IF RNG', 'IF ERR', 'IF ARM', 'TDP', 'OF RNG', 'OF ERR', 'OF ARM', 'C ABI', 'C FRM', 'C ARM']],
  ['Running', ['SPE', 'SR', 'STE', 'RUN']],
];
// Columns on the internal scale when the export carries no units_by_col
// (the 20-80 split the export used before it stamped units).
const INTERNAL_FALLBACK = new Set([
  ...Object.values(ATTR_POOL).flat(),
  ...RATING_GROUPS.filter(([g]) => /^(Hitting potential|Pitching|Pitching potential)$/.test(g)).flatMap(([, list]) => list),
]);
// Per-league unit lookup. unitOf(col) = UNIT for an internal-point column,
// else the display step of the league's scale. A pooled row (BABIP, Power,
// ...) takes the unit of its first source column.
function ratingUnits(ageCurves) {
  const scale = ratingScale(ageCurves);
  const disp = DISPLAY_UNIT[scale];
  const byCol = ageCurves?.units_by_col;
  const stamped = !!byCol && typeof byCol === 'object' && Object.keys(byCol).length > 0;
  const internal = c => {
    const src = ATTR_POOL[c] ? ATTR_POOL[c][0] : c;
    return stamped ? byCol[src] === 'internal' : INTERNAL_FALLBACK.has(src);
  };
  return { scale, disp, unitOf: c => (internal(c) ? UNIT : disp) };
}
// Words for a unit, and a group label that says which unit its rows use.
const ptsWordOf = unit => (unit === UNIT ? 'internal points' : 'display points');
const groupLabel = (g, unit) => `${g} (${ptsWordOf(unit)})`;
// A threshold in the row's unit, written short: "15" for internal points,
// "0.5" on 20-80, "0.8" on 1-100.
const fmtThreshold = v => (Number.isInteger(v) ? String(v) : v.toFixed(1));
const SUMMARY_AGES = Array.from({ length: 15 }, (_, i) => 16 + i);   // 16..30; past 29 is scout re-reads
const GROWTH_AGES = [17, 18, 19, 20, 21, 22, 23, 24];                 // where development happens
const MIN_N = 50;                                                     // pull-pair observations per cell
const ratingLabel = c => RATING_LABEL[c] || c;
// One color scale for every table: green grows, gray flat, red falls.
// unit = UNIT for internal-point rows, the display step for the rest
function gainClass(v, unit = UNIT) {
  if (v == null) return 'text-slate-700';
  if (v >= 2 * unit) return 'bg-green-500/30 text-green-200 font-semibold';
  if (v >= 1 * unit) return 'bg-green-500/15 text-green-300';
  if (v >= 0.3 * unit) return 'bg-green-500/5 text-green-400/80';
  if (v > -0.3 * unit) return 'text-slate-500';
  if (v > -1 * unit) return 'bg-red-500/10 text-red-300/80';
  return 'bg-red-500/25 text-red-200';
}
const fmtGain = (v, unit = UNIT) => {
  if (v == null) return '';
  const r = unit === UNIT ? Math.round(v) : Math.round(v * 10) / 10;
  return r > 0 ? `+${r}` : String(r);
};

// Weighted mean gain over cells: each cell = [gain, ..., n, years] (gap/trait
// shape) or [gain, n, years] (raw shape). Weight = player-years.
function meanGain(cells) {
  let num = 0, den = 0;
  for (const c of cells) {
    if (!Array.isArray(c) || !isCount(c[0])) continue;
    const n = c.length >= 4 ? c[2] : c[1];
    const y = c.length >= 4 ? c[3] : c[2];
    if (!isCount(n) || n < MIN_N || !isCount(y) || y <= 0) continue;
    num += c[0] * y; den += y;
  }
  return den > 0 ? { mean: num / den, years: den } : { mean: null, years: 0 };
}

function AgeTable({ title, note, rows, source, shape, rowHeader = 'Rating', showKeys = true }) {
  // rows: [{key, label, group?}]; source[key][age] = cell
  const cell = (key, age) => {
    const c = source?.[key]?.[String(age)];
    if (!Array.isArray(c)) return null;
    const n = shape === 'gap' ? c[2] : c[1];
    return isCount(n) && n >= MIN_N && isCount(c[0]) ? c[0] : null;
  };
  let lastGroup = null;
  return (
    <div className="bg-slate-900 border border-slate-800 rounded-xl overflow-hidden">
      <div className="px-4 py-2.5 border-b border-slate-800">
        <h3 className="text-sm font-bold text-slate-200">{title}</h3>
        {note && <p className="text-[11px] text-slate-500 mt-0.5">{note}</p>}
      </div>
      <div className="overflow-x-auto">
        <table className="text-xs whitespace-nowrap">
          <thead>
            <tr className="text-[10px] uppercase tracking-wider text-slate-500 border-b border-slate-800">
              <th className="text-left px-3 py-1.5 sticky left-0 bg-slate-900">{rowHeader}</th>
              {SUMMARY_AGES.map(a => <th key={a} className="px-1.5 py-1.5 text-right w-12">{a}</th>)}
            </tr>
          </thead>
          <tbody>
            {rows.map(r => {
              const groupRow = r.group && r.group !== lastGroup;
              lastGroup = r.group || lastGroup;
              return (
                <React.Fragment key={r.key}>
                  {groupRow && (
                    <tr><td colSpan={SUMMARY_AGES.length + 1} className="px-3 pt-2 pb-0.5 text-[10px] uppercase tracking-wider text-slate-500">{r.group}</td></tr>
                  )}
                  <tr className="border-b border-slate-800/40 hover:bg-slate-800/30">
                    <td className="px-3 py-1 text-slate-300 sticky left-0 bg-slate-900">
                      {r.label}{showKeys && r.label !== r.key && <span className="text-slate-600"> {r.key}</span>}
                    </td>
                    {SUMMARY_AGES.map(a => {
                      const v = cell(r.key, a);
                      const u = r.unit ?? UNIT;
                      return <td key={a} className={`px-1.5 py-1 text-right font-mono ${gainClass(v, u)}`}>{fmtGain(v, u)}</td>;
                    })}
                  </tr>
                </React.Fragment>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function DevSummary({ ageCurves }) {
  // Units for this league: the display scale and each column's step.
  const { scale, unitOf } = useMemo(() => ratingUnits(ageCurves), [ageCurves]);
  const gaps = useMemo(() => {
    const g = ageCurves?.gaps || {};
    const rest = Object.fromEntries(Object.entries(g).filter(([c]) => !POOLED_COLS.has(c)));
    return { ...pooled(g, 'gap'), ...rest };
  }, [ageCurves]);
  const raw = useMemo(() => {
    const r = ageCurves?.cols || {};
    const rest = Object.fromEntries(Object.entries(r).filter(([c]) => !POOLED_COLS.has(c)));
    return { ...pooled(r, 'raw'), ...rest };
  }, [ageCurves]);
  // hitting skills first, then pitching, then anything new
  const GAP_ORDER = ['Ovr', 'BABIP', 'Gap', 'Power', 'Eye', 'Avoid K', 'STU', 'HRR', 'PBABIP', 'CON'];
  const gapCols = Object.keys(gaps).sort((x, y) => {
    const ix = GAP_ORDER.indexOf(x), iy = GAP_ORDER.indexOf(y);
    return (ix < 0 ? 99 : ix) - (iy < 0 ? 99 : iy) || x.localeCompare(y);
  });
  const allCols = Object.keys(raw);
  // The skill rows of one league share a unit (internal points in a 20-80
  // export, display points in a 1-100 one); Overall is always display points.
  const skillUnit = unitOf(gapCols.find(c => c !== OVR) ?? 'STU');
  const ovrUnit = unitOf(OVR);
  const skillPts = ptsWordOf(skillUnit);
  const hasInternal = [...gapCols, ...allCols].some(c => unitOf(c) === UNIT);

  // Headline: average growth across the potential-bearing ratings, per age.
  const overall = useMemo(() => {
    if (!gaps[OVR]) return null;
    const byAge = SUMMARY_AGES.map(a => ({ age: a, ...meanGain([gaps[OVR][String(a)]]) }));
    const shown = byAge.filter(x => x.mean != null);
    if (!shown.length) return null;
    const peak = shown.reduce((b, x) => (x.mean > b.mean ? x : b), shown[0]);
    const stop = shown.find(x => x.age > peak.age && x.mean < peak.mean / 2);
    return { peak, stop };
  }, [gaps]);
  const headline = useMemo(() => {
    const byAge = SUMMARY_AGES.map(a => ({ age: a, ...meanGain(gapCols.filter(c => c !== OVR).map(c => gaps[c]?.[String(a)])) }));
    const shown = byAge.filter(x => x.mean != null);
    if (!shown.length) return null;
    const peak = shown.reduce((b, x) => (x.mean > b.mean ? x : b), shown[0]);
    // first age after the peak where growth has fallen under half the peak
    const stop = shown.find(x => x.age > peak.age && x.mean < peak.mean / 2);
    return { byAge, peak, stop };
  }, [ageCurves]); // eslint-disable-line react-hooks/exhaustive-deps

  // Factors: one table per lens (rows = its groups, columns = ages), each
  // cell the growth averaged over the potential-bearing ratings; plus one
  // number per group over the growth ages for the ranking table.
  const factors = useMemo(() => {
    const traits = ageCurves?.traits || {};
    const meta = ageCurves?.trait_meta || {};
    const keys = [...Object.keys(meta), ...Object.keys(traits).filter(k => !(k in meta))];
    return keys.filter(k => traits[k] && Object.keys(traits[k]).length).map(k => {
      const m = meta[k] || {};
      const listed = Array.isArray(m.buckets) ? m.buckets.map(String) : [];
      const buckets = [...new Set([...listed, ...Object.keys(traits[k])])];
      const unit = m.basis_by_side ? [m.basis_by_side.hit, m.basis_by_side.pit].filter(Boolean).join('/') : null;
      const source = {};   // bucket -> age -> [mean, null, gate, player-years]; skills rows and Overall rows
      const bucketLabel = b => withUnit(String(m.bucket_labels?.[b] ?? b), unit);
      const build = (pickCols, keyOf) => buckets.map(b => {
        const cols = pickCols(Object.keys(traits[k][b] || {}));
        const sk = keyOf(b);
        source[sk] = {};
        for (const a of SUMMARY_AGES) {
          const g = meanGain(cols.map(c => traits[k][b][c]?.[String(a)]));
          source[sk][String(a)] = [g.mean, null, g.years >= 10 ? MIN_N : 0, g.years];
        }
        const cells = [];
        for (const c of cols) for (const a of GROWTH_AGES) cells.push(traits[k][b][c]?.[String(a)]);
        const g = meanGain(cells);
        return { key: b, label: bucketLabel(b), mean: g.mean, years: g.years / Math.max(1, cols.length) };
      });
      const rows = build(cols => cols.filter(c => c !== OVR), b => b);              // skills, internal points
      const rowsO = build(cols => cols.filter(c => c === OVR), b => `${OVR}:${b}`);   // Overall, display points
      // "too few" is a not-enough-data bucket, not a real group: it never
      // decides best or worst. Verdict is DIRECTIONAL: most of the factor vs
      // least of it (personality buckets run High -> Low; others low -> high).
      const judge = (rs, u) => {
        const ok = rs.filter(r => r.mean != null && r.years >= 30 && !/too few/i.test(r.label));   // 30 player-years per rating
        let verdict = 'not enough players', spread = null, best = null, worst = null;
        if (ok.length >= 2) {
          const hnl = ok[0].key === 'H' || ok[0].key === 'N' || ok[0].key === 'L';
          const most = hnl ? ok[0] : ok[ok.length - 1];
          const least = hnl ? ok[ok.length - 1] : ok[0];
          spread = most.mean - least.mean;   // + = more of it helps, - = more of it hurts
          best = most; worst = least;
          const a = Math.abs(spread);
          verdict = a < 0.2 * u ? "Doesn't matter"
            : spread > 0 ? (a >= 0.5 * u ? 'Matters' : 'A little')
            : (a >= 0.5 * u ? 'Hurts' : 'Hurts a little');
        }
        return { verdict, spread, best, worst };
      };
      const ovr = rowsO.some(r => r.mean != null) ? { rows: rowsO, ...judge(rowsO, ovrUnit) } : null;
      return { key: k, label: m.label || k, rows, source, ovr, ...judge(rows, skillUnit) };
    });
  }, [ageCurves, skillUnit, ovrUnit]);
  const ranked = useMemo(
    () => [...factors].sort((a, b) => Math.abs(b.spread ?? -1) - Math.abs(a.spread ?? -1)),
    [factors]
  );
  // Rating families that barely move / drift down, for the plain-words list.
  // A family "barely changes" only when EVERY rating in it barely changes
  // (max over its ratings); "drifts down" on the family mean.
  const families = useMemo(() => RATING_GROUPS.map(([g, list]) => {
    // ratings with a potential are judged on players with room (the gap table);
    // the rest on every player (raw)
    const src = c => (gaps[c] ? gaps[c] : raw[c]);
    const present = list.filter(c => src(c));
    const unit = unitOf(present[0] ?? list[0]);
    const per = present.map(c => meanGain(GROWTH_AGES.map(a => src(c)[String(a)])).mean).filter(v => v != null);
    const cells = [];
    for (const c of present) for (const a of GROWTH_AGES) cells.push(src(c)[String(a)]);
    return { group: g, unit, ...meanGain(cells), maxAbs: per.length ? Math.max(...per.map(Math.abs)) : null };
  }).filter(f => f.mean != null), [ageCurves, gaps, raw, unitOf]);

  if (!gapCols.length && !allCols.length) return null;
  const verdictClass = v => (v === 'Matters' ? 'text-green-400' : v === 'A little' ? 'text-amber-300' : v.startsWith('Hurts') ? 'text-red-300' : v === "Doesn't matter" ? 'text-slate-400' : 'text-slate-600');
  const gapRows = gapCols.map(c => ({ key: c, label: c === OVR ? 'Overall (display points)' : ratingLabel(c), unit: unitOf(c) }));
  const rawRows = RATING_GROUPS.flatMap(([g, list]) => list.filter(c => raw[c]).map(c => {
    const unit = unitOf(c);
    return { key: c, label: ratingLabel(c), group: unit === UNIT ? g : groupLabel(g, unit), unit };
  }));
  const leftover = allCols.filter(c => !rawRows.some(r => r.key === c)).map(c => ({ key: c, label: ratingLabel(c), group: groupLabel('Other', unitOf(c)), unit: unitOf(c) }));

  return (
    <div className="space-y-4">
      {headline && (
        <div className="bg-slate-900 border border-slate-800 rounded-xl p-4">
          <h2 className="text-base font-bold text-white">Development: what the archive says</h2>
          <ul className="text-sm text-slate-300 mt-2 space-y-1.5 list-disc pl-5">
            <li>
              Ratings grow fastest at age <span className="font-semibold text-white">{headline.peak.age}</span>
              {' '}(about <span className="font-mono text-green-300">{fmtGain(headline.peak.mean, skillUnit)}</span> {skillPts} a year)
              {headline.stop
                ? <>. It has fallen under half of that by <span className="font-semibold text-white">{headline.stop.age}</span> ({fmtGain(headline.stop.mean, skillUnit)} a year).</>
                : <> and keeps going through every age measured.</>}
            </li>
            {overall && (
              <li>
                <span className="font-semibold text-white">Overall grade</span> (OOTP's own, display points) grows fastest at age <span className="font-semibold text-white">{overall.peak.age}</span>
                {' '}(about <span className="font-mono text-green-300">{fmtGain(overall.peak.mean, ovrUnit)}</span> a year, players still below their potential grade)
                {overall.stop ? <>, under half of that by <span className="font-semibold text-white">{overall.stop.age}</span>.</> : '.'}
              </li>
            )}
            {ranked.filter(f => f.verdict !== "Doesn't matter" && f.spread != null).map(f => (
              <li key={f.key}>
                <span className="font-semibold text-white">{f.label}</span>
                {f.verdict === 'Matters' ? ' matters: more of it helps. ' : f.verdict === 'A little' ? ' matters a little: more of it helps. '
                  : f.verdict === 'Hurts' ? ' hurts: more of it means less growth. ' : ' hurts a little: more of it means less growth. '}
                <span className="text-slate-400">{f.best.label}</span> grows <span className="font-mono text-slate-200">{fmtGain(f.best.mean, skillUnit)}</span> a year,
                {' '}<span className="text-slate-400">{f.worst.label}</span> grows <span className="font-mono text-slate-200">{fmtGain(f.worst.mean, skillUnit)}</span> ({skillPts}).
              </li>
            ))}
            {ranked.some(f => f.verdict === "Doesn't matter") && (
              <li>
                <span className="font-semibold text-white">Doesn't matter:</span>{' '}
                {ranked.filter(f => f.verdict === "Doesn't matter").map(f => f.label.toLowerCase()).join(', ')}.
              </li>
            )}
            {ranked.some(f => f.ovr && f.ovr.spread != null) && (
              <li>
                <span className="font-semibold text-white">For the overall grade:</span>{' '}
                {(() => {
                  const yes = ranked.filter(f => f.ovr && f.ovr.spread != null && f.ovr.verdict !== "Doesn't matter" && f.ovr.verdict !== 'not enough players');
                  const no = ranked.filter(f => f.ovr && f.ovr.verdict === "Doesn't matter");
                  return <>
                    {yes.length ? yes.map(f => `${f.label.toLowerCase()} ${f.ovr.verdict.toLowerCase()} (${f.ovr.best.label} ${fmtGain(f.ovr.best.mean, ovrUnit)} vs ${f.ovr.worst.label} ${fmtGain(f.ovr.worst.mean, ovrUnit)} a year)`).join('; ') + '. ' : ''}
                    {no.length ? `Doesn't matter: ${no.map(f => f.label.toLowerCase()).join(', ')}.` : ''}
                  </>;
                })()}
              </li>
            )}
            {families.filter(f => f.maxAbs != null && f.maxAbs < 0.3 * f.unit).length > 0 && (
              <li>
                <span className="font-semibold text-white">Barely change:</span>{' '}
                {families.filter(f => f.maxAbs != null && f.maxAbs < 0.3 * f.unit).map(f => f.group.toLowerCase()).join(', ')} ratings.
              </li>
            )}
            {families.filter(f => f.mean <= -0.3 * f.unit).length > 0 && (
              <li>
                <span className="font-semibold text-white">Drift down:</span>{' '}
                {families.filter(f => f.mean <= -0.3 * f.unit).map(f => `${f.group.toLowerCase()} (${fmtGain(f.mean, f.unit)} a year)`).join(', ')}. Potential ratings come down as players age without reaching them.
              </li>
            )}
          </ul>
          <p className="text-[11px] text-slate-500 mt-2">
            {hasInternal
              ? `Ratings in this league show on the ${scale} scale. Batting and pitching numbers below are points on OOTP's internal 1-600 rating scale gained per year of age, from every archived pull, MLB and minors. One 5-point step on the 20-80 display is about 45-50 internal points in the 30s and 40s and only 14-19 from 55 to 80 (a 50 is 375-412, a 60 is 437-449), so growth is counted underneath the display, where a step at 60 costs far less than a step at 40. The band table is approximate: the archive confirms the shape (sharp narrowing from 55 up), not every edge. Fielding, running, stamina and hold show no such narrowing and stay in display steps.`
              : `Ratings in this league show on the ${scale} scale, and every number below is display points on that scale gained per year of age, from every archived pull, MLB and minors.${scale === '1-100' ? ' One 20-80 point is about 1.67 points here, so one step is 1.67 points.' : ''}`}
            {' '}Green = grows, gray = flat, red = falls. Blank = too few players. Ages past 30 are left off: almost nobody is still developing there.
          </p>
        </div>
      )}

      {gapCols.length > 0 && (
        <AgeTable
          title="Growth toward potential, by age"
          note="Only players whose current rating sat below their potential. These are the ratings OOTP gives a potential for; vR and vL are pooled into one row per skill."
          rows={gapRows} source={gaps} shape="gap"
        />
      )}

      {ranked.length > 0 && (
        <div className="bg-slate-900 border border-slate-800 rounded-xl overflow-hidden">
          <div className="px-4 py-2.5 border-b border-slate-800">
            <h3 className="text-sm font-bold text-slate-200">What helps growth most, and least</h3>
            <p className="text-[11px] text-slate-500 mt-0.5">
              {skillPts[0].toUpperCase() + skillPts.slice(1)} gained per year at ages {GROWTH_AGES[0]}–{GROWTH_AGES[GROWTH_AGES.length - 1]}, averaged over the ratings above. Most of the factor vs least of it. Matters = more of it adds {fmtThreshold(0.5 * skillUnit)} a year or more; A little = {fmtThreshold(0.2 * skillUnit)} to {fmtThreshold(0.5 * skillUnit)}; Doesn't matter = under {fmtThreshold(0.2 * skillUnit)} either way; Hurts = more of it means less growth. The two right-hand columns judge OOTP's overall grade the same way, in display points (Matters = {fmtThreshold(0.5 * ovrUnit)} a year or more). Each factor has its own table below.
            </p>
          </div>
          <table className="w-full text-xs">
            <thead>
              <tr className="text-[10px] uppercase tracking-wider text-slate-500 border-b border-slate-800">
                <th className="text-left px-3 py-1.5">Factor</th>
                <th className="text-left px-2 py-1.5">Verdict</th>
                <th className="text-left px-2 py-1.5">Most of it</th>
                <th className="text-left px-2 py-1.5">Least of it</th>
                <th className="text-right px-3 py-1.5">Gap (pts/yr)</th>
                <th className="text-left px-2 py-1.5 border-l border-slate-800">Overall verdict</th>
                <th className="text-right px-3 py-1.5">Overall gap</th>
              </tr>
            </thead>
            <tbody>
              {ranked.map(f => (
                <tr key={f.key} className="border-b border-slate-800/40">
                  <td className="px-3 py-1.5 text-slate-200 whitespace-nowrap">{f.label}</td>
                  <td className={`px-2 py-1.5 font-semibold whitespace-nowrap ${verdictClass(f.verdict)}`}>{f.verdict}</td>
                  <td className="px-2 py-1.5 whitespace-nowrap">
                    {f.best ? <><span className="text-slate-400">{f.best.label}</span> <span className={`font-mono px-1 rounded ${gainClass(f.best.mean, skillUnit)}`}>{fmtGain(f.best.mean, skillUnit)}</span></> : '—'}
                  </td>
                  <td className="px-2 py-1.5 whitespace-nowrap">
                    {f.worst ? <><span className="text-slate-400">{f.worst.label}</span> <span className={`font-mono px-1 rounded ${gainClass(f.worst.mean, skillUnit)}`}>{fmtGain(f.worst.mean, skillUnit)}</span></> : '—'}
                  </td>
                  <td className="px-3 py-1.5 text-right font-mono text-slate-300">{f.spread == null ? '—' : fmtGain(f.spread, skillUnit)}</td>
                  <td className={`px-2 py-1.5 font-semibold whitespace-nowrap border-l border-slate-800 ${verdictClass(f.ovr?.verdict || 'not enough players')}`}>{f.ovr?.verdict || '—'}</td>
                  <td className="px-3 py-1.5 text-right font-mono text-slate-300">{f.ovr?.spread == null ? '—' : fmtGain(f.ovr.spread, ovrUnit)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {ranked.map(f => (
        <AgeTable
          key={f.key}
          title={`${f.label}: growth by age`}
          note={`${f.verdict}${f.spread != null ? ` (most of it vs least of it: ${fmtGain(f.spread, skillUnit)} a year)` : ''}. Rows are the groups; cells are ${skillPts} gained per year.`}
          rows={[
            ...f.rows.map(r => ({ key: r.key, label: r.label, unit: skillUnit, group: groupLabel('Skills', skillUnit) })),
            ...(f.ovr ? f.ovr.rows.map(r => ({ key: `${OVR}:${r.key}`, label: r.label, unit: ovrUnit, group: 'Overall (display points)' })) : []),
          ]}
          source={f.source} shape="gap" rowHeader="Group" showKeys={false}
        />
      ))}

      {allCols.length > 0 && (
        <AgeTable
          title="Every rating: average change per year, by age"
          note="All players, whether or not they had room to grow. Potential ratings come down with age; fielding and running barely move."
          rows={[...rawRows, ...leftover]} source={raw} shape="raw"
        />
      )}
    </div>
  );
}

export default function TrendsPage({ league }) {
  const [trends, setTrends] = useState(undefined);
  useEffect(() => {
    setTrends(undefined);
    let on = true;
    loadRatingTrends(league).then(t => { if (on) setTrends(t); });
    return () => { on = false; };
  }, [league]);

  const windows = useMemo(() => Object.keys(trends?.movers || {}).map(Number).sort((a, b) => a - b), [trends]);
  const [win, setWin] = useState(null);
  useEffect(() => {
    if (windows.length && !windows.includes(win)) setWin(windows.includes(3) ? 3 : windows[windows.length - 1]);
  }, [windows]); // eslint-disable-line react-hooks/exhaustive-deps

  if (trends === undefined) {
    return (
      <div className="flex items-center justify-center h-full text-slate-400 gap-2">
        <Loader2 size={18} className="animate-spin" /> Loading rating trends…
      </div>
    );
  }
  if (!trends || !trends.pulls || trends.pulls.length < 2) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="text-center max-w-md text-slate-400 text-sm space-y-2">
          <p className="text-white font-bold">No rating history yet for {league}</p>
          <p>The trends board needs at least two archived ratings pulls. Run:</p>
          <code className="block text-xs text-blue-400 bg-slate-900 rounded p-2">
            python tgs-viz/backtest/ratings_db.py --backfill --export   (StatsPlus leagues)  or  Sim Dev League.bat  (dump leagues)
          </code>
        </div>
      </div>
    );
  }

  const mv = win != null ? trends.movers[String(win)] : null;
  const nPulls = trends.pulls.length;

  return (
    <div className="h-full overflow-auto p-5 space-y-4">
      <div className="flex items-end justify-between flex-wrap gap-2">
        <div>
          <h1 className="text-xl font-black text-white">Rating Trends — {league}</h1>
          <p className="text-xs text-slate-500 mt-0.5">
            {nPulls} archived ratings vintages (
            {trends.pulls[0].g && trends.pulls[nPulls - 1].g
              ? `in-game ${trends.pulls[0].g} → ${trends.pulls[nPulls - 1].g}`
              : `${trends.pulls[0].d} → ${trends.pulls[nPulls - 1].d}`}) ·
            informational only — projections always use the current pull
          </p>
        </div>
        {windows.length > 0 && (
          <label className="flex items-center gap-2 text-xs text-slate-400">
            Mover window
            <select
              value={win ?? ''}
              onChange={e => setWin(Number(e.target.value))}
              className="bg-slate-800 border border-slate-700 rounded px-2 py-1 text-white text-sm"
            >
              {windows.map(w => <option key={w} value={w}>last {w} pull{w > 1 ? 's' : ''}</option>)}
            </select>
          </label>
        )}
      </div>

      {mv && (
        <>
          <p className="text-xs text-slate-500">
            {mv.from} → {mv.to}: <span className="text-slate-300 font-semibold">{mv.changed.toLocaleString()}</span> players
            had at least one scouting-rating change. Total Δ = sum of all rating-point changes on the {ratingScale(trends.age_curves)} scale.
          </p>
          <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
            <MoverTable
              title="Top Risers" rows={mv.risers}
              icon={<TrendingUp size={15} className="text-green-400" />} accent="text-green-400"
            />
            <MoverTable
              title="Top Fallers" rows={mv.fallers}
              icon={<TrendingDown size={15} className="text-red-400" />} accent="text-red-400"
            />
          </div>
        </>
      )}

      <DevSummary ageCurves={trends.age_curves} />

      <details className="bg-slate-900/50 border border-slate-800 rounded-xl">
        <summary className="px-4 py-2.5 text-xs text-slate-400 cursor-pointer select-none">
          Old chart explorer (one rating at a time, split by a factor)
        </summary>
        <div className="p-2">
          <AgeCurveExplorer ageCurves={trends.age_curves} />
        </div>
      </details>
    </div>
  );
}
