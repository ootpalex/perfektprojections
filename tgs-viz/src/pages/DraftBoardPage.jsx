import React, { useState, useMemo } from 'react';
import { usePlayersWithFV, usePlayersWithDraftFV, usePlayersWithG5FV, usePlayersWithHybridFV } from '../hooks/usePlayerData';
import PlayerDetail from '../components/PlayerDetail';
import { useSelectedById } from '../hooks/useSelectedById';
import { formatCellValue, getCellColorClass } from '../lib/columns';
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Cell, ScatterChart, Scatter, ZAxis } from 'recharts';
import { TrendingUp, Users, Zap, Download } from 'lucide-react';

export default function DraftBoardPage({ hitters, pitchers, allHitters, allPitchers }) {
  const [viewMode, setViewMode] = useState('combined'); // combined, hitters, pitchers
  const [sortBy, setSortBy] = useState('_draftRawFV'); // default to Draft FV Raw
  const [maxAge, setMaxAge] = useState(30);
  const [minFV, setMinFV] = useState(20);
  const [hideWrecked, setHideWrecked] = useState(true);
  const [hideImpossible, setHideImpossible] = useState(true);

  // Chain: raw data → FV → Draft FV → G5 → Hybrid
  const hittersWithFV = usePlayersWithFV(hitters);
  const pitchersWithFV = usePlayersWithFV(pitchers);
  const hittersWithDraftFV = usePlayersWithDraftFV(hittersWithFV, allHitters || [], 'hitter');
  const pitchersWithDraftFV = usePlayersWithDraftFV(pitchersWithFV, allPitchers || [], 'pitcher');
  const hittersWithG5 = usePlayersWithG5FV(hittersWithDraftFV, allHitters || [], 'hitter');
  const pitchersWithG5 = usePlayersWithG5FV(pitchersWithDraftFV, allPitchers || [], 'pitcher');
  const hittersWithHybrid = usePlayersWithHybridFV(hittersWithG5);
  const pitchersWithHybrid = usePlayersWithHybridFV(pitchersWithG5);
  // The open card is kept by player ID and found again in the current rows.
  const rowsByKind = useMemo(() => ({ hitter: hittersWithHybrid, pitcher: pitchersWithHybrid }), [hittersWithHybrid, pitchersWithHybrid]);
  const { selected: selectedPlayer, kind: playerType, select, clear } = useSelectedById(rowsByKind);

  // Combined and sorted draft board
  const draftBoard = useMemo(() => {
    let players = [];

    if (viewMode !== 'pitchers') {
      players.push(...hittersWithHybrid.map(p => ({ ...p, _type: 'H' })));
    }
    if (viewMode !== 'hitters') {
      players.push(...pitchersWithHybrid.map(p => ({ ...p, _type: 'P' })));
    }

    // Filter (draft files are already pre-filtered to draftable players by extract_data.py)
    players = players.filter(p => {
      if (!p.Name) return false;
      const age = parseFloat(p.Age) || 99;
      const fv = p._fvScale || 0;
      if (age > maxAge || fv < minFV) return false;
      if (hideWrecked && p._wrecked) return false;
      if (hideImpossible && p.DEM === 'Impossible' && (p._draftFV || 0) < 60) return false;
      if (p._draftCeiling === null) return false; // no projection data at all
      return true;
    });

    // Sort — players with raw ceiling > 0 always rank above players with ceiling <= 0
    players.sort((a, b) => {
      const aAbove = (a._draftCeiling ?? -Infinity) > 0;
      const bAbove = (b._draftCeiling ?? -Infinity) > 0;
      if (aAbove !== bAbove) return aAbove ? -1 : 1;
      const aVal = parseFloat(a[sortBy]) || 0;
      const bVal = parseFloat(b[sortBy]) || 0;
      return bVal - aVal;
    });

    return players.slice(0, 200);
  }, [hittersWithHybrid, pitchersWithHybrid, viewMode, sortBy, maxAge, minFV, hideWrecked, hideImpossible]);

  // Age distribution chart
  const ageDistribution = useMemo(() => {
    const buckets = {};
    draftBoard.forEach(p => {
      const age = Math.round(parseFloat(p.Age) || 0);
      if (!buckets[age]) buckets[age] = { age, hitters: 0, pitchers: 0 };
      if (p._type === 'H') buckets[age].hitters++;
      else buckets[age].pitchers++;
    });
    return Object.values(buckets).sort((a, b) => a.age - b.age);
  }, [draftBoard]);

  // Draft FV vs Age scatter
  const scatterData = useMemo(() => {
    return draftBoard.slice(0, 100).map(p => ({
      age: parseFloat(p.Age) || 0,
      fv: p._draftRawFV || 0,
      name: p.Name,
      type: p._type,
      pos: p.POS,
    }));
  }, [draftBoard]);

  const fvColor = (fv) => {
    if (fv >= 70) return '#8b5cf6';
    if (fv >= 60) return '#06b6d4';
    if (fv >= 55) return '#22c55e';
    if (fv >= 50) return '#eab308';
    if (fv >= 45) return '#f97316';
    return '#94a3b8';
  };

  const durColor = (prone) => {
    const map = { 'Wrecked': '#f87171', 'Fragile': '#fb923c', 'Normal': '#cbd5e1', 'Durable': '#4ade80', 'Iron Man': '#22d3ee' };
    return map[prone] || '#cbd5e1';
  };

  const exportDraftList = () => {
    const csv = draftBoard.map(p => p.ID || '').join('\n');
    const blob = new Blob([csv], { type: 'text/csv' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'draft_board.csv';
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="h-full flex flex-col overflow-auto">
      <div className="p-4">
        <h1 className="text-2xl font-bold text-white">Draft Board</h1>
        <p className="text-sm text-slate-400 mt-1">
          Draft FV: age percentile 30% + ceiling 60% + projected peak 10%, all in WAA | Fragile, work ethic and intelligence adjust it
          <span className="block text-xs text-slate-500 mt-0.5">
            Value columns display WAA (vs average). <b>Ceiling</b> = best case, no haircut. <b>Proj Peak</b> = where we project him to top out (Proj Potential): from the ML model when the row has it (his WAA today + the ML median gain, washouts counted), else his WAA today + the DEV cell gain or the measured curve. Ceiling is the payoff, Age Pctl is the probability.
          </span>
        </p>
      </div>

      {/* Controls */}
      <div className="flex flex-wrap items-center gap-3 px-4 pb-3">
        <div className="flex gap-1 bg-slate-800 rounded-lg p-0.5">
          {['combined', 'hitters', 'pitchers'].map(mode => (
            <button key={mode} onClick={() => setViewMode(mode)}
              className={`px-3 py-1.5 text-xs font-medium rounded-md transition-all ${
                viewMode === mode ? 'bg-blue-600 text-white' : 'text-slate-400 hover:text-white'
              }`}>
              {mode.charAt(0).toUpperCase() + mode.slice(1)}
            </button>
          ))}
        </div>

        <select value={sortBy} onChange={e => setSortBy(e.target.value)}
          className="py-1.5 px-2 bg-slate-800 border border-slate-600 rounded-lg text-sm text-slate-200">
          <option value="_draftRawFV">Sort by Draft FV</option>
          <option value="_draftCeilingWAA">Sort by Ceiling (WAA)</option>
          <option value="_agePercentile">Sort by Age Percentile</option>
          <option value="_futureValue">Sort by Future Value</option>
          <option value="_fvScale">Sort by FV (20-80)</option>
          <option value="_g5FV">Sort by G5 FV (Peak)</option>
          <option value="_hybridFV">Sort by Hybrid FV</option>
          <option value="_potentialWAA">Sort by Proj Peak (WAA)</option>
          <option value="_peakWAA">Sort by Peak WAA</option>
        </select>

        <div className="flex items-center gap-2">
          <label className="text-xs text-slate-500">Max Age:</label>
          <input type="range" min="16" max="35" value={maxAge} onChange={e => setMaxAge(parseInt(e.target.value))}
            className="w-24" />
          <span className="text-sm text-slate-300 w-6">{maxAge}</span>
        </div>

        <div className="flex items-center gap-2">
          <label className="text-xs text-slate-500">Min FV:</label>
          <input type="range" min="20" max="70" step="5" value={minFV} onChange={e => setMinFV(parseInt(e.target.value))}
            className="w-24" />
          <span className="text-sm text-slate-300 w-6">{minFV}</span>
        </div>

        <label className="flex items-center gap-1.5 text-xs text-slate-400 cursor-pointer">
          <input type="checkbox" checked={hideWrecked} onChange={e => setHideWrecked(e.target.checked)}
            className="rounded border-slate-600" />
          Hide Wrecked
        </label>

        <label className="flex items-center gap-1.5 text-xs text-slate-400 cursor-pointer">
          <input type="checkbox" checked={hideImpossible} onChange={e => setHideImpossible(e.target.checked)}
            className="rounded border-slate-600" />
          Hide Impossible (&lt;60)
        </label>

        <span className="ml-auto text-xs text-slate-500">{draftBoard.length} prospects</span>

        <button onClick={exportDraftList}
          className="flex items-center gap-1.5 px-3 py-1.5 bg-green-700 hover:bg-green-600 text-white text-xs font-medium rounded-lg transition-colors"
          title="Export draft list as CSV (with player IDs for StatsPlus)">
          <Download size={14} />
          Export CSV
        </button>
      </div>

      {/* Charts Row */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 px-4 pb-4">
        <div className="bg-slate-800/50 rounded-lg p-3">
          <h3 className="text-xs font-semibold text-slate-400 uppercase mb-2">Draft FV vs Age</h3>
          <ResponsiveContainer width="100%" height={200}>
            <ScatterChart margin={{ top: 5, right: 10, bottom: 5, left: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
              <XAxis dataKey="age" type="number" domain={['dataMin - 1', 'dataMax + 1']}
                tick={{ fill: '#94a3b8', fontSize: 11 }} name="Age" />
              <YAxis dataKey="fv" tick={{ fill: '#94a3b8', fontSize: 11 }} name="Draft FV (Raw)" />
              <ZAxis range={[30, 30]} />
              <Tooltip
                contentStyle={{ background: '#1e293b', border: '1px solid #475569', borderRadius: 8 }}
                labelStyle={{ color: '#e2e8f0' }}
                formatter={(value, name) => [typeof value === 'number' ? value.toFixed(1) : value, name]}
                labelFormatter={(label) => `Age: ${label}`}
              />
              <Scatter data={scatterData.filter(d => d.type === 'H')} fill="#3b82f6" name="Hitters" />
              <Scatter data={scatterData.filter(d => d.type === 'P')} fill="#f59e0b" name="Pitchers" />
            </ScatterChart>
          </ResponsiveContainer>
          <div className="flex justify-center gap-4 text-xs mt-1">
            <span className="text-blue-400">Hitters</span>
            <span className="text-amber-400">Pitchers</span>
          </div>
        </div>

        <div className="bg-slate-800/50 rounded-lg p-3">
          <h3 className="text-xs font-semibold text-slate-400 uppercase mb-2">Age Distribution</h3>
          <ResponsiveContainer width="100%" height={200}>
            <BarChart data={ageDistribution}>
              <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
              <XAxis dataKey="age" tick={{ fill: '#94a3b8', fontSize: 11 }} />
              <YAxis tick={{ fill: '#94a3b8', fontSize: 10 }} />
              <Tooltip contentStyle={{ background: '#1e293b', border: '1px solid #475569', borderRadius: 8 }} />
              <Bar dataKey="hitters" stackId="a" fill="#3b82f6" name="Hitters" />
              <Bar dataKey="pitchers" stackId="a" fill="#f59e0b" name="Pitchers" radius={[4, 4, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>

      {/* Draft Board Table */}
      <div className="flex-1 px-4 pb-4">
        <div className="table-container" style={{ maxHeight: 'calc(100vh - 520px)' }}>
          <table className="data-table">
            <thead>
              <tr>
                <th className="w-16">ID</th>
                <th className="w-10">#</th>
                <th>Type</th>
                <th>Name</th>
                <th>POS</th>
                <th>ORG</th>
                <th>Age</th>
                <th title="age percentile x 0.30 + ceiling x 0.70, then the durability / work-ethic / intelligence modifiers.">Draft FV</th>
                <th title="Percentile vs the whole league at this age, on current performance. The PROBABILITY half of Draft FV.">Age Pctl</th>
                <th title="Best-case peak, WAA (vs average) — the sheet's own MAX WAA P / WAP. No risk haircut. The PAYOFF half of Draft FV. (Draft FV itself scores this in WAR so bats, SP and RP share one scale.)">Ceiling</th>
                <th>Durability</th>
                <th>INT</th>
                <th className="border-l border-slate-700">FV</th>
                <th>Future$</th>
                <th>G5 FV</th>
                <th>G5 Peak</th>
                <th>Dev%</th>
                <th className="border-l border-slate-700">Hybrid</th>
                <th title="Proj Potential, WAA: where we project him to top out. From the ML model when the row has it (his WAA today + the ML median gain, washouts counted), else his WAA today + the DEV cell gain or the measured curve.">Proj Peak</th>
              </tr>
            </thead>
            <tbody>
              {draftBoard.map((player, idx) => (
                <tr key={player.ID || player.Name || idx}
                  className={`cursor-pointer hover:bg-slate-800 ${player._wrecked ? 'opacity-40 line-through' : ''}`}
                  onClick={() => select(player, player._type === 'H' ? 'hitter' : 'pitcher')}>
                  <td className="text-slate-600 font-mono text-xs">{player.ID}</td>
                  <td className="text-slate-500 font-mono">{idx + 1}</td>
                  <td>
                    <span className={`px-1.5 py-0.5 rounded text-xs font-bold ${
                      player._type === 'H' ? 'bg-blue-900/50 text-blue-400' : 'bg-amber-900/50 text-amber-400'
                    }`}>
                      {player._type}
                    </span>
                  </td>
                  <td className="font-medium text-white">
                    {player.Name}
                    {(player['Bat Peak'] != null || player['Arm Peak'] != null) && (
                      <span className="ml-1.5 px-1 rounded text-xs font-bold bg-purple-900/50 text-purple-300"
                        title={`Genuine two-way threat — ${player['Bat Peak'] != null ? 'bat' : 'arm'} also peaks at +${player['Bat Peak'] ?? player['Arm Peak']} WAA`}>
                        2W
                      </span>
                    )}
                  </td>
                  <td>{player.POS}</td>
                  <td className="text-slate-400">{player.ORG}</td>
                  <td>{Math.round(parseFloat(player.Age) || 0)}</td>
                  <td>
                    <span className="px-2 py-0.5 rounded font-bold text-sm"
                      style={{ color: fvColor(player._draftFV), background: `${fvColor(player._draftFV)}15` }}>
                      {formatCellValue(player._draftRawFV, '_draftRawFV')}
                    </span>
                  </td>
                  <td className={getCellColorClass(player._agePercentile, '_agePercentile')}>
                    {formatCellValue(player._agePercentile, '_agePercentile')}
                  </td>
                  <td className={getCellColorClass(player._draftCeilingWAA, '_draftCeilingWAA')}
                    title={`WAR basis (what Draft FV scores): ${formatCellValue(player._draftCeiling, '_draftCeiling')}`}>
                    {formatCellValue(player._draftCeilingWAA, '_draftCeilingWAA')}
                  </td>
                  <td style={{ color: durColor(player._durability) }} className="text-xs">
                    {player._durability}
                    {player._weBoost && <span className="ml-1 text-green-400" title="High Work Ethic (+5%)">+WE</span>}
                  </td>
                  <td className={getCellColorClass(player._highINT, '_highINT')}>
                    {formatCellValue(player._highINT, '_highINT')}
                  </td>
                  <td className="border-l border-slate-700">
                    <span className="px-1.5 py-0.5 rounded text-xs"
                      style={{ color: fvColor(player._fvScale), background: `${fvColor(player._fvScale)}10` }}>
                      {player._fvScale}
                    </span>
                  </td>
                  <td className={getCellColorClass(player._futureValue, '_futureValue')}>
                    {formatCellValue(player._futureValue, '_futureValue')}
                  </td>
                  <td>
                    <span className="px-1.5 py-0.5 rounded text-xs"
                      style={{ color: fvColor(player._g5FV), background: `${fvColor(player._g5FV)}10` }}>
                      {player._g5FV}
                    </span>
                  </td>
                  <td className={getCellColorClass(player._g5Raw, '_g5Raw')}>
                    {formatCellValue(player._g5Raw, '_g5Raw')}
                  </td>
                  <td className={getCellColorClass(player._g5DevPct, '_g5DevPct')}>
                    {formatCellValue(player._g5DevPct, '_g5DevPct')}
                  </td>
                  <td className="border-l border-slate-700">
                    <span className="px-2 py-0.5 rounded font-bold text-sm"
                      style={{ color: fvColor(player._hybridFV), background: `${fvColor(player._hybridFV)}15` }}>
                      {player._hybridFV}
                    </span>
                  </td>
                  <td className={getCellColorClass(player._potentialWAA, '_potentialWAA')}>
                    {formatCellValue(player._potentialWAA, '_potentialWAA')}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
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
