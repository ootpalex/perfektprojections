// ============================================================================
// PlayerComparePage — ours' Player Compare (ootp-dashboard app/src/components/
// PlayerCompareView.jsx): up to five players side by side.
//
// What changed from ours is in docs/phase4/views.md; in short:
//   - FV = his engine's projected peak; value rows are WAA, with WAR shown
//     beside it where the pull carries WAR (SSB; null elsewhere until a re-pull).
//   - Adaptability is gone (not in his data). Ours' "Greed" (FIN) reads Greed.
//   - Velocity is OOTP's range string; Dev% is gone; ages are whole years.
//   - Service time is OOTP's years figure and total days, not ours' split.
// ============================================================================
import { useState, useMemo, useDeferredValue } from 'react';
import { S, TOKENS as T, posColor, levelChip, proneColor, waaStyle, warStyle, intangibleColor, gradeStyle } from '../theme.js';
import {
  getName, getPos, getLevel, getAge, getBestPos, getBats, getThrows, getProne, getOvr, getPot, getPrice,
  getOptionsUsed, getRunsP, isEligible, isStarter, getRating, getVelo, getIntangible, getPlayerType, resolveKey, num,
  getMaxWaa, getMaxWaaP, getMaxWar, getMaxWarP, getSpWaa, getSpWaaP, getRpWaa, getRpWaaP, getSpWar, getRpWar,
} from '../lib/accessors.js';
import { levelKey } from '../lib/columns.js';
import { fmtSigned, fmtAge, orgLabel, playerUid, fmtService, intangibleGrades, FV_SOURCE_LABEL } from '../lib/viewFormat.js';
import { fvProjPeak } from '../lib/prospectTiers.js';
import { usePlayersWithFV } from '../hooks/usePlayerData';
import { Section, SearchInput, PageHead, colRule } from '../components/oursUi.jsx';

const MAX = 5;
const FIELD_POS = ['C', '1B', '2B', '3B', 'SS', 'LF', 'CF', 'RF'];
const LEVEL_NAME = { mlb: 'MLB', aaa: 'AAA', aa: 'AA', aplus: 'A+', a: 'A', r: 'R', int: 'INT' };
const chipCss = (lev) => {
  const c = levelChip(LEVEL_NAME[levelKey(lev)] ?? lev);
  return { background: c.bg, color: c.text, borderColor: c.border, ...(c.borderStyle ? { borderStyle: c.borderStyle } : {}) };
};
const posText = { fontFamily: T.fonts.narrow, fontWeight: 600 };
const pc = (pos) => { const s = String(pos || '').replace('*', ''); return posColor(s === 'CL' ? 'RP' : s); };
// Greed is the one trait where high is bad, so its colour is inverted (ours
// coloured it like the others, painting a greedy player green).
const flipHL = { H: 'L', L: 'H' };
const intRow = (key, label, inverted = false) => ({ key, label, get: (p) => getIntangible(p, key), text: true, color: (v) => intangibleColor(inverted ? (flipHL[v] ?? v) : v), weight: 600 });

// Each stat: get(p) → value; numeric rows mark best (good) / worst (bad) when
// two or more players have a value, unless `style` colours the value itself.
const COMPARE_STATS = [
  { group: 'Profile', stats: [
    { key: 'best', label: 'Best Pos', get: (p) => getBestPos(p), text: true, color: (v) => pc(v), pos: true },
    { key: 'lev', label: 'Level', get: (p) => getLevel(p), chip: true },
    { key: 'bt', label: 'B/T', get: (p) => `${getBats(p) ?? '—'}/${getThrows(p) ?? '—'}`, text: true },
    { key: 'prone', label: 'Prone', get: (p) => getProne(p), text: true, color: (v) => proneColor(v) },
    { key: 'ovr', label: 'Overall', get: (p) => getOvr(p), numeric: true, precision: 0 },
    { key: 'pot', label: 'Potential', get: (p) => getPot(p), numeric: true, precision: 0 },
  ] },
  { group: 'Value (Hitters)', appliesTo: 'hitter', stats: [
    { key: 'fv', label: 'Future Value', get: fvProjPeak, numeric: true, style: waaStyle, signed: true, title: 'Projected peak WAA (FV engine)' },
    { key: 'src', label: 'FV source', get: (p) => FV_SOURCE_LABEL[p._potentialSource] ?? null, text: true },
    { key: 'waa', label: 'WAA', get: (p) => getMaxWaa(p), numeric: true, style: waaStyle, signed: true },
    { key: 'waaP', label: 'WAA Potential', get: (p) => getMaxWaaP(p), numeric: true, style: waaStyle, signed: true },
    { key: 'war', label: 'WAR', get: (p) => getMaxWar(p), numeric: true, style: warStyle },
    { key: 'warP', label: 'WAR Potential', get: (p) => getMaxWarP(p), numeric: true, style: warStyle },
  ] },
  { group: 'Value (Pitchers)', appliesTo: 'pitcher', stats: [
    { key: 'fv', label: 'Future Value', get: fvProjPeak, numeric: true, style: waaStyle, signed: true, title: 'Projected peak WAA (FV engine)' },
    { key: 'src', label: 'FV source', get: (p) => FV_SOURCE_LABEL[p._potentialSource] ?? null, text: true },
    { key: 'spWaa', label: 'SP WAA', get: (p) => getSpWaa(p), numeric: true, style: waaStyle, signed: true },
    { key: 'rpWaa', label: 'RP WAA', get: (p) => getRpWaa(p), numeric: true, style: waaStyle, signed: true },
    { key: 'spWaaP', label: 'SP Potential', get: (p) => getSpWaaP(p), numeric: true, style: waaStyle, signed: true },
    { key: 'rpWaaP', label: 'RP Potential', get: (p) => getRpWaaP(p), numeric: true, style: waaStyle, signed: true },
    { key: 'spWar', label: 'SP WAR', get: (p) => getSpWar(p), numeric: true, style: warStyle },
    { key: 'rpWar', label: 'RP WAR', get: (p) => getRpWar(p), numeric: true, style: warStyle },
    { key: 'starter', label: 'Starter', get: (p) => { const s = isStarter(p); return s == null ? null : s ? 'Yes' : 'No'; }, text: true },
    { key: 'stm', label: 'Stamina', get: (p) => getRating(p, 'stm'), numeric: true, precision: 0 },
    { key: 'velo', label: 'Velocity', get: (p) => getVelo(p), text: true },
  ] },
  { group: 'Defense (Hitters)', appliesTo: 'hitter', stats: FIELD_POS.map((pos) => ({
    key: `${pos}RunsP`, label: `${pos} RunsP`, numeric: true, precision: 1,
    get: (p) => (isEligible(p, pos) ? getRunsP(p, pos) : null),
  })) },
  { group: 'Splits (Hitters)', appliesTo: 'hitter', stats: [
    { key: 'OBP vR', label: 'OBP vs R', get: (p) => num(resolveKey(p, 'OBP vR')), numeric: true, precision: 3 },
    { key: 'OBP vL', label: 'OBP vs L', get: (p) => num(resolveKey(p, 'OBP vL')), numeric: true, precision: 3 },
    { key: 'wOBA vR', label: 'wOBA vs R', get: (p) => num(resolveKey(p, 'wOBA vR')), numeric: true, precision: 3 },
    { key: 'wOBA vL', label: 'wOBA vs L', get: (p) => num(resolveKey(p, 'wOBA vL')), numeric: true, precision: 3 },
  ] },
  { group: 'Intangibles', stats: [
    { key: 'intg', label: 'Intangibles', get: (p) => p._intangibles ?? null, text: true, color: (v) => gradeStyle(v).color, title: '20-80 composite, z-scored across the league' },
    intRow('int', 'Intelligence'),
    intRow('we', 'Work Ethic'),
    intRow('lea', 'Leadership'),
    intRow('loy', 'Loyalty'),
    intRow('greed', 'Greed', true),
  ] },
  { group: 'Contract', stats: [
    { key: 'price', label: 'Salary', get: (p) => getPrice(p), text: true, format: (v) => '$' + v.toLocaleString() },
    { key: 'svc', label: 'ML Service', get: (p) => { const s = fmtService(p); return s === '—' ? null : s; }, text: true },
    { key: 'opt', label: 'Options used', get: (p) => getOptionsUsed(p), text: true },
  ] },
];

export default function PlayerComparePage({ hitters: hittersIn = [], pitchers: pitchersIn = [] }) {
  const hitters = usePlayersWithFV(hittersIn);
  const pitchers = usePlayersWithFV(pitchersIn);
  const [search, setSearch] = useState('');
  const deferredSearch = useDeferredValue(search);
  const [selectedIds, setSelectedIds] = useState([]);   // playerUid, so a re-pull shows current numbers
  const [dropdownOpen, setDropdownOpen] = useState(false);

  const intGrades = useMemo(() => intangibleGrades([...hittersIn, ...pitchersIn]), [hittersIn, pitchersIn]);
  const byUid = useMemo(() => {
    const m = new Map();
    for (const p of [...hitters, ...pitchers]) m.set(playerUid(p), p);
    return m;
  }, [hitters, pitchers]);
  const selected = useMemo(() => selectedIds.map((uid) => byUid.get(uid)).filter(Boolean)
    .map((p) => ({ ...p, _uid: playerUid(p), _kind: getPlayerType(p), _intangibles: intGrades.get(playerUid(p)) ?? null })),
  [selectedIds, byUid, intGrades]);

  const searchResults = useMemo(() => {
    if (!deferredSearch || deferredSearch.length < 2) return [];
    const s = deferredSearch.toLowerCase();
    const taken = new Set(selectedIds);
    const out = [];
    for (const [uid, p] of byUid) {
      if (taken.has(uid)) continue;
      if ((getName(p) || '').toLowerCase().includes(s)) out.push(p);
      if (out.length >= 8) break;
    }
    return out;
  }, [deferredSearch, byUid, selectedIds]);

  const addPlayer = (p) => {
    if (selectedIds.length >= MAX) return;
    setSelectedIds((prev) => [...prev, playerUid(p)]);
    setSearch('');
    setDropdownOpen(false);
  };
  const removePlayer = (uid) => setSelectedIds((prev) => prev.filter((x) => x !== uid));

  const cmpCols = useMemo(() => [{ key: 'label', group: 'label' }, ...selected.map((p) => ({ key: p._uid, group: 'players' }))], [selected]);
  const cellRule = (ci) => colRule(cmpCols, ci) || {};

  return (
    <div style={{ height: '100%', overflow: 'auto', padding: '18px 24px', background: T.bg, color: T.text, fontFamily: T.fonts.ui }}>
      <PageHead title="Player Compare" sub="Up to five players side by side · values are WAA unless marked WAR" />
      <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
        <Section title="Players" count={`(${selected.length}/${MAX})`} state={selected.length === 0 ? `Search and add up to ${MAX} players` : undefined}
          actions={selected.length >= 2 ? <button type="button" onClick={() => setSelectedIds([])} style={S.btn}>Clear all</button> : undefined}>
          <div style={{ maxWidth: 400 }}>
            <SearchInput type="text" placeholder={selected.length >= MAX ? `Max ${MAX} players` : 'Search player name...'}
              value={search} onChange={(e) => { setSearch(e.target.value); setDropdownOpen(true); }} onFocus={() => setDropdownOpen(true)}
              disabled={selected.length >= MAX} aria-label="Search players to compare" style={{ width: '100%', boxSizing: 'border-box' }} />
            {dropdownOpen && searchResults.length > 0 && (
              <div role="listbox" aria-label="Search results" style={{ marginTop: 4, background: T.panel, border: `1px solid ${T.line2}`, borderRadius: T.radius, maxHeight: 300, overflowY: 'auto' }}>
                {searchResults.map((p) => (
                  <div key={playerUid(p)} role="option" aria-selected="false" onClick={() => addPlayer(p)}
                    style={{ padding: '6px 10px', cursor: 'pointer', display: 'flex', gap: 8, alignItems: 'center', borderBottom: `1px solid ${T.line}`, fontSize: 12.5 }}
                    onMouseEnter={(e) => { e.currentTarget.style.background = T.panel3; }}
                    onMouseLeave={(e) => { e.currentTarget.style.background = 'transparent'; }}>
                    <span style={{ fontWeight: 600, color: T.text, flex: 1 }}>{getName(p)}</span>
                    <span style={{ ...posText, color: pc(getPos(p)) }}>{getPos(p)}</span>
                    <span style={{ color: T.text3, maxWidth: 120, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{orgLabel(p)}</span>
                    <span style={{ color: T.text3, fontVariantNumeric: 'tabular-nums' }}>{fmtAge(getAge(p))}</span>
                  </div>
                ))}
              </div>
            )}
          </div>
          {selected.length > 0 && (
            <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginTop: 10, alignItems: 'center' }}>
              {selected.map((p) => (
                <div key={p._uid} style={{ background: T.accentBg2, border: `1px solid ${T.line2}`, borderRadius: T.radius, padding: '3px 8px', fontSize: 12, display: 'flex', alignItems: 'center', gap: 6 }}>
                  <span style={{ ...posText, color: pc(getPos(p)) }}>{getPos(p)}</span>
                  <span style={{ color: T.text, fontWeight: 600 }}>{getName(p)}</span>
                  <span style={{ color: T.text3 }}>{orgLabel(p)}</span>
                  <button type="button" onClick={() => removePlayer(p._uid)} aria-label={`Remove ${getName(p)}`} style={{ background: 'none', border: 'none', color: T.bad, cursor: 'pointer', fontSize: 12, padding: '0 2px', lineHeight: 1 }}>✕</button>
                </div>
              ))}
            </div>
          )}
        </Section>

        {selected.length > 0 ? (
          <Section title="Comparison" count={`(${selected.length})`}>
            <div style={{ margin: -12 }}>
              <div style={{ ...S.tableWrap, border: 'none', borderRadius: 0 }}>
                <table style={S.table}>
                  <thead><tr>
                    <th style={{ ...S.th, width: 130 }}>Stat</th>
                    {selected.map((p, i) => (
                      <th key={p._uid} style={{ ...S.th, ...cellRule(i + 1), minWidth: 130, textAlign: 'center' }}>
                        <div style={{ color: T.text, fontWeight: 700, fontSize: 12.5 }}>{getName(p)}</div>
                        <div style={{ display: 'flex', gap: 4, justifyContent: 'center', marginTop: 2, fontWeight: 500 }}>
                          <span style={{ ...posText, color: pc(getPos(p)) }}>{getPos(p)}</span>
                          <span style={{ color: T.textDisabled }}>|</span>
                          <span style={{ color: T.text3 }}>{orgLabel(p)}</span>
                          <span style={{ color: T.textDisabled }}>|</span>
                          <span style={{ color: T.text2, fontVariantNumeric: 'tabular-nums' }}>{fmtAge(getAge(p))}</span>
                        </div>
                      </th>
                    ))}
                  </tr></thead>
                  <tbody>
                    {COMPARE_STATS.flatMap((group) => {
                      if (group.appliesTo && !selected.some((p) => p._kind === group.appliesTo)) return [];
                      return [
                        <tr key={`gh-${group.group}`}>
                          <td colSpan={selected.length + 1} style={{ ...S.td, height: 26, background: T.panel2, color: T.text3, fontFamily: T.fonts.narrow, fontWeight: 600, fontSize: 12, padding: '0 8px' }}>{group.group}</td>
                        </tr>,
                        ...group.stats.map((stat, si) => {
                          const applies = (p) => !group.appliesTo || p._kind === group.appliesTo;
                          const vals = selected.map((p) => (applies(p) ? stat.get(p) : null));
                          let bestIdx = -1, worstIdx = -1;
                          if (stat.numeric && !stat.style) {
                            let best = -Infinity, worst = Infinity, n = 0;
                            vals.forEach((v, i) => {
                              if (v == null || !Number.isFinite(v)) return;
                              n++;
                              if (v > best) { best = v; bestIdx = i; }
                              if (v < worst) { worst = v; worstIdx = i; }
                            });
                            if (n < 2) { bestIdx = -1; worstIdx = -1; }
                          }
                          return (
                            <tr key={`${group.group}-${stat.key}`} style={si % 2 === 1 ? S.zebraRow : undefined}>
                              <td style={{ ...S.td, fontWeight: 600, color: T.text2, fontSize: 12 }} title={stat.title}>{stat.label}</td>
                              {selected.map((p, i) => {
                                const base = { ...S.td, ...cellRule(i + 1), textAlign: 'center' };
                                const v = vals[i];
                                if (!applies(p) || v == null || v === '') return <td key={p._uid} style={{ ...base, color: T.textDisabled }}>—</td>;
                                if (stat.chip) return <td key={p._uid} style={base}><span style={{ ...S.badge, ...chipCss(v) }}>{v}</span></td>;
                                if (stat.text) {
                                  const shown = stat.format ? stat.format(v) : v;
                                  return <td key={p._uid} style={{ ...base, color: stat.color?.(v) ?? T.text2, ...(stat.pos ? posText : {}), ...(stat.weight ? { fontWeight: stat.weight } : {}) }}>{shown}</td>;
                                }
                                const prec = stat.precision ?? 2;
                                const shown = stat.signed ? fmtSigned(v, prec) : v.toFixed(prec);
                                const style = { ...base };
                                if (stat.style) Object.assign(style, stat.style(v));
                                else if (i === bestIdx) Object.assign(style, { color: T.good, fontWeight: 700 });
                                else if (i === worstIdx) style.color = T.bad;
                                else style.color = T.text2;
                                return <td key={p._uid} style={style}>{shown}</td>;
                              })}
                            </tr>
                          );
                        }),
                      ];
                    })}
                  </tbody>
                </table>
              </div>
            </div>
          </Section>
        ) : (
          <div style={{ textAlign: 'center', padding: 40, color: T.text3, fontSize: 13 }}>Search and select players above to compare them side by side.</div>
        )}
      </div>
    </div>
  );
}
