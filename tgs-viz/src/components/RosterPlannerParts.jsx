// Roster Planner building blocks: the draggable player row, droppable bucket
// panels, coverage tiles, decision queues, suggestions and the moves log.
// Port of ours' views/RosterPlanner/{Panels,CompactPlayerRow,DepthChartPanels,
// QueuePanels,SuggestionsPanel,MovesLogPanel}.jsx onto his app: accessors for
// every player field, Night Scorecard tokens (CSS variables / ns-* classes).
import React, { memo, useState } from 'react';
import { useDraggable, useDroppable, DndContext, PointerSensor, KeyboardSensor, useSensor, useSensors, closestCenter } from '@dnd-kit/core';
import { SortableContext, useSortable, verticalListSortingStrategy, sortableKeyboardCoordinates } from '@dnd-kit/sortable';
import { CSS } from '@dnd-kit/utilities';
import { warStyle } from '../theme';
import { posClass } from '../lib/columns';
import { getPos, getName, getLevel, isEligible, isCurrentlyEligible } from '../lib/accessors';
import { fmtSalary } from '../lib/rosterPlanning/status';
import { COVERAGE_POSITIONS, ACTIVE_COVER_NEED, ACTIVE_COVER_IDEAL } from '../lib/rosterPlanning/rosterRules';

export const BUCKET_ACCENT = {
  active: 'var(--good)', fortyMan: 'var(--accent)', ilShort: 'var(--warn)', ilLong: 'var(--warn)',
  r5Risk: 'var(--warn)', prospects: 'var(--chart-series-5)', departing: 'var(--bad)',
};

export const MOVE_LABELS = {
  protect: 'Add to 40-man (R5)', dfa: 'DFA / release', trade: 'Trade away',
  promote: 'Promote to active', demote: 'Demote to inactive',
  sign: 'Re-sign (MLB)', sign_milb: 'Re-sign (MiLB)',
  decline_option: 'Decline option', accept_option: 'Accept option',
  nonTender: 'Non-tender', tender: 'Tender (arb)',
  ilShort: 'Place on short IL', ilLong: 'Place on 60-day IL',
};
const ACTION_COLORS = {
  protect: 'var(--warn)', dfa: 'var(--bad)', trade: 'var(--bad)', promote: 'var(--good)', demote: 'var(--text-2)',
  sign: 'var(--good-soft)', sign_milb: 'var(--chart-series-5)', decline_option: 'var(--bad-soft)',
  accept_option: 'var(--good-soft)', nonTender: 'var(--bad)', tender: 'var(--good-soft)',
  ilShort: 'var(--warn)', ilLong: 'var(--warn)',
};

const POTENTIAL_BG = 'color-mix(in oklab, var(--chart-series-5) 12%, var(--panel))';
const fmt1 = (v) => (v == null || !Number.isFinite(v) ? '—' : v.toFixed(1));
const TAG = { display: 'inline-block', fontFamily: 'var(--font-narrow)', fontWeight: 700, fontSize: 11, lineHeight: '16px', padding: '0 5px', borderRadius: 'var(--radius)', whiteSpace: 'nowrap' };

export function actionBtnStyle(color) {
  return { fontSize: 11.5, padding: '2px 9px', borderColor: color, color };
}

// ── stat tile ────────────────────────────────────────────────────────────────
export const SummaryCard = memo(function SummaryCard({ label, value, subtitle, color = 'var(--text-2)', alert }) {
  return (
    <div className="ns-box" style={{ flex: '1 1 120px', minWidth: 120, borderColor: alert ? 'var(--bad)' : undefined }}>
      <div className="ns-strip" style={{ minHeight: 26, padding: '4px 12px', fontSize: 12, fontWeight: 600, color: alert ? 'var(--bad-soft)' : 'var(--text-3)', background: alert ? 'var(--bad-bg)' : undefined }}>
        {label}
      </div>
      <div style={{ padding: '8px 12px 10px' }}>
        <div className="tabular-nums" style={{ fontSize: 22, fontWeight: 800, color, lineHeight: 1.1 }}>{value}</div>
        {subtitle && <div className="ns-muted" style={{ fontSize: 11.5, marginTop: 3 }}>{subtitle}</div>}
      </div>
    </div>
  );
});

// ── player row ───────────────────────────────────────────────────────────────
// Fixed tracks so every row (its own grid) lines up with the header; tags take the rest.
const ROW_COLS = '18px 32px 150px 30px 36px 42px 42px 42px 96px 34px minmax(0,1fr)';

export function RowHeader() {
  const th = { fontFamily: 'var(--font-narrow)', fontSize: 12, color: 'var(--text-2)', fontWeight: 600, whiteSpace: 'nowrap' };
  const r = { ...th, textAlign: 'right' };
  return (
    <div style={{ display: 'grid', gridTemplateColumns: ROW_COLS, alignItems: 'center', gap: 4, padding: '0 6px', height: 26, background: 'var(--panel-2)', borderBottom: '1px solid var(--line-2)' }}>
      <span /><span style={th}>Pos</span><span style={th}>Name</span><span style={th}>Age</span><span style={th}>Lev</span>
      <span style={r} title="Current WAR">WAR</span><span style={r} title="Potential WAR">Pot</span><span style={r} title="Future value (WAR)">FV</span>
      <span style={r} title="Status for the plan year">Year</span><span style={{ ...th, textAlign: 'center' }} title="Option years used (the export's OptionsUsed)">Opt</span><span />
    </div>
  );
}

const DEV_NOTE_POSITIONS = ['C', 'SS', 'CF', '2B', '3B', 'LF', 'RF'];
function needsReps(p) {
  if (!p || p._type === 'pitcher') return [];
  const primary = getPos(p);
  return DEV_NOTE_POSITIONS.filter((pos) => pos !== primary && isEligible(p, pos) && !isCurrentlyEligible(p, pos));
}

function yearCell(st) {
  if (!st) return { text: '—', color: 'var(--text-disabled)', title: undefined };
  if (st.status === 'unknown') return { text: 'Unknown', color: 'var(--text-3)', title: 'No salary-report cell or contract year covers this year' };
  if (st.status === 'fa') return { text: 'FA', color: 'var(--bad-soft)', title: 'Free agent this year (OOTP salary report)' };
  if (st.status === 'minors') return { text: st.statusLabel === 'MiLB' ? 'MiLB' : st.statusLabel, color: 'var(--text-3)', title: st.termUnknown ? 'Minor-league deal; when it ends is in no data field' : undefined };
  const sal = fmtSalary(st.salary);
  const tag = st.status === 'option' ? ` ${st.statusLabel}` : st.status === 'arb' ? ` ${st.statusLabel}` : '';
  const nonG = st.salary > 0 && st.guaranteed === false;
  return { text: `${sal || st.label}${tag}`, color: st.status === 'option' ? 'var(--good-soft)' : nonG ? 'var(--warn)' : 'var(--text)', title: nonG ? 'Not guaranteed (arbitration / renewal)' : st.statusLabel };
}

export const PlayerRow = memo(function PlayerRow({ player, yearStatus, onSelect, tags, highlight, highlightKind, actions, draggable = true }) {
  const drag = useDraggable({ id: player._uid, disabled: !draggable });
  const [hovered, setHovered] = useState(false);
  const pos = getPos(player) || '?';
  const used = player._options?.used;
  const yc = yearCell(yearStatus);
  const needs = needsReps(player);
  const t = drag.transform;
  const bg = highlight ? (highlightKind === 'potential' ? POTENTIAL_BG : 'var(--accent-bg)') : hovered ? 'var(--panel-3)' : undefined;
  const rule = highlight ? (highlightKind === 'potential' ? 'var(--chart-series-5)' : 'var(--accent)') : hovered ? 'var(--accent)' : null;
  return (
    <div ref={drag.setNodeRef} {...drag.attributes} {...drag.listeners}
      onMouseEnter={() => setHovered(true)} onMouseLeave={() => setHovered(false)}
      className="tabular-nums"
      style={{
        display: 'grid', gridTemplateColumns: ROW_COLS, alignItems: 'center', gap: 4, padding: '0 6px', minHeight: 29,
        borderBottom: '1px solid var(--line)', fontSize: 12, color: 'var(--text)', cursor: draggable ? 'grab' : 'default',
        transform: t ? `translate(${t.x}px, ${t.y}px)` : undefined, background: bg,
        boxShadow: rule ? `inset 2px 0 0 ${rule}` : undefined, opacity: drag.isDragging ? 0.6 : 1,
      }}>
      <span className="ns-dim" style={{ fontSize: 10, textAlign: 'center' }}>{draggable ? '☰' : ''}</span>
      <span className={posClass(pos)} style={{ fontSize: 12.5 }}>{pos}</span>
      <span style={{ fontWeight: 600, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', cursor: 'pointer' }}
        onPointerDown={(e) => e.stopPropagation()}
        onClick={(e) => { e.stopPropagation(); onSelect?.(player); }} title={getName(player) || undefined}>
        {getName(player) || '?'}
      </span>
      <span className="ns-text-2">{player._age ?? '—'}</span>
      <span className="ns-muted" style={{ fontSize: 11.5 }}>{getLevel(player) || '—'}</span>
      <span style={{ textAlign: 'right', ...warStyle(player._war) }}>{fmt1(player._war)}</span>
      <span style={{ textAlign: 'right', ...warStyle(player._warP) }}>{fmt1(player._warP)}</span>
      <span style={{ textAlign: 'right', ...warStyle(player._fv) }}>{fmt1(player._fv)}</span>
      <span style={{ textAlign: 'right', fontSize: 11.5, fontWeight: 600, color: yc.color, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }} title={yc.title}>{yc.text}</span>
      <span className="ns-muted" style={{ fontFamily: 'var(--font-narrow)', fontSize: 11, textAlign: 'center' }} title={used != null ? `${used} option year${used === 1 ? '' : 's'} used; remaining is not in the data` : 'Options used: not in the export for this player'}>
        {used != null ? `${used}u` : ''}
      </span>
      <span style={{ fontSize: 11, display: 'flex', gap: 4, justifyContent: 'flex-end', flexWrap: 'wrap', alignItems: 'center', padding: '2px 0' }}>
        {needs.length > 0 && (
          <span title={`Has the ratings for ${needs.join(', ')} but not yet the in-game reps.`}
            style={{ ...TAG, background: 'color-mix(in oklab, var(--chart-series-5) 15%, var(--panel))', color: 'var(--chart-series-5)' }}>
            Needs reps: {needs.join('/')}
          </span>
        )}
        {tags && tags.map((tg, i) => <span key={i} style={{ ...TAG, background: tg.bg, color: tg.color }} title={tg.title}>{tg.label}</span>)}
        {actions}
      </span>
    </div>
  );
});

export function DragOverlayRow({ player }) {
  if (!player) return null;
  const pos = getPos(player);
  return (
    <div style={{ display: 'flex', gap: 8, alignItems: 'center', padding: '5px 12px', background: 'var(--panel-3)', border: '2px solid var(--accent)', borderRadius: 'var(--radius)', fontSize: 12.5, color: 'var(--text)' }}>
      <span className={posClass(pos)}>{pos}</span>
      <span style={{ fontWeight: 600 }}>{getName(player)}</span>
    </div>
  );
}

// ── droppable panel / coverage / slot groups ─────────────────────────────────
export function DroppablePanel({ bucketId, title, subtitle, accent, children }) {
  const { setNodeRef, isOver } = useDroppable({ id: bucketId });
  return (
    <div ref={setNodeRef} className="ns-box" style={{ background: isOver ? 'var(--accent-bg-2)' : undefined, borderColor: isOver ? 'var(--accent)' : undefined, transition: 'border-color 0.15s, background 0.15s' }}>
      <div className="ns-strip" style={{ justifyContent: 'flex-start', paddingLeft: 14, boxShadow: `inset 3px 0 0 ${accent}` }}>
        <h2>{title}</h2>
        {subtitle && <span style={{ fontSize: 12, fontWeight: 500, color: 'var(--text-3)' }}>{subtitle}</span>}
      </div>
      {children}
    </div>
  );
}

function tileColors(count, need, ideal) {
  if (count < need) return { bg: 'var(--bad-bg)', color: 'var(--bad-soft)', border: 'var(--bad)' };
  if (ideal != null && count < ideal) return { bg: 'var(--warn-bg)', color: 'var(--warn)', border: 'var(--warn)' };
  return { bg: 'var(--good-bg)', color: 'var(--good-soft)', border: 'var(--good)' };
}

export function CoverageStrip({ coverage, coveragePotential, onHover, hoveredPos, requirements, ideals }) {
  const order = requirements ? Object.keys(requirements) : COVERAGE_POSITIONS;
  return (
    <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', padding: '8px 12px', borderBottom: '1px solid var(--line)' }}>
      {order.map((pos) => {
        const count = coverage[pos] ?? 0;
        const pot = coveragePotential?.[pos] ?? 0;
        const need = requirements ? requirements[pos] : ACTIVE_COVER_NEED;
        const ideal = ideals ? ideals[pos] : (pos === 'C' ? null : ACTIVE_COVER_IDEAL);
        const c = tileColors(count, need, ideal);
        const req = ideal != null ? `need ${need}+, ideal ${ideal}+` : `need ${need}+`;
        return (
          <span key={pos} onMouseEnter={() => onHover?.(pos)} onMouseLeave={() => onHover?.(null)}
            title={pot > 0 ? `${pos}: ${count} eligible now, ${pot} with the ratings but not the reps (${req})` : `${count} ${pos} (${req})`}
            style={{ display: 'inline-flex', alignItems: 'center', gap: 5, padding: '2px 8px', borderRadius: 'var(--radius)', background: c.bg, border: `1px solid ${hoveredPos === pos ? 'var(--accent)' : c.border}`, color: c.color, fontFamily: 'var(--font-narrow)', fontSize: 12.5, fontWeight: 700 }}>
            <span className={posClass(pos)}>{pos}</span>
            <span>{count}</span>
            {pot > 0 && <span style={{ color: 'var(--chart-series-5)', fontSize: 11, fontWeight: 600 }}>+{pot}</span>}
          </span>
        );
      })}
    </div>
  );
}

export function SlotGroup({ title, players, years, onSelect, target, need, highlightUids, highlightUidsPotential }) {
  const short = need != null && players.length < need;
  return (
    <div style={{ marginBottom: 8 }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '4px 10px', background: 'var(--panel-2)', borderBottom: '1px solid var(--line)', borderTop: '1px solid var(--line-2)' }}>
        <span style={{ fontFamily: 'var(--font-narrow)', fontSize: 12.5, fontWeight: 700, color: short ? 'var(--bad-soft)' : 'var(--text)' }}>{title}</span>
        <span style={{ fontFamily: 'var(--font-narrow)', fontSize: 12, fontWeight: 600, color: short ? 'var(--bad-soft)' : 'var(--text-3)' }}>
          {players.length}{target ? `/${target}` : ''}{need != null ? ` (min ${need})` : ''}
        </span>
      </div>
      {players.length === 0
        ? <div className="ns-muted" style={{ padding: '6px 10px', fontSize: 12, fontStyle: 'italic' }}>{short ? 'Requirement unmet' : '—'}</div>
        : <RowHeader />}
      {players.map((p) => {
        const cur = highlightUids && highlightUids.has(p._uid);
        const pot = !cur && highlightUidsPotential && highlightUidsPotential.has(p._uid);
        return <PlayerRow key={p._uid} player={p} yearStatus={years?.[p._uid]} onSelect={onSelect} highlight={cur || pot} highlightKind={pot ? 'potential' : 'current'} />;
      })}
    </div>
  );
}

// ── decision queues ──────────────────────────────────────────────────────────
export function CollapsiblePanel({ title, count, accent, children, defaultOpen = true }) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div className="ns-box">
      <button type="button" onClick={() => setOpen((o) => !o)} aria-expanded={open} className="ns-strip"
        style={{ width: '100%', justifyContent: 'flex-start', cursor: 'pointer', textAlign: 'left', paddingLeft: 14, boxShadow: `inset 3px 0 0 ${accent}`, color: accent, border: 'none', borderBottom: open ? '1px solid var(--line-2)' : 'none' }}>
        <span className="ns-muted" style={{ fontSize: 11, width: 12 }}>{open ? '▾' : '▸'}</span>
        <span>{title}</span>
        {count != null && <span className="ns-count">({count})</span>}
      </button>
      {open && <div>{children}</div>}
    </div>
  );
}

export function QueueRow({ player, children }) {
  const pos = getPos(player);
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '4px 12px', minHeight: 31, borderBottom: '1px solid var(--line)', fontSize: 12.5 }}>
      <span className={posClass(pos)} style={{ width: 28 }}>{pos}</span>
      <span style={{ fontWeight: 600, flex: 1 }}>{getName(player)}</span>
      {children}
    </div>
  );
}

// ── suggestions ──────────────────────────────────────────────────────────────
const SUG_TITLES = { protect: 'Must protect (Rule 5)', considerProtect: 'Consider protecting (Rule 5)', dfa: 'DFA candidates', promote: 'Promote to active' };
const SUG_COLORS = { protect: 'var(--warn)', considerProtect: 'var(--warn)', dfa: 'var(--bad)', promote: 'var(--good)' };

export function SuggestionsPanel({ suggestions, moves, applyMove }) {
  const [show, setShow] = useState(false);
  return (
    <div className="ns-box">
      <div className="ns-strip">
        <h2>Smart suggestions <span className="ns-count">({suggestions.length})</span></h2>
        <button type="button" className="ns-btn ns-btn-sm" aria-pressed={show} onClick={() => setShow(!show)}>{show ? 'Hide' : 'Show'}</button>
      </div>
      <div className="ns-box-body">
        {!show && <div className="ns-muted" style={{ fontSize: 12.5 }}>Rule 5 protects, DFA candidates and promotions. Planning advice, not OOTP rules.</div>}
        {show && suggestions.length === 0 && <div className="ns-muted" style={{ fontSize: 12.5, fontStyle: 'italic' }}>No suggestions for this year.</div>}
        {show && suggestions.length > 0 && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
            {Object.keys(SUG_TITLES).map((type) => {
              const group = suggestions.filter((s) => s.type === type);
              if (!group.length) return null;
              return (
                <div key={type}>
                  <div style={{ fontFamily: 'var(--font-narrow)', fontSize: 12.5, fontWeight: 700, color: SUG_COLORS[type], marginBottom: 6 }}>{SUG_TITLES[type]}</div>
                  {group.map((s) => {
                    const done = moves[s.playerId]?.action === s.action;
                    const pos = getPos(s.player);
                    return (
                      <div key={`${type}:${s.playerId}`} style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '4px 10px', minHeight: 31, marginBottom: 4, background: done ? 'var(--good-bg)' : 'var(--panel)', border: `1px solid ${done ? 'var(--good)' : 'var(--line)'}`, borderRadius: 'var(--radius)' }}>
                        <span className={posClass(pos)}>{pos}</span>
                        <span style={{ fontSize: 12.5, fontWeight: 600, flex: 1 }}>{getName(s.player)}</span>
                        <span className="ns-muted" style={{ fontSize: 12, flex: 2 }}>{s.reason}</span>
                        {done
                          ? <span style={{ fontFamily: 'var(--font-narrow)', fontSize: 12, color: 'var(--good)', fontWeight: 700 }}>Applied</span>
                          : <button type="button" className="ns-btn" style={actionBtnStyle(SUG_COLORS[type])} onClick={() => applyMove(s.playerId, s.action)}>Apply</button>}
                      </div>
                    );
                  })}
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}

// ── moves log ────────────────────────────────────────────────────────────────
function SortableMoveRow({ id, move, player, deleteMove }) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({ id });
  const pos = player ? getPos(player) : null;
  return (
    <div ref={setNodeRef} style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '3px 8px', minHeight: 31, marginBottom: 4, background: isDragging ? 'var(--accent-bg)' : 'var(--panel)', border: `1px solid ${isDragging ? 'var(--accent)' : 'var(--line)'}`, borderRadius: 'var(--radius)', transform: CSS.Transform.toString(transform), transition }}>
      <span {...attributes} {...listeners} title="Drag to reorder" className="ns-dim" style={{ fontSize: 12, cursor: 'grab', padding: '0 4px', userSelect: 'none' }}>{'☰'}</span>
      <span className={posClass(pos)} style={{ width: 28 }}>{pos || '?'}</span>
      <span style={{ fontSize: 12.5, fontWeight: 600, flex: 1 }}>{player ? getName(player) : (move.uid || id)}</span>
      <span style={{ fontFamily: 'var(--font-narrow)', fontSize: 12.5, fontWeight: 700, minWidth: 130, color: ACTION_COLORS[move.action] || 'var(--text-2)' }}>{MOVE_LABELS[move.action] || move.action}</span>
      <button type="button" className="ns-btn ns-btn-sm" style={{ fontSize: 11.5, padding: '2px 8px' }} onClick={() => deleteMove(id)} title="Remove this move">Undo</button>
    </div>
  );
}

function YearGroup({ year, items, deleteMove, reorderMoves }) {
  const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 4 } }), useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }));
  return (
    <div>
      <div className="ns-label" style={{ marginBottom: 6 }}>{year} season</div>
      <DndContext sensors={sensors} collisionDetection={closestCenter}
        onDragEnd={({ active, over }) => { if (over && active.id !== over.id) reorderMoves(year, active.id, over.id); }}>
        <SortableContext items={items.map((i) => i.key)} strategy={verticalListSortingStrategy}>
          {items.map((it) => <SortableMoveRow key={it.key} id={it.key} move={it.move} player={it.player} deleteMove={deleteMove} />)}
        </SortableContext>
      </DndContext>
    </div>
  );
}

export function MovesLogPanel({ movesLog, total, deleteMove, reorderMoves }) {
  if (!movesLog.length) return null;
  return (
    <div className="ns-box">
      <div className="ns-strip"><h2>Moves log <span className="ns-count">({total})</span></h2></div>
      <div className="ns-box-body" style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
        <div className="ns-muted" style={{ fontSize: 12 }}>Drag the {'☰'} handle to reorder by priority. Saved in this browser, per league and org.</div>
        {movesLog.map(({ year, items }) => <YearGroup key={year} year={year} items={items} deleteMove={deleteMove} reorderMoves={reorderMoves} />)}
      </div>
    </div>
  );
}
