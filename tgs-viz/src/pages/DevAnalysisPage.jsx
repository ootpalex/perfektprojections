import React, { useState, useMemo } from 'react';
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, ReferenceLine } from 'recharts';
import {
  FV_DEFAULTS, getGapFactor, getAgingFactor, getRiskFactor, computeImpact,
  MEDIAN_CURRENT_WAA_BY_AGE,
} from '../lib/futureValue';

const AGES = [16, 18, 20, 22, 24, 25, 26, 28, 30];
const PERCENTILES = [
  { pct: 10, label: '10th Dev%' },
  { pct: 25, label: '25th Dev%' },
  { pct: 50, label: '50th Dev%' },
  { pct: 75, label: '75th Dev%' },
  { pct: 90, label: '90th Dev%' },
  { pct: 95, label: '95th Dev%' },
  { pct: 99, label: '99th Dev%' },
];

function SliderControl({ label, value, onChange, min, max, step, description }) {
  return (
    <div className="flex items-center gap-3 mb-3">
      <span className="text-sm ns-text w-32 shrink-0">{label}</span>
      <input
        type="range" min={min} max={max} step={step} value={value}
        onChange={e => onChange(parseFloat(e.target.value))}
        className="flex-1 h-1.5 appearance-none cursor-pointer accent-[var(--accent)]"
      />
      <input
        type="number" min={min} max={max} step={step} value={value}
        onChange={e => onChange(parseFloat(e.target.value) || min)}
        className="w-16 px-2 py-1 ns-input text-sm text-center"
      />
      {description && <span className="text-[11px] ns-muted w-32">{description}</span>}
    </div>
  );
}

function fvCellColor(fv) {
  if (fv >= 70) return 'ns-g80';
  if (fv >= 60) return 'ns-g70';
  if (fv >= 55) return 'ns-g55';
  if (fv >= 50) return 'ns-text-2';
  if (fv >= 45) return 'ns-g30';
  if (fv >= 40) return 'ns-text';
  return 'ns-muted';
}

export default function DevAnalysisPage() {
  const [potentialWAA, setPotentialWAA] = useState(3.0);

  // Gap Factor params
  const [maturityAge, setMaturityAge] = useState(FV_DEFAULTS.MATURITY_AGE);
  const [gapMax, setGapMax] = useState(FV_DEFAULTS.GAP_MAX);
  const [gapSteepness, setGapSteepness] = useState(FV_DEFAULTS.GAP_STEEPNESS);

  // Risk params
  const [riskFloor, setRiskFloor] = useState(FV_DEFAULTS.RISK_FLOOR);
  const [riskCeiling, setRiskCeiling] = useState(FV_DEFAULTS.RISK_CEILING);

  // Aging params
  const [peakEnd, setPeakEnd] = useState(FV_DEFAULTS.PEAK_END);
  const [declineRate, setDeclineRate] = useState(FV_DEFAULTS.DECLINE_RATE);
  const [cliffAge, setCliffAge] = useState(FV_DEFAULTS.CLIFF_AGE);
  const [cliffRate, setCliffRate] = useState(FV_DEFAULTS.CLIFF_RATE);

  // Discount
  const [discountRate, setDiscountRate] = useState(FV_DEFAULTS.DISCOUNT_RATE);

  const params = useMemo(() => ({
    MATURITY_AGE: maturityAge,
    GAP_MAX: gapMax,
    GAP_STEEPNESS: gapSteepness,
    RISK_FLOOR: riskFloor,
    RISK_CEILING: riskCeiling,
    PEAK_END: peakEnd,
    DECLINE_RATE: declineRate,
    CLIFF_AGE: cliffAge,
    CLIFF_RATE: cliffRate,
    DISCOUNT_RATE: discountRate,
    MAX_CAREER_AGE: FV_DEFAULTS.MAX_CAREER_AGE,
    DEFAULT_YEARS_OF_CONTROL: FV_DEFAULTS.DEFAULT_YEARS_OF_CONTROL,
  }), [maturityAge, gapMax, gapSteepness, riskFloor, riskCeiling, peakEnd, declineRate, cliffAge, cliffRate, discountRate]);

  // Impact table data
  const impactTable = useMemo(() => {
    return AGES.map(age => {
      const row = { age };
      for (const { pct } of PERCENTILES) {
        const result = computeImpact(age, potentialWAA, pct, params);
        row[`fv_${pct}`] = result.futureValue;
        row[`scale_${pct}`] = result.fvScale;
        row[`curr_${pct}`] = result.currentWAA;
      }
      return row;
    });
  }, [potentialWAA, params]);

  // Gap factor curve data
  const gapCurveData = useMemo(() => {
    const data = [];
    for (let age = 14; age <= 35; age += 0.5) {
      data.push({
        age,
        gapFactor: getGapFactor(age, params),
      });
    }
    return data;
  }, [params]);

  // Aging factor curve data
  const agingCurveData = useMemo(() => {
    const data = [];
    for (let age = 20; age <= 40; age += 0.5) {
      data.push({
        age,
        agingFactor: getAgingFactor(age, params),
      });
    }
    return data;
  }, [params]);

  // Settings summary
  const settingsStr = `Maturity=${maturityAge}, GapMax=${gapMax}, Steep=${gapSteepness}, ` +
    `RiskMin=${riskFloor}, RiskMax=${riskCeiling}, ` +
    `PeakEnd=${peakEnd}, Decline=${declineRate}, Cliff=${cliffAge}@${cliffRate}, ` +
    `Discount=${discountRate}, Potential=${potentialWAA} WAA`;

  return (
    <div className="ns-page overflow-auto [&>*]:shrink-0">
      <header className="ns-page-head">
        <div>
          <h1>Future Value Impact Analysis</h1>
          <p className="ns-page-sub">
            Shows Future Value for a player with the given potential WAA, using the current WAA from the data at each age/percentile.
            Fallback model only. It runs when the DEV age curve file is missing. The lists and player cards use the DEV curve
            and the ML model, so these sliders do not change them.
          </p>
        </div>
      </header>

      {/* Potential WAA Input */}
      <div className="pb-3 flex items-center gap-3">
        <span className="text-sm ns-text">Example Potential WAA:</span>
        <input
          type="number" step="0.5" min="-5" max="10" value={potentialWAA}
          onChange={e => setPotentialWAA(parseFloat(e.target.value) || 0)}
          className="ns-input w-20 text-center font-bold"
        />
      </div>

      {/* Impact Table */}
      <div className="pb-2">
        <div className="table-container">
          <table className="data-table">
            <thead>
              <tr>
                <th className="w-16">Age</th>
                {PERCENTILES.map(({ pct, label }) => (
                  <th key={pct} className="text-center">{label}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {impactTable.map(row => (
                <tr key={row.age}>
                  <td className="font-bold ns-text">{row.age}</td>
                  {PERCENTILES.map(({ pct }) => {
                    const fv = row[`fv_${pct}`];
                    const scale = row[`scale_${pct}`];
                    const curr = row[`curr_${pct}`];
                    const isDevAge = row.age < maturityAge;
                    return (
                      <td key={pct} className="text-center">
                        <div className={`text-sm font-bold ${fvCellColor(scale)}`}>
                          {fv.toFixed(2)}
                        </div>
                        <div className="text-[11px] ns-muted">
                          {isDevAge ? `curr: ${curr.toFixed(1)}` : `at peak`}
                        </div>
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="text-[11px] ns-muted mt-1">
          Settings: {settingsStr}
        </div>
      </div>

      {/* Fallback model settings (futureValue.computeImpact: the assumed model, no DEV curve) */}
      <div className="pb-4">
        <h2 className="ns-subhead mb-3">Fallback model settings</h2>
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">

          {/* Gap Factor Panel */}
          <div className="ns-card">
            <h3 className="ns-strip">Gap Factor</h3>
            <SliderControl label="Maturity Age" value={maturityAge} onChange={setMaturityAge}
              min={22} max={32} step={1} />
            <SliderControl label="Gap Max" value={gapMax} onChange={setGapMax}
              min={0.5} max={1.0} step={0.01} description="0=full gap penalty, 1.0=no gap penalty" />
            <SliderControl label="Gap Steepness" value={gapSteepness} onChange={setGapSteepness}
              min={0.1} max={2.0} step={0.05} description="Higher = sharper S-curve" />

            <div className="mt-4">
              <ResponsiveContainer width="100%" height={200}>
                <LineChart data={gapCurveData}>
                  <CartesianGrid strokeDasharray="3 3" stroke="var(--chart-grid)" />
                  <XAxis dataKey="age" tick={{ fill: 'var(--chart-axis)', fontSize: 11 }}
                    domain={[14, 35]} type="number" />
                  <YAxis tick={{ fill: 'var(--chart-axis)', fontSize: 11 }}
                    domain={[0, 1]} />
                  <Tooltip
                    contentStyle={{ background: 'var(--chart-tooltip-bg)', border: '1px solid var(--chart-tooltip-border)', borderRadius: 3 }}
                    labelStyle={{ color: 'var(--chart-tooltip-text)' }}
                    formatter={(v) => [v.toFixed(3), 'Gap Factor']}
                    labelFormatter={(l) => `Age: ${l}`}
                  />
                  <ReferenceLine x={maturityAge} stroke="var(--chart-ref-line)" strokeDasharray="5 5"
                    label={{ value: `Maturity (${maturityAge})`, fill: 'var(--chart-ref-line)', fontSize: 11, position: 'top' }} />
                  <Line type="monotone" dataKey="gapFactor" stroke="var(--chart-series-3)" strokeWidth={2.5} dot={false} />
                </LineChart>
              </ResponsiveContainer>
              <div className="text-center text-[11px] ns-muted">Age</div>
            </div>
          </div>

          {/* Risk & Aging Panel */}
          <div className="ns-card">
            <h3 className="ns-strip">Risk & Aging</h3>
            <SliderControl label="Risk Floor" value={riskFloor} onChange={setRiskFloor}
              min={0.5} max={1.0} step={0.01} description="Min credit (worst pct)" />
            <SliderControl label="Risk Ceiling" value={riskCeiling} onChange={setRiskCeiling}
              min={0.5} max={1.0} step={0.01} description="Max credit (best pct)" />
            <SliderControl label="Peak End" value={peakEnd} onChange={setPeakEnd}
              min={25} max={32} step={1} />
            <SliderControl label="Decline Rate" value={declineRate} onChange={setDeclineRate}
              min={0.01} max={0.10} step={0.005} description="Annual % after peak" />
            <SliderControl label="Cliff Age" value={cliffAge} onChange={setCliffAge}
              min={28} max={38} step={1} />
            <SliderControl label="Cliff Rate" value={cliffRate} onChange={setCliffRate}
              min={0.02} max={0.15} step={0.005} description="Annual % after cliff" />
            <SliderControl label="Discount Rate" value={discountRate} onChange={setDiscountRate}
              min={0} max={0.10} step={0.005} description="Time value discount" />

            <div className="mt-4">
              <ResponsiveContainer width="100%" height={200}>
                <LineChart data={agingCurveData}>
                  <CartesianGrid strokeDasharray="3 3" stroke="var(--chart-grid)" />
                  <XAxis dataKey="age" tick={{ fill: 'var(--chart-axis)', fontSize: 11 }}
                    domain={[20, 40]} type="number" />
                  <YAxis tick={{ fill: 'var(--chart-axis)', fontSize: 11 }}
                    domain={[0, 1.1]} />
                  <Tooltip
                    contentStyle={{ background: 'var(--chart-tooltip-bg)', border: '1px solid var(--chart-tooltip-border)', borderRadius: 3 }}
                    labelStyle={{ color: 'var(--chart-tooltip-text)' }}
                    formatter={(v) => [v.toFixed(3), 'Aging Factor']}
                    labelFormatter={(l) => `Age: ${l}`}
                  />
                  <ReferenceLine x={peakEnd} stroke="var(--chart-series-2)" strokeDasharray="5 5"
                    label={{ value: `Peak End (${peakEnd})`, fill: 'var(--chart-series-2)', fontSize: 11, position: 'top' }} />
                  <ReferenceLine x={cliffAge} stroke="var(--chart-series-3)" strokeDasharray="5 5"
                    label={{ value: `Cliff (${cliffAge})`, fill: 'var(--chart-series-3)', fontSize: 11, position: 'top' }} />
                  <Line type="monotone" dataKey="agingFactor" stroke="var(--chart-series-4)" strokeWidth={2.5} dot={false} />
                </LineChart>
              </ResponsiveContainer>
              <div className="text-center text-[11px] ns-muted">Age</div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
