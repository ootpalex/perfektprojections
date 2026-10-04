// ============================================================================
// ScoutPage — ours' Scout view (ootp-dashboard app/src/components/ScoutView.jsx)
// on his data: pick another club, compare positional strength against yours,
// see its players at your weak positions ranked by trade fit, and its roster.
//
// What changed from ours is in docs/phase4/views.md; in short:
//   - Positional strength is his engine (lib/positionalStrength.js), lenses
//     Majors / Farm, z and rank within the league.
//   - Fit = his FV engine's listed potential WAA (or projected peak with the
//     Future Value toggle) plus ours' bonuses (lib/scoutFit.js).
//   - Value columns are WAA. Dev% is gone.
// ============================================================================
import { useState, useMemo, useEffect, useRef } from 'react';
import { S, TOKENS as T, posColor, levelChip, proneColor, waaStyle, zHeat } from '../theme.js';
import {
  getName, getPos, getLevel, getOrg, getAge, getBestPos, getBats, getThrows, getProne, getPrice, isOn40Man,
  genericSort, passesPositionFilter, passesLevelFilter, getPlayerType,
} from '../lib/accessors.js';
import { levelKey } from '../lib/columns.js';
import { fmtSigned, fmtAge, rankSuffix, paginateRows, playerUid, intangibleGrades } from '../lib/viewFormat.js';
import { fvProjPeak, fvCurrent, fvListedPot, fvRole, fvReplOffset } from '../lib/prospectTiers.js';
import {
  SCOUT_POSITIONS, rosterPos, teamZ, teamRanks, orgNeedFromZ, weakPositions, tradeOpportunities, fitScore, aboveReplacement,
} from '../lib/scoutFit.js';
import { buildPositionalStrength, LENSES } from '../lib/positionalStrength.js';
import { leagueOrgs } from '../lib/rosterOptimizer.js';
import { resolveLeagueClubs } from '../lib/leagueClubs.js';
import { useAppConfig } from '../lib/controlApi';
import { usePlayersWithFV } from '../hooks/usePlayerData';
import { useSelectedById } from '../hooks/useSelectedById';
import PlayerDetail from '../components/PlayerDetail';
import { LEAGUE_TEAMS } from './TeamStandingsPage';
import { Section, SortHeader, PillBtn, PositionFilter, LevelFilter, Toggle, Pagination, PageHead, colRule } from '../components/oursUi.jsx';

const PER_PAGE = 50;
const LEVEL_NAME = { mlb: 'MLB', aaa: 'AAA', aa: 'AA', aplus: 'A+', a: 'A', r: 'R', int: 'INT' };
const levelBadge = (lev) => {
  const c = levelChip(LEVEL_NAME[levelKey(lev)] ?? lev);
  return { ...S.badge, background: c.bg, color: c.text, borderColor: c.border, ...(c.borderStyle ? { borderStyle: c.borderStyle } : {}) };
};
const posText = { fontFamily: T.fonts.narrow, fontWeight: 600 };
const pc = (pos) => posColor(String(pos || '').replace('*', '') === 'CL' ? 'RP' : String(pos || '').replace('*', ''));

const TRADE_TARGET_COLS = (fitLabel) => [
  { k: '_fit', l: fitLabel, w: 65, group: 'identity', num: true }, { k: 'name', l: 'Name', w: 170, group: 'identity' },
  { k: 'pos', l: 'POS', w: 48, group: 'identity' }, { k: 'best', l: 'Best', w: 48, group: 'identity' },
  { k: 'age', l: 'Age', w: 45, group: 'identity', num: true }, { k: 'lev', l: 'Lvl', w: 45, group: 'identity' },
  { k: 'cur', l: 'WAA', w: 65, group: 'value', num: true }, { k: 'pot', l: 'Pot WAA', w: 65, group: 'value', num: true },
  { k: 'prone', l: 'Prone', w: 65, group: 'health' },
];
const ROSTER_COLS = (fitLabel) => [
  { key: 'Name', label: 'Name', w: 170, group: 'identity' }, { key: 'Age', label: 'Age', w: 45, group: 'identity', num: true },
  { key: 'POS', label: 'POS', w: 48, group: 'identity' }, { key: '_bestPos', label: 'Best', w: 48, group: 'identity' },
  { key: 'bt', label: 'B/T', w: 50, group: 'identity' }, { key: 'Lev', label: 'Lvl', w: 45, group: 'identity' },
  { key: 'on40', label: '40M', w: 45, group: 'identity' },
  { key: '_fv', label: 'FV', w: 60, group: 'value', num: true, title: 'Projected peak WAA (FV engine)' },
  { key: '_cur', label: 'WAA', w: 65, group: 'value', num: true, title: 'Current WAA, best role' },
  { key: '_pot', label: 'Pot WAA', w: 65, group: 'value', num: true, title: 'Listed potential WAA, best role' },
  { key: 'Prone', label: 'Prone', w: 65, group: 'health' }, { key: '_fit', label: fitLabel, w: 60, group: 'health', num: true },
  { key: 'Price', label: 'Salary', w: 85, group: 'health', num: true },
];

// One club's z and rank per position, weakest (for refTeam) first.
function StrengthTable({ build, team, refTeam }) {
  const z = teamZ(build, team);
  const ranks = teamRanks(build, team);
  const cells = build?.cells?.[team] || {};
  const refZ = teamZ(build, refTeam);
  const order = [...SCOUT_POSITIONS].sort((a, b) => (refZ[a] ?? 0) - (refZ[b] ?? 0));
  const n = build?.teams?.length || 0;
  return (
    <table style={S.table}>
      <thead><tr>
        <th style={S.th}>Pos</th>
        <th style={{ ...S.th, textAlign: 'right' }} title="Rank among this league's clubs (1 = best)">Rank</th>
        <th style={{ ...S.th, textAlign: 'right' }} title="Starter WAA at this slot (SP = top 5 summed, RP = top 8)">WAA</th>
        <th style={{ ...S.th, textAlign: 'right' }} title="Standard deviations from the league mean at this position">z</th>
      </tr></thead>
      <tbody>
        {order.map((pos, i) => {
          const h = zHeat(z[pos]);
          return (
            <tr key={pos} style={i % 2 === 1 ? S.zebraRow : undefined}>
              <td style={{ ...S.td, ...posText, color: pc(pos) }}>{pos}</td>
              <td style={{ ...S.td, textAlign: 'right', background: h.bg, color: h.text, fontWeight: 600 }}>{ranks[pos] ?? '—'}<span style={{ opacity: 0.7, fontWeight: 400 }}>/{n}</span></td>
              <td style={{ ...S.td, textAlign: 'right', background: h.bg, color: h.text }}>{fmtSigned(cells[pos]?.waa)}</td>
              <td style={{ ...S.td, textAlign: 'right', color: T.text3 }}>{fmtSigned(z[pos])}</td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

export default function ScoutPage({ hitters: hittersIn = [], pitchers: pitchersIn = [], metadata, league }) {
  const hitters = usePlayersWithFV(hittersIn);
  const pitchers = usePlayersWithFV(pitchersIn);
  const known = useMemo(() => resolveLeagueClubs(metadata, LEAGUE_TEAMS[league]).known, [metadata, league]);
  const teams = useMemo(() => leagueOrgs(hittersIn, pitchersIn, known).sort(), [hittersIn, pitchersIn, known]);

  // Your club: the league's my_org from the settings, else the first club.
  const myOrg = useAppConfig()?.leagues?.[league]?.my_org;
  const [myTeam, setMyTeam] = useState('');
  const pickedMine = useRef(false);
  useEffect(() => {
    if (!teams.length) return;
    if (pickedMine.current && teams.includes(myTeam)) return;
    const want = teams.find((t) => t === myOrg) || teams[0];
    if (want !== myTeam) setMyTeam(want);
  }, [teams, myOrg]); // eslint-disable-line react-hooks/exhaustive-deps
  const [scoutTeam, setScoutTeam] = useState('');
  useEffect(() => {
    if (!teams.length || (scoutTeam && teams.includes(scoutTeam) && scoutTeam !== myTeam)) return;
    setScoutTeam(teams.find((t) => t !== myTeam) || teams[0]);
  }, [teams, myTeam]); // eslint-disable-line react-hooks/exhaustive-deps

  const [lens, setLens] = useState('mlb');
  const build = useMemo(() => buildPositionalStrength(hittersIn, pitchersIn, { league, knownTeams: known, lens }),
    [hittersIn, pitchersIn, league, known, lens]);

  const [rosterLevel, setRosterLevel] = useState([]);
  const [posFilter, setPosFilter] = useState([]);
  const [rosterSort, setRosterSort] = useState({ col: '_fit', dir: 'desc' });
  const [page, setPage] = useState(0);
  const [toggles, setToggles] = useState({ fv: false, orgNeed: false, injury: false, intangibles: false });
  const setToggle = (key) => setToggles((t) => ({ ...t, [key]: !t[key] }));
  const togglesOn = Object.values(toggles).filter(Boolean).length;
  const fitLabel = togglesOn ? 'Smart' : 'Fit';

  const myZ = useMemo(() => teamZ(build, myTeam), [build, myTeam]);
  const scoutZ = useMemo(() => teamZ(build, scoutTeam), [build, scoutTeam]);
  const myRanks = teamRanks(build, myTeam);
  const scoutRanks = teamRanks(build, scoutTeam);
  const orgNeed = useMemo(() => orgNeedFromZ(myZ), [myZ]);
  const weakPos = useMemo(() => weakPositions(myZ), [myZ]);
  const opportunities = useMemo(() => tradeOpportunities(scoutZ, myZ), [scoutZ, myZ]);

  // League-relative 20-80 intangibles grade (ours' Dashboard enrich step).
  const intGrades = useMemo(() => intangibleGrades([...hittersIn, ...pitchersIn]), [hittersIn, pitchersIn]);

  const baseRows = useMemo(() => {
    if (!scoutTeam) return [];
    return [...hitters, ...pitchers].filter((p) => getOrg(p) === scoutTeam).map((p) => {
      const type = getPlayerType(p);
      const role = fvRole(p);
      const entry = {
        ...p,
        _kind: type,
        _baseVal: fvListedPot(p),
        _fv: fvProjPeak(p),
        _cur: fvCurrent(p),
        _role: type === 'pitcher' ? (role === 'rp' ? 'rp' : 'sp') : null,
        _intangibles: intGrades.get(playerUid(p)) ?? null,
        _repl: fvReplOffset(p),
      };
      entry._fit = fitScore(entry, toggles, orgNeed);
      return entry;
    });
  }, [hitters, pitchers, scoutTeam, intGrades, toggles, orgNeed]);

  const roster = useMemo(() => {
    let rows = baseRows;
    if (posFilter.length > 0) rows = rows.filter((p) => passesPositionFilter(p, posFilter));
    if (rosterLevel.length > 0) rows = rows.filter((p) => passesLevelFilter(p, rosterLevel));
    rows = [...rows];
    genericSort(rows, rosterSort.col, rosterSort.dir, {
      _fit: (p) => p._fit, _fv: (p) => p._fv, _cur: (p) => p._cur, _pot: (p) => p._baseVal,
      Name: (p) => getName(p), Age: (p) => getAge(p), Price: (p) => getPrice(p), Prone: (p) => getProne(p),
      bt: (p) => `${getBats(p) ?? ''}/${getThrows(p) ?? ''}`, on40: (p) => (isOn40Man(p) === true ? 1 : 0),
    });
    return rows;
  }, [baseRows, posFilter, rosterLevel, rosterSort]);
  const { paged, totalPages } = paginateRows(roster, page, PER_PAGE);

  // Trade Targets: the scouted club's players at MY below-average positions,
  // above replacement on the fit, ranked by fit.
  const tradeTargets = useMemo(() => baseRows
    .filter((p) => weakPos.has(rosterPos(p)) && aboveReplacement(p._fit, p._repl))
    .sort((a, b) => b._fit - a._fit), [baseRows, weakPos]);

  const { selected, kind, select, clear } = useSelectedById({ hitter: hitters, pitcher: pitchers });
  const toggleSort = (col) => { setRosterSort((prev) => ({ col, dir: prev.col === col && prev.dir === 'desc' ? 'asc' : 'desc' })); setPage(0); };
  const ttCols = TRADE_TARGET_COLS(fitLabel);
  const rosterCols = ROSTER_COLS(fitLabel);
  const rosterSortLabel = rosterCols.find((c) => c.key === rosterSort.col)?.label ?? rosterSort.col;
  const numTd = (c) => (c.num ? { textAlign: 'right' } : {});
  const edgeWrap = { ...S.tableWrap, border: 'none', borderRadius: 0 };
  const subhead = { fontFamily: T.fonts.narrow, fontSize: 13, fontWeight: 700, color: T.text, marginBottom: 8 };
  const levCell = (lev) => (lev ? <span style={levelBadge(lev)}>{lev}</span> : <span style={{ color: T.textDisabled }}>—</span>);
  const teamSelect = (value, onChange, label, exclude) => (
    <select value={value} onChange={(e) => onChange(e.target.value)} aria-label={label} style={{ ...S.filterSelect, minWidth: 180 }}>
      {teams.filter((t) => t !== exclude).map((t) => <option key={t} value={t}>{t}</option>)}
    </select>
  );
  const ctlLabel = { fontFamily: T.fonts.narrow, fontWeight: 600, fontSize: 12.5, color: T.text2 };

  if (!teams.length) {
    return <div style={{ padding: 24, color: T.text3, background: T.bg }}>No clubs found for {league}.</div>;
  }

  return (
    <div style={{ height: '100%', overflow: 'auto', padding: '18px 24px', background: T.bg, color: T.text, fontFamily: T.fonts.ui }}>
      <PageHead title="Scout" sub={<>Another {league} club against yours · values are WAA from the FV engine · strength = {LENSES[lens].note}</>} />
      <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
        <div style={{ display: 'grid', gridTemplateColumns: 'minmax(0, 2fr) minmax(300px, 1fr)', gap: 16, alignItems: 'stretch' }}>
          <Section title="Positional Strength Comparison" state={`${LENSES[lens].label} · z vs league`}
            toolbar={
              <>
                <label style={ctlLabel}>Scout team</label>
                {teamSelect(scoutTeam, (v) => { setScoutTeam(v); setPage(0); }, 'Scout team', myTeam)}
                <label style={ctlLabel}>Your club</label>
                {teamSelect(myTeam, (v) => { pickedMine.current = true; setMyTeam(v); setPage(0); }, 'Your club', null)}
                <div style={{ display: 'flex', gap: 6, marginLeft: 'auto' }} role="tablist" aria-label="Strength pool">
                  {Object.values(LENSES).map((l) => <PillBtn key={l.key} active={lens === l.key} onClick={() => setLens(l.key)}>{l.label}</PillBtn>)}
                </div>
              </>
            }>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, minmax(0, 1fr))', gap: 24 }}>
              <div>
                <div style={subhead}>{scoutTeam}</div>
                <StrengthTable build={build} team={scoutTeam} refTeam={myTeam} />
              </div>
              <div>
                <div style={subhead}>{myTeam} <span style={{ color: T.text3, fontWeight: 500 }}>(you)</span></div>
                <StrengthTable build={build} team={myTeam} refTeam={myTeam} />
              </div>
            </div>
            {opportunities.length > 0 && (
              <div style={{ marginTop: 14, padding: '8px 12px', background: T.goodBg, border: `1px solid ${T.good}`, borderRadius: T.radius }}>
                <div style={{ fontFamily: T.fonts.narrow, fontSize: 12.5, fontWeight: 700, color: T.good, marginBottom: 2 }}>Trade opportunity positions</div>
                <div style={{ fontSize: 12, color: T.text2 }}>
                  {scoutTeam} is strong where you are weak:{' '}
                  {opportunities.map((pos, i) => (
                    <span key={pos}>
                      {i > 0 && ', '}
                      <span style={{ color: pc(pos), fontWeight: 700 }}>{pos}</span>
                      <span style={{ color: T.text3 }}> ({rankSuffix(scoutRanks[pos])} vs {rankSuffix(myRanks[pos])})</span>
                    </span>
                  ))}
                </div>
              </div>
            )}
          </Section>

          <Section title="Smart Rank Adjustments" state={`${togglesOn} of 4 on`}>
            <div style={{ margin: -12 }}>
              <Toggle label="Future Value" description="Use the projected peak instead of listed potential" checked={toggles.fv} onChange={() => setToggle('fv')} />
              <Toggle label="Org Positional Need" description="Boost players at your club's weak positions" checked={toggles.orgNeed} onChange={() => setToggle('orgNeed')} />
              <Toggle label="Injury Proneness" description="Bonus for Iron Man / Durable, penalty for Fragile / Wrecked" checked={toggles.injury} onChange={() => setToggle('injury')} />
              <Toggle label="Intangibles" description="Bonus for strong 20-80 intangibles grades, penalty for poor ones" checked={toggles.intangibles} onChange={() => setToggle('intangibles')} />
            </div>
          </Section>
        </div>

        {tradeTargets.length > 0 && (
          <Section title="Trade Targets" count={`(${tradeTargets.length})`} state={`Sorted by ${fitLabel}, descending`}
            footer={<>Players at positions where {myTeam} is below league average and above replacement on the {fitLabel.toLowerCase()} score. Showing the top {Math.min(30, tradeTargets.length)}.</>}>
            <div style={{ margin: -12 }}>
              <div style={edgeWrap}>
                <table style={S.table}>
                  <thead><tr>
                    {ttCols.map((c, ci) => <th key={c.k} style={{ ...S.th, ...(colRule(ttCols, ci) || {}), ...numTd(c), width: c.w }}>{c.l}</th>)}
                  </tr></thead>
                  <tbody>
                    {tradeTargets.slice(0, 30).map((p, i) => {
                      const td = (ci, extra) => ({ ...S.td, ...(colRule(ttCols, ci) || {}), ...numTd(ttCols[ci]), ...extra });
                      const prone = getProne(p);
                      return (
                        <tr key={playerUid(p)} style={i % 2 === 1 ? S.zebraRow : undefined}>
                          <td style={td(0, { ...waaStyle(p._fit), fontWeight: 700 })}>{fmtSigned(p._fit)}</td>
                          <td style={td(1, { ...S.tdName, cursor: 'pointer' })} onClick={() => select(p, p._kind)}>{getName(p)}</td>
                          <td style={td(2, { ...posText, color: pc(getPos(p)) })}>{getPos(p)}</td>
                          <td style={td(3, { ...posText, color: pc(getBestPos(p)) })}>{getBestPos(p) || '—'}</td>
                          <td style={td(4, { color: T.text2 })}>{fmtAge(getAge(p))}</td>
                          <td style={td(5)}>{levCell(getLevel(p))}</td>
                          <td style={td(6, waaStyle(p._cur))}>{fmtSigned(p._cur)}</td>
                          <td style={td(7, waaStyle(p._baseVal))}>{fmtSigned(p._baseVal)}</td>
                          <td style={td(8, { color: prone ? proneColor(prone) : T.textDisabled })}>{prone || '—'}</td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </div>
          </Section>
        )}

        <Section title={`${scoutTeam} Roster`} count={`(${roster.length})`} state={`Sorted by ${rosterSortLabel}, ${rosterSort.dir === 'desc' ? 'descending' : 'ascending'}`}
          toolbar={
            <>
              <PositionFilter value={posFilter} onChange={(v) => { setPosFilter(v); setPage(0); }} />
              <LevelFilter players={baseRows} value={rosterLevel} onChange={(v) => { setRosterLevel(v); setPage(0); }} />
              {weakPos.size > 0 && (
                <span style={{ marginLeft: 'auto', fontFamily: T.fonts.narrow, fontSize: 12, color: T.text3 }}>
                  <span style={{ display: 'inline-block', width: 10, height: 10, background: T.goodBg, border: `1px solid ${T.good}`, borderRadius: 2, verticalAlign: -1, marginRight: 5 }} />
                  Trade-fit row: at a position where {myTeam} is below league average
                </span>
              )}
            </>
          }>
          <div style={{ margin: -12 }}>
            <div style={edgeWrap}>
              <table style={S.table}>
                <thead><tr>
                  {rosterCols.map((c, ci) => <SortHeader key={c.key} label={c.label} width={c.w} sortCol={rosterSort.col} sortDir={rosterSort.dir} colKey={c.key} rule={colRule(rosterCols, ci)} align={c.num ? 'right' : undefined} title={c.title} onClick={() => toggleSort(c.key)} />)}
                </tr></thead>
                <tbody>
                  {paged.map((p, i) => {
                    const isTradeFit = weakPos.has(rosterPos(p));
                    const td = (ci, extra) => ({ ...S.td, ...(colRule(rosterCols, ci) || {}), ...numTd(rosterCols[ci]), ...extra });
                    const prone = getProne(p);
                    const price = getPrice(p);
                    const on40 = isOn40Man(p);
                    return (
                      <tr key={playerUid(p)} style={isTradeFit ? { background: T.goodBg } : i % 2 === 1 ? S.zebraRow : undefined}>
                        <td style={td(0, { ...S.tdName, minWidth: 170, cursor: 'pointer' })} onClick={() => select(p, p._kind)}>{getName(p)}</td>
                        <td style={td(1, { color: T.text2 })}>{fmtAge(getAge(p))}</td>
                        <td style={td(2, { ...posText, color: pc(getPos(p)) })}>{getPos(p)}</td>
                        <td style={td(3, { ...posText, color: pc(getBestPos(p)) })}>{getBestPos(p) || '—'}</td>
                        <td style={td(4, { color: T.text2 })}>{getBats(p) ?? ''}/{getThrows(p) ?? ''}</td>
                        <td style={td(5)}>{levCell(getLevel(p))}</td>
                        <td style={td(6, { color: on40 == null ? T.textDisabled : T.text2 })} title={on40 == null ? 'Not in the roster export' : undefined}>{on40 === true ? '✓' : on40 == null ? '—' : ''}</td>
                        <td style={td(7, waaStyle(p._fv))}>{fmtSigned(p._fv)}</td>
                        <td style={td(8, waaStyle(p._cur))}>{fmtSigned(p._cur)}</td>
                        <td style={td(9, waaStyle(p._baseVal))}>{fmtSigned(p._baseVal)}</td>
                        <td style={td(10, { color: prone ? proneColor(prone) : T.textDisabled })}>{prone || '—'}</td>
                        <td style={td(11, p._fit != null ? { ...waaStyle(p._fit), fontWeight: 700 } : { color: T.textDisabled })}>{fmtSigned(p._fit)}</td>
                        <td style={td(12, { color: price != null ? T.text2 : T.textDisabled })}>{price != null ? '$' + price.toLocaleString() : '—'}</td>
                      </tr>
                    );
                  })}
                  {paged.length === 0 && <tr><td colSpan={rosterCols.length} style={{ ...S.td, textAlign: 'center', color: T.text3 }}>No players found</td></tr>}
                </tbody>
              </table>
            </div>
            <Pagination page={page} totalPages={totalPages} total={roster.length} onPrev={() => setPage(Math.max(0, page - 1))} onNext={() => setPage(Math.min(totalPages - 1, page + 1))} />
          </div>
        </Section>
      </div>
      {selected && <PlayerDetail player={selected} onClose={clear} type={kind} />}
    </div>
  );
}
