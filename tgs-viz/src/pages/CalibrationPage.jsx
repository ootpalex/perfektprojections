import React, { useState, useEffect, useMemo, useRef } from 'react';
import { useDataVersion } from '../lib/dataVersion';
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
  // Each run of departing ratings is its own range: a block with a low and a
  // high tail (extra-base hits: 20-35 and 70-80) must not read as one 20-80
  // range when the middle matches the sheet. A matching rating ends a run;
  // a rating with no model or sheet value is skipped.
  const departs = useMemo(() => {
    if (!hasSheet) return null;
    let same = 0; const runs = []; let run = null;
    const rows = [...b.rows].sort((p, q) => Number(p.r) - Number(q.r));
    for (const x of rows) {
      if (x.model === null || x.model === undefined || x.sheet === null || x.sheet === undefined) continue;
      if (Math.abs(x.model - x.sheet) < 1e-9) { same += 1; run = null; continue; }
      if (run) run[1] = x.r; else { run = [x.r, x.r]; runs.push(run); }
    }
    if (!runs.length) return { text: 'identical to the sheet at every rating', all: false };
    if (!same) return { text: 'replaces the sheet line across the whole range', all: true };
    const parts = runs.map(([lo, hi]) => (lo === hi ? String(lo) : lo + '-' + hi));
    const list = parts.length > 1 ? parts.slice(0, -1).join(', ') + ' and ' + parts[parts.length - 1] : parts[0];
    return { text: 'same as the sheet except ratings ' + list, all: false };
  }, [b, hasSheet]);

  return (
    <div className="ns-card">
      <div className="ns-strip flex items-baseline justify-between flex-wrap gap-2">
        <h3>
          {b.label}
          {b.role && <span className={`ml-2 text-xs ns-pos ns-pos-${b.role.toLowerCase()}`}>{b.role}</span>}
        </h3>
        <span className="text-[11px] ns-muted">by {b.rating} · {b.unit}</span>
      </div>
      {err && (
        <div className="text-[11px] mb-2">
          <span className="ns-muted">average miss: </span>
          <span style={{ color: 'var(--chart-series-5)' }}>{(err.model * 100).toFixed(2)} pts model</span>
          {hasSheet && (
            <>
              <span className="ns-muted"> vs </span>
              <span style={{ color: 'var(--chart-series-4)' }}>{(err.sheet * 100).toFixed(2)} pts sheet only</span>
              <span className={err.model <= err.sheet ? 'ns-good ml-2' : 'ns-bad ml-2'}>
                {err.model <= err.sheet ? '✓ model closer' : '! sheet closer'}
              </span>
            </>
          )}
        </div>
      )}
      {departs && (
        <div className={departs.all ? 'text-[11px] mb-2 ns-warn' : 'text-[11px] mb-2 ns-muted'}>
          {departs.text}
        </div>
      )}

      <ResponsiveContainer width="100%" height={190}>
        <ComposedChart data={data} margin={{ top: 5, right: 8, bottom: 4, left: -18 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="var(--chart-grid)" />
          <XAxis dataKey="r" tick={{ fill: 'var(--chart-axis)', fontSize: 11 }} />
          <YAxis tick={{ fill: 'var(--chart-axis)', fontSize: 11 }} width={46}
                 tickFormatter={(v) => v.toFixed(0) + '%'} />
          <Tooltip
            contentStyle={{ background: 'var(--chart-tooltip-bg)', border: '1px solid var(--chart-tooltip-border)', borderRadius: 3 }}
            labelStyle={{ color: 'var(--chart-tooltip-text)' }}
            labelFormatter={(v) => 'rating ' + v}
            formatter={(v, k) => [v === null || v === undefined ? '—' : v.toFixed(2) + '%', k]}
          />
          <Legend wrapperStyle={{ fontSize: 11 }} />
          {hasSheet && (
            <Line type="monotone" dataKey="Sheet only" stroke="var(--chart-series-4)" strokeWidth={1.5}
                  strokeDasharray="4 3" dot={false} connectNulls />
          )}
          <Line type="monotone" dataKey="Model" stroke="var(--chart-series-5)" strokeWidth={2}
                dot={{ r: 2 }} connectNulls />
          <Scatter dataKey="Actual" fill="var(--chart-series-2)" shape="circle" />
        </ComposedChart>
      </ResponsiveContainer>

      <div className="overflow-x-auto mt-2">
        <table className="w-full text-[11px]">
          <thead>
            <tr className="ns-muted">
              <th className="text-left font-semibold py-1">Rating</th>
              <th className="text-right font-semibold">Players</th>
              <th className="text-right font-semibold">Sample</th>
              <th className="text-right font-semibold" style={{ color: 'var(--chart-series-2)' }}>Actual</th>
              <th className="text-right font-semibold" style={{ color: 'var(--chart-series-5)' }}>Model</th>
              {hasSheet && <th className="text-right font-semibold" style={{ color: 'var(--chart-series-4)' }}>Sheet only</th>}
              <th className="text-right font-semibold">Miss</th>
            </tr>
          </thead>
          <tbody className="">
            {b.rows.map((x) => {
              const ok = x.emp !== null && x.emp !== undefined
                && x.model !== null && x.model !== undefined;
              const miss = ok ? (x.model - x.emp) * 100 : null;
              return (
                <tr key={x.r} className="border-t border-[var(--line)]">
                  <td className="py-[3px] ns-text">{x.r}</td>
                  <td className="text-right ns-muted">{x.n === null || x.n === undefined ? '—' : x.n}</td>
                  <td className="text-right ns-muted">{num(x.w)}</td>
                  <td className="text-right" style={{ color: 'var(--chart-series-2)' }}>{pct(x.emp)}</td>
                  <td className="text-right" style={{ color: 'var(--chart-series-5)' }}>{pct(x.model)}</td>
                  {hasSheet && <td className="text-right" style={{ color: 'var(--chart-series-4)' }}>{pct(x.sheet)}</td>}
                  <td className={
                    miss === null ? 'text-right ns-muted'
                      : Math.abs(miss) < 0.5 ? 'text-right ns-text-2'
                      : Math.abs(miss) < 1.5 ? 'text-right ns-warn' : 'text-right ns-bad'}>
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
  // Live refresh: the file loads again when it changes. Only a league change
  // shows the loading line, and a reload that fails keeps the table on screen.
  const version = useDataVersion(league, 'calibration');
  const shownLeague = useRef(null);

  useEffect(() => {
    let on = true;
    const refresh = shownLeague.current === league;
    shownLeague.current = league;
    if (!refresh) setCal(undefined);
    fetch('/data/' + league + '/calibration.json')
      .then((res) => {
        const ct = res.headers.get('content-type') || '';
        if (!res.ok || ct.includes('text/html')) throw new Error('absent');
        return res.json();
      })
      .then((j) => { if (on) setCal(j); })
      .catch(() => { if (on) setCal(prev => (refresh && prev ? prev : null)); });
    return () => { on = false; };
  }, [league, version]);

  if (cal === undefined) {
    return <div className="p-6 ns-text-2">Loading calibration…</div>;
  }
  if (cal === null) {
    return (
      <div className="p-6 ns-text-2 max-w-2xl">
        <h1 className="text-2xl font-extrabold ns-text mb-2">Model vs Actual</h1>
        <p className="text-sm">
          No calibration file for {league}. Run{' '}
          <code className="bg-[var(--bg)] border border-[var(--line)] px-1.5 py-0.5 ns-text">
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
    <div className="ns-page overflow-auto [&>*]:shrink-0">
      <header className="ns-page-head">
        <div>
        <h1>Model vs Actual</h1>
        <p className="ns-page-sub max-w-3xl">
          At each rating, what the sims actually produced (<span style={{ color: 'var(--chart-series-2)' }}>green dots</span>)
          against what the projections say (<span style={{ color: 'var(--chart-series-5)' }}>purple</span>)
          {tab !== 'ladder' && <> and what the sheet&apos;s own fit alone would say (<span style={{ color: 'var(--chart-series-4)' }}>amber</span>)</>}.
          {tab === 'hitters' && ' The two are the SAME except in the tail regions the sims proved the straight line was missing.'}
          {tab === 'pitchers' && ' Each block shown runs on its fitted S-curve. In BLM, a block that did not beat the two lines on the live season stays on them, moved to the league\'s level, and is not shown.'}
          {tab === 'ladder'
            ? ' Measured on the LIVE season, out of sample — the honest test.'
            : ' Measured on the calibration archive.'}
        </p>
        <p className="text-[11px] ns-muted mt-1">{cal.league} · built {cal.built_at}</p>
        </div>
      </header>

      <div className="flex gap-1 mb-4">
        {tabs.map(([k, lab]) => (
          <button key={k} type="button" onClick={() => setTab(k)} aria-pressed={tab === k} className="ns-btn ns-btn-sm">
            {lab}
          </button>
        ))}
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
        {blocks.map((b, i) => (
          <Block key={(b.role || '') + (b.block || b.label) + i} b={b} showSheet={tab !== 'ladder'} />
        ))}
      </div>
    </div>
  );
}
