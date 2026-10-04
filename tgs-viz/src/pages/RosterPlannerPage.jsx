// ============================================================================
// ROSTER PLANNER — port of ours' (ootp-dashboard) views/RosterPlanner.
// Plan the 40-man and active roster a few seasons ahead: drag players between
// buckets to model moves; decide arbitration, team options and expiring deals;
// see coverage gaps and Rule 5 exposure. docs/phase4/roster_planner.md has the
// field map and the list of ours' rules that were dropped (they live in no
// data field: Super Two, option limits, MiLB free agency, the R5 signing-age rule).
// ============================================================================
import React, { useState, useMemo, useCallback, useEffect, useRef } from 'react';
import { DndContext, DragOverlay, useSensor, useSensors, PointerSensor, KeyboardSensor } from '@dnd-kit/core';
import { listOrgs } from '../lib/orgBuilder';
import { useAppConfig } from '../lib/controlApi';
import { getOrg, getRosterExportDate, getRosterExportGapDays } from '../lib/accessors';
import PlayerDetail from '../components/PlayerDetail';
import { enrichForPlanner } from '../lib/rosterPlanning/enrich';
import { detectGameYear, detectContractYear, fmtSalary } from '../lib/rosterPlanning/status';
import { buildRosterProjection, bucketOf } from '../lib/rosterPlanning/projection';
import { filterR5Protect } from '../lib/rosterPlanning/eligibility';
import { buildDepthChart } from '../lib/rosterPlanning/depth';
import { analyzeCrunch, suggestActions, protectReason } from '../lib/rosterPlanning/crunch';
import { FORTY_MAN_LIMIT, ACTIVE_ROSTER_LIMIT, INACTIVE_FORTY_SLOTS, ROTATION_SLOTS, BULLPEN_TARGET, R5_DEFAULT_THRESHOLD } from '../lib/rosterPlanning/rosterRules';
import {
  BUCKET_ACCENT, SummaryCard, DroppablePanel, CoverageStrip, SlotGroup, RowHeader, PlayerRow, DragOverlayRow,
  CollapsiblePanel, QueueRow, SuggestionsPanel, MovesLogPanel, actionBtnStyle,
} from '../components/RosterPlannerParts';

const YEAR_COUNT = 4;
const SEVERITY_CLASS = { error: 'ns-alert-bad', warning: 'ns-alert-warn', info: '' };

// Moves persist per league + org in this browser. Every read/write is guarded:
// storage can be missing (private window) and the page must still work.
const planKey = (league, org) => `ssb_roster_plan:${league || 'default'}:${org}`;
function loadPlan(league, org) {
  try {
    const v = JSON.parse(window.localStorage.getItem(planKey(league, org)) || 'null');
    return { moves: v?.moves && typeof v.moves === 'object' ? v.moves : {}, order: Array.isArray(v?.order) ? v.order : [], r5: Number.isFinite(v?.r5) ? v.r5 : R5_DEFAULT_THRESHOLD };
  } catch { return { moves: {}, order: [], r5: R5_DEFAULT_THRESHOLD }; }
}
function savePlan(league, org, plan) {
  try { window.localStorage.setItem(planKey(league, org), JSON.stringify(plan)); } catch { /* storage unavailable */ }
}

function Alert({ w }) {
  const cls = SEVERITY_CLASS[w.severity] ?? '';
  return (
    <div className={cls || 'ns-box'} style={{ padding: '7px 12px', fontSize: 12.5, fontWeight: 600, color: cls ? undefined : 'var(--text-2)' }}>
      {w.message}
    </div>
  );
}

export default function RosterPlannerPage({ hitters, pitchers, metadata, league }) {
  const rows = useMemo(() => [...hitters, ...pitchers].map(enrichForPlanner), [hitters, pitchers]);
  const orgs = useMemo(() => listOrgs(hitters, pitchers), [hitters, pitchers]);

  // Default org: the league's my_org (app config), else /cub/i, else the first
  // org — the Org Builder / Waivers rule. A user pick sticks while it exists.
  const [org, setOrg] = useState('');
  const myOrg = useAppConfig()?.leagues?.[league]?.my_org;
  const pickedOrg = useRef(false);
  useEffect(() => {
    if (!orgs.length) return;
    if (pickedOrg.current && orgs.includes(org)) return;
    const want = orgs.find((o) => o === myOrg) || orgs.find((o) => /cub/i.test(o)) || orgs[0];
    if (want !== org) setOrg(want);
  }, [orgs, myOrg]); // eslint-disable-line react-hooks/exhaustive-deps

  // Plan state, reloaded when the league or org changes.
  const [plan, setPlan] = useState({ moves: {}, order: [], r5: R5_DEFAULT_THRESHOLD });
  const [history, setHistory] = useState([]);
  useEffect(() => { if (org) { setPlan(loadPlan(league, org)); setHistory([]); } }, [league, org]);
  const updatePlan = useCallback((fn) => {
    setPlan((prev) => { const next = fn(prev); savePlan(league, org, next); return next; });
  }, [league, org]);
  const { moves, order: moveOrder, r5: r5Threshold } = plan;

  const game = useMemo(() => detectGameYear(metadata, rows), [metadata, rows]);
  const gameYear = game.year;
  const contractYear = useMemo(() => (gameYear == null ? null : detectContractYear(rows, gameYear)), [rows, gameYear]);

  // The first year worth planning: next season once contracts have rolled.
  const minOffset = gameYear != null && contractYear != null ? Math.max(0, contractYear - gameYear) : 0;
  const [offsetRaw, setOffset] = useState(null);
  const planOffset = Math.min(minOffset + YEAR_COUNT - 1, Math.max(minOffset, offsetRaw ?? minOffset));
  const planYear = gameYear != null ? gameYear + planOffset : null;

  const teamRows = useMemo(() => rows.filter((p) => getOrg(p) === org), [rows, org]);
  const projection = useMemo(() => (gameYear == null || !org ? null : buildRosterProjection(teamRows, {
    gameYear, contractYear, moves, displayYear: planYear, lastYear: gameYear + minOffset + YEAR_COUNT - 1,
  })), [teamRows, gameYear, contractYear, moves, planYear, minOffset, org]);

  const years = projection?.years?.[planYear] || {};
  const prevYears = projection?.years?.[planYear - 1] || null;

  // A future year leaves its free agents out of the depth chart.
  const depthRows = useMemo(() => {
    if (!projection) return [];
    return planOffset === 0 ? projection.enriched : projection.enriched.filter((ep) => years[ep._uid]?.status !== 'fa');
  }, [projection, planOffset, years]);
  const depth = useMemo(() => buildDepthChart(depthRows), [depthRows]);
  const r5 = useMemo(() => (projection ? filterR5Protect(projection.enriched, r5Threshold) : null), [projection, r5Threshold]);

  const arbDecisions = useMemo(() => (projection ? projection.enriched.filter((ep) => years[ep._uid]?.status === 'arb') : []), [projection, years]);
  const optionDecisions = useMemo(() => (projection && planOffset > 0
    ? projection.enriched.filter((ep) => years[ep._uid]?.status === 'option' && years[ep._uid]?.optionType === 'club' && ep._st.on40) : []), [projection, years, planOffset]);
  const expiring = useMemo(() => (projection && planOffset > 0 && prevYears
    ? projection.enriched.filter((ep) => years[ep._uid]?.status === 'fa' && prevYears[ep._uid] && prevYears[ep._uid].status !== 'fa' && prevYears[ep._uid].status !== 'minors' && ep._st.on40) : []), [projection, years, prevYears, planOffset]);

  const warnings = useMemo(() => {
    if (!projection) return [];
    const r5Lines = planOffset > 0 ? { r5Shortlist: r5.shortlist, r5Threshold } : {};
    return [...analyzeCrunch(projection, r5Lines), ...depth.warnings];
  }, [projection, depth, r5, r5Threshold, planOffset]);

  const suggestions = useMemo(() => {
    if (!projection) return [];
    const base = suggestActions(projection);
    if (planOffset === 0) return base;
    return [
      ...r5.mustProtect.map((e) => ({ type: 'protect', playerId: e.player._uid, player: e.player, action: 'protect', reason: protectReason(e, 'protect') })),
      ...r5.considerProtecting.map((e) => ({ type: 'considerProtect', playerId: e.player._uid, player: e.player, action: 'protect', reason: protectReason(e, 'considerProtect') })),
      ...base,
    ];
  }, [projection, r5, planOffset]);

  // ── moves ──────────────────────────────────────────────────────────────────
  const applyMove = useCallback((uid, action) => {
    const arb = action === 'tender' || action === 'nonTender';
    const key = arb ? `t:${uid}:${planYear}` : uid;
    const value = arb ? { action, startYear: planYear, uid } : { action, startYear: planYear };
    updatePlan((p) => ({ ...p, moves: { ...p.moves, [key]: value }, order: p.order.includes(key) ? p.order : [...p.order, key] }));
    setHistory((h) => [...h, key]);
  }, [planYear, updatePlan]);
  const deleteMove = useCallback((key) => {
    updatePlan((p) => { const m = { ...p.moves }; delete m[key]; return { ...p, moves: m, order: p.order.filter((k) => k !== key) }; });
    setHistory((h) => h.filter((k) => k !== key));
  }, [updatePlan]);
  const undoLast = useCallback(() => { if (history.length) deleteMove(history[history.length - 1]); }, [history, deleteMove]);
  const resetPlan = useCallback(() => { updatePlan((p) => ({ ...p, moves: {}, order: [] })); setHistory([]); }, [updatePlan]);
  const setR5Threshold = useCallback((v) => updatePlan((p) => ({ ...p, r5: v })), [updatePlan]);
  const yearOf = useCallback((m) => m?.startYear ?? (gameYear != null ? gameYear + 1 : null), [gameYear]);
  const reorderMoves = useCallback((year, fromKey, toKey) => {
    updatePlan((p) => {
      const all = [...p.order, ...Object.keys(p.moves).filter((k) => !p.order.includes(k))];
      const inYear = all.filter((k) => yearOf(p.moves[k]) === year);
      const a = inYear.indexOf(fromKey), b = inYear.indexOf(toKey);
      if (a < 0 || b < 0 || a === b) return p;
      const re = [...inYear]; const [m] = re.splice(a, 1); re.splice(b, 0, m);
      let i = 0;
      return { ...p, order: all.map((k) => (yearOf(p.moves[k]) === year ? re[i++] : k)) };
    });
  }, [updatePlan, yearOf]);

  const movesLog = useMemo(() => {
    const byUid = new Map(teamRows.map((p) => [p._uid, p]));
    const idx = new Map(moveOrder.map((k, i) => [k, i]));
    const byYear = {};
    Object.entries(moves).forEach(([key, move], i) => {
      const yr = yearOf(move);
      (byYear[yr] ||= []).push({ key, move, player: byUid.get(move.uid || key), sort: idx.has(key) ? idx.get(key) : moveOrder.length + i });
    });
    return Object.entries(byYear).sort(([a], [b]) => Number(a) - Number(b))
      .map(([year, items]) => ({ year: Number(year), items: items.sort((x, y) => x.sort - y.sort) }));
  }, [moves, moveOrder, teamRows, yearOf]);

  // ── drag and drop ──────────────────────────────────────────────────────────
  const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 5 } }), useSensor(KeyboardSensor));
  const [dragId, setDragId] = useState(null);
  const [notice, setNotice] = useState(null);
  const onDragEnd = useCallback(({ active, over }) => {
    setDragId(null);
    if (!active || !over || !projection) return;
    const uid = active.id;
    const target = over.id;
    const source = bucketOf(projection, uid);
    if (!source || source === target) return;
    setNotice(null);
    if (target === 'ilShort') applyMove(uid, 'ilShort');
    else if (target === 'ilLong') applyMove(uid, 'ilLong');
    else if (target === 'active') applyMove(uid, 'promote');
    else if (target === 'fortyMan' && source === 'departing') applyMove(uid, 'sign');
    else if (target === 'fortyMan' && (source === 'prospects' || source === 'r5Risk')) applyMove(uid, 'protect');
    else if (target === 'fortyMan') applyMove(uid, 'demote');
    else if (target === 'departing') applyMove(uid, 'dfa');
    else if (target === 'prospects' || target === 'r5Risk') {
      if (moves[uid]) deleteMove(uid);
      else setNotice('Moving a 40-man player off the 40-man is a DFA / outright: drop him on Departing.');
    }
  }, [projection, applyMove, deleteMove, moves]);
  const dragged = dragId && projection ? projection.enriched.find((p) => p._uid === dragId) : null;

  const [hoverActive, setHoverActive] = useState(null);
  const [hoverInactive, setHoverInactive] = useState(null);
  const [showOtherR5, setShowOtherR5] = useState(false);
  const [showProspects, setShowProspects] = useState(false);
  const [selected, setSelected] = useState(null);
  const select = useCallback((p) => setSelected(p), []);

  // ── render ─────────────────────────────────────────────────────────────────
  const exportDate = useMemo(() => { for (const p of teamRows) { const d = getRosterExportDate(p); if (d) return d; } return null; }, [teamRows]);
  const exportGap = useMemo(() => { for (const p of teamRows) { const g = getRosterExportGapDays(p); if (g != null) return g; } return null; }, [teamRows]);

  if (!orgs.length) {
    return <div className="ns-page"><div className="ns-page-head"><h1>Roster Planner</h1></div><div className="ns-muted">No players loaded for this league.</div></div>;
  }
  if (gameYear == null) {
    return <div className="ns-page"><div className="ns-page-head"><h1>Roster Planner</h1></div><div className="ns-alert-warn" style={{ padding: '8px 12px' }}>No game date in metadata.json and no contract years in the player rows: the planner has no year to start from.</div></div>;
  }

  if (!projection) return null;   // the org is picked on the first effect pass
  const p = projection;
  const openSlots = FORTY_MAN_LIMIT - p.fortyManCount;
  const seasonMoves = Object.values(moves).filter((m) => yearOf(m) === planYear).length;
  const cov = depth.coverage;
  const icov = depth.inactiveCoverage;
  const hl = (c, pos) => (pos ? c.coverageUids[pos] : null);
  const hlp = (c, pos) => (pos ? c.coverageUidsPotential?.[pos] : null);
  const r5Tag = (ep, dim) => ({ label: 'R5 eligible', bg: dim ? 'var(--panel-3)' : 'var(--warn-bg)', color: dim ? 'var(--text-2)' : 'var(--warn)',
    title: ep._r5?.yearsProtected ? `Protection period on file: ${ep._r5.yearsProtected} years` : 'Rule5Eligible flag from the OOTP roster export' });

  return (
    <div className="ns-page overflow-auto">
      <div className="ns-page-head">
        <div>
          <h1>Roster Planner</h1>
          <div className="ns-page-sub">
            Game year <b>{gameYear}</b>{game.source === 'contracts' ? ' (from contract years)' : ''}
            {contractYear > gameYear ? <> · contracts have rolled to <b>{contractYear}</b></> : null}
            {exportDate ? <> · Rule 5 and options from the OOTP export of <b>{exportDate}</b>{exportGap ? ` (${exportGap} game days old)` : ''}</> : null}
          </div>
        </div>
        <div className="ns-head-actions">
          <select className="ns-select" value={org} onChange={(e) => { pickedOrg.current = true; setOrg(e.target.value); }} aria-label="Organization">
            {orgs.map((o) => <option key={o} value={o}>{o}</option>)}
          </select>
        </div>
      </div>

      <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
        <div className="ns-box">
          <div className="ns-toolbar" style={{ borderBottom: 'none' }}>
            <span className="ns-label">Plan year</span>
            {Array.from({ length: YEAR_COUNT }, (_, i) => {
              const off = minOffset + i;
              return <button key={off} type="button" className="ns-btn ns-btn-sm" aria-pressed={planOffset === off} onClick={() => setOffset(off)}>{gameYear + off}</button>;
            })}
            <span style={{ flex: 1 }} />
            <button type="button" className="ns-btn ns-btn-sm" disabled={!history.length} onClick={undoLast}>Undo</button>
            <button type="button" className="ns-btn ns-btn-sm" disabled={!Object.keys(moves).length} onClick={resetPlan}
              style={Object.keys(moves).length ? { borderColor: 'var(--bad)', color: 'var(--bad)' } : undefined}>Reset</button>
          </div>
          <div className="ns-foot" style={{ display: 'flex', gap: 16, flexWrap: 'wrap' }}>
            <span>Drag players between sections to model moves.</span>
            <span>Year column: OOTP salary report, then the contract. <span style={{ color: 'var(--warn)' }}>Amber</span> = not guaranteed.</span>
            <span>Opt = option years used; options remaining is not in the data.</span>
          </div>
        </div>

        {!p.on40Known && (
          <div className="ns-alert-warn" style={{ padding: '7px 12px', fontSize: 12.5 }}>
            This league's rows carry no 40-man / active flags, so every player sits in the pipeline until you move him.
          </div>
        )}

        <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
          <SummaryCard label="40-man" value={`${p.fortyManCount}/${FORTY_MAN_LIMIT}`} color={p.fortyManCount > FORTY_MAN_LIMIT ? 'var(--bad-soft)' : 'var(--good)'} alert={p.fortyManCount > FORTY_MAN_LIMIT} />
          <SummaryCard label="Active" value={`${p.activeCount}/${ACTIVE_ROSTER_LIMIT}`} color={p.activeCount > ACTIVE_ROSTER_LIMIT ? 'var(--bad-soft)' : 'var(--accent)'} />
          <SummaryCard label="Open 40-man spots" value={openSlots} color={openSlots <= 0 ? 'var(--bad-soft)' : openSlots <= 2 ? 'var(--warn)' : 'var(--good)'} alert={openSlots < 0} />
          {planOffset > 0 && <SummaryCard label="R5 to protect" value={r5.shortlist.length} subtitle={`FV ${r5Threshold.toFixed(1)} or better`} color={r5.shortlist.length ? 'var(--warn)' : 'var(--good)'} />}
          <SummaryCard label="Status unknown" value={p.unknownStatus} subtitle="40-man, no report or contract" color={p.unknownStatus ? 'var(--warn)' : 'var(--text-2)'} />
          {seasonMoves > 0 && <SummaryCard label="Planned moves" value={seasonMoves} color="var(--chart-series-5)" />}
        </div>

        {notice && <div className="ns-alert-warn" style={{ padding: '7px 12px', fontSize: 12.5 }}>{notice}</div>}
        {warnings.length > 0 && <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>{warnings.map((w, i) => <Alert key={i} w={w} />)}</div>}

        {arbDecisions.length > 0 && (
          <CollapsiblePanel title={`Arbitration (${planYear}): tender or non-tender`} count={arbDecisions.length} accent="var(--accent)">
            {arbDecisions.map((ep) => {
              const st = years[ep._uid];
              const key = `t:${ep._uid}:${planYear}`;
              const d = moves[key]?.action;
              return (
                <QueueRow key={ep._uid} player={ep}>
                  <span style={{ color: 'var(--accent)', fontSize: 12, fontWeight: 600, minWidth: 40 }}>{st.statusLabel}</span>
                  <span className="tabular-nums" style={{ color: st.salary ? 'var(--warn)' : 'var(--text-disabled)', fontSize: 12, fontWeight: 600, minWidth: 64, textAlign: 'right' }} title="OOTP's projected arbitration salary (salary report)">{fmtSalary(st.salary) || '—'}</span>
                  {!d ? (
                    <div style={{ display: 'flex', gap: 6 }}>
                      <button type="button" className="ns-btn" style={actionBtnStyle('var(--good)')} onClick={() => applyMove(ep._uid, 'tender')}>Tender</button>
                      <button type="button" className="ns-btn" style={actionBtnStyle('var(--bad)')} onClick={() => applyMove(ep._uid, 'nonTender')}>Non-tender</button>
                    </div>
                  ) : (
                    <button type="button" className="ns-btn" title="Click to undo" style={actionBtnStyle(d === 'nonTender' ? 'var(--bad)' : 'var(--good)')} onClick={() => deleteMove(key)}>
                      {d === 'nonTender' ? 'Non-tendered' : 'Tendered'} ✕
                    </button>
                  )}
                </QueueRow>
              );
            })}
          </CollapsiblePanel>
        )}

        {optionDecisions.length > 0 && (
          <CollapsiblePanel title={`Team options due (${planYear})`} count={optionDecisions.length} accent="var(--warn)">
            {optionDecisions.map((ep) => {
              const d = moves[ep._uid]?.action;
              return (
                <QueueRow key={ep._uid} player={ep}>
                  <span style={{ color: 'var(--warn)', fontSize: 12, fontWeight: 600 }}>{years[ep._uid]?.label}</span>
                  {d === 'accept_option' || d === 'decline_option' ? (
                    <button type="button" className="ns-btn" title="Click to undo" style={actionBtnStyle(d === 'accept_option' ? 'var(--good)' : 'var(--bad)')} onClick={() => deleteMove(ep._uid)}>
                      {d === 'accept_option' ? 'Accepted' : 'Declined'} ✕
                    </button>
                  ) : (
                    <div style={{ display: 'flex', gap: 6 }}>
                      <button type="button" className="ns-btn" style={actionBtnStyle('var(--good)')} onClick={() => applyMove(ep._uid, 'accept_option')}>Accept</button>
                      <button type="button" className="ns-btn" style={actionBtnStyle('var(--bad)')} onClick={() => applyMove(ep._uid, 'decline_option')}>Decline</button>
                    </div>
                  )}
                </QueueRow>
              );
            })}
          </CollapsiblePanel>
        )}

        {expiring.length > 0 && (
          <CollapsiblePanel title={`Contracts ending before ${planYear}`} count={expiring.length} accent="var(--bad)">
            {expiring.map((ep) => (
              <QueueRow key={ep._uid} player={ep}>
                <span className="ns-muted" style={{ fontSize: 12 }}>FA in {planYear}</span>
                <button type="button" className="ns-btn" style={actionBtnStyle('var(--good)')} onClick={() => applyMove(ep._uid, 'sign')}>Re-sign</button>
              </QueueRow>
            ))}
          </CollapsiblePanel>
        )}

        <DndContext sensors={sensors} onDragStart={(e) => setDragId(e.active.id)} onDragCancel={() => setDragId(null)} onDragEnd={onDragEnd}>
          <DroppablePanel bucketId="active" title={`Active roster (${depth.counts.active}/${ACTIVE_ROSTER_LIMIT})`}
            subtitle={`${cov.hitterCount} hitters · ${cov.pitcherCount} pitchers (${cov.spCount} SP / ${cov.rpCount} RP)`} accent={BUCKET_ACCENT.active}>
            <CoverageStrip coverage={cov.coverage} coveragePotential={cov.coveragePotential} onHover={setHoverActive} hoveredPos={hoverActive} />
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(520px, 1fr))', gap: 8, padding: 8 }}>
              <div>
                <SlotGroup title="Catchers" players={depth.activeSlots.C} years={years} onSelect={select} need={2} highlightUids={hl(cov, hoverActive)} highlightUidsPotential={hlp(cov, hoverActive)} />
                <SlotGroup title="Infield" players={depth.activeSlots.IF} years={years} onSelect={select} highlightUids={hl(cov, hoverActive)} highlightUidsPotential={hlp(cov, hoverActive)} />
                <SlotGroup title="Outfield" players={depth.activeSlots.OF} years={years} onSelect={select} highlightUids={hl(cov, hoverActive)} highlightUidsPotential={hlp(cov, hoverActive)} />
                <SlotGroup title="Designated hitter" players={depth.activeSlots.DH} years={years} onSelect={select} highlightUids={hl(cov, hoverActive)} highlightUidsPotential={hlp(cov, hoverActive)} />
                {depth.activeSlots.bench.length > 0 && <SlotGroup title="Other hitters" players={depth.activeSlots.bench} years={years} onSelect={select} />}
              </div>
              <div>
                <SlotGroup title="Rotation" players={depth.activeSlots.SP} years={years} onSelect={select} target={ROTATION_SLOTS} need={ROTATION_SLOTS} highlightUids={hl(cov, hoverActive)} />
                <SlotGroup title="Bullpen" players={depth.activeSlots.RP} years={years} onSelect={select} target={BULLPEN_TARGET} highlightUids={hl(cov, hoverActive)} />
              </div>
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(420px, 1fr))', gap: 8, padding: '0 8px 8px' }}>
              {[['ilShort', 'Short IL', 'stays on the 40-man'], ['ilLong', '60-day IL', 'off the 40-man']].map(([id, t, sub]) => (
                <DroppablePanel key={id} bucketId={id} title={`${t} (${depth[id].length})`} subtitle={sub} accent={BUCKET_ACCENT[id]}>
                  {depth[id].length === 0
                    ? <div className="ns-muted" style={{ padding: '8px 12px', fontSize: 12, fontStyle: 'italic' }}>Empty. Drag players here.</div>
                    : <SlotGroup title=" " players={depth[id]} years={years} onSelect={select} />}
                </DroppablePanel>
              ))}
            </div>
          </DroppablePanel>

          <DroppablePanel bucketId="fortyMan" title={`40-man inactive (${depth.counts.inactive40}/${INACTIVE_FORTY_SLOTS})`}
            subtitle="Backup tiles: C / SS / CF 1+, SP 2+, RP 2+" accent={BUCKET_ACCENT.fortyMan}>
            <CoverageStrip coverage={icov.coverage} coveragePotential={icov.coveragePotential} onHover={setHoverInactive} hoveredPos={hoverInactive}
              requirements={icov.requirements} ideals={{ C: null, SS: null, CF: null, SP: null, RP: null }} />
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(520px, 1fr))', gap: 8, padding: 8 }}>
              <div>
                <SlotGroup title="Catchers" players={depth.inactiveSlots.C} years={years} onSelect={select} highlightUids={hl(icov, hoverInactive)} highlightUidsPotential={hlp(icov, hoverInactive)} />
                <SlotGroup title="Infield" players={depth.inactiveSlots.IF} years={years} onSelect={select} highlightUids={hl(icov, hoverInactive)} highlightUidsPotential={hlp(icov, hoverInactive)} />
                <SlotGroup title="Outfield" players={depth.inactiveSlots.OF} years={years} onSelect={select} highlightUids={hl(icov, hoverInactive)} highlightUidsPotential={hlp(icov, hoverInactive)} />
                {depth.inactiveSlots.DH.length > 0 && <SlotGroup title="Designated hitter" players={depth.inactiveSlots.DH} years={years} onSelect={select} />}
                {depth.inactiveSlots.bench.length > 0 && <SlotGroup title="Other hitters" players={depth.inactiveSlots.bench} years={years} onSelect={select} />}
              </div>
              <div>
                <SlotGroup title="SP depth" players={depth.inactiveSlots.SP} years={years} onSelect={select} need={2} highlightUids={hl(icov, hoverInactive)} />
                <SlotGroup title="RP depth" players={depth.inactiveSlots.RP} years={years} onSelect={select} need={2} highlightUids={hl(icov, hoverInactive)} />
              </div>
            </div>
          </DroppablePanel>

          {planOffset > 0 && (
            <DroppablePanel bucketId="r5Risk" title={`Rule 5 protection shortlist (${r5.shortlist.length})`}
              subtitle={`FV ${r5Threshold.toFixed(1)} or better: drag into the 40-man to protect`} accent={BUCKET_ACCENT.r5Risk}>
              <div className="ns-toolbar">
                <span className="ns-label">FV threshold</span>
                <input type="range" min={-3} max={3} step={0.1} value={r5Threshold} onChange={(e) => setR5Threshold(parseFloat(e.target.value))}
                  style={{ flex: 1, maxWidth: 280, accentColor: 'var(--accent)' }} aria-label="Rule 5 FV threshold" />
                <span className="tabular-nums" style={{ fontSize: 12.5, color: 'var(--warn)', fontWeight: 700, minWidth: 40, textAlign: 'right' }}>{r5Threshold.toFixed(1)}</span>
                <button type="button" className="ns-btn ns-btn-sm" onClick={() => setR5Threshold(R5_DEFAULT_THRESHOLD)}>Reset</button>
                <span className="ns-muted" style={{ fontSize: 12 }}>Eligibility is the OOTP export's Rule5Eligible flag; when a player becomes eligible is not in the data.</span>
              </div>
              {r5.shortlist.length === 0
                ? <div className="ns-muted" style={{ padding: '8px 12px', fontSize: 12, fontStyle: 'italic' }}>No Rule 5 exposed players meet the threshold.</div>
                : <><RowHeader />{r5.shortlist.map((ep) => <PlayerRow key={ep._uid} player={ep} yearStatus={years[ep._uid]} onSelect={select} tags={[r5Tag(ep, false)]} />)}</>}
              {r5.others.length > 0 && (
                <div style={{ padding: '8px 12px 10px' }}>
                  <button type="button" className="ns-btn ns-btn-sm" aria-pressed={showOtherR5} onClick={() => setShowOtherR5(!showOtherR5)}>
                    {showOtherR5 ? 'Hide' : 'Show'} R5 eligible below the threshold ({r5.others.length})
                  </button>
                  {showOtherR5 && (
                    <div className="ns-box" style={{ marginTop: 8 }}>
                      <RowHeader />
                      {r5.others.map((ep) => <PlayerRow key={ep._uid} player={ep} yearStatus={years[ep._uid]} onSelect={select} tags={[r5Tag(ep, true)]} />)}
                    </div>
                  )}
                </div>
              )}
            </DroppablePanel>
          )}

          <DroppablePanel bucketId="prospects" title={`Minor-league pipeline (${p.buckets.prospects.length + (planOffset > 0 ? 0 : p.buckets.r5Risk.length)})`}
            subtitle="Off the 40-man. Drag into the 40-man to add; drop a moved player back here to undo" accent={BUCKET_ACCENT.prospects}>
            <div style={{ padding: '8px 12px' }}>
              <button type="button" className="ns-btn ns-btn-sm" aria-pressed={showProspects} onClick={() => setShowProspects(!showProspects)}>
                {showProspects ? 'Hide' : 'Show'} players
              </button>
            </div>
            {showProspects && (
              <>
                <RowHeader />
                {[...(planOffset > 0 ? [] : p.buckets.r5Risk), ...p.buckets.prospects].map((ep) => (
                  <PlayerRow key={ep._uid} player={ep} yearStatus={years[ep._uid]} onSelect={select} tags={ep._r5?.exposed ? [r5Tag(ep, true)] : undefined} />
                ))}
              </>
            )}
          </DroppablePanel>

          <DroppablePanel bucketId="departing" title={`Departing (${p.buckets.departing.length})`}
            subtitle="Drop here to DFA / release. Free agents for the plan year land here too" accent={BUCKET_ACCENT.departing}>
            {p.buckets.departing.length === 0
              ? <div className="ns-muted" style={{ padding: '10px 12px', fontSize: 12, fontStyle: 'italic' }}>Empty. Drag players here to take them off the plan.</div>
              : <><RowHeader />{p.buckets.departing.map((ep) => <PlayerRow key={ep._uid} player={ep} yearStatus={years[ep._uid]} onSelect={select} />)}</>}
          </DroppablePanel>

          <DragOverlay>{dragged && <DragOverlayRow player={dragged} />}</DragOverlay>
        </DndContext>

        <SuggestionsPanel suggestions={suggestions} moves={moves} applyMove={applyMove} />
        <MovesLogPanel movesLog={movesLog} total={Object.keys(moves).length} deleteMove={deleteMove} reorderMoves={reorderMoves} />
      </div>

      {selected && <PlayerDetail player={selected} onClose={() => setSelected(null)} type={selected._type === 'pitcher' ? 'pitcher' : 'hitter'} />}
    </div>
  );
}
