// ============================================================================
// ProspectsPage — ours' Prospects view (ootp-dashboard app/src/components/
// ProspectsView.jsx: The Board + Farm Rankings) on his data and his FV engine.
//
// Ported in ours' Night Scorecard inline-style grammar (theme.js `S`). What
// changed from ours is in docs/phase4/views.md; in short:
//   - FV = his engine's projected peak (usePlayersWithFV `_potentialWAA`, WAA),
//     not ours' v21 curve. "Src" says which path produced it per row.
//   - Value columns are WAA (current / listed potential), not WAR / WAR P.
//   - Dev% is gone (his data ships no DEV percentile curve).
//   - Prospects = in an org, not AMA / FA, under 45 MLB service days (ours' rule).
// ============================================================================
import { useState, useMemo, useCallback, useEffect, useDeferredValue } from 'react';
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from 'recharts';
import { S, TOKENS as T, FV_TIER_COLORS, posColor, levelChip, tierChip, waaStyle, scoutingRatingColor } from '../theme.js';
import { getName, getPos, getLevel, getOrg, getAge, getBestPos, genericSort, passesPositionFilter, passesLevelFilter } from '../lib/accessors.js';
import { levelKey } from '../lib/columns.js';
import { fmt, fmtSigned, fmtAge, paginateRows, searchFilter, orgLabel, playerUid, FV_SOURCE_LABEL, fvSourceCounts } from '../lib/viewFormat.js';
import {
  FV_TIERS, defaultDollarValues, isOrgProspect, isMlbSquad, buildProspectPool, suggestThresholds,
  assignFVTier, getDollarValue, tierStats as calcTierStats, rankPool, countAtOrAbove, calcFarmRankings,
  prospectSettingsKey, fvCurrent,
} from '../lib/prospectTiers.js';
import { leagueOrgs } from '../lib/rosterOptimizer.js';
import { resolveLeagueClubs } from '../lib/leagueClubs.js';
import { usePlayersWithFV } from '../hooks/usePlayerData';
import { useSelectedById } from '../hooks/useSelectedById';
import PlayerDetail from '../components/PlayerDetail';
import { LEAGUE_TEAMS } from './TeamStandingsPage';
import { Section, SortHeader, PillBtn, PositionFilter, LevelFilter, MultiSelectDropdown, TabGroup, Pagination, SearchInput, PageHead, colRule } from '../components/oursUi.jsx';

const PER_PAGE = 50;
const SUB_TABS = [{ id: 'board', label: 'The Board' }, { id: 'farm', label: 'Farm Rankings' }];
const SRC_SHORT = { ML: 'ML', 'DEV cell': 'Cell', 'measured curve': 'Curve', model: 'Model' };

const tierPill = (id) => { const c = tierChip(id); return { ...S.tierPill, background: c.bg, color: c.text }; };
const levelBadge = (lev) => {
  const c = levelChip(LEVEL_NAME[levelKey(lev)] ?? lev);
  return { ...S.badge, background: c.bg, color: c.text, borderColor: c.border, ...(c.borderStyle ? { borderStyle: c.borderStyle } : {}) };
};
// levelKey (his columns.js) folds R+/R-/A- onto ours' level names for the chip.
const LEVEL_NAME = { mlb: 'MLB', aaa: 'AAA', aa: 'AA', aplus: 'A+', a: 'A', r: 'R', int: 'INT' };
const numCell = { textAlign: 'right', fontVariantNumeric: 'tabular-nums' };
const posCell = { fontFamily: T.fonts.narrow, fontWeight: 600, fontSize: 13 };
const cellStyles = (cols) => {
  const m = {};
  cols.forEach((c, i) => {
    m[c.key] = { ...(colRule(cols, i) || {}), ...(i === 0 ? { paddingLeft: 12 } : {}), ...(i === cols.length - 1 ? { paddingRight: 12 } : {}) };
  });
  return m;
};
const edgeWrap = { ...S.tableWrap, margin: -12, border: 'none', borderRadius: 0 };
const footWrap = { margin: '0 -12px -12px' };

function loadSettings(league) {
  try { return JSON.parse(localStorage.getItem(prospectSettingsKey(league)) || 'null'); } catch { return null; }
}
function saveSettings(league, value) {
  try { localStorage.setItem(prospectSettingsKey(league), JSON.stringify(value)); } catch { /* storage unavailable */ }
}

export default function ProspectsPage({ hitters: hittersIn = [], pitchers: pitchersIn = [], metadata, league }) {
  const [subTab, setSubTab] = useState('board');
  const hitters = usePlayersWithFV(hittersIn);
  const pitchers = usePlayersWithFV(pitchersIn);

  // The league's clubs: the same set the standings rank (metadata.clubs, else
  // the page's built-in sets, else any org carrying a real roster).
  const known = useMemo(() => resolveLeagueClubs(metadata, LEAGUE_TEAMS[league]).known, [metadata, league]);
  const teams = useMemo(() => leagueOrgs(hitters, pitchers, known).sort(), [hitters, pitchers, known]);

  // Only the league's own clubs: SSB's rows also carry other leagues' clubs
  // (KBO, NPB), whose players would otherwise fill tiers scaled to 28 teams.
  const prospectPool = useMemo(() => {
    const clubs = new Set(teams);
    const inLeague = (p) => isOrgProspect(p) && clubs.has(getOrg(p));
    return buildProspectPool([...hitters.filter(inLeague), ...pitchers.filter(inLeague)]);
  }, [hitters, pitchers, teams]);

  // Saved per league; none saved → suggested from this pool.
  const [settings, setSettings] = useState(() => ({ league, ...(loadSettings(league) || {}) }));
  useEffect(() => { setSettings({ league, ...(loadSettings(league) || {}) }); }, [league]);
  const dollarValues = settings.dollarValues || defaultDollarValues();
  const suggested = useMemo(() => suggestThresholds(prospectPool, teams.length || 30), [prospectPool, teams.length]);
  const thresholds = settings.thresholds && Object.keys(settings.thresholds).length ? settings.thresholds : suggested;
  const update = useCallback((patch) => {
    setSettings((prev) => {
      const next = { ...prev, ...patch };
      saveSettings(league, { thresholds: next.thresholds, dollarValues: next.dollarValues });
      return next;
    });
  }, [league]);
  const setThresholds = (fn) => update({ thresholds: typeof fn === 'function' ? fn(thresholds) : fn });
  const setDollarValues = (fn) => update({ dollarValues: typeof fn === 'function' ? fn(dollarValues) : fn });

  const [boardOrgFilter, setBoardOrgFilter] = useState([]);
  const [boardTierFilter, setBoardTierFilter] = useState([]);
  const navigateToBoard = useCallback((team, tierId) => {
    setBoardOrgFilter(team ? [team] : []);
    setBoardTierFilter(tierId ? [tierId] : []);
    setSubTab('board');
  }, []);

  const { selected, kind, select, clear } = useSelectedById({ hitter: hitters, pitcher: pitchers });
  const sources = useMemo(() => fvSourceCounts(prospectPool), [prospectPool]);

  return (
    <div style={{ height: '100%', overflow: 'auto', padding: '18px 24px', background: T.bg, color: T.text, fontFamily: T.fonts.ui }}>
      <PageHead title="Prospects"
        sub={<>{prospectPool.length.toLocaleString()} prospects in {teams.length} {league} orgs · FV = projected peak WAA from the FV engine
          {sources.length > 0 && <> ({sources.map((s) => `${s.label} ${s.n.toLocaleString()}`).join(' · ')})</>}</>} />
      <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
        <TabGroup label="Prospect sections" style={{ alignSelf: 'flex-start' }}>
          {SUB_TABS.map((tab) => (
            <PillBtn key={tab.id} active={subTab === tab.id} onClick={() => {
              if (tab.id === 'farm') { setBoardOrgFilter([]); setBoardTierFilter([]); }
              setSubTab(tab.id);
            }}>{tab.label}</PillBtn>
          ))}
        </TabGroup>
        {subTab === 'board' && (
          <ProspectBoard hitters={hitters} pitchers={pitchers} teams={teams} prospectPool={prospectPool}
            thresholds={thresholds} setThresholds={setThresholds} suggested={suggested}
            dollarValues={dollarValues} setDollarValues={setDollarValues}
            orgFilter={boardOrgFilter} setOrgFilter={setBoardOrgFilter}
            tierFilter={boardTierFilter} setTierFilter={setBoardTierFilter}
            onSelectPlayer={(p) => select(p, p._poolType)} />
        )}
        {subTab === 'farm' && (
          <FarmRankings teams={teams} prospectPool={prospectPool} thresholds={thresholds}
            dollarValues={dollarValues} onNavigate={navigateToBoard} />
        )}
      </div>
      {selected && <PlayerDetail player={selected} onClose={clear} type={kind} />}
    </div>
  );
}

function ProspectBoard({ hitters, pitchers, teams, prospectPool, thresholds, setThresholds, suggested, dollarValues, setDollarValues, orgFilter, setOrgFilter, tierFilter, setTierFilter, onSelectPlayer }) {
  const [search, setSearch] = useState('');
  const deferredSearch = useDeferredValue(search);
  const [posFilter, setPosFilter] = useState([]);
  const [levelFilter, setLevelFilter] = useState([]);
  const [sort, setSort] = useState({ col: '_fv', dir: 'desc' });
  const [page, setPage] = useState(0);
  const [configOpen, setConfigOpen] = useState(false);

  // Big-league squad values for the "MLB players at or above this tier" count,
  // on the same scale as the tier cut: the FV engine's current WAA.
  const mlbVals = useMemo(() => [...hitters, ...pitchers].filter(isMlbSquad).map(fvCurrent)
    .filter((v) => v != null).sort((a, b) => b - a), [hitters, pitchers]);

  const tierStats = useMemo(() => calcTierStats(prospectPool, thresholds), [prospectPool, thresholds]);
  const rankedPool = useMemo(() => rankPool(prospectPool, thresholds, dollarValues), [prospectPool, thresholds, dollarValues]);

  const displayPool = useMemo(() => {
    let rows = [...rankedPool];
    rows = searchFilter(rows, deferredSearch);
    if (posFilter.length > 0) rows = rows.filter((r) => passesPositionFilter(r, posFilter));
    if (orgFilter.length > 0) rows = rows.filter((r) => orgFilter.includes(getOrg(r)));
    if (levelFilter.length > 0) rows = rows.filter((r) => passesLevelFilter(r, levelFilter));
    if (tierFilter.length > 0) rows = rows.filter((r) => tierFilter.includes(r._tierId));
    genericSort(rows, sort.col, sort.dir, {
      _fv: (p) => p._fv ?? p._baseVal,
      _currentVal: (p) => p._currentVal,
      _baseVal: (p) => p._baseVal,
      _dollarVal: (p) => p._dollarVal,
      _overallRank: (p) => p._overallRank,
      _orgRank: (p) => p._orgRank,
      _tierId: (p) => FV_TIERS.findIndex((t) => t.id === p._tierId),
      _fvSource: (p) => p._fvSource,
      Name: (p) => getName(p),
      Age: (p) => getAge(p),
      ORG: (p) => orgLabel(p),
    });
    return rows;
  }, [rankedPool, deferredSearch, posFilter, orgFilter, levelFilter, tierFilter, sort]);

  const { paged, totalPages } = paginateRows(displayPool, page, PER_PAGE);
  const cfgInputStyle = { ...S.searchInput, width: 65, height: 24, padding: '3px 4px', fontSize: 11, textAlign: 'right', fontVariantNumeric: 'tabular-nums' };

  const cfgCols = [
    { key: 'tier', label: 'Tier', w: 50, group: 'tier' },
    { key: 'thresh', label: 'FV ≥ (WAA)', w: 80, group: 'thresholds', align: 'center' },
    { key: 'bat', label: 'Bat $M', w: 65, group: 'money', align: 'center' },
    { key: 'pit', label: 'Pit $M', w: 65, group: 'money', align: 'center' },
    { key: 'count', label: 'Count', w: 45, group: 'counts', align: 'right' },
    { key: 'hit', label: 'H', w: 35, group: 'counts', align: 'right' },
    { key: 'pitc', label: 'P', w: 35, group: 'counts', align: 'right' },
    { key: 'cum', label: 'Cum.', w: 45, group: 'counts', align: 'right' },
    { key: 'range', label: 'FV Range', w: 100, group: 'ranges' },
    { key: 'mlb', label: 'MLB Players ≥ FV', w: 140, group: 'ranges', align: 'right', title: "Major-league squad players whose current WAA (FV engine) is at or above this tier's cut" },
  ];
  const cfgCell = cellStyles(cfgCols);

  const cols = [
    { key: '_overallRank', label: 'Rank', w: 45, group: 'rank', align: 'right' },
    { key: '_orgRank', label: 'Org', w: 40, group: 'rank', align: 'right' },
    { key: '_tierId', label: 'FV Tier', w: 65, group: 'rank' },
    { key: 'Name', label: 'Name', w: 170, group: 'identity' },
    { key: 'Age', label: 'Age', w: 45, group: 'identity', align: 'right' },
    { key: '_fvSource', label: 'Src', w: 52, group: 'development', title: 'Where the projected peak comes from: ML model, DEV cell, measured DEV curve, or the assumed model' },
    { key: 'POS', label: 'POS', w: 48, group: 'position' },
    { key: '_bestPos', label: 'Best', w: 48, group: 'position' },
    { key: 'ORG', label: 'Team', w: 130, group: 'position' },
    { key: 'Lev', label: 'Lvl', w: 45, group: 'position' },
    { key: '_fv', label: 'FV', w: 60, group: 'value', align: 'right', title: 'Projected peak WAA (FV engine "Proj Pot")' },
    { key: '_currentVal', label: 'WAA', w: 65, group: 'value', align: 'right', title: 'Current WAA, best role' },
    { key: '_baseVal', label: 'Pot WAA', w: 65, group: 'value', align: 'right', title: 'Listed potential WAA, best role' },
    { key: '_dollarVal', label: '$ Val', w: 55, group: 'contract', align: 'right' },
  ];
  const cell = cellStyles(cols);
  const sortedLabel = cols.find((c) => c.key === sort.col)?.label;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
      <Section title="Prospect Board Configuration"
        state={`${FV_TIERS.length} tiers · ${prospectPool.length.toLocaleString()} prospects`}
        actions={
          <>
            <button type="button" onClick={() => setConfigOpen(!configOpen)} style={S.btn} aria-expanded={configOpen}>{configOpen ? 'Hide Config' : 'Show Config'}</button>
            <button type="button" onClick={() => setThresholds(suggested)} style={{ ...S.btn, ...S.btnPrimary }}>Suggest Thresholds</button>
            <button type="button" onClick={() => setDollarValues(defaultDollarValues())} style={S.btn}>Reset $ Defaults</button>
          </>
        }
        footer={configOpen ? `${prospectPool.length} total prospects across ${teams.length} teams · cuts are in projected peak WAA` : null}>
        {configOpen ? (
          <div style={edgeWrap}>
            <table style={S.table}>
              <thead><tr>
                {cfgCols.map((c) => (
                  <th key={c.key} style={{ ...S.th, ...cfgCell[c.key], width: c.w, ...(c.align ? { textAlign: c.align } : {}) }} title={c.title}>{c.label}</th>
                ))}
              </tr></thead>
              <tbody>
                {FV_TIERS.map((tier, ti) => {
                  const ts = tierStats[tier.id];
                  const thresh = thresholds[tier.id];
                  const mlbCount = countAtOrAbove(mlbVals, thresh);
                  return (
                    <tr key={tier.id} style={ti % 2 === 1 ? S.zebraRow : undefined}>
                      <td style={{ ...S.td, ...cfgCell.tier }}><span style={tierPill(tier.id)}>{tier.label}</span></td>
                      <td style={{ ...S.td, ...cfgCell.thresh, textAlign: 'center' }}>
                        <input type="number" step="0.1" value={thresh ?? ''} onChange={(e) => {
                          const v = parseFloat(e.target.value);
                          if (!isNaN(v)) setThresholds((prev) => ({ ...prev, [tier.id]: v }));
                        }} style={cfgInputStyle} aria-label={`FV threshold for tier ${tier.label}`} />
                      </td>
                      <td style={{ ...S.td, ...cfgCell.bat, textAlign: 'center' }}>
                        <input type="number" step="0.5" value={dollarValues[tier.id]?.bat ?? 0} onChange={(e) => {
                          const v = parseFloat(e.target.value);
                          if (!isNaN(v)) setDollarValues((prev) => ({ ...prev, [tier.id]: { ...prev[tier.id], bat: v } }));
                        }} style={cfgInputStyle} aria-label={`Batter dollar value for tier ${tier.label}`} />
                      </td>
                      <td style={{ ...S.td, ...cfgCell.pit, textAlign: 'center' }}>
                        <input type="number" step="0.5" value={dollarValues[tier.id]?.pit ?? 0} onChange={(e) => {
                          const v = parseFloat(e.target.value);
                          if (!isNaN(v)) setDollarValues((prev) => ({ ...prev, [tier.id]: { ...prev[tier.id], pit: v } }));
                        }} style={cfgInputStyle} aria-label={`Pitcher dollar value for tier ${tier.label}`} />
                      </td>
                      <td style={{ ...S.td, ...cfgCell.count, ...numCell, fontWeight: 600, color: ts.count > 0 ? T.text : T.textDisabled }}>{ts.count}</td>
                      <td style={{ ...S.td, ...cfgCell.hit, ...numCell, color: ts.hit > 0 ? T.CHART.series1 : T.textDisabled }}>{ts.hit}</td>
                      <td style={{ ...S.td, ...cfgCell.pitc, ...numCell, color: ts.pit > 0 ? T.CHART.series3 : T.textDisabled }}>{ts.pit}</td>
                      <td style={{ ...S.td, ...cfgCell.cum, ...numCell, color: T.text3 }}>{ts.cumulative}</td>
                      <td style={{ ...S.td, ...cfgCell.range, color: ts.count > 0 ? T.text3 : T.textDisabled, fontSize: 12 }}>
                        {ts.count > 0 ? `${fmtSigned(ts.minFV)} – ${fmtSigned(ts.maxFV)}` : '—'}
                      </td>
                      <td style={{ ...S.td, ...cfgCell.mlb, ...numCell, color: mlbCount == null ? T.textDisabled : T.text2, fontSize: 12 }}>
                        {mlbCount == null ? '—' : `${mlbCount} of ${mlbVals.length}`}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        ) : (
          <div style={{ fontSize: 12.5, color: T.text2 }}>
            Tier thresholds and per-tier $ values are hidden — <span style={{ color: T.text3 }}>Show Config to edit.</span>
          </div>
        )}
      </Section>

      <Section title="The Board" count={`(${displayPool.length.toLocaleString()})`}
        state={sortedLabel ? `Sorted by ${sortedLabel}, ${sort.dir === 'asc' ? 'ascending' : 'descending'}` : null}
        toolbar={
          <>
            <PositionFilter value={posFilter} onChange={(v) => { setPosFilter(v); setPage(0); }} />
            <MultiSelectDropdown options={teams.map((t) => ({ value: t, label: t }))} value={orgFilter}
              onChange={(v) => { setOrgFilter(v); setPage(0); }} placeholder="All Teams" ariaLabel="Filter by team" />
            <LevelFilter players={prospectPool} value={levelFilter} onChange={(v) => { setLevelFilter(v); setPage(0); }} />
            <MultiSelectDropdown options={FV_TIERS.map((t) => ({ value: t.id, label: t.label }))} value={tierFilter}
              onChange={(v) => { setTierFilter(v); setPage(0); }} placeholder="All Tiers" ariaLabel="Filter by tier" minWidth={130} />
            <SearchInput type="text" placeholder="Search name..." value={search} onChange={(e) => { setSearch(e.target.value); setPage(0); }} aria-label="Search prospects by name" />
          </>
        }>
        <div style={edgeWrap}>
          <table style={S.table}>
            <thead><tr>
              {cols.map((c) => (
                <SortHeader key={c.key} label={c.label} width={c.w} sortCol={sort.col} sortDir={sort.dir} colKey={c.key} rule={cell[c.key]} align={c.align} title={c.title}
                  onClick={() => setSort((prev) => ({ col: c.key, dir: prev.col === c.key && prev.dir === 'desc' ? 'asc' : 'desc' }))} />
              ))}
            </tr></thead>
            <tbody>
              {paged.map((p, i) => {
                const pos = getPos(p);
                const best = getBestPos(p);
                const lev = getLevel(p);
                return (
                  <tr key={playerUid(p)} style={i % 2 === 1 ? S.zebraRow : undefined}>
                    <td style={{ ...S.td, ...cell._overallRank, ...numCell, color: T.text, fontWeight: 700 }}>{p._overallRank}</td>
                    <td style={{ ...S.td, ...cell._orgRank, ...numCell, color: T.text3 }}>{p._orgRank}</td>
                    <td style={{ ...S.td, ...cell._tierId }}><span style={tierPill(p._tierId)}>{p._tierId}</span></td>
                    <td style={{ ...S.td, ...S.tdName, ...cell.Name, minWidth: 170, cursor: 'pointer' }} onClick={() => onSelectPlayer?.(p)}>{getName(p)}</td>
                    <td style={{ ...S.td, ...cell.Age, ...numCell }}>{fmtAge(getAge(p))}</td>
                    <td style={{ ...S.td, ...cell._fvSource, color: p._fvSource === 'model' ? T.text3 : T.text2, fontSize: 12 }} title={FV_SOURCE_LABEL[p._fvSource]}>{SRC_SHORT[p._fvSource] ?? '—'}</td>
                    <td style={{ ...S.td, ...cell.POS, ...posCell, color: posColor(pos === 'CL' ? 'RP' : pos) }}>{pos}</td>
                    <td style={{ ...S.td, ...cell._bestPos, ...posCell, color: best ? posColor(String(best).replace('*', '')) : T.textDisabled }}>{best || '—'}</td>
                    <td style={{ ...S.td, ...cell.ORG }}>{orgLabel(p)}</td>
                    <td style={{ ...S.td, ...cell.Lev }}>{lev ? <span style={levelBadge(lev)}>{lev}</span> : <span style={{ color: T.textDisabled }}>—</span>}</td>
                    <td style={{ ...S.td, ...cell._fv, ...numCell, ...waaStyle(p._fv) }}>{fmtSigned(p._fv)}</td>
                    <td style={{ ...S.td, ...cell._currentVal, ...numCell, ...waaStyle(p._currentVal) }}>{fmtSigned(p._currentVal)}</td>
                    <td style={{ ...S.td, ...cell._baseVal, ...numCell, ...waaStyle(p._baseVal) }}>{fmtSigned(p._baseVal)}</td>
                    <td style={{ ...S.td, ...cell._dollarVal, ...numCell, color: p._dollarVal > 0 ? T.warn : T.textDisabled, fontWeight: 600 }}>{p._dollarVal > 0 ? `$${fmt(p._dollarVal, 1)}M` : '—'}</td>
                  </tr>
                );
              })}
              {paged.length === 0 && <tr><td colSpan={cols.length} style={{ ...S.td, textAlign: 'center', color: T.text3 }}>No prospects found</td></tr>}
            </tbody>
          </table>
        </div>
        <div style={footWrap}>
          <Pagination page={page} totalPages={totalPages} total={displayPool.length} onPrev={() => setPage(Math.max(0, page - 1))} onNext={() => setPage(Math.min(totalPages - 1, page + 1))} />
        </div>
      </Section>
    </div>
  );
}

function FarmStackedTooltip({ active, payload, label, playersByTeamTier, hoveredTier }) {
  if (!active || !payload || !payload.length || !hoveredTier) return null;
  const players = playersByTeamTier?.[label]?.[hoveredTier] || [];
  const tierValue = payload.find((p) => p.dataKey === `tier_${hoveredTier}`)?.value ?? 0;
  if (tierValue === 0 && players.length === 0) return null;
  return (
    <div style={{ background: T.CHART.tooltipBg, border: `1px solid ${T.CHART.tooltipBorder}`, borderRadius: T.radius, padding: '10px 14px', fontSize: 12, color: T.CHART.tooltipText, maxWidth: 280 }}>
      <div style={{ fontWeight: 700, fontSize: 13, marginBottom: 2, fontFamily: T.fonts.narrow }}>{label}</div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 6 }}>
        <span style={tierPill(hoveredTier)}>FV {hoveredTier}</span>
        <span style={{ color: T.warn, fontWeight: 600 }}>${fmt(tierValue, 1)}M</span>
        <span style={{ color: T.text3 }}>{players.length} player{players.length !== 1 ? 's' : ''}</span>
      </div>
      {players.map((p, i) => (
        <div key={i} style={{ display: 'flex', gap: 6, color: T.text2, paddingLeft: 4 }}>
          <span style={{ color: T.text, fontWeight: 500, minWidth: 110 }}>{p.name}</span>
          <span style={{ color: posColor(p.pos), minWidth: 24, fontFamily: T.fonts.narrow, fontWeight: 600 }}>{p.pos}</span>
          <span style={{ color: T.text3, fontVariantNumeric: 'tabular-nums' }}>{fmtSigned(p.fv)}</span>
        </div>
      ))}
    </div>
  );
}

function FarmRankings({ teams, prospectPool, thresholds, dollarValues, onNavigate }) {
  const [sort, setSort] = useState({ col: 'totalValue', dir: 'desc' });
  const [hoveredTier, setHoveredTier] = useState(null);

  const pool = prospectPool;   // already the league's own clubs only
  const rankings = useMemo(() => calcFarmRankings(pool, thresholds, dollarValues, teams), [pool, thresholds, dollarValues, teams]);

  const { chartData, playersByTeamTier } = useMemo(() => {
    const lookup = {};
    teams.forEach((t) => { lookup[t] = {}; FV_TIERS.forEach((tier) => { lookup[t][tier.id] = []; }); });
    pool.forEach((p) => {
      const org = getOrg(p);
      if (!lookup[org]) return;
      const fv = p._fv ?? p._baseVal ?? 0;
      const tierId = assignFVTier(fv, thresholds);
      if (!tierId) return;
      lookup[org][tierId].push({ name: getName(p), pos: getBestPos(p) || getPos(p), fv, type: p._poolType });
    });
    Object.values(lookup).forEach((tiers) => Object.values(tiers).forEach((arr) => arr.sort((a, b) => b.fv - a.fv)));
    const cd = [...rankings].sort((a, b) => b.totalValue - a.totalValue).map((r) => {
      const row = { team: r.team };
      FV_TIERS.forEach((t) => {
        let v = 0;
        (lookup[r.team]?.[t.id] || []).forEach((p) => { v += getDollarValue(t.id, p.type, dollarValues); });
        row[`tier_${t.id}`] = Math.round(v * 10) / 10;
      });
      return row;
    });
    return { chartData: cd, playersByTeamTier: lookup };
  }, [rankings, pool, thresholds, dollarValues, teams]);

  const sortedRankings = useMemo(() => {
    const rows = [...rankings];
    const { col, dir } = sort;
    rows.sort((a, b) => {
      let va, vb;
      if (col === 'team') { va = a.team; vb = b.team; } else if (col.startsWith('tier_')) {
        const tid = col.replace('tier_', '');
        va = a.tierCounts[tid] || 0; vb = b.tierCounts[tid] || 0;
      } else { va = a[col]; vb = b[col]; }
      if (typeof va === 'string') return dir === 'asc' ? va.localeCompare(vb) : vb.localeCompare(va);
      return dir === 'asc' ? (va ?? 0) - (vb ?? 0) : (vb ?? 0) - (va ?? 0);
    });
    return rows;
  }, [rankings, sort]);

  const doSort = (col) => setSort((prev) => ({ col, dir: prev.col === col && prev.dir === 'desc' ? 'asc' : 'desc' }));
  const clickStyle = { cursor: 'pointer', textDecoration: 'none', borderBottom: '1px dashed currentColor' };
  const cols = [
    { key: 'rank', label: '#', w: 35, group: 'identity', align: 'right' },
    { key: 'team', label: 'Team', w: 110, group: 'identity' },
    { key: 'totalValue', label: 'Value', w: 65, group: 'value', align: 'right' },
    { key: 'count', label: '#P', w: 35, group: 'value', align: 'right' },
    { key: 'avgValue', label: 'Avg', w: 50, group: 'value', align: 'right' },
    ...FV_TIERS.map((t) => ({ key: `tier_${t.id}`, label: t.label, w: 35, group: 'tiers', align: 'right' })),
    { key: 'ceiling', label: 'Ceil', w: 40, group: 'scouting', align: 'right' },
    { key: 'floor', label: 'Floor', w: 42, group: 'scouting', align: 'right' },
    { key: 'batting', label: 'Bat', w: 38, group: 'scouting', align: 'right' },
    { key: 'pitching', label: 'Pit', w: 38, group: 'scouting', align: 'right' },
    { key: 'report', label: 'Scouting Report', w: 260, group: 'report' },
  ];
  const cell = cellStyles(cols);
  const sortedLabel = cols.find((c) => c.key === sort.col)?.label;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
      <Section title="Farm System Rankings" count={`(${sortedRankings.length})`}
        state={sortedLabel ? `Sorted by ${sortedLabel}, ${sort.dir === 'asc' ? 'ascending' : 'descending'}` : null}
        footer="Click a team or a tier count to open it on the Board. Ceil / Floor / Bat / Pit are 20-80 z-grades within this league.">
        <div style={edgeWrap}>
          <table style={S.table}>
            <thead><tr>
              {cols.map((c) => (
                <SortHeader key={c.key} label={c.label} width={c.w} sortCol={sort.col} sortDir={sort.dir} colKey={c.key} rule={cell[c.key]} align={c.align} onClick={() => doSort(c.key)} />
              ))}
            </tr></thead>
            <tbody>
              {sortedRankings.map((r, i) => (
                <tr key={r.team} style={i % 2 === 1 ? S.zebraRow : undefined}>
                  <td style={{ ...S.td, ...cell.rank, ...numCell, color: T.text3, fontWeight: 600 }}>{r.rank}</td>
                  <td style={{ ...S.td, ...cell.team, fontWeight: 600, color: T.accent }}><span style={clickStyle} onClick={() => onNavigate(r.team, null)}>{r.team}</span></td>
                  <td style={{ ...S.td, ...cell.totalValue, ...numCell, color: T.warn, fontWeight: 700 }}>${fmt(r.totalValue, 1)}M</td>
                  <td style={{ ...S.td, ...cell.count, ...numCell }}>{r.count}</td>
                  <td style={{ ...S.td, ...cell.avgValue, ...numCell, color: T.text2 }}>${fmt(r.avgValue, 1)}</td>
                  {FV_TIERS.map((t) => {
                    const cnt = r.tierCounts[t.id] || 0;
                    return (
                      <td key={t.id} style={{ ...S.td, ...cell[`tier_${t.id}`], ...numCell, color: cnt > 0 ? FV_TIER_COLORS[t.id].bg : T.textDisabled, fontWeight: cnt > 0 ? 600 : 400 }}>
                        {cnt > 0 ? <span style={clickStyle} onClick={() => onNavigate(r.team, t.id)}>{cnt}</span> : 0}
                      </td>
                    );
                  })}
                  <td style={{ ...S.td, ...cell.ceiling, ...numCell, color: scoutingRatingColor(r.ceiling), fontWeight: 600 }}>{r.ceiling}</td>
                  <td style={{ ...S.td, ...cell.floor, ...numCell, color: scoutingRatingColor(r.floor), fontWeight: 600 }}>{r.floor}</td>
                  <td style={{ ...S.td, ...cell.batting, ...numCell, color: scoutingRatingColor(r.batting), fontWeight: 600 }}>{r.batting}</td>
                  <td style={{ ...S.td, ...cell.pitching, ...numCell, color: scoutingRatingColor(r.pitching), fontWeight: 600 }}>{r.pitching}</td>
                  <td style={{ ...S.td, ...cell.report, fontSize: 12, color: T.text2, whiteSpace: 'normal', maxWidth: 260, height: 'auto', padding: '5px 12px 5px 6px', lineHeight: 1.35 }}>{r.report}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Section>

      <Section title="Farm System Values" state="System value ($M) by FV tier"
        footer={
          <span style={{ display: 'flex', gap: 12, flexWrap: 'wrap', alignItems: 'center' }}>
            {FV_TIERS.map((t) => (
              <span key={t.id} style={{ display: 'inline-flex', alignItems: 'center', gap: 5 }}>
                <span style={{ width: 10, height: 10, borderRadius: T.radius, background: FV_TIER_COLORS[t.id].bg, display: 'inline-block' }} />
                <span style={{ color: T.text2 }}>{t.label}</span>
              </span>
            ))}
          </span>
        }>
        <div style={{ width: '100%', height: 420, overflowX: 'auto' }}>
          <div style={{ width: Math.max(chartData.length * 50, 600), height: 400 }}>
            <ResponsiveContainer>
              <BarChart data={chartData} margin={{ top: 10, right: 20, left: 10, bottom: 60 }}>
                <CartesianGrid strokeDasharray="3 3" stroke={T.CHART.grid} vertical={false} />
                <XAxis dataKey="team" tick={{ fill: T.CHART.axis, fontSize: 11 }} angle={-45} textAnchor="end" interval={0} height={60} />
                <YAxis tick={{ fill: T.CHART.axis, fontSize: 11 }} label={{ value: 'System Value ($M)', angle: -90, position: 'insideLeft', fill: T.CHART.axis, fontSize: 11 }} />
                <Tooltip content={<FarmStackedTooltip playersByTeamTier={playersByTeamTier} hoveredTier={hoveredTier} />} cursor={{ fill: T.panel3 }} />
                {[...FV_TIERS].reverse().map((t) => (
                  <Bar key={t.id} dataKey={`tier_${t.id}`} stackId="value" fill={FV_TIER_COLORS[t.id].bg} name={`FV ${t.label}`}
                    onMouseEnter={() => setHoveredTier(t.id)} onMouseLeave={() => setHoveredTier(null)} />
                ))}
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>
      </Section>
    </div>
  );
}
