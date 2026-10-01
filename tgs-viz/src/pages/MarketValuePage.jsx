import React, { useState, useMemo } from 'react';
import { ScatterChart, Scatter, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Legend, BarChart, Bar, Cell } from 'recharts';
import { analyzeMarket, calculatePlayerValue, resolveRate, getPlayerRole, formatMoney } from '../lib/marketValue';
import { formatControl } from '../lib/serviceTime';
import { usePlayersWithFV } from '../hooks/usePlayerData';
import { useSelectedById } from '../hooks/useSelectedById';
import { Search, ChevronDown, ChevronUp, DollarSign, TrendingUp, Info } from 'lucide-react';

/**
 * Market Value Page — FA-market fit ($/WAR + floor) and contract valuation.
 * The line is FITTED at load from fresh free-agent signings (salary ~ WAR OLS,
 * WAR = WAA + measured replacement offsets); it re-fits on every data refresh.
 * Helps answer: "Is this contract good?" and "How much should I offer this FA?"
 */
export default function MarketValuePage({ hitters, pitchers, marketBank }) {
  // Compute FV for all players (needed for year-by-year projections)
  const hittersWithFV = usePlayersWithFV(hitters);
  const pitchersWithFV = usePlayersWithFV(pitchers);

  const [search, setSearch] = useState('');
  const [filterType, setFilterType] = useState('ALL'); // ALL, IFA, MLB, PROSPECT, CONTRACT
  const [sortKey, setSortKey] = useState('_ctrSurplus');
  const [sortDir, setSortDir] = useState('desc');
  // Manual override knobs (in $M) — blank = use the fitted values
  const [slopeOverride, setSlopeOverride] = useState('');
  const [floorOverride, setFloorOverride] = useState('');

  // Run market analysis (fits the FA line, or keeps the banked one when FA
  // opening has collapsed the live sample — see marketValue.js fitFAMarket)
  const market = useMemo(
    () => analyzeMarket(hittersWithFV, pitchersWithFV, { banked: marketBank }),
    [hittersWithFV, pitchersWithFV, marketBank]);
  const fit = market.fit;
  const prov = fit?.provenance;

  const override = useMemo(() => ({
    slope: slopeOverride !== '' && !isNaN(parseFloat(slopeOverride)) ? parseFloat(slopeOverride) * 1_000_000 : undefined,
    floor: floorOverride !== '' && !isNaN(parseFloat(floorOverride)) ? parseFloat(floorOverride) * 1_000_000 : undefined,
  }), [slopeOverride, floorOverride]);

  const hitterRate = useMemo(() => resolveRate(fit, 'hitter', override), [fit, override]);
  const pitcherRate = useMemo(() => resolveRate(fit, 'pitcher', override), [fit, override]);
  // Reference shape drawn on the scatter (pooled resolution + overrides).
  // resolveRate with a role nobody uses resolves to the POOLED cell, so this
  // carries the pooled priceAt — straight when the pooled fit is a line,
  // curved when the curvature term cleared its gates.
  const lineRate = useMemo(() => resolveRate(fit, '_pooled', override), [fit, override]);

  // Enrich all players with market value calculations
  const allPlayers = useMemo(() => {
    const combined = [
      ...hittersWithFV.map(p => ({ ...p, _playerType: 'Hitter' })),
      ...pitchersWithFV.map(p => ({ ...p, _playerType: 'Pitcher' })),
    ];

    return combined.map(p => {
      const rate = getPlayerRole(p) === 'pitcher' ? pitcherRate : hitterRate;
      const val = calculatePlayerValue(p, rate);
      return {
        ...p,
        _war: val.warNow,
        _marketValue: val.adjustedValue,
        _annualValue: val.annualValue,
        _mktPrice: val.marketPrice,
        _mktSurplus: val.marketSurplus,
        _mktTier: val.tier,
        _offerFloor: val.offerFloor,
        _offerMid: val.offerMid,
        _offerCeiling: val.offerCeiling,
        _surplus: val.surplus,
        _ctrYears: val.contract ? val.contract.yearsRemaining : null,
        _ctrSurplus: val.contract ? val.contract.surplus : null,
        _isProspect: val.isProspect,
        _perWAA: p.Price > 0 && val.warNow > 0 ? Math.round(p.Price / val.warNow) : null,
        _valuation: val,
      };
    });
  }, [hittersWithFV, pitchersWithFV, hitterRate, pitcherRate]);

  // The detail card must track the CURRENT enrichment: override changes re-run
  // the valuation, and a data refresh brings new rows, so a click-time snapshot
  // would go stale. The shared hook keeps the pick by ID and finds the row again.
  const rowsByKind = useMemo(() => ({
    hitter: allPlayers.filter(p => p._playerType !== 'Pitcher'),
    pitcher: allPlayers.filter(p => p._playerType === 'Pitcher'),
  }), [allPlayers]);
  const { selected: selectedCurrent, select, clear } = useSelectedById(rowsByKind);
  const selectedPlayer = selectedCurrent;
  const kindOf = (p) => (p._playerType === 'Pitcher' ? 'pitcher' : 'hitter');

  // Filter and sort
  const filteredPlayers = useMemo(() => {
    let result = allPlayers;

    if (filterType === 'IFA') {
      result = result.filter(p => p.Lev === 'INT');
    } else if (filterType === 'MLB') {
      result = result.filter(p => p.Lev === 'MLB');
    } else if (filterType === 'PROSPECT') {
      result = result.filter(p => p._isProspect);
    } else if (filterType === 'FREE_AGENT') {
      result = result.filter(p => !p.ORG || p.ORG === '' || p.ORG === '-');
    } else if (filterType === 'CONTRACT') {
      result = result.filter(p => p._ctrYears);
    }

    if (search) {
      const s = search.toLowerCase();
      result = result.filter(p =>
        (p.Name || '').toLowerCase().includes(s) ||
        (p.ORG || '').toLowerCase().includes(s)
      );
    }

    result = [...result].sort((a, b) => {
      const aVal = parseFloat(a[sortKey]);
      const bVal = parseFloat(b[sortKey]);
      const aa = isNaN(aVal) ? -Infinity : aVal;
      const bb = isNaN(bVal) ? -Infinity : bVal;
      return sortDir === 'desc' ? bb - aa : aa - bb;
    });

    return result;
  }, [allPlayers, filterType, search, sortKey, sortDir]);

  // Scatter chart data: every paid MLB player, FA-sample points highlighted
  const scatterData = useMemo(() => market.dataPoints.map(d => ({
    war: Math.round(d.war * 100) / 100,
    price: d.price,
    name: d.name, pos: d.pos, age: d.age,
    isFA: d.isFA, isPreArb: d.isPreArb,
  })), [market]);

  const warExtent = useMemo(() => {
    const ws = scatterData.map(d => d.war);
    return { min: Math.min(...ws, 0), max: Math.max(...ws, 1) };
  }, [scatterData]);

  // The fitted shape, SAMPLED — a straight ReferenceLine would misdraw a
  // curved fit (and would hide the no-extrapolation clamp at the top).
  const fitCurve = useMemo(() => {
    if (!(lineRate.slope > 0)) return [];
    const steps = 60;
    const out = [];
    for (let i = 0; i <= steps; i++) {
      const w = warExtent.min + (warExtent.max - warExtent.min) * (i / steps);
      out.push({ war: Math.round(w * 100) / 100, price: lineRate.priceAt(w) });
    }
    return out;
  }, [lineRate, warExtent]);

  const handleSort = (key) => {
    if (sortKey === key) {
      setSortDir(d => d === 'desc' ? 'asc' : 'desc');
    } else {
      setSortKey(key);
      setSortDir('desc');
    }
  };

  const fmtSlope = (v) => `${formatMoney(v)}/WAR`;

  return (
    <div className="h-full overflow-y-auto">
      <div className="p-4 space-y-6">
        {/* Header */}
        <div>
          <h1 className="text-2xl font-bold text-white flex items-center gap-2">
            <DollarSign size={24} className="text-green-400" />
            Market Value — FA Fit
          </h1>
          <p className="text-sm text-slate-400 mt-1">
            AAV ~ WAR fitted on genuine open-market signings only: MLB, first year of the deal, and
            ≥6 service years <em>measured in days at the moment of signature</em> — which is what excludes
            pre-free-agency extensions. WAR = WAA + measured MARKET replacement offsets
            (what freely-available talent produces). The floor is pinned at the league minimum, and the
            curvature and the hitter/pitcher split each have to earn their place out of sample
            (see “How this fit was chosen”). Two economies:{' '}
            <span className="text-slate-300">line value — replaceable tier</span> vs{' '}
            <span className="text-amber-300">market price — scarcity tier</span> (tier-local fit of comparable-WAR signings).
            Everything re-fits automatically on every data refresh.
          </p>
        </div>

        {/* Banked-fit notice — never price off a stale line silently */}
        {prov?.used === 'banked' && (
          <div className="bg-amber-950/40 rounded-lg border border-amber-800/60 p-3 text-sm text-amber-200">
            <span className="font-semibold">Market fit: banked {prov.bankedAt}</span>
            {' '}(n={prov.bankedN}) — the live sample is only n={prov.liveN}, too small to
            re-price a win. Free agency resets every contract to year 1, which empties the
            open-market sample. The live fit takes over again by itself once it rests on at
            least as many signings.
          </div>
        )}

        {/* Fitted Market Cards */}
        <div className="grid grid-cols-3 lg:grid-cols-6 gap-3">
          <StatCard
            label="Fitted $/WAR"
            value={fit?.pooled ? fmtSlope(fit.pooled.slope) : '-'}
            sub={fit?.pooled
              ? `pooled, n=${fit.pooled.n}`
                + (prov?.used === 'banked' ? ` · BANKED ${prov.bankedAt}` : '')
              : 'no FA sample'}
            color="text-green-400"
          />
          <StatCard
            label="Fitted Floor"
            value={fit?.pooled ? formatMoney(fit.pooled.floor) : '-'}
            sub={fit?.pooled?.floorMode === 'pinned'
              ? `pinned at the measured league minimum${fit.minSalaryInfo ? ` (${Math.round(fit.minSalaryInfo.share * 100)}% of ${fit.minSalaryInfo.pool} pre-arb deals)` : ''}`
              : 'free intercept (pin lost the out-of-sample test)'}
            color="text-cyan-400"
          />
          <StatCard
            label="Fit Quality"
            value={fit?.pooled ? `r² ${fit.pooled.r2.toFixed(2)}` : '-'}
            sub={fit?.pooled ? `resid SD ${formatMoney(fit.pooled.residSD)} · shape ${fit.pooled.shape}` : ''}
            color="text-slate-300"
          />
          <StatCard
            label="Hitter Fit"
            value={fit?.hitter ? fmtSlope(fit.hitter.slope) : '-'}
            sub={fit?.hitter
              ? `floor ${formatMoney(fit.hitter.floor)} = league min · n=${fit.hitter.n}, r² ${fit.hitter.r2.toFixed(2)}`
                + (fit.useRoleLine?.hitter ? '' : ' · prices on the POOLED line')
              : 'too few'}
            color="text-blue-400"
          />
          <StatCard
            label="Pitcher Fit"
            value={fit?.pitcher ? fmtSlope(fit.pitcher.slope) : '-'}
            /* v3: the old label called this floor "the flat RP salary market".
               That was wrong — the 2026-08-07 replacement re-measurement showed
               it was UNPRICED REPLACEMENT WINS (pitcher WAR was understated, so
               the fit pushed the miss into the intercept). With the offsets
               fixed and the extensions filtered out, the free intercept is
               statistically indistinguishable from the league minimum, and the
               shipped floor IS the league minimum. */
            sub={fit?.pitcher
              ? `floor ${formatMoney(fit.pitcher.floor)} = league min · n=${fit.pitcher.n}, r² ${fit.pitcher.r2.toFixed(2)}`
                + (fit.useRoleLine?.pitcher ? '' : ' · prices on the POOLED line')
              : 'too few'}
            color="text-yellow-300"
          />
          <StatCard
            label="P/H Slope Ratio"
            value={fit?.ratioPH ? `${fit.ratioPH.toFixed(2)}x` : '-'}
            sub={fit?.perRole
              ? `per-role line(s) earned out-of-sample (slope diff t=${fit.slopeDiffT?.toFixed(1)})`
              : `roles POOLED — the split did not pay for itself out of sample (t=${fit.slopeDiffT?.toFixed(1)})`}
            color="text-purple-400"
          />
        </div>

        {/* Fit provenance — every gate the shipped line had to clear */}
        {fit?.notes?.length > 0 && (
          <details className="bg-slate-900 rounded-lg border border-slate-800 p-4">
            <summary className="text-sm font-semibold text-white cursor-pointer">
              How this fit was chosen ({fit.sample.length} open-market signings
              {fit.serviceBasis ? ` · service basis: ${fit.serviceBasis}` : ''})
            </summary>
            <ul className="mt-3 space-y-1 text-xs text-slate-400 list-disc list-inside">
              {fit.notes.map((n, i) => <li key={i}>{n}</li>)}
            </ul>
          </details>
        )}

        {/* Manual override */}
        <div className="bg-slate-900 rounded-lg border border-slate-800 p-4">
          <div className="flex items-center gap-4 flex-wrap">
            <div className="flex items-center gap-2">
              <span className="text-sm text-slate-400">$/WAR ($M):</span>
              <input
                type="number"
                step="0.1"
                value={slopeOverride}
                onChange={(e) => setSlopeOverride(e.target.value)}
                placeholder={fit?.pooled ? (fit.pooled.slope / 1_000_000).toFixed(2) : '-'}
                className="w-24 bg-slate-800 text-white text-sm rounded px-3 py-1.5 border border-slate-700 focus:border-blue-500 focus:outline-none placeholder-slate-500"
              />
              <span className="text-sm text-slate-400">Floor ($M):</span>
              <input
                type="number"
                step="0.1"
                value={floorOverride}
                onChange={(e) => setFloorOverride(e.target.value)}
                placeholder={fit?.pooled ? (fit.pooled.floor / 1_000_000).toFixed(2) : '-'}
                className="w-24 bg-slate-800 text-white text-sm rounded px-3 py-1.5 border border-slate-700 focus:border-blue-500 focus:outline-none placeholder-slate-500"
              />
              {(slopeOverride || floorOverride) && (
                <button
                  onClick={() => { setSlopeOverride(''); setFloorOverride(''); }}
                  className="text-xs text-slate-500 hover:text-slate-300"
                >
                  Reset to fitted
                </button>
              )}
            </div>
            <div className="text-xs text-slate-500 flex items-center gap-1">
              <Info size={12} />
              Override the fitted line to model scenarios. Blank = fitted values (auto-refit each data refresh).
            </div>
          </div>
        </div>

        {/* Two-column layout: Chart + Buckets */}
        <div className="grid grid-cols-2 gap-4">
          {/* Scatter: Salary vs WAR */}
          <div className="bg-slate-900 rounded-lg border border-slate-800 p-4">
            <h2 className="text-sm font-semibold text-white mb-3">Salary vs WAR (MLB contracts; FA signings = fit sample)</h2>
            <ResponsiveContainer width="100%" height={320}>
              <ScatterChart margin={{ top: 10, right: 20, bottom: 20, left: 20 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
                <XAxis
                  dataKey="war"
                  name="WAR"
                  type="number"
                  domain={['auto', 'auto']}
                  tick={{ fill: '#94a3b8', fontSize: 11 }}
                  label={{ value: 'WAR', position: 'insideBottom', offset: -10, fill: '#64748b', fontSize: 11 }}
                />
                <YAxis
                  dataKey="price"
                  name="Salary"
                  type="number"
                  tickFormatter={(v) => formatMoney(v)}
                  tick={{ fill: '#94a3b8', fontSize: 11 }}
                  label={{ value: 'Salary', angle: -90, position: 'insideLeft', offset: 10, fill: '#64748b', fontSize: 11 }}
                />
                <Tooltip content={<ScatterTooltip />} />
                {fitCurve.length > 0 && (
                  <Scatter
                    data={fitCurve}
                    line={{ stroke: '#22c55e', strokeDasharray: '5 5', strokeWidth: 1.5 }}
                    shape={() => null}
                    legendType="none"
                    isAnimationActive={false}
                    name="Fitted market"
                  />
                )}
                <Scatter data={scatterData.filter(d => d.isFA)} fill="#3b82f6" fillOpacity={0.85} r={4} name="FA signings (fit sample)" />
                <Scatter data={scatterData.filter(d => !d.isFA && !d.isPreArb)} fill="#64748b" fillOpacity={0.45} r={3} name="Other contracts" />
                <Scatter data={scatterData.filter(d => !d.isFA && d.isPreArb)} fill="#f59e0b" fillOpacity={0.35} r={2} name="Pre-arb" />
                <Legend wrapperStyle={{ fontSize: 11 }} />
              </ScatterChart>
            </ResponsiveContainer>
            <p className="text-xs text-slate-500 mt-2">
              Green = the pooled fitted shape ({lineRate.shape === 'quad'
                ? `curved: ${fmtSlope(lineRate.slope)} + ${formatMoney(lineRate.curv)}/WAR², clamped above ${lineRate.maxX?.toFixed(2)} WAR`
                : `straight: ${fmtSlope(lineRate.slope)}`}, floor {formatMoney(lineRate.floor)}
              {lineRate.floorMode === 'pinned' ? ' pinned at the measured league minimum' : ' free'}).
              Valuations use whichever line each role earned out of sample; offers use the tier-local fit.
              Only blue points set the fits — and only genuine open-market signings count:
              MLB, first year of the deal, and ≥6 service YEARS measured IN DAYS at the moment of signature
              (MLBSvcDays − MLBSvcDaysTY ≥ 6×172), which is what keeps pre-free-agency extensions out.
              The y-axis is this season's salary; the fit itself regresses AAV.
            </p>
          </div>

          {/* WAR Bucket Analysis */}
          <div className="bg-slate-900 rounded-lg border border-slate-800 p-4">
            <h2 className="text-sm font-semibold text-white mb-3">Avg FA Salary by WAR Tier</h2>
            <ResponsiveContainer width="100%" height={320}>
              <BarChart data={market.buckets} margin={{ top: 10, right: 20, bottom: 20, left: 20 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
                <XAxis dataKey="label" tick={{ fill: '#94a3b8', fontSize: 11 }} />
                <YAxis
                  tickFormatter={(v) => formatMoney(v)}
                  tick={{ fill: '#94a3b8', fontSize: 11 }}
                  label={{ value: 'Avg FA salary', angle: -90, position: 'insideLeft', offset: 10, fill: '#64748b', fontSize: 11 }}
                />
                <Tooltip content={<BucketTooltip />} />
                <Bar dataKey="avgPrice" radius={[4, 4, 0, 0]}>
                  {market.buckets.map((entry, i) => (
                    <Cell key={i} fill={BUCKET_COLORS[i] || '#3b82f6'} fillOpacity={0.8} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
            <p className="text-xs text-slate-500 mt-2">
              Average salary of FA-sample signings per WAR bucket — a model-free look at the same market the line is fitted on.
            </p>

            {/* Tier breakdown table */}
            <div className="mt-4">
              <table className="w-full text-xs">
                <thead>
                  <tr className="text-slate-500 border-b border-slate-800">
                    <th className="text-left py-1">FA Tier</th>
                    <th className="text-right py-1">Players</th>
                    <th className="text-right py-1">WAR Range</th>
                    <th className="text-right py-1">Avg Salary</th>
                  </tr>
                </thead>
                <tbody>
                  {market.tiers.map((tier, i) => (
                    <tr key={i} className="border-b border-slate-800/50 text-slate-300">
                      <td className="py-1.5 font-medium">{tier.label}</td>
                      <td className="text-right">{tier.count}</td>
                      <td className="text-right">{tier.minWAR.toFixed(1)} - {tier.maxWAR.toFixed(1)}</td>
                      <td className="text-right text-green-400">{formatMoney(tier.avgPrice)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </div>

        {/* Player Valuation Table */}
        <div className="bg-slate-900 rounded-lg border border-slate-800 p-4">
          <div className="flex items-center justify-between mb-3">
            <h2 className="text-sm font-semibold text-white flex items-center gap-2">
              <TrendingUp size={16} className="text-green-400" />
              Player Valuations
            </h2>
            <div className="flex items-center gap-2">
              <select
                value={filterType}
                onChange={(e) => setFilterType(e.target.value)}
                className="bg-slate-800 text-white text-xs rounded px-2 py-1.5 border border-slate-700 focus:border-blue-500 focus:outline-none"
              >
                <option value="ALL">All Players</option>
                <option value="CONTRACT">Under Contract</option>
                <option value="IFA">International FA</option>
                <option value="FREE_AGENT">Unsigned FA</option>
                <option value="MLB">MLB Only</option>
                <option value="PROSPECT">Prospects Only</option>
              </select>

              <div className="relative">
                <Search size={14} className="absolute left-2 top-1/2 -translate-y-1/2 text-slate-500" />
                <input
                  type="text"
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                  placeholder="Search name or org..."
                  className="bg-slate-800 text-white text-xs rounded pl-7 pr-3 py-1.5 w-48 border border-slate-700 focus:border-blue-500 focus:outline-none placeholder-slate-500"
                />
              </div>
            </div>
          </div>

          <div className="overflow-x-auto max-h-[500px] overflow-y-auto">
            <table className="w-full text-xs">
              <thead className="sticky top-0 bg-slate-900 z-10">
                <tr className="text-slate-500 border-b border-slate-700">
                  <Th col="Name" label="Name" current={sortKey} dir={sortDir} onClick={handleSort} />
                  <Th col="_playerType" label="Type" current={sortKey} dir={sortDir} onClick={handleSort} />
                  <Th col="POS" label="Pos" current={sortKey} dir={sortDir} onClick={handleSort} />
                  <Th col="ORG" label="Org" current={sortKey} dir={sortDir} onClick={handleSort} />
                  <Th col="Lev" label="Lev" current={sortKey} dir={sortDir} onClick={handleSort} />
                  <Th col="Age" label="Age" current={sortKey} dir={sortDir} onClick={handleSort} />
                  <Th col="_war" label="WAR" current={sortKey} dir={sortDir} onClick={handleSort} />
                  <Th col="_fvScale" label="FV" current={sortKey} dir={sortDir} onClick={handleSort} />
                  <Th col="Price" label="Salary" current={sortKey} dir={sortDir} onClick={handleSort} />
                  <Th col="_annualValue" label="Line Value" current={sortKey} dir={sortDir} onClick={handleSort} />
                  <Th col="_surplus" label="Line Surplus" current={sortKey} dir={sortDir} onClick={handleSort} />
                  <Th col="_mktTier" label="Tier" current={sortKey} dir={sortDir} onClick={handleSort} />
                  <Th col="_mktPrice" label="Mkt Price" current={sortKey} dir={sortDir} onClick={handleSort} />
                  <Th col="_mktSurplus" label="Mkt Surplus" current={sortKey} dir={sortDir} onClick={handleSort} />
                  <Th col="_ctrYears" label="Ctr Yrs" current={sortKey} dir={sortDir} onClick={handleSort} />
                  <Th col="_ctrSurplus" label="Ctr Surplus" current={sortKey} dir={sortDir} onClick={handleSort} />
                  <Th col="_offerMid" label="Fair AAV" current={sortKey} dir={sortDir} onClick={handleSort} />
                  <Th col="_offerFloor" label="Offer Low" current={sortKey} dir={sortDir} onClick={handleSort} />
                  <Th col="_offerCeiling" label="Offer High" current={sortKey} dir={sortDir} onClick={handleSort} />
                </tr>
              </thead>
              <tbody>
                {filteredPlayers.slice(0, 500).map((p, i) => (
                  <tr
                    key={p.ID || i}
                    onClick={() => (selectedPlayer?.ID === p.ID && selectedPlayer?._playerType === p._playerType ? clear() : select(p, kindOf(p)))}
                    className={`border-b border-slate-800/50 hover:bg-slate-800/50 cursor-pointer transition-colors ${
                      selectedPlayer?.ID === p.ID ? 'bg-blue-900/20' : ''
                    }`}
                  >
                    <td className="py-1.5 px-2 font-medium text-white whitespace-nowrap">{p.Name}</td>
                    <td className="py-1.5 px-2 text-slate-400">{p._playerType}</td>
                    <td className="py-1.5 px-2 text-slate-300">{p.POS}</td>
                    <td className="py-1.5 px-2 text-slate-400 whitespace-nowrap max-w-[120px] truncate">{p.ORG || '-'}</td>
                    <td className={`py-1.5 px-2 ${p.Lev === 'INT' ? 'text-yellow-400 font-semibold' : 'text-slate-400'}`}>{p.Lev || '-'}</td>
                    <td className="py-1.5 px-2 text-slate-300">{p.Age}</td>
                    <td className={`py-1.5 px-2 font-mono ${waaColor(p._war)}`}>{p._war.toFixed(1)}</td>
                    <td className={`py-1.5 px-2 font-mono ${fvColor(p._fvScale)}`}>{p._fvScale || '-'}</td>
                    <td className="py-1.5 px-2 text-green-400 font-mono">{p.Price > 0 ? formatMoney(p.Price) : '-'}</td>
                    <td className="py-1.5 px-2 text-slate-300 font-mono">{formatMoney(p._annualValue)}</td>
                    <td className={`py-1.5 px-2 font-mono ${surplusColor(p._surplus)}`}>{p.Price > 0 ? formatMoney(p._surplus) : '-'}</td>
                    <td className={`py-1.5 px-2 ${p._mktTier === 'scarcity' ? 'text-amber-400 font-semibold' : 'text-slate-500'}`}>
                      {p._mktTier === 'scarcity' ? 'Scarcity' : 'Line'}
                    </td>
                    <td className="py-1.5 px-2 text-amber-300 font-mono">{formatMoney(p._mktPrice)}</td>
                    <td className={`py-1.5 px-2 font-mono ${surplusColor(p._mktSurplus)}`}>{p.Price > 0 ? formatMoney(p._mktSurplus) : '-'}</td>
                    <td className="py-1.5 px-2 text-slate-400 font-mono">{p._ctrYears || '-'}</td>
                    <td className={`py-1.5 px-2 font-mono font-semibold ${p._ctrSurplus === null ? 'text-slate-600' : surplusColor(p._ctrSurplus)}`}>
                      {p._ctrSurplus === null ? '-' : formatMoney(p._ctrSurplus)}
                    </td>
                    <td className="py-1.5 px-2 text-green-400 font-mono">{formatMoney(p._offerMid)}</td>
                    <td className="py-1.5 px-2 text-slate-400 font-mono">{formatMoney(p._offerFloor)}</td>
                    <td className="py-1.5 px-2 text-yellow-300 font-mono">{formatMoney(p._offerCeiling)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <p className="text-xs text-slate-500 mt-2">
            Showing {Math.min(filteredPlayers.length, 500)} of {filteredPlayers.length} players |
            Line Value/Surplus = the fitted line (replaceable-tier economy) |
            Mkt Price/Surplus = tier-local fit of comparable-WAR signings (what the market actually pays; departs the line in the scarcity tier) |
            Ctr Surplus = Σ (aged-WAR line value − salary) × 0.97^yr over the remaining contract |
            Fair AAV = tier-local price at the mean aged WAR over the proposed years
          </p>
        </div>

        {/* Selected Player Detail */}
        {selectedCurrent && selectedCurrent._valuation && (
          <PlayerValuationDetail player={selectedCurrent} />
        )}
      </div>
    </div>
  );
}

// ============================================================
// SUB-COMPONENTS
// ============================================================

function StatCard({ label, value, sub, color }) {
  return (
    <div className="bg-slate-900 rounded-lg border border-slate-800 p-3">
      <p className="text-xs text-slate-500 uppercase tracking-wider">{label}</p>
      <p className={`text-xl font-bold mt-1 ${color}`}>{value}</p>
      <p className="text-xs text-slate-600 mt-0.5">{sub}</p>
    </div>
  );
}

function Th({ col, label, current, dir, onClick }) {
  return (
    <th
      className="py-2 px-2 text-right cursor-pointer hover:text-slate-300 select-none whitespace-nowrap"
      onClick={() => onClick(col)}
    >
      <span className="inline-flex items-center gap-0.5">
        {label}
        {current === col && (
          dir === 'desc' ? <ChevronDown size={10} /> : <ChevronUp size={10} />
        )}
      </span>
    </th>
  );
}

function ScatterTooltip({ active, payload }) {
  if (!active || !payload?.length) return null;
  const d = payload[0]?.payload;
  if (!d) return null;

  return (
    <div className="bg-slate-800 border border-slate-700 rounded-lg p-2 text-xs shadow-lg">
      <p className="font-semibold text-white">{d.name}</p>
      <p className="text-slate-400">{d.pos} | Age {d.age}</p>
      <p className="text-green-400">Salary: {formatMoney(d.price)}</p>
      <p className="text-blue-400">WAR: {d.war.toFixed(1)}</p>
      {d.isFA && <p className="text-cyan-400 mt-1">FA signing (in fit sample)</p>}
      {!d.isFA && d.isPreArb && <p className="text-yellow-400 mt-1">Pre-arb (excluded from fit)</p>}
      {!d.isFA && !d.isPreArb && <p className="text-slate-500 mt-1">Arb/extension (excluded from fit)</p>}
    </div>
  );
}

function BucketTooltip({ active, payload }) {
  if (!active || !payload?.length) return null;
  const d = payload[0]?.payload;
  if (!d) return null;

  return (
    <div className="bg-slate-800 border border-slate-700 rounded-lg p-2 text-xs shadow-lg">
      <p className="font-semibold text-white">{d.label} WAR</p>
      <p className="text-slate-400">{d.faCount} FA signings ({d.count} MLB total)</p>
      <p className="text-green-400">Avg FA Salary: {formatMoney(d.avgPrice)}</p>
    </div>
  );
}

function PlayerValuationDetail({ player }) {
  const val = player._valuation;
  const rate = val.rateUsed;

  return (
    <div className="bg-slate-900 rounded-lg border border-blue-800/50 p-4">
      <div className="flex items-start justify-between mb-4">
        <div>
          <h3 className="text-lg font-bold text-white">{player.Name}</h3>
          <p className="text-sm text-slate-400">
            {player.POS} | {player.ORG || 'Free Agent'} | {player.Lev} | Age {player.Age} | {player._playerType}
          </p>
        </div>
        <div className="text-right">
          <p className="text-xs text-slate-500">FV Scale</p>
          <p className={`text-2xl font-bold ${fvColor(player._fvScale)}`}>{player._fvScale}</p>
        </div>
      </div>

      <div className="grid grid-cols-7 gap-3 mb-4">
        <MiniStat label="Current WAR" value={val.warNow.toFixed(1)} color={waaColor(val.warNow)} />
        {/* Remaining team control — the horizon behind the offer table below. */}
        <MiniStat
          label="Control"
          value={formatControl(val.control)}
          color={val.control.source === 'default' ? 'text-amber-400' : 'text-slate-300'}
        />
        <MiniStat label="Current Salary" value={formatMoney(player.Price)} color="text-green-400" />
        <MiniStat
          label={val.tier === 'scarcity' ? 'Line Value (understates tier)' : 'Line Value — replaceable tier'}
          value={formatMoney(val.annualValue)}
          color="text-cyan-400"
        />
        <MiniStat
          label={val.tier === 'scarcity' ? 'Market Price — scarcity tier' : 'Market Price (≈ line)'}
          value={formatMoney(val.marketPrice)}
          color="text-amber-300"
        />
        <MiniStat
          label={val.contract ? `Contract Surplus (${val.contract.yearsRemaining} yr)` : 'Yr Surplus (line)'}
          value={formatMoney(val.contract ? val.contract.surplus : val.surplus)}
          color={(val.contract ? val.contract.surplus : val.surplus) >= 0 ? 'text-green-400' : 'text-red-400'}
        />
        <MiniStat label="Rate Used" value={rate.curv ? `${formatMoney(rate.slope)}/W + ${formatMoney(rate.curv)}/W² + ${formatMoney(rate.floor)}` : `${formatMoney(rate.slope)}/W + ${formatMoney(rate.floor)}`} color="text-slate-300" />
      </div>

      {/* Scarcity-tier context (copy only — the numbers above are all fitted) */}
      {val.tier === 'scarcity' && (
        <p className="text-xs text-amber-300/90 bg-amber-900/15 border border-amber-800/40 rounded px-3 py-2 mb-4">
          Scarcity tier: comparable-WAR players sign for more than the global line predicts
          (local price departs the line by over 1 residual SD). Retention pricing at this tier
          reflects outside bidders (NPB clubs bid cash) and the engine&apos;s demand anchors —
          judge his salary against the tier-local market price, not the line.
        </p>
      )}

      {/* Contract year-by-year */}
      {val.contract && (
        <div className="bg-slate-800 rounded-lg p-3 mb-4">
          <p className="text-xs text-slate-500 uppercase tracking-wider mb-2">
            Remaining Contract — aged WAR vs salary (3%/yr time discount)
          </p>
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="text-slate-500 border-b border-slate-700">
                  <th className="text-left py-1 px-2">Yr</th>
                  <th className="text-right py-1 px-2">Age</th>
                  <th className="text-right py-1 px-2">Aged WAR</th>
                  <th className="text-right py-1 px-2">Market Value</th>
                  <th className="text-right py-1 px-2">Salary</th>
                  <th className="text-right py-1 px-2">Surplus</th>
                  <th className="text-right py-1 px-2">Disc. Surplus</th>
                </tr>
              </thead>
              <tbody>
                {val.contract.years.map((yr) => (
                  <tr key={yr.year} className="border-b border-slate-800/40">
                    <td className="py-1 px-2 text-slate-300">{yr.year}</td>
                    <td className="py-1 px-2 text-right text-slate-400">{yr.age}</td>
                    <td className={`py-1 px-2 text-right font-mono ${waaColor(yr.agedWAR)}`}>{yr.agedWAR.toFixed(1)}</td>
                    <td className="py-1 px-2 text-right font-mono text-cyan-400">{formatMoney(yr.value)}</td>
                    <td className="py-1 px-2 text-right font-mono text-green-400">{formatMoney(yr.salary)}</td>
                    <td className={`py-1 px-2 text-right font-mono ${surplusColor(yr.surplus)}`}>{formatMoney(yr.surplus)}</td>
                    <td className={`py-1 px-2 text-right font-mono ${surplusColor(yr.discSurplus)}`}>{formatMoney(yr.discSurplus)}</td>
                  </tr>
                ))}
              </tbody>
              <tfoot>
                <tr className="border-t border-slate-700 font-semibold">
                  <td className="py-1.5 px-2 text-slate-300" colSpan={3}>Total</td>
                  <td className="py-1.5 px-2 text-right font-mono text-cyan-400">{formatMoney(val.contract.totalValue)}</td>
                  <td className="py-1.5 px-2 text-right font-mono text-green-400">{formatMoney(val.contract.totalSalary)}</td>
                  <td />
                  <td className={`py-1.5 px-2 text-right font-mono ${surplusColor(val.contract.surplus)}`}>
                    {formatMoney(val.contract.surplus)}
                  </td>
                </tr>
              </tfoot>
            </table>
          </div>
        </div>
      )}

      {/* Fair offer by contract length */}
      {val.offerByLength && val.offerByLength.length > 0 && (
        <div className="bg-slate-800 rounded-lg p-3 mb-4">
          <p className="text-xs text-slate-500 uppercase tracking-wider mb-2">
            Fair Offer by Contract Length — tier-local: AAV = local fit of comparable-WAR signings at the mean aged WAR; band = ±1 LOCAL residual SD (falls back to the line ± {formatMoney(rate.residSD)} if the tier is too thin)
          </p>
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="text-slate-500 border-b border-slate-700">
                  <th className="text-left py-1 px-2">Years</th>
                  <th className="text-right py-1 px-2">Mean Aged WAR</th>
                  <th className="text-right py-1 px-2">Low AAV</th>
                  <th className="text-right py-1 px-2">Fair AAV</th>
                  <th className="text-right py-1 px-2">High AAV</th>
                  <th className="text-right py-1 px-2">Fair Total</th>
                </tr>
              </thead>
              <tbody>
                {val.offerByLength.map((o) => (
                  <tr key={o.years} className={`border-b border-slate-800/40 ${o.years === val.offerYears ? 'bg-blue-900/20' : ''}`}>
                    <td className="py-1 px-2 text-slate-300">{o.years}{o.years === val.offerYears ? ' *' : ''}</td>
                    <td className={`py-1 px-2 text-right font-mono ${waaColor(o.meanWAR)}`}>{o.meanWAR.toFixed(1)}</td>
                    <td className="py-1 px-2 text-right font-mono text-slate-400">{formatMoney(o.low ?? Math.max(0, o.aav - rate.residSD))}</td>
                    <td className="py-1 px-2 text-right font-mono text-green-400 font-semibold">{formatMoney(o.aav)}</td>
                    <td className="py-1 px-2 text-right font-mono text-yellow-300">{formatMoney(o.high ?? (o.aav + rate.residSD))}</td>
                    <td className="py-1 px-2 text-right font-mono text-cyan-400">{formatMoney(o.total)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="text-[10px] text-slate-500 mt-1">
            * default horizon ({val.offerYears} yrs — this player&apos;s remaining control
            {val.control.serviceYears !== null && `, ${val.control.serviceYears.toFixed(1)} svc yrs`}
            {val.control.contractYears !== null && `, ${val.control.contractYears} yr left on the deal`}
            {val.control.source === 'default' && ' — NO service data, 6-yr fallback'}
            , clipped at career end)
          </p>
        </div>
      )}

      {/* Year-by-year career projection */}
      {val.yearlyValues && val.yearlyValues.length > 0 && (
        <div>
          <p className="text-xs text-slate-500 uppercase tracking-wider mb-2">
            Career Projection (at {formatMoney(rate.slope)}/WAR{rate.curv ? ` + ${formatMoney(rate.curv)}/WAR²` : ''} + {formatMoney(rate.floor)} floor)
          </p>
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="text-slate-500 border-b border-slate-800">
                  <th className="text-left py-1 px-2">Age</th>
                  <th className="text-right py-1 px-2">Proj WAR</th>
                  <th className="text-right py-1 px-2">Year Value (disc.)</th>
                </tr>
              </thead>
              <tbody>
                {val.yearlyValues.map((yr, i) => (
                  <tr key={i} className={`border-b border-slate-800/30 ${yr.rawWAA > 0 ? '' : 'opacity-40'}`}>
                    <td className="py-1 px-2 text-slate-300">{yr.age}</td>
                    <td className={`py-1 px-2 text-right font-mono ${waaColor(yr.rawWAA)}`}>{yr.rawWAA.toFixed(1)}</td>
                    <td className="py-1 px-2 text-right font-mono text-green-400">{formatMoney(yr.yearValue)}</td>
                  </tr>
                ))}
              </tbody>
              <tfoot>
                <tr className="border-t border-slate-700 font-semibold">
                  <td className="py-1.5 px-2 text-slate-300" colSpan={2}>Total</td>
                  <td className="py-1.5 px-2 text-right font-mono text-cyan-400">
                    {formatMoney(val.totalValue)}
                  </td>
                </tr>
              </tfoot>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}

function MiniStat({ label, value, color }) {
  return (
    <div>
      <p className="text-xs text-slate-500">{label}</p>
      <p className={`text-sm font-semibold ${color}`}>{value}</p>
    </div>
  );
}

// ============================================================
// HELPERS
// ============================================================

function waaColor(waa) {
  if (waa >= 3) return 'text-purple-400';
  if (waa >= 1.5) return 'text-cyan-400';
  if (waa >= 0) return 'text-green-400';
  if (waa >= -1) return 'text-orange-400';
  return 'text-red-400';
}

function surplusColor(v) {
  if (v > 0) return 'text-green-400';
  if (v < 0) return 'text-red-400';
  return 'text-slate-500';
}

function fvColor(fv) {
  if (fv >= 70) return 'text-purple-400';
  if (fv >= 60) return 'text-cyan-400';
  if (fv >= 50) return 'text-green-400';
  if (fv >= 40) return 'text-yellow-300';
  return 'text-red-400';
}

const BUCKET_COLORS = ['#64748b', '#3b82f6', '#06b6d4', '#22c55e', '#f59e0b', '#a855f7'];
