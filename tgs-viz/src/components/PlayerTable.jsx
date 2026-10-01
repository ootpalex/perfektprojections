import React, { useState, useMemo, useCallback, useRef, useEffect } from 'react';
import { formatCellValue, getCellColorClass, getCellTitle, COLUMN_LABELS } from '../lib/columns';
import { ChevronUp, ChevronDown, Search, X, Filter } from 'lucide-react';

// Per-column hide (user, 2026-09-24): the set of hidden columns is kept in
// localStorage under one key per table instance so a hide survives a reload
// and does not bleed into another table. Every storage call is wrapped:
// private windows and blocked site data throw.
function hiddenStorageKey(storageKey) {
  return storageKey ? `ptable.hidden.${storageKey}` : null;
}

function readHiddenCols(storageKey) {
  const key = hiddenStorageKey(storageKey);
  if (!key) return new Set();
  try {
    const raw = window.localStorage.getItem(key);
    const list = raw ? JSON.parse(raw) : [];
    return new Set(Array.isArray(list) ? list.filter(c => typeof c === 'string') : []);
  } catch {
    return new Set();
  }
}

function writeHiddenCols(storageKey, cols) {
  const key = hiddenStorageKey(storageKey);
  if (!key) return;
  try {
    if (cols.size === 0) window.localStorage.removeItem(key);
    else window.localStorage.setItem(key, JSON.stringify(Array.from(cols)));
  } catch {
    // storage unavailable: the hide still applies for this visit
  }
}

/**
 * High-performance player data table with virtual scrolling,
 * column group toggling, sorting, and filtering.
 */
// ─── Hitter positions and their WAA column mappings ──────────────
const HITTER_POSITIONS = ['C', '1B', '2B', '3B', 'SS', 'LF', 'CF', 'RF', 'DH'];

// Maps a position to the WAA columns that replace the "Max WAA" defaults
function getPositionWAAColumns(pos) {
  return {
    'Max WAA wtd': `${pos} WAA wtd`,
    'Max WAA vR':  `${pos} WAA vR`,
    'Max WAA vL':  `${pos} WAA vL`,
    'MAX WAA P':   `${pos} WAA P`,
  };
}

export default function PlayerTable({
  players,
  columnGroups,
  defaultActiveGroups = ['info', 'value'],
  onPlayerClick,
  selectedPlayerId,
  maxRows = 500,
  positionViewMode = false, // When true, position dropdown remaps WAA columns instead of filtering
  storageKey, // Optional. Names the localStorage slot for this table's hidden columns.
}) {
  const [activeGroups, setActiveGroups] = useState(new Set(defaultActiveGroups));
  // Columns the user hid with the x on the header (user, 2026-09-24).
  const [hiddenCols, setHiddenCols] = useState(() => readHiddenCols(storageKey));
  // The same PlayerTable instance serves several routes (Hitters, Draft
  // Hitters, FA Hitters), so reload the set when the storage key changes.
  const storageKeyRef = useRef(storageKey);
  useEffect(() => {
    if (storageKeyRef.current === storageKey) return;
    storageKeyRef.current = storageKey;
    setHiddenCols(readHiddenCols(storageKey));
  }, [storageKey]);
  const [sortKey, setSortKey] = useState(null);
  const [sortDir, setSortDir] = useState('desc');
  const [search, setSearch] = useState('');
  const [posFilter, setPosFilter] = useState('ALL');
  const [orgFilter, setOrgFilter] = useState('ALL');
  const [levelFilter, setLevelFilter] = useState('ALL');
  const [minWAA, setMinWAA] = useState('');
  const tableRef = useRef(null);

  const toggleGroup = useCallback((key) => {
    setActiveGroups(prev => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  }, []);

  // Position-to-column remapping when in positionViewMode
  const posColumnMap = useMemo(() => {
    if (!positionViewMode || posFilter === 'ALL') return null;
    if (HITTER_POSITIONS.includes(posFilter)) return getPositionWAAColumns(posFilter);
    return null;
  }, [positionViewMode, posFilter]);

  const hideColumn = useCallback((col) => {
    setHiddenCols(prev => {
      const next = new Set(prev);
      next.add(col);
      writeHiddenCols(storageKey, next);
      return next;
    });
  }, [storageKey]);

  const resetHiddenColumns = useCallback(() => {
    const next = new Set();
    writeHiddenCols(storageKey, next);
    setHiddenCols(next);
  }, [storageKey]);

  // Get visible columns (deduplicated — columns may appear in multiple groups)
  // When posColumnMap is active, swap Max WAA columns for position-specific ones
  // Columns the user hid from the header are left out.
  const visibleColumns = useMemo(() => {
    const cols = [];
    const seen = new Set();
    for (const [key, group] of Object.entries(columnGroups)) {
      if (activeGroups.has(key)) {
        for (const col of group.columns) {
          const mappedCol = posColumnMap?.[col] || col;
          if (!seen.has(mappedCol) && !hiddenCols.has(mappedCol)) {
            seen.add(mappedCol);
            cols.push(mappedCol);
          }
        }
      }
    }
    return cols;
  }, [columnGroups, activeGroups, posColumnMap, hiddenCols]);

  // Unique values for filters
  const organizations = useMemo(() => {
    const orgs = new Set(players.map(p => p.ORG).filter(Boolean));
    return ['ALL', ...Array.from(orgs).sort()];
  }, [players]);

  const levels = useMemo(() => {
    const lvls = new Set(players.map(p => p.Lev).filter(Boolean));
    return ['ALL', ...Array.from(lvls).sort()];
  }, [players]);

  const positions = useMemo(() => {
    if (positionViewMode) {
      return ['ALL', ...HITTER_POSITIONS];
    }
    const pos = new Set(players.map(p => p.POS).filter(Boolean));
    return ['ALL', ...Array.from(pos).sort()];
  }, [players, positionViewMode]);

  // Filter and sort
  const displayPlayers = useMemo(() => {
    let result = players;

    if (search) {
      const s = search.toLowerCase();
      result = result.filter(p =>
        (p.Name || '').toLowerCase().includes(s) ||
        (p.ID || '').toString().includes(s)
      );
    }

    if (posFilter !== 'ALL' && !positionViewMode) {
      result = result.filter(p => (p.POS || '') === posFilter);
    }
    if (orgFilter !== 'ALL') {
      result = result.filter(p => (p.ORG || '') === orgFilter);
    }
    if (levelFilter !== 'ALL') {
      result = result.filter(p => (p.Lev || '') === levelFilter);
    }
    if (minWAA !== '') {
      const min = parseFloat(minWAA);
      if (!isNaN(min)) {
        // When viewing a specific position, filter by that position's WAA
        const waaCol = (positionViewMode && posFilter !== 'ALL' && HITTER_POSITIONS.includes(posFilter))
          ? `${posFilter} WAA wtd`
          : null;
        result = result.filter(p => {
          const waa = parseFloat(waaCol ? p[waaCol] : (p['Max WAA wtd'] || p['WAA wtd'] || p['_futureValue']));
          return !isNaN(waa) && waa >= min;
        });
      }
    }

    if (sortKey) {
      result = [...result].sort((a, b) => {
        let aVal = a[sortKey];
        let bVal = b[sortKey];
        const aNum = parseFloat(aVal);
        const bNum = parseFloat(bVal);
        if (!isNaN(aNum) && !isNaN(bNum)) {
          return sortDir === 'asc' ? aNum - bNum : bNum - aNum;
        }
        aVal = String(aVal || '');
        bVal = String(bVal || '');
        return sortDir === 'asc' ? aVal.localeCompare(bVal) : bVal.localeCompare(aVal);
      });
    }

    return result.slice(0, maxRows);
  }, [players, search, posFilter, orgFilter, levelFilter, minWAA, sortKey, sortDir, maxRows]);

  const handleSort = useCallback((key) => {
    setSortKey(prev => {
      if (prev === key) {
        setSortDir(d => d === 'desc' ? 'asc' : 'desc');
        return key;
      }
      setSortDir('desc');
      return key;
    });
  }, []);

  return (
    <div className="flex flex-col h-full">
      {/* Column Group Toggles */}
      <div className="flex flex-wrap gap-1.5 p-3 bg-slate-900 border-b border-slate-700">
        <span className="text-xs text-slate-500 self-center mr-1">Columns:</span>
        {Object.entries(columnGroups).map(([key, group]) => (
          <button
            key={key}
            onClick={() => toggleGroup(key)}
            className={`px-2.5 py-1 rounded-full text-xs font-medium transition-all ${
              activeGroups.has(key)
                ? 'bg-blue-600 text-white'
                : 'bg-slate-800 text-slate-400 hover:bg-slate-700 hover:text-slate-300'
            }`}
          >
            {group.label}
          </button>
        ))}
        {hiddenCols.size > 0 && (
          <span className="ml-auto self-center text-xs text-slate-500">
            {hiddenCols.size} hidden ·{' '}
            <button
              type="button"
              onClick={resetHiddenColumns}
              className="underline hover:text-slate-300"
              title="Show every hidden column again"
            >
              reset
            </button>
          </span>
        )}
      </div>

      {/* Filters */}
      <div className="flex flex-wrap items-center gap-3 p-3 bg-slate-900/50 border-b border-slate-700">
        <div className="relative">
          <Search size={14} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-slate-500" />
          <input
            type="text"
            value={search}
            onChange={e => setSearch(e.target.value)}
            placeholder="Search players..."
            className="pl-8 pr-8 py-1.5 bg-slate-800 border border-slate-600 rounded-lg text-sm text-slate-200 w-52 focus:outline-none focus:border-blue-500"
          />
          {search && (
            <button onClick={() => setSearch('')} className="absolute right-2 top-1/2 -translate-y-1/2 text-slate-500 hover:text-slate-300">
              <X size={14} />
            </button>
          )}
        </div>

        <select value={posFilter} onChange={e => { setPosFilter(e.target.value); if (positionViewMode && e.target.value !== 'ALL') { setSortKey(`${e.target.value} WAA wtd`); setSortDir('desc'); } }}
          className="py-1.5 px-2 bg-slate-800 border border-slate-600 rounded-lg text-sm text-slate-200">
          {positions.map(p => <option key={p} value={p}>{p === 'ALL' ? (positionViewMode ? 'View as Position' : 'All Positions') : (positionViewMode ? `View as ${p}` : p)}</option>)}
        </select>

        <select value={orgFilter} onChange={e => setOrgFilter(e.target.value)}
          className="py-1.5 px-2 bg-slate-800 border border-slate-600 rounded-lg text-sm text-slate-200">
          {organizations.map(o => <option key={o} value={o}>{o === 'ALL' ? 'All Orgs' : o}</option>)}
        </select>

        <select value={levelFilter} onChange={e => setLevelFilter(e.target.value)}
          className="py-1.5 px-2 bg-slate-800 border border-slate-600 rounded-lg text-sm text-slate-200">
          {levels.map(l => <option key={l} value={l}>{l === 'ALL' ? 'All Levels' : l}</option>)}
        </select>

        <div className="flex items-center gap-1.5">
          <label className="text-xs text-slate-500">Min WAA:</label>
          <input
            type="number"
            value={minWAA}
            onChange={e => setMinWAA(e.target.value)}
            placeholder="0"
            step="0.5"
            className="w-16 py-1.5 px-2 bg-slate-800 border border-slate-600 rounded-lg text-sm text-slate-200"
          />
        </div>

        <div className="ml-auto text-xs text-slate-500">
          {displayPlayers.length} of {players.length} players
        </div>
      </div>

      {/* Table */}
      <div className="flex-1 overflow-auto" ref={tableRef}>
        <table className="data-table">
          <thead>
            <tr>
              {visibleColumns.map((col, idx) => (
                // The first column stays put while the table scrolls right and
                // cannot be hidden (user, 2026-09-24).
                <th key={col} onClick={() => handleSort(col)} title={col} className={idx === 0 ? 'col-sticky' : undefined}>
                  <div className="flex items-center gap-1">
                    <span>{COLUMN_LABELS[col] || col}</span>
                    {sortKey === col && (
                      sortDir === 'desc'
                        ? <ChevronDown size={12} />
                        : <ChevronUp size={12} />
                    )}
                  </div>
                  {idx > 0 && (
                    <button
                      type="button"
                      className="col-hide"
                      title={`Hide ${COLUMN_LABELS[col] || col}`}
                      onClick={(e) => { e.stopPropagation(); hideColumn(col); }}
                    >
                      <X size={11} />
                    </button>
                  )}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {displayPlayers.map((player, idx) => {
              const id = player.ID || player.Name || idx;
              const isSelected = selectedPlayerId === id;
              return (
                <tr
                  key={id}
                  className={`cursor-pointer ${isSelected ? 'selected' : ''}`}
                  onClick={() => onPlayerClick?.(player)}
                >
                  {visibleColumns.map((col, idx) => {
                    const raw = player[col];
                    const display = formatCellValue(raw, col);
                    const colorClass = getCellColorClass(raw, col, player);
                    const title = getCellTitle(player, col);
                    // Name: cut at 150px with the full name on hover; the
                    // first cell of the row stays put while scrolling right
                    // (user, 2026-09-24).
                    const isName = col === 'Name';
                    const cellClass = [colorClass, idx === 0 ? 'col-sticky' : ''].filter(Boolean).join(' ') || undefined;
                    const cellTitle = title || (isName && raw ? String(raw) : undefined);
                    return (
                      <td key={col} className={cellClass} title={cellTitle}>
                        {isName ? <span className="block max-w-[150px] truncate">{display}</span> : display}
                      </td>
                    );
                  })}
                </tr>
              );
            })}
          </tbody>
        </table>
        {displayPlayers.length === 0 && (
          <div className="flex items-center justify-center h-32 text-slate-500">
            No players match your filters
          </div>
        )}
      </div>
    </div>
  );
}
