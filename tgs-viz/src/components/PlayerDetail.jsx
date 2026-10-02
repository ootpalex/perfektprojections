import React, { useMemo, useState, useEffect } from 'react';
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, BarChart, Bar, Cell } from 'recharts';
import { calculateFutureValue } from '../lib/futureValue';
import { controlWindow, formatControl } from '../lib/serviceTime';
import { formatCellValue, getCellColorClass } from '../lib/columns';
import { loadRatingTrends, playerHistory } from '../lib/ratingTrends';
import { loadAgeCurve } from '../lib/ageCurve';
import { useDataVersion } from '../lib/dataVersion';
import { devSummary, devPeakText, devBasisText, devIsMl, devMlWords, fmtWaa } from '../lib/devSignals';
import { getWorkEthicModifier, getIntelligenceModifier } from '../lib/draftFV';
import { trainingNotes, TRAIN_PEAK_BAR } from '../lib/orgBuilder';
import { X } from 'lucide-react';

/**
 * One line of dev signals for a player aged 16-26 (lib/devSignals.js), the
 * Exp peak sentence when the row has one, and the basis in small print.
 * MLB %, Starter % and Star % (the chance his peak reaches -1 / 0 / +1.5 WAA
 * from where he is now: from the ML model, else the share of his DEV
 * lookalikes at a similar current whose gain covered the distance; 100%
 * "already there" when his current sits at the bar; user, 2026-09-24) sit
 * in devSummary in that order ("MLB x%" first: the chance he is ever
 * anything in the majors, user, 2026-09-24). Make it % left the card with
 * its list column (user, 2026-09-26): it is playing time, not quality.
 * Renders nothing for a row without an entry.
 */
function DevSignalsLine({ player }) {
  if (!player || !player.Dev_Role) return null;
  const flag = player.Dev_Flag;
  const peak = devPeakText(player);
  return (
    <div className="border-t border-slate-700/50 mt-1 pt-1">
      <div className="flex justify-between items-start gap-2 py-0.5">
        <span className="text-xs text-slate-300">
          <span className="text-slate-500">Dev signals: </span>{devSummary(player)}
        </span>
        {flag && (
          <span className={`text-xs font-bold shrink-0 ${flag === 'keep' ? 'text-green-400' : 'text-red-400'}`}>
            {flag.toUpperCase()}
          </span>
        )}
      </div>
      {peak && (
        <div className="text-xs text-slate-300 py-0.5">
          <span className="text-slate-500">Exp peak: </span>{peak}
        </div>
      )}
      <div className="text-[10px] text-slate-600">{devBasisText(player)}</div>
    </div>
  );
}

/**
 * OOTP-style 20-80 rating chip. The whole point is legibility: a big number in
 * a bucket color you can read across the room, like the game's own star scale.
 */
function ratingClass(v) {
  if (v === null || v === undefined || isNaN(v)) return 'bg-slate-800 text-slate-600';
  if (v >= 75) return 'bg-sky-500/25 text-sky-300';
  if (v >= 65) return 'bg-emerald-500/25 text-emerald-300';
  if (v >= 55) return 'bg-lime-500/20 text-lime-300';
  if (v >= 45) return 'bg-yellow-500/15 text-yellow-200';
  if (v >= 40) return 'bg-amber-600/25 text-amber-300';
  if (v >= 30) return 'bg-orange-600/25 text-orange-300';
  return 'bg-red-600/25 text-red-300';
}

function RChip({ value, dim }) {
  const v = parseFloat(value);
  const has = !isNaN(v);
  return (
    <span className={`inline-flex items-center justify-center w-9 h-7 rounded-md text-sm font-bold tabular-nums ${
      has ? ratingClass(v) : 'bg-slate-800/60 text-slate-600'
    } ${dim ? 'opacity-70' : ''}`}>
      {has ? Math.round(v) : '–'}
    </span>
  );
}

/** Ratings table: label | vR | vL | Pot — every cell a colored 20-80 chip. */
function RatingsTable({ rows, player }) {
  return (
    <table className="w-full border-separate" style={{ borderSpacing: '0 3px' }}>
      <thead>
        <tr className="text-[10px] text-slate-500 uppercase tracking-wider">
          <th className="text-left font-semibold"> </th>
          <th className="font-semibold w-10">vR</th>
          <th className="font-semibold w-10">vL</th>
          <th className="font-semibold w-10">Pot</th>
        </tr>
      </thead>
      <tbody>
        {rows.map(([label, vr, vl, pot]) => (
          <tr key={label}>
            <td className="text-xs text-slate-400 pr-1">{label}</td>
            <td className="text-center"><RChip value={player[vr]} /></td>
            <td className="text-center"><RChip value={player[vl]} /></td>
            <td className="text-center"><RChip value={player[pot]} /></td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

/** Ratings without splits (speed, stamina, fielding...): the same aligned
 * label-left / value-right rows the rest of the panel uses, chip-valued. */
function ChipRow({ items, player, cols = 2 }) {
  return (
    <div className={`grid ${cols === 1 ? 'grid-cols-1' : 'grid-cols-2'} gap-x-5`}>
      {items.map(([label, key]) => (
        <div key={label} className="flex items-center justify-between py-[3px]">
          <span className="text-xs text-slate-400">{label}</span>
          <RChip value={player[key]} />
        </div>
      ))}
    </div>
  );
}

// OOTP pitch codes -> names; potential is the same code + 'P'.
const PITCHES = [
  ['FB', 'Fastball'], ['SI', 'Sinker'], ['CT', 'Cutter'], ['SL', 'Slider'],
  ['CB', 'Curveball'], ['CH', 'Changeup'], ['SP', 'Splitter'], ['FO', 'Forkball'],
  ['CC', 'Circle Ch.'], ['SC', 'Screwball'], ['KC', 'Knuckle Cu.'], ['KN', 'Knuckleball'],
];

function PitchRepertoire({ player }) {
  const owned = PITCHES
    .map(([code, name]) => ({ code, name, cur: parseFloat(player[code]), pot: parseFloat(player[code + 'P']) }))
    .filter(p => !isNaN(p.cur) && p.cur > 0);
  if (!owned.length) return null;
  owned.sort((a, b) => b.cur - a.cur);
  return (
    <div>
      <h4 className="text-[10px] text-slate-500 uppercase tracking-wider mb-1.5 mt-3">
        Pitches ({owned.length})
      </h4>
      <div className="space-y-1">
        {owned.map(p => (
          <div key={p.code} className="flex items-center gap-2">
            <span className="text-xs text-slate-400 w-20">{p.name}</span>
            <RChip value={p.cur} />
            {!isNaN(p.pot) && p.pot > p.cur ? (
              <>
                <span className="text-slate-600 text-xs">→</span>
                <RChip value={p.pot} dim />
              </>
            ) : null}
          </div>
        ))}
      </div>
    </div>
  );
}

/** Tiny inline sparkline for a rating series (nulls = missing pulls, skipped). */
function Sparkline({ values, delta }) {
  const pts = values
    .map((v, i) => (v === null || v === undefined ? null : [i, v]))
    .filter(Boolean);
  if (pts.length < 2) return <span className="w-[72px] inline-block" />;
  const xs = pts.map(p => p[0]), ys = pts.map(p => p[1]);
  const minX = Math.min(...xs), maxX = Math.max(...xs);
  const minY = Math.min(...ys), maxY = Math.max(...ys);
  const W = 72, H = 18, PAD = 2;
  const sx = x => PAD + (maxX === minX ? 0.5 : (x - minX) / (maxX - minX)) * (W - 2 * PAD);
  const sy = y => H - PAD - (maxY === minY ? 0.5 : (y - minY) / (maxY - minY)) * (H - 2 * PAD);
  const color = delta > 0 ? '#4ade80' : delta < 0 ? '#f87171' : '#64748b';
  return (
    <svg width={W} height={H} className="shrink-0">
      <polyline
        points={pts.map(([x, y]) => `${sx(x).toFixed(1)},${sy(y).toFixed(1)}`).join(' ')}
        fill="none" stroke={color} strokeWidth="1.5"
      />
      {pts.map(([x, y], i) => (
        <circle key={i} cx={sx(x)} cy={sy(y)} r="1.6" fill={color} />
      ))}
    </svg>
  );
}

/**
 * Compact per-rating history from the ratings-history DB export (the Rating
 * Trends file). Shows only ratings that CHANGED across the archived pulls in
 * the window. Nothing here feeds a projection: projections price the current
 * ratings as they are, and the dev numbers read last year's growth from the
 * same archive upstream (backtest/dev_signals.py, backtest/ml/dataset.py).
 */
function RatingHistory({ player }) {
  const [trends, setTrends] = useState(undefined); // undefined=loading, null=unavailable
  // Live refresh: loads again when the league's trends file changes.
  const trendsVersion = useDataVersion(player._appLeague || null, 'trends');
  useEffect(() => {
    let on = true;
    loadRatingTrends(player._appLeague).then(t => { if (on) setTrends(prev => (t == null && prev ? prev : t)); });
    return () => { on = false; };
  }, [player._appLeague, trendsVersion]);

  if (trends === undefined) return null;           // still loading — stay quiet
  if (trends === null) return null;                // no trends file — feature hidden
  const hist = playerHistory(trends, player.ID);
  if (!hist) return null;
  const { dates, rows, vintages } = hist;
  const shown = rows.slice(0, 12);
  const range = dates.length ? `${dates[0]} → ${dates[dates.length - 1]}` : '';

  return (
    <div className="bg-slate-800/50 rounded-lg p-3">
      <h3 className="text-xs font-semibold text-slate-400 uppercase mb-1">Rating History</h3>
      <div className="text-[10px] text-slate-500 mb-2">
        {range} · {vintages} archived pulls. Projections price the current ratings as they are; last year's growth from this archive feeds the dev numbers.
      </div>
      {rows.length === 0 ? (
        <div className="text-xs text-slate-500">No rating changes across the last {dates.length} pulls.</div>
      ) : (
        <>
          {shown.map(r => (
            <div key={r.col} className="flex items-center justify-between gap-2 py-0.5">
              <span className="text-slate-500 text-xs w-16 shrink-0">{r.col}</span>
              <Sparkline values={r.values} delta={r.delta} />
              <span className="text-xs font-mono text-slate-300 w-16 text-right">
                {r.first} → {r.last}
              </span>
              <span className={`text-xs font-mono w-9 text-right ${
                r.delta > 0 ? 'text-green-400' : r.delta < 0 ? 'text-red-400' : 'text-slate-500'
              }`}>
                {r.delta > 0 ? '+' : ''}{Math.round(r.delta * 10) / 10}
              </span>
            </div>
          ))}
          {rows.length > shown.length && (
            <div className="text-[10px] text-slate-600 mt-1">
              +{rows.length - shown.length} more changed ratings
            </div>
          )}
        </>
      )}
    </div>
  );
}

/**
 * A Draft FV personality modifier (draftFV.js getWorkEthicModifier /
 * getIntelligenceModifier: 1.015 / 1.0 / 0.985) as "+1.5%" / "-1.5%", or ''
 * when it leaves Draft FV even.
 */
function draftStep(mod) {
  const v = Math.round((mod - 1) * 1000) / 10;
  return v > 0 ? `+${v}%` : v < 0 ? `${v}%` : '';
}
const stepClass = (s) => (!s ? 'text-slate-600' : s.startsWith('+') ? 'text-green-400' : 'text-red-400');

/**
 * Training positions for a hitter (user, 2026-09-24: "notate the positions
 * they lack training by each of the prospects to work as a reminder"): every
 * position where he is 0 WAA or better if he reaches his potential but has
 * not mastered (position rating current/potential, 0 = never trained), best
 * first. The rule and the math are orgBuilder.trainingNotes. Hover a
 * position for his WAA there at his potential. Renders nothing when there
 * is none.
 */
function TrainingLine({ player }) {
  const notes = useMemo(() => trainingNotes(player), [player]);
  if (!notes.length) return null;
  const signed = (v) => (v >= 0 ? '+' : '') + v.toFixed(1);
  return (
    <div className="border-t border-slate-700/50 mt-1 pt-1 py-0.5 text-xs text-slate-300">
      <span className="text-slate-500">Training: </span>
      {notes.map((n, i) => (
        <span key={n.pos} title={`at his potential, ${n.pos}: ${signed(n.peak)} WAA${n.untrained ? '; never trained there, his tools carry it' : ''}`}>{i > 0 ? ', ' : ''}{n.pos} {n.untrained ? 'new' : `${n.cur}/${n.pot}`}</span>
      ))}
      <span className="text-slate-500"> ({TRAIN_PEAK_BAR} WAA or better there at his potential)</span>
    </div>
  );
}

export default function PlayerDetail({ player, onClose, type = 'hitter' }) {
  if (!player) return null;

  // FV counts the seasons this club still holds, not a flat six (serviceTime).
  const control = useMemo(() => controlWindow(player), [player]);

  // Measured league dev curve (null until loaded / absent for the league)
  const [ageCurve, setAgeCurve] = useState(null);
  // Live refresh: loads again when DEV's curve or the league's own curve changes.
  const curveVersion = useDataVersion(player._appLeague || null, 'age_curve');
  useEffect(() => {
    let on = true;
    loadAgeCurve(player._appLeague).then(c => { if (on) setAgeCurve(prev => c ?? prev); });
    return () => { on = false; };
  }, [player._appLeague, curveVersion]);

  // valueYears: control is what you keep, valueYears is what is worth counting (a free
  // agent controls 0 seasons but is not worth 0). See serviceTime.controlWindow.
  // The measured DEV curve and the row's DEV cell gain make this the same
  // year-by-year path model the lists run (usePlayersWithFV), so the card's
  // numbers match the boards. Until the curve loads the assumed model shows.
  const fv = useMemo(
    () => calculateFutureValue(player, control.valueYears, { ageCurve, devGain: player.Dev_PeakGainP50 }),
    [player, control, ageCurve],
  );

  // Development curve data: the projected path to age 40 on the measured DEV
  // curve (fv.fullPath), or the assumed model's window when there is no curve.
  // Display-WAA basis (y.waa), never y.rawWAA (the internal WAR/market track).
  const devCurve = useMemo(() => {
    if (fv.fullPath) return fv.fullPath.map(x => ({ age: x.age, WAA: x.waa }));
    return fv.yearByYear.map(y => ({ age: y.age, WAA: y.waa ?? y.rawWAA }));
  }, [fv]);

  // "Next season" line: the change from today to next year's projected WAA.
  // ML rows (2026-09-25): the ML model's median change for next season and
  // its 25th to 75th percentile range (Dev_MlD[0], Dev_MlD1Lo / Hi). The
  // ML path models learn only from players who stayed in the league, so the
  // line reads "if he keeps playing"; the peak numbers (Proj Potential)
  // count the washouts. For ages 26 and under the display path (chart, Year
  // by year) is smoothed (no dip before 28) and capped at Proj Potential, so
  // its year 1 can differ from this median (checker: 585 TGS rows sat below
  // it).
  const nextSeason = useMemo(() => {
    const p = fv.fullPath;
    if (!p || p.length < 2) return null;
    const out = { age: p[1].age, delta: Math.round((p[1].waa - p[0].waa) * 10) / 10, waa: p[1].waa };
    const d1 = Array.isArray(player.Dev_MlD) ? player.Dev_MlD[0] : null;
    if (fv.targetSource === 'ml' && Number.isFinite(d1)) {
      out.delta = Math.round(d1 * 10) / 10;
      out.ml = true;
      out.lo = Number.isFinite(player.Dev_MlD1Lo) ? player.Dev_MlD1Lo : null;
      out.hi = Number.isFinite(player.Dev_MlD1Hi) ? player.Dev_MlD1Hi : null;
    }
    return out;
  }, [fv, player]);

  // Position WAA bar chart (hitters only)
  const posWAAData = type === 'hitter' ? [
    { pos: 'C', waa: parseFloat(player['C WAA wtd']) || 0 },
    { pos: '1B', waa: parseFloat(player['1B WAA wtd']) || 0 },
    { pos: '2B', waa: parseFloat(player['2B WAA wtd']) || 0 },
    { pos: '3B', waa: parseFloat(player['3B WAA wtd']) || 0 },
    { pos: 'SS', waa: parseFloat(player['SS WAA wtd']) || 0 },
    { pos: 'LF', waa: parseFloat(player['LF WAA wtd']) || 0 },
    { pos: 'CF', waa: parseFloat(player['CF WAA wtd']) || 0 },
    { pos: 'RF', waa: parseFloat(player['RF WAA wtd']) || 0 },
    { pos: 'DH', waa: parseFloat(player['DH WAA wtd']) || 0 },
  ].filter(d => d.waa !== 0) : [];

  // Work ethic and intelligence move Draft FV by the same step each.
  const weStep = draftStep(getWorkEthicModifier(player.WrkEthic));
  const intStep = draftStep(getIntelligenceModifier(player.Int));

  const statLine = (label, value, colorCol) => {
    const display = formatCellValue(value, colorCol || label);
    const colorClass = getCellColorClass(value, colorCol || label);
    return (
      <div className="flex justify-between items-center py-0.5">
        <span className="text-slate-500 text-xs">{label}</span>
        <span className={`text-sm font-mono ${colorClass}`}>{display}</span>
      </div>
    );
  };

  return (
    <div className="fixed inset-0 bg-black/60 backdrop-blur-sm z-50 flex items-center justify-center p-4" onClick={onClose}>
      <div className="bg-slate-900 border border-slate-700 rounded-xl max-w-5xl w-full max-h-[90vh] overflow-auto shadow-2xl" onClick={e => e.stopPropagation()}>
        {/* Header */}
        <div className="flex items-center justify-between p-4 border-b border-slate-700 sticky top-0 bg-slate-900 z-10">
          <div>
            <h2 className="text-xl font-bold text-white">{player.Name}</h2>
            <div className="flex gap-3 mt-1 text-sm text-slate-400">
              <span>{player.POS}</span>
              <span>{player.ORG}</span>
              <span>Age {Math.round(parseFloat(player.Age) || 0)}</span>
              <span>{player.B}/{player.T}</span>
              <span>Lvl: {player.Lev}</span>
            </div>
          </div>
          <div className="flex items-center gap-4">
            {player._draftFV !== undefined && (
              <div className="text-center">
                <div className="text-3xl font-black text-green-400">{player._draftFV}</div>
                <div className="text-[10px] text-slate-500 uppercase tracking-wide">Draft FV</div>
              </div>
            )}
            <div className="text-center">
              <div className="text-3xl font-black text-blue-400">{fv.fvScale}</div>
              <div className="text-[10px] text-slate-500 uppercase tracking-wide">Future Value</div>
            </div>
            <button onClick={onClose} className="text-slate-400 hover:text-white p-1">
              <X size={20} />
            </button>
          </div>
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-3 gap-4 p-4">
          {/* Column 1: Key Stats */}
          <div className="space-y-4">
            <div className="bg-slate-800/50 rounded-lg p-3">
              <h3 className="text-xs font-semibold text-slate-400 uppercase mb-2">Value Summary</h3>
              {type === 'hitter' ? (
                <>
                  {statLine('Max WAA (wtd)', player['Max WAA wtd'], 'Max WAA wtd')}
                  {statLine('Max WAA (vR)', player['Max WAA vR'], 'Max WAA vR')}
                  {statLine('Max WAA (vL)', player['Max WAA vL'], 'Max WAA vL')}
                  {statLine('wOBA (wtd)', player['wOBA wtd'], 'wOBA wtd')}
                  {statLine('OBP (wtd)', player['OBP wtd'], 'OBP wtd')}
                  {statLine('BatR (wtd)', player['BatR wtd'], 'BatR wtd')}
                  {statLine('BSR (wtd)', player['BSR wtd'], 'BSR wtd')}
                </>
              ) : (
                <>
                  {statLine('SP WAA (wtd)', player['WAA wtd'], 'WAA wtd')}
                  {statLine('SP WAR', player['WAR wtd'], 'WAR wtd')}
                  {statLine('RP WAA (wtd)', player['WAA wtd RP'], 'WAA wtd RP')}
                  {statLine('RA/9 (wtd)', player['RA/9 wtd'], 'RA/9 wtd')}
                  {statLine('RA/9 RP', player['RA/9 wtd RP'], 'RA/9 wtd RP')}
                  {statLine('wOBA (wtd)', player['wOBA wtd'], 'wOBA wtd')}
                </>
              )}
              <DevSignalsLine player={player} />
              {type === 'hitter' && <TrainingLine player={player} />}
            </div>

            {type === 'hitter' && (() => {
              const num = k => { const v = parseFloat(player[k]); return isNaN(v) ? null : v; };
              const off = num('Off Runs'), def = num('Def Runs'), offP = num('Off Runs P');
              if (off === null || def === null) return null;
              const best = player['Best Pos'];
              const bat = num('BatR wtd'), bsr = num('BSR wtd');
              const glove = best && best !== 'DH' ? num(`${best} RunsP`) : null;
              const posadj = glove !== null ? def - glove : def;
              const R = ({ label, v, strong, indent }) => v === null ? null : (
                <div className={`flex justify-between items-center py-0.5 ${strong ? 'border-t border-slate-700/50 mt-0.5 pt-1' : ''}`}>
                  <span className={`text-xs ${strong ? 'text-slate-300 font-semibold' : 'text-slate-500'} ${indent ? 'pl-3' : ''}`}>{label}</span>
                  <span className={`text-sm font-mono ${strong ? 'font-bold' : ''} ${
                    v > 0.05 ? 'text-green-400' : v < -0.05 ? 'text-red-400' : 'text-slate-400'
                  }`}>{v > 0 ? '+' : ''}{v.toFixed(1)}</span>
                </div>
              );
              return (
                <div className="bg-slate-800/50 rounded-lg p-3">
                  <h3 className="text-xs font-semibold text-slate-400 uppercase mb-2">
                    Runs Breakdown{best ? ` (at ${best})` : ''}
                  </h3>
                  <R label="Batting" v={bat} indent />
                  <R label="Baserunning" v={bsr} indent />
                  <R label="Offense" v={off} strong />
                  <R label={glove !== null ? `Glove (${best})` : 'Glove'} v={glove} indent />
                  <R label={best === 'DH' ? 'DH charge' : 'Position adj'} v={posadj} indent />
                  <R label="Defense" v={def} strong />
                  <R label="Offense at potential" v={offP} strong />
                  <div className="text-[10px] text-slate-600 mt-1.5">
                    Runs per 600 PA season. Offense + Defense ÷ runs-per-win = Best WAA.
                    {best === 'C' ? ' Catcher offense is on the 500-PA catcher basis, so the components are approximate.' : ''}
                  </div>
                </div>
              );
            })()}

            <div className="bg-slate-800/50 rounded-lg p-3">
              <h3 className="text-xs font-semibold text-slate-400 uppercase mb-2">Future Value Breakdown</h3>
              {statLine('FV (20-80)', fv.fvScale, '_fvScale')}
              {statLine('Total Future$', fv.futureValue, '_futureValue')}
              {/* WAA (vs average) — same basis as the boards. fv.currentWAA /
                  expectedPeakWAA / potentialWAA are the internal WAR values and must
                  NOT be shown under a WAA label; fv.displayWAA is the converted track. */}
              {statLine('Current WAA', fv.displayWAA?.current, '_currentWAA')}
              {/* Proj Potential = the top of the projected path (fv.expectedPeak);
                  the suffix says what it grew toward (futureValue.targetSource):
                  current + the DEV cell gain, or the measured curve on his listed gap.
                  ML rows aged 26 and under: current + the ML gain q50 (on the line his
                  money uses; a pitcher's Exp peak starts from his better WAA line). */}
              {statLine(
                fv.targetSource === 'ml' ? 'Proj Potential (WAA, ML)'
                  : fv.targetSource === 'cell' ? 'Proj Potential (WAA, DEV cell)'
                  : fv.targetSource === 'listed' ? 'Proj Potential (WAA, measured curve)'
                  : 'Proj Potential (WAA)',
                fv.displayWAA?.expectedPeak, '_potentialWAA')}
              {statLine('Peak Potential (WAA)', fv.displayWAA?.potential, '_rawPotentialWAA')}
              {statLine('Peak WAA', fv.displayWAA?.peakProjected, '_peakWAA')}
              {/* The internal WAR basis, shown raw so the WAA numbers above are auditable.
                  Plain divs, not statLine — statLine runs values through formatCellValue,
                  which parseFloat()s a composite string down to its first number. */}
              <div className="flex justify-between items-center py-0.5 border-t border-slate-700/50 mt-1 pt-1">
                <span className="text-slate-500 text-xs">Internal WAR (cur / peak)</span>
                <span className="text-sm font-mono text-slate-400">{fv.currentWAA} / {fv.expectedPeakWAA}</span>
              </div>
              <div className="flex justify-between items-center py-0.5">
                <span className="text-slate-500 text-xs">Role (cur / peak)</span>
                <span className="text-sm font-mono text-slate-400">
                  {fv.currentRole ?? '?'} / {fv.potentialRole ?? '?'}
                  {fv.currentRole !== fv.potentialRole && (
                    <span className="ml-1 text-amber-400" title="Current and peak roles differ — the two ends carry different replacement offsets.">*</span>
                  )}
                </span>
              </div>
              {statLine('To Peak (WAA)', fv.displayWAA
                ? Math.round((fv.displayWAA.expectedPeak - fv.displayWAA.current) * 10) / 10
                : null, '_potentialWAA')}
              {statLine('ETA to Peak', fv.yearsTilPeak > 0
                ? `${fv.yearsTilPeak} yrs${fv.peakAge ? ` (age ${fv.peakAge})` : ''}`
                : 'At peak')}
              {nextSeason && (
                <div className="flex justify-between items-center py-0.5">
                  <span className="text-slate-500 text-xs">{nextSeason.ml ? 'Next season, if he keeps playing' : 'Next season'}</span>
                  <span className={`text-sm font-mono ${
                    nextSeason.delta > 0.05 ? 'text-green-400' : nextSeason.delta < -0.05 ? 'text-red-400' : 'text-slate-400'
                  }`} title={nextSeason.ml
                    ? `Median change next season (age ${nextSeason.age}) from ${devMlWords(player)}, 25th to 75th pct ${fmtWaa(nextSeason.lo)} to ${fmtWaa(nextSeason.hi)}. It assumes he keeps playing: the path models learn only from players who stayed in the league${devIsMl(player)
                      ? `, while Proj Potential counts the ones who wash out. The chart and the Year by year columns are capped at Proj Potential and smoothed (no dip before 28); projected WAA at age ${nextSeason.age} there: ${nextSeason.waa.toFixed(1)}`
                      : `. Projected WAA at age ${nextSeason.age} on the chart: ${nextSeason.waa.toFixed(1)}`}`
                    : `Projected WAA at age ${nextSeason.age}: ${nextSeason.waa.toFixed(1)}`}>
                    {nextSeason.delta > 0 ? '+' : ''}{nextSeason.delta.toFixed(1)} WAA{nextSeason.ml ? '' : ` (age ${nextSeason.age})`}
                    {nextSeason.ml && nextSeason.lo !== null && nextSeason.hi !== null
                      ? ` (range ${fmtWaa(nextSeason.lo)} to ${fmtWaa(nextSeason.hi)})` : ''}
                  </span>
                </div>
              )}
              {/* Remaining control — the window everything above is summed over.
                  Plain div, not statLine: formatCellValue would parseFloat the
                  composite string down to its leading number. */}
              <div className="flex justify-between items-center py-0.5 border-t border-slate-700/50 mt-1 pt-1">
                <span className="text-slate-500 text-xs">Control</span>
                <span
                  className={`text-sm font-mono ${control.source === 'default' ? 'text-amber-400' : 'text-slate-300'}`}
                  title={control.serviceYears !== null
                    ? `${control.serviceYears.toFixed(1)} MLB service yrs (${control.serviceBasis})`
                    : 'No service data on this row — falling back to a full 6-year window'}
                >
                  {formatControl(control)}
                </span>
              </div>
            </div>

            {player._draftFV !== undefined && (
              <div className="bg-slate-800/50 rounded-lg p-3 border border-blue-900/30">
                <h3 className="text-xs font-semibold text-blue-400 uppercase mb-2">Draft FV Breakdown</h3>
                {statLine('Draft FV (20-80)', player._draftFV, '_draftFV')}
                {statLine('Draft Raw Score', player._draftRawFV, '_draftRawFV')}
                {statLine('Age Percentile', player._agePercentile, '_agePercentile')}
                {statLine('Ceiling (WAA)', player._draftCeilingWAA, '_draftCeilingWAA')}
                {player._ceilingRole && statLine('Ceiling role', player._ceilingRole)}
                <div className="flex justify-between items-center py-0.5">
                  <span className="text-slate-500 text-xs">Durability</span>
                  <span className={`text-sm font-mono ${getCellColorClass(player._durability, '_durability')}`}>
                    {player._durability}
                  </span>
                </div>
                <div className="flex justify-between items-center py-0.5">
                  <span className="text-slate-500 text-xs">Work ethic</span>
                  <span className={`text-sm font-mono ${stepClass(weStep)}`}>
                    {weStep ? `${weStep} Draft FV` : 'None'}
                  </span>
                </div>
                {player._toolPenalty !== undefined && player._toolPenalty < 1.0 && (
                  <div className="flex justify-between items-center py-0.5">
                    <span className="text-slate-500 text-xs">Tool Penalty</span>
                    <span className="text-sm font-mono text-red-400">
                      -{Math.round((1 - player._toolPenalty) * 100)}% (age pctl)
                    </span>
                  </div>
                )}
                <div className="flex justify-between items-center py-0.5">
                  <span className="text-slate-500 text-xs">High INT</span>
                  <span className={`text-sm font-mono ${stepClass(intStep)}`}>
                    {player._highINT ? `Yes (${intStep} Draft FV)` : intStep ? `No (low: ${intStep} Draft FV)` : 'No'}
                  </span>
                </div>
                {player._wrecked && (
                  <div className="mt-2 text-center text-red-400 font-bold text-xs uppercase bg-red-900/20 rounded py-1">
                    Undraftable (Wrecked)
                  </div>
                )}
              </div>
            )}
          </div>

          {/* Column 2: Charts */}
          <div className="space-y-4">
            {/* Ratings — big colored 20-80 chips, not a radar. This is the card the
                user reads first: what ARE this guy's ratings. */}
            <div className="bg-slate-800/50 rounded-lg p-3">
              <h3 className="text-xs font-semibold text-slate-400 uppercase mb-2">
                {type === 'hitter' ? 'Batting Ratings' : 'Pitching Ratings'}
              </h3>
              {type === 'hitter' ? (
                <>
                  <RatingsTable
                    player={player}
                    rows={[
                      ['BABIP', 'BA vR', 'BA vL', 'HT P'],
                      ['Gap', 'GAP vR', 'GAP vL', 'GAP P'],
                      ['Power', 'POW vR', 'POW vL', 'POW P'],
                      ['Eye', 'EYE vR', 'EYE vL', 'EYE P'],
                      ['Avoid K', 'K vR', 'K vL', 'K P'],
                    ]}
                  />
                  <h4 className="text-[10px] text-slate-500 uppercase tracking-wider mb-1.5 mt-3">Running</h4>
                  <ChipRow player={player} items={[['Speed', 'SPE'], ['Steal', 'STE'], ['Baserun', 'RUN']]} />
                </>
              ) : (
                <>
                  <RatingsTable
                    player={player}
                    rows={[
                      ['Stuff', 'STU vR', 'STU vL', 'STU P'],
                      ['Control', 'CON vR', 'CON vL', 'CON P'],
                      ['HR Rate', 'HRR vR', 'HRR vL', 'HRR P'],
                      ['pBABIP', 'PBABIP vR', 'PBABIP vL', 'PBABIP P'],
                    ]}
                  />
                  <h4 className="text-[10px] text-slate-500 uppercase tracking-wider mb-1.5 mt-3">Usage</h4>
                  <ChipRow player={player} items={[['Stamina', 'STM'], ['Hold', 'HLD'], ['GB%', 'GB']]} />
                  <PitchRepertoire player={player} />
                </>
              )}
            </div>

            {/* Position WAA Bar Chart (hitters only) */}
            {type === 'hitter' && posWAAData.length > 0 && (
              <div className="bg-slate-800/50 rounded-lg p-3">
                <h3 className="text-xs font-semibold text-slate-400 uppercase mb-2">WAA by Position</h3>
                <ResponsiveContainer width="100%" height={160}>
                  <BarChart data={posWAAData}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
                    <XAxis dataKey="pos" tick={{ fill: '#94a3b8', fontSize: 11 }} />
                    <YAxis tick={{ fill: '#94a3b8', fontSize: 10 }} />
                    <Tooltip
                      contentStyle={{ background: '#1e293b', border: '1px solid #475569', borderRadius: 8 }}
                      labelStyle={{ color: '#e2e8f0' }}
                    />
                    <Bar dataKey="waa" radius={[4, 4, 0, 0]}>
                      {posWAAData.map((entry, i) => (
                        <Cell key={i} fill={entry.waa >= 0 ? '#3b82f6' : '#ef4444'} />
                      ))}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              </div>
            )}
          </div>

          {/* Column 3: Development Curve */}
          <div className="space-y-4">
            <div className="bg-slate-800/50 rounded-lg p-3">
              <h3 className="text-xs font-semibold text-slate-400 uppercase mb-2">Projected Development Curve</h3>
              <ResponsiveContainer width="100%" height={220}>
                <LineChart data={devCurve}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
                  <XAxis dataKey="age" tick={{ fill: '#94a3b8', fontSize: 11 }} />
                  <YAxis tick={{ fill: '#94a3b8', fontSize: 10 }} />
                  <Tooltip
                    contentStyle={{ background: '#1e293b', border: '1px solid #475569', borderRadius: 8 }}
                    labelStyle={{ color: '#e2e8f0' }}
                  />
                  <Line type="monotone" dataKey="WAA" stroke="#3b82f6" strokeWidth={2} dot={{ r: 3 }} />
                </LineChart>
              </ResponsiveContainer>
              <div className="text-center text-xs text-slate-500 mt-1">
                {fv.targetSource === 'ml' ? (
                  <>
                    <span className="text-blue-400">
                      {devIsMl(player)
                        ? 'projected path: five ML years (smoothed, capped at Proj Potential), then the measured DEV curve'
                        : 'projected path: five ML years, then the measured DEV curve'}
                    </span>
                  </>
                ) : fv.measured ? (
                  <>
                    <span className="text-blue-400">projected path (measured DEV curve)</span>
                    {ageCurve ? ` (${ageCurve.source_league ? `${ageCurve.source_league} true ratings, ` : ''}${ageCurve.players} players, ${ageCurve.span_years}yr)` : ''}
                  </>
                ) : (
                  <span className="text-blue-400">model curve</span>
                )}
              </div>
            </div>

            {type === 'hitter' && (
              <div className="bg-slate-800/50 rounded-lg p-3">
                <h3 className="text-xs font-semibold text-slate-400 uppercase mb-2">Fielding Ratings</h3>
                <ChipRow
                  player={player}
                  items={[
                    ['IF Range', 'IF RNG'], ['OF Range', 'OF RNG'],
                    ['IF Error', 'IF ERR'], ['OF Error', 'OF ERR'],
                    ['IF Arm', 'IF ARM'], ['OF Arm', 'OF ARM'],
                    ['Turn DP', 'TDP'], ['C Frame', 'C FRM'],
                    ['C Ability', 'C ABI'], ['C Arm', 'C ARM'],
                  ]}
                />
              </div>
            )}

            <RatingHistory player={player} />
          </div>
        </div>
      </div>
    </div>
  );
}
