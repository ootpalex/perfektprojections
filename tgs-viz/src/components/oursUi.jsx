// ============================================================================
// oursUi.jsx — the UI primitives ours' views are built from, ported from
// ootp-dashboard app/src/components/shared.jsx (Night Scorecard, inline styles
// from theme.js `S` / TOKENS). Only what the ported pages use is here.
//
// Changed from ours: LevelFilter reads levels through lib/accessors.js and has
// no per-rookie-team expansion (his rows carry no team abbreviation, so ours'
// "tm:" grouping has no source; bridge.md §4).
// ============================================================================
import { useState, useRef, useEffect, useMemo } from 'react';
import { TOKENS as T, S } from '../theme.js';
import { categorizeLevel, LEVEL_CATEGORY_ORDER, getLevel } from '../lib/accessors.js';

const R = T.radius;
const FOCUS_RING = `0 0 0 2px ${T.focusRing}`;
const focusStyle = { border: `1px solid ${T.focus}`, boxShadow: FOCUS_RING };

function useFocusRing() {
  const [focused, setFocused] = useState(false);
  return {
    focused,
    onFocus: (e) => { try { setFocused(e.currentTarget.matches(':focus-visible')); } catch { setFocused(true); } },
    onBlur: () => setFocused(false),
  };
}

function WellInput({ style, ...props }) {
  const ring = useFocusRing();
  return (
    <input
      {...props}
      onFocus={(e) => { ring.onFocus(e); props.onFocus?.(e); }}
      onBlur={(e) => { ring.onBlur(e); props.onBlur?.(e); }}
      style={{ ...S.searchInput, ...style, ...(ring.focused ? focusStyle : {}) }}
    />
  );
}

const SEARCH_ICON = `url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='${encodeURIComponent(T.text3)}' stroke-width='2.2' stroke-linecap='round'><circle cx='11' cy='11' r='7'/><path d='m20 20-3.5-3.5'/></svg>")`;
const searchWellStyle = { ...S.searchInput, paddingLeft: 26, backgroundImage: SEARCH_ICON, backgroundRepeat: 'no-repeat', backgroundSize: 13, backgroundPosition: '8px center' };

export function SearchInput({ style, ...props }) {
  return <WellInput {...props} style={{ ...searchWellStyle, ...style }} />;
}

// Scorecard box: panel + line2 rule + header strip.
export function Section({ title, children, actions, count, state, toolbar, footer }) {
  return (
    <div style={S.box}>
      <div style={S.boxHead}>
        <h2 style={{ ...S.sectionTitle, display: 'flex', alignItems: 'center', gap: 6, minWidth: 0 }}>
          <span>{title}</span>
          {count != null && count !== '' && <span style={{ fontWeight: 500, color: T.text3 }}>{count}</span>}
        </h2>
        {(state != null || actions) && (
          <div style={{ marginLeft: 'auto', display: 'flex', gap: 8, alignItems: 'center' }}>
            {state != null && <span style={S.boxHeadRight}>{state}</span>}
            {actions}
          </div>
        )}
      </div>
      {toolbar && <div style={S.toolbar}>{toolbar}</div>}
      <div style={{ padding: 12 }}>{children}</div>
      {footer && <div style={S.boxFoot}>{footer}</div>}
    </div>
  );
}

// Column-group rule: the 1px left rule for column i when it starts a new group.
export function colRule(cols, i) {
  if (!cols || i <= 0) return null;
  const g = cols[i]?.group, prev = cols[i - 1]?.group;
  return g != null && g !== prev ? S.groupRule : null;
}

export function SortHeader({ label, width, sortCol, sortDir, colKey, onClick, rule, align, title }) {
  const active = sortCol === colKey;
  const ariaSort = active ? (sortDir === 'asc' ? 'ascending' : 'descending') : 'none';
  return (
    <th onClick={onClick} onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onClick(); } }} tabIndex={0} aria-sort={ariaSort} title={title}
      onMouseEnter={(e) => { e.currentTarget.style.color = T.text; }}
      onMouseLeave={(e) => { e.currentTarget.style.color = active ? T.text : T.text2; }}
      style={{ ...S.th, ...(active ? S.thSorted : {}), ...(rule || {}), ...(align ? { textAlign: align } : {}), width, minWidth: width, cursor: 'pointer', userSelect: 'none' }}>
      <span>{label}</span>{active && <span style={{ marginLeft: 3, fontSize: 10 }} aria-hidden="true">{sortDir === 'asc' ? '▲' : '▼'}</span>}
    </th>
  );
}

export function PillBtn({ active, onClick, children, style: extraStyle, role: roleProp, ariaLabel }) {
  return (
    <button type="button" onClick={onClick} role={roleProp || 'tab'} aria-selected={active} aria-label={ariaLabel}
      style={{ ...S.pillBtn, fontSize: 13, ...(active ? { background: T.accentBg, color: T.accent, borderColor: T.accent } : { background: T.panel, color: T.text2, borderColor: T.line2 }), ...extraStyle }}>
      {children}
    </button>
  );
}

export function TabGroup({ children, label, style: extraStyle }) {
  return (
    <div role="tablist" aria-label={label} style={{ display: 'inline-flex', alignItems: 'center', gap: 4, padding: 3, background: T.panel2, border: `1px solid ${T.line2}`, borderRadius: R, ...extraStyle }}>
      {children}
    </div>
  );
}

const triggerStyle = ({ open, active, focused, minWidth }) => ({
  ...S.filterSelect,
  padding: '5px 8px 5px 10px',
  border: `1px solid ${open || focused ? T.focus : T.line2}`,
  color: active ? T.accent : T.text,
  minWidth,
  textAlign: 'left',
  display: 'inline-flex',
  alignItems: 'center',
  justifyContent: 'space-between',
  gap: 8,
  boxShadow: focused ? FOCUS_RING : 'none',
  transition: 'border-color 0.12s',
});
const caretStyle = (open) => ({ fontSize: 9, color: T.text3, transform: open ? 'rotate(180deg)' : 'none', transition: 'transform 0.12s' });
const popoverStyle = { position: 'absolute', top: 'calc(100% + 4px)', left: 0, background: T.panel, border: `1px solid ${T.line2}`, borderRadius: R, zIndex: 1000 };
const popoverHeadStyle = { display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 8, fontFamily: T.fonts.narrow, fontSize: 12, fontWeight: 600, color: T.text2 };
const clearLinkStyle = { background: 'none', border: 'none', color: T.accent, fontFamily: T.fonts.narrow, fontSize: 12, fontWeight: 600, cursor: 'pointer', padding: 0 };

// Checkbox dropdown; value is an array, empty = no filter.
export function MultiSelectDropdown({ options, value, onChange, placeholder = 'All', ariaLabel = 'Filter', minWidth = 200, popoverMinWidth = 220 }) {
  const [open, setOpen] = useState(false);
  const ref = useRef(null);
  const ring = useFocusRing();
  useEffect(() => {
    if (!open) return undefined;
    const onDown = (e) => { if (!ref.current?.contains(e.target)) setOpen(false); };
    const onEsc = (e) => { if (e.key === 'Escape') setOpen(false); };
    document.addEventListener('mousedown', onDown);
    document.addEventListener('keydown', onEsc);
    return () => {
      document.removeEventListener('mousedown', onDown);
      document.removeEventListener('keydown', onEsc);
    };
  }, [open]);

  const sel = Array.isArray(value) ? value : [];
  const toggle = (opt) => onChange(sel.includes(opt) ? sel.filter((o) => o !== opt) : [...sel, opt]);
  const labelFor = (val) => options.find((o) => o.value === val)?.label ?? val;
  let label;
  if (sel.length === 0) label = placeholder;
  else if (sel.length === 1) label = labelFor(sel[0]);
  else if (sel.length <= 3) label = sel.map(labelFor).join(', ');
  else label = `${sel.slice(0, 2).map(labelFor).join(', ')} +${sel.length - 2}`;

  return (
    <div ref={ref} style={{ position: 'relative', display: 'inline-block' }}>
      <button type="button" onClick={() => setOpen((o) => !o)} onFocus={ring.onFocus} onBlur={ring.onBlur}
        aria-haspopup="listbox" aria-expanded={open} aria-label={ariaLabel}
        style={triggerStyle({ open, active: sel.length > 0, focused: ring.focused, minWidth })}>
        <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
          {label}
          {sel.length > 1 && (
            <span style={{ padding: '0 5px', borderRadius: R, background: T.accentBg, border: `1px solid ${T.accent}`, fontSize: 10.5, lineHeight: '14px', color: T.accent, fontWeight: 700 }}>{sel.length}</span>
          )}
        </span>
        <span style={caretStyle(open)} aria-hidden="true">▾</span>
      </button>
      {open && (
        <div role="listbox" aria-multiselectable="true" style={{ ...popoverStyle, minWidth: popoverMinWidth, maxHeight: 380, overflowY: 'auto', padding: 4 }}>
          <div style={{ ...popoverHeadStyle, padding: '5px 8px 6px', borderBottom: `1px solid ${T.line}`, marginBottom: 3 }}>
            <span>{ariaLabel}</span>
            {sel.length > 0 && <button type="button" onClick={() => onChange([])} style={clearLinkStyle}>Clear all</button>}
          </div>
          {options.flatMap((opt) => {
            const checked = sel.includes(opt.value);
            const items = [];
            if (opt.dividerBefore) items.push(<div key={opt.value + '-div'} style={{ height: 1, background: T.line, margin: '3px 6px' }} />);
            if (opt.header) {
              items.push(<div key={opt.value} style={{ padding: '5px 8px 2px', fontFamily: T.fonts.narrow, fontSize: 12, color: T.text3, fontWeight: 600 }}>{opt.label}</div>);
              return items;
            }
            items.push(
              <label key={opt.value} style={{
                display: 'flex', alignItems: 'center', gap: 9, padding: '5px 8px', paddingLeft: opt.indent ? 22 : 8,
                borderRadius: R, cursor: 'pointer', background: checked ? T.accentBg : 'transparent',
                color: checked ? T.text : T.text2, fontSize: 12.5, fontWeight: checked ? 600 : 500, userSelect: 'none',
              }}
              onMouseEnter={(e) => { if (!checked) e.currentTarget.style.background = T.panel3; }}
              onMouseLeave={(e) => { if (!checked) e.currentTarget.style.background = 'transparent'; }}>
                <input type="checkbox" checked={checked} onChange={() => toggle(opt.value)} style={{ accentColor: T.accent, margin: 0, cursor: 'pointer' }} />
                <span>{opt.label}</span>
              </label>
            );
            return items;
          })}
        </div>
      )}
    </div>
  );
}

const POSITION_FILTER_ORDER = ['Hitters', 'Pitchers', 'SP', 'RP', 'C', '1B', '2B', '3B', 'SS', 'INF', 'LF', 'CF', 'RF', 'OF'];
const POSITION_FILTER_DIVIDERS = new Set(['SP', 'C']);
const POSITION_FILTER_OPTIONS = POSITION_FILTER_ORDER.map((p) => ({ value: p, label: p, dividerBefore: POSITION_FILTER_DIVIDERS.has(p) }));

export function PositionFilter({ value, onChange }) {
  return <MultiSelectDropdown options={POSITION_FILTER_OPTIONS} value={value} onChange={onChange} placeholder="All Positions" ariaLabel="Filter by position" />;
}

// Level categories present in `players`, in ours' order.
export function LevelFilter({ players, value, onChange, placeholder = 'All Levels' }) {
  const options = useMemo(() => {
    const cats = new Set();
    for (const p of players || []) {
      const c = categorizeLevel(getLevel(p));
      if (c) cats.add(c);
    }
    return LEVEL_CATEGORY_ORDER.filter((c) => cats.has(c)).map((c, i) => ({ value: c, label: c, dividerBefore: i > 0 && c === 'Rookie' }));
  }, [players]);
  return <MultiSelectDropdown options={options} value={value} onChange={onChange} placeholder={placeholder} ariaLabel="Filter by level" />;
}

// Switch row (ours' Toggle, variant "row").
export function Toggle({ label, checked, onChange, description }) {
  const ring = useFocusRing();
  const handle = (e) => { e.preventDefault(); onChange(!checked); };
  return (
    <label style={{ display: 'flex', alignItems: 'flex-start', gap: 10, cursor: 'pointer', padding: '8px 12px', borderTop: `1px solid ${T.line}` }}
      onMouseEnter={(e) => { e.currentTarget.style.background = T.panel2; }}
      onMouseLeave={(e) => { e.currentTarget.style.background = 'transparent'; }}>
      <div onClick={handle} role="switch" aria-checked={checked} aria-label={label} tabIndex={0}
        onKeyDown={(e) => { if (e.key === ' ' || e.key === 'Enter') handle(e); }}
        onFocus={ring.onFocus} onBlur={ring.onBlur}
        style={{ width: 30, height: 17, boxSizing: 'border-box', borderRadius: 9, background: checked ? T.accent : T.bg, border: `1px solid ${checked ? T.accent : T.line2}`, position: 'relative', cursor: 'pointer', transition: 'background 0.12s, border-color 0.12s', flexShrink: 0, marginTop: 2, outline: 'none', boxShadow: ring.focused ? FOCUS_RING : 'none' }}>
        <div style={{ width: 11, height: 11, borderRadius: '50%', background: checked ? T.accentText : T.text3, position: 'absolute', top: 2, left: checked ? 15 : 2, transition: 'left 0.12s ease' }} />
      </div>
      <div>
        <div style={{ fontSize: 13, color: checked ? T.text : T.text2, fontWeight: 600 }}>{label}</div>
        {description && <div style={{ fontSize: 12, color: T.text3, marginTop: 1 }}>{description}</div>}
      </div>
    </label>
  );
}

// Foot strip with the pager.
export function Pagination({ page, totalPages, total, onPrev, onNext }) {
  const prevOff = page === 0;
  const nextOff = page >= totalPages - 1;
  // borderColor is always set (ours toggled it on and off over S.pageBtn's
  // border shorthand, which React warns about on every re-render).
  const btn = (off) => ({ ...S.pageBtn, borderColor: off ? T.line : T.line2, ...(off ? { color: T.textDisabled, cursor: 'default' } : {}) });
  return (
    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 10, padding: '8px 12px', background: T.panel2, borderTop: `1px solid ${T.line2}`, fontFamily: T.fonts.narrow, fontSize: 12.5, color: T.text2 }}>
      <span>{total.toLocaleString()} items</span>
      <div style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
        <button type="button" onClick={onPrev} disabled={prevOff} style={btn(prevOff)}>‹ Prev</button>
        <span>Page {page + 1} of {Math.max(1, totalPages)}</span>
        <button type="button" onClick={onNext} disabled={nextOff} style={btn(nextOff)}>Next ›</button>
      </div>
    </div>
  );
}

// Page header in ours' grammar: 28px/800 title over the cream rule.
export function PageHead({ title, sub, right }) {
  return (
    <header style={{ display: 'flex', alignItems: 'flex-end', gap: 16, paddingBottom: 10, marginBottom: 18, borderBottom: `2px solid ${T.text}` }}>
      <div style={{ minWidth: 0 }}>
        <h1 style={{ fontFamily: T.fonts.ui, fontSize: 28, fontWeight: 800, color: T.text, margin: 0, lineHeight: 1.1 }}>{title}</h1>
        {sub && <p style={{ fontSize: 13, color: T.text2, margin: '6px 0 0' }}>{sub}</p>}
      </div>
      {right && <div style={{ marginLeft: 'auto' }}>{right}</div>}
    </header>
  );
}
