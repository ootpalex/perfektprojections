import React, { useState, useEffect, useMemo } from 'react';
import {
  ComposedChart, Line, Scatter, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Legend,
} from 'recharts';

/**
 * Model vs actual, per rating rung.
 *
 * Every fitted layer already grades itself against the sim archive: at each
 * rating it stores how often the outcome ACTUALLY happened (emp) beside what the
 * model says and what the sheet's straight-line fit says. engine/export_calibration.py
 * ships those tables to public/data/<LG>/calibration.json; this only displays them.
 * Nothing here recomputes a projection.
 */
const pct = (v) => (v === null || v === undefined ? '—' : (v * 100).toFixed(1) + '%');
const num = (v) => (v === null || v === undefined ? '—' : Math.round(v).toLocaleString());

function Block({ b, showSheet }) {
  const data = useMemo(() => b.rows.map((x) => ({
    r: x.r,
    Actual: x.emp === null || x.emp === undefined ? null : x.emp * 100,
    Model: x.model === null || x.model === undefined ? null : x.model * 100,
    'Sheet only': x.sheet === null || x.sheet === undefined ? null : x.sheet * 100,
    n: x.n, w: x.w,
  })), [b]);

  // how far off each side is, weighted by how much data sits on the rung
  const err = useMemo(() => {
    let mw = 0, sw = 0, tot = 0;
    for (const x of b.rows) {
      const w = x.w || x.n || 1;
      if (x.emp === null || x.emp === undefined) continue;
      if (x.model !== null && x.model !== undefined) mw += w * Math.abs(x.model - x.emp);
      if (x.sheet !== null && x.sheet !== undefined) sw += w * Math.abs(x.sheet - x.emp);
      tot += w;
    }
    return tot ? { model: mw / tot, sheet: sw / tot } : null;
  }, [b]);

  const hasSheet = showSheet && b.rows.some((x) => x.sheet !== null && x.sheet !== undefined);

  // Where does the live engine actually depart from the sheet's own fit? For
  // hitters that is only the audited tail regions; for pitchers the S-curve
  // replaces the line everywhere. Stating it beats making the reader infer it.
  const departs = useMemo(() => {
    if (!hasSheet) return null;
    let same = 0; const at = [];
    for (const x of b.rows) {
      if (x.model === null || x.model === undefined || x.sheet === null || x.sheet === undefined) continue;
      if (Math.abs(x.model - x.sheet) < 1e-9) same += 1; else at.push(x.r);
    }
    if (!at.length) return { text: 'identical to the sheet at every rating', all: false };
    if (!same) return { text: 'replaces the sheet line across the whole range', all: true };
    return { text: 'same as the sheet except ratings ' + Math.min(...at) + '-' + Math.max(...at), all: false };
  }, [b, hasSheet]);

  return (
    <div className="bg-slate-800/50 rounded-lg p-4">
      <div className="flex items-baseline justify-between flex-wrap gap-2 mb-1">
        <h3 className="text-sm font-bold text-white">
          {b.label}
          {b.role && <span className="ml-2 text-xs font-semibold text-blue-400">{b.role}</span>}
        </h3>
        <span className="text-[11px] text-slate-500">by {b.rating} · {b.unit}</span>
      </div>
      {err && (
        <div className="text-[11px] mb-2">
          <span className="text-slate-500">average miss: </span>
          <span className="text-purple-300 font-mono">{(err.model * 100).toFixed(2)} pts model</span>
          {hasSheet && (
            <>
              <span className="text-slate-600"> vs </span>
              <span className="text-amber-300 font-mono">{(err.sheet * 100).toFixed(2)} pts sheet only</span>
              <span className={err.model <= err.sheet ? 'text-green-400 ml-2' : 'text-red-400 ml-2'}>
                {err.model <= err.sheet ? '✓ model closer' : '! sheet closer'}
              </span>
            </>
          )}
        </div>
      )}
      {departs && (
        <div className={departs.all ? 'text-[11px] mb-2 text-amber-300/80' : 'text-[11px] mb-2 text-slate-500'}>
          {departs.text}
        </div>
      )}

      <ResponsiveContainer width="100%" height={190}>
        <ComposedChart data={data} margin={{ top: 5, right: 8, bottom: 4, left: -18 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
          <XAxis dataKey="r" tick={{ fill: '#94a3b8', fontSize: 11 }} />
          <YAxis tick={{ fill: '#94a3b8', fontSize: 10 }} width={46}
                 tickFormatter={(v) => v.toFixed(0) + '%'} />
          <Tooltip
            contentStyle={{ background: '#1e293b', border: '1px solid #475569', borderRadius: 8 }}
            labelStyle={{ color: '#e2e8f0' }}
            labelFormatter={(v) => 'rating ' + v}
            formatter={(v, k) => [v === null || v === undefined ? '—' : v.toFixed(2) + '%', k]}
          />
          <Legend wrapperStyle={{ fontSize: 11 }} />
          {hasSheet && (
            <Line type="monotone" dataKey="Sheet only" stroke="#fbbf24" strokeWidth={1.5}
                  strokeDasharray="4 3" dot={false} connectNulls />
          )}
          <Line type="monotone" dataKey="Model" stroke="#a78bfa" strokeWidth={2}
                dot={{ r: 2 }} connectNulls />
          <Scatter dataKey="Actual" fill="#4ade80" shape="circle" />
        </ComposedChart>
      </ResponsiveContainer>

      <div className="overflow-x-auto mt-2">
        <table className="w-full text-[11px]">
          <thead>
            <tr className="text-slate-500 uppercase tracking-wide">
              <th className="text-left font-semibold py-1">Rating</th>
              <th className="text-right font-semibold">Players</th>
              <th className="text-right font-semibold">Sample</th>
              <th className="text-right font-semibold text-green-400">Actual</th>
              <th className="text-right font-semibold text-purple-300">Model</th>
              {hasSheet && <th className="text-right font-semibold text-amber-300">Sheet only</th>}
              <th className="text-right font-semibold">Miss</th>
            </tr>
          </thead>
          <tbody className="font-mono">
            {b.rows.map((x) => {
              const ok = x.emp !== null && x.emp !== undefined
                && x.model !== null && x.model !== undefined;
              const miss = ok ? (x.model - x.emp) * 100 : null;
              return (
                <tr key={x.r} className="border-t border-slate-700/40">
                  <td className="py-[3px] text-slate-300">{x.r}</td>
                  <td className="text-right text-slate-500">{x.n === null || x.n === undefined ? '—' : x.n}</td>
                  <td className="text-right text-slate-500">{num(x.w)}</td>
                  <td className="text-right text-green-400">{pct(x.emp)}</td>
                  <td className="text-right text-purple-300">{pct(x.model)}</td>
                  {hasSheet && <td className="text-right text-amber-300">{pct(x.sheet)}</td>}
                  <td className={
                    miss === null ? 'text-right text-slate-600'
                      : Math.abs(miss) < 0.5 ? 'text-right text-slate-400'
                      : Math.abs(miss) < 1.5 ? 'text-right text-yellow-400' : 'text-right text-red-400'}>
                    {miss === null ? '—' : (miss > 0 ? '+' : '') + miss.toFixed(2)}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export default function CalibrationPage({ league }) {
  const [cal, setCal] = useState(undefined);   // undefined = loading, null = absent
  const [tab, setTab] = useState('hitters');

  useEffect(() => {
    let on = true;
    setCal(undefined);
    fetch('/data/' + league + '/calibration.json')
      .then((res) => {
        const ct = res.headers.get('content-type') || '';
        if (!res.ok || ct.includes('text/html')) throw new Error('absent');
        return res.json();
      })
      .then((j) => { if (on) setCal(j); })
      .catch(() => { if (on) setCal(null); });
    return () => { on = false; };
  }, [league]);

  if (cal === undefined) {
    return <div className="p-6 text-slate-400">Loading calibration…</div>;
  }
  if (cal === null) {
    return (
      <div className="p-6 text-slate-400 max-w-2xl">
        <h1 className="text-2xl font-bold text-white mb-2">Model vs Actual</h1>
        <p className="text-sm">
          No calibration file for {league}. Run{' '}
          <code className="bg-slate-800 px-1.5 py-0.5 rounded text-slate-300">
            python tgs-viz/engine/export_calibration.py --league {league} --write
          </code>{' '}
          — a recalibration does it automatically.
        </p>
      </div>
    );
  }

  const tabs = [
    ['hitters', 'Hitting (' + cal.hitters.length + ')'],
    ['pitchers', 'Pitching (' + cal.pitchers.length + ')'],
    ['ladder', 'Live season (' + cal.ladder.length + ')'],
  ].filter(([k]) => (cal[k] || []).length);

  const blocks = cal[tab] || [];

  return (
    <div className="h-full overflow-auto">
      <div className="p-4 pb-2">
        <h1 className="text-2xl font-bold text-white">Model vs Actual</h1>
        <p className="text-sm text-slate-400 mt-1 max-w-3xl">
          At each rating, what the sims actually produced (<span className="text-green-400">green dots</span>)
          against what the projections say (<span className="text-purple-300">purple</span>)
          {tab !== 'ladder' && <> and what the sheet&apos;s own fit alone would say (<span className="text-amber-300">amber</span>)</>}.
          {tab === 'hitters' && ' The two are the SAME except in the tail regions the sims proved the straight line was missing.'}
          {tab === 'pitchers' && ' Here the fitted S-curve replaces the two straight lines across the whole range.'}
          {tab === 'ladder'
            ? ' Measured on the LIVE season, out of sample — the honest test.'
            : ' Measured on the calibration archive.'}
        </p>
        <p className="text-[11px] text-slate-600 mt-1">{cal.league} · built {cal.built_at}</p>

        <div className="flex gap-1 mt-3">
          {tabs.map(([k, lab]) => (
            <button key={k} onClick={() => setTab(k)}
              className={tab === k
                ? 'px-3 py-1.5 text-xs font-semibold rounded-lg bg-blue-600 text-white'
                : 'px-3 py-1.5 text-xs font-semibold rounded-lg bg-slate-800 text-slate-400 hover:text-slate-200'}>
              {lab}
            </button>
          ))}
        </div>
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-2 gap-4 p-4 pt-2">
        {blocks.map((b, i) => (
          <Block key={(b.role || '') + (b.block || b.label) + i} b={b} showSheet={tab !== 'ladder'} />
        ))}
      </div>
    </div>
  );
}
