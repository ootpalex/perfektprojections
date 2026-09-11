import React, { useState, useEffect, useMemo } from 'react';
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Cell, ReferenceLine } from 'recharts';
import { loadRatingTrends } from '../lib/ratingTrends';
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
  const [minN, setMinN] = useState(50);
  const [split, setSplit] = useState('none'); // none | WE | INT | LEA
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
    return Object.entries(colSource[col])
      .map(([age, v]) => effMode === 'gap'
        ? { age: Number(age), mean: v[0], n: v[2], years: v[3] }
        : { age: Number(age), mean: v[0], n: v[1], years: v[2] })
      .filter(d => d.n >= minN && d.age >= 15 && d.age <= 45)
      .sort((a, b) => a.age - b.age);
  }, [colSource, col, minN, effMode]);

  const splitData = useMemo(() => {
    if (split === 'none' || !hasTraits || !col) return [];
    const t = ageCurves.traits[split] || {};
    const ages = new Set();
    ['H', 'N', 'L'].forEach(b => Object.keys(t[b]?.[col] || {}).forEach(a => ages.add(Number(a))));
    return [...ages].sort((a, b) => a - b).map(a => {
      const row = { age: a };
      ['H', 'N', 'L'].forEach(b => {
        const e = t[b]?.[col]?.[String(a)];
        if (e && e[2] >= minN) { row[b] = e[0]; row[b + '_n'] = e[2]; }
      });
      return row;
    }).filter(r => r.H !== undefined || r.N !== undefined || r.L !== undefined);
  }, [ageCurves, split, col, minN, hasTraits]);

  if (!cols.length) return null;
  const TRAIT_LABEL = { WE: 'Work Ethic', INT: 'Intelligence', LEA: 'Leadership' };
  return (
    <div className="bg-slate-900 border border-slate-800 rounded-xl p-4">
      <div className="flex items-center justify-between flex-wrap gap-2 mb-2">
        <h3 className="text-sm font-bold text-slate-200">
          {effMode === 'gap' ? 'Growth Toward Potential (gap holders only)' : 'Average Gain per Year of Age'}
        </h3>
        <div className="flex items-center gap-3 text-xs text-slate-400">
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
          {hasTraits && (
            <label className="flex items-center gap-1.5">
              Split by
              <select
                value={split}
                onChange={e => setSplit(e.target.value)}
                className="bg-slate-800 border border-slate-700 rounded px-2 py-1 text-white"
              >
                <option value="none">—</option>
                <option value="WE">Work Ethic</option>
                <option value="INT">Intelligence</option>
                <option value="LEA">Leadership</option>
              </select>
            </label>
          )}
          <label className="flex items-center gap-1.5">
            Min sample
            <input
              type="number" min={1} step={25} value={minN}
              onChange={e => setMinN(Math.max(1, parseInt(e.target.value) || 1))}
              className="w-16 bg-slate-800 border border-slate-700 rounded px-2 py-1 text-white"
            />
          </label>
        </div>
      </div>
      <ResponsiveContainer width="100%" height={240}>
        {split === 'none' ? (
          <BarChart data={data}>
            <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
            <XAxis dataKey="age" tick={{ fill: '#94a3b8', fontSize: 11 }} />
            <YAxis tick={{ fill: '#94a3b8', fontSize: 10 }} tickFormatter={v => v.toFixed(2)} />
            <ReferenceLine y={0} stroke="#64748b" />
            <Tooltip
              contentStyle={{ background: '#1e293b', border: '1px solid #475569', borderRadius: 8 }}
              labelStyle={{ color: '#e2e8f0' }}
              formatter={(v, _name, item) => [
                effMode === 'gap'
                  ? `${v > 0 ? '+' : ''}${v.toFixed(2)} pts/yr toward potential (n=${item?.payload?.n}`
                    + (item?.payload?.years != null ? `, ${item.payload.years.toFixed(0)} player-yrs)` : ')')
                  : `${v > 0 ? '+' : ''}${v.toFixed(2)} per year of age (n=${item?.payload?.n}`
                    + (item?.payload?.years != null ? `, ${item.payload.years.toFixed(0)} player-yrs)` : ')'), col]}
              labelFormatter={age => `Age ${age}`}
            />
            <Bar dataKey="mean" radius={[3, 3, 0, 0]}>
              {data.map((d, i) => <Cell key={i} fill={d.mean >= 0 ? '#3b82f6' : '#ef4444'} />)}
            </Bar>
          </BarChart>
        ) : (
          <BarChart data={splitData}>
            <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
            <XAxis dataKey="age" tick={{ fill: '#94a3b8', fontSize: 11 }} />
            <YAxis tick={{ fill: '#94a3b8', fontSize: 10 }} tickFormatter={v => v.toFixed(2)} />
            <ReferenceLine y={0} stroke="#64748b" />
            <Tooltip
              contentStyle={{ background: '#1e293b', border: '1px solid #475569', borderRadius: 8 }}
              labelStyle={{ color: '#e2e8f0' }}
              formatter={(v, name, item) => [
                `${v > 0 ? '+' : ''}${v.toFixed(2)} pts/yr (n=${item?.payload?.[name + '_n'] ?? '?'})`,
                `${TRAIT_LABEL[split]} ${name}`]}
              labelFormatter={age => `Age ${age}`}
            />
            <Bar dataKey="H" name="H" fill="#22c55e" radius={[3, 3, 0, 0]} />
            <Bar dataKey="N" name="N" fill="#64748b" radius={[3, 3, 0, 0]} />
            <Bar dataKey="L" name="L" fill="#f97316" radius={[3, 3, 0, 0]} />
          </BarChart>
        )}
      </ResponsiveContainer>
      {split !== 'none' && (
        <div className="flex gap-4 justify-center text-[11px] mt-1">
          <span className="text-green-400">High {TRAIT_LABEL[split]}</span>
          <span className="text-slate-400">Normal</span>
          <span className="text-orange-400">Low</span>
          <span className="text-slate-500">(ages 15–25)</span>
        </div>
      )}
      <div className="flex items-start gap-2 mt-2 text-[11px] text-slate-500">
        <Info size={13} className="shrink-0 mt-0.5" />
        <p>
          {effMode === 'gap'
            ? 'Only players whose CURRENT sat below their POTENTIAL for this rating at each interval — maxed players never dilute the growth of players with room. Bars = rating POINTS gained per year of age; the gap is re-read every pull pair, so re-scouts and caught-up ratings switch tracking automatically. Bars past ~29 are scout alignment on veterans, not development.'
            : ageCurves.note}
        </p>
      </div>
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
            python tgs-viz/backtest/ratings_db.py --backfill --export
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
            {nPulls} archived ratings vintages ({trends.pulls[0].d} → {trends.pulls[nPulls - 1].d}) ·
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
            had at least one scouting-rating change. Total Δ = sum of all 20–80 rating-point changes.
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

      <AgeCurveExplorer ageCurves={trends.age_curves} />
    </div>
  );
}
