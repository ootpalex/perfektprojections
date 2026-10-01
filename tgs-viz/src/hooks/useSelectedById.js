import { useState, useMemo, useCallback, useEffect } from 'react';

/**
 * The open player card, kept by player ID (DESIGN 9.4).
 *
 * rowsByKind: { hitter: rows, pitcher: rows } (a page with one list passes one kind).
 * It stores {id, kind}, never the row, and finds the row again in the current
 * list after every data change, so an open card shows the current numbers.
 * When the ID is gone from the list (a league switch), it clears itself and
 * the card closes.
 *
 * Returns { selected, kind, select(row, kind), clear() }.
 */
export function useSelectedById(rowsByKind) {
  const [pick, setPick] = useState(null);   // { id: string, kind }

  const selected = useMemo(() => {
    if (!pick) return null;
    const rows = rowsByKind?.[pick.kind];
    if (!Array.isArray(rows)) return null;
    return rows.find(r => r && r.ID !== undefined && r.ID !== null && String(r.ID) === pick.id) || null;
  }, [pick, rowsByKind?.[pick?.kind]]); // eslint-disable-line react-hooks/exhaustive-deps

  // Rows loaded but the player is gone: drop the pick, so it cannot come back later.
  const rows = pick ? rowsByKind?.[pick.kind] : null;
  useEffect(() => {
    if (pick && Array.isArray(rows) && rows.length && !selected) setPick(null);
  }, [pick, rows, selected]);

  const select = useCallback((row, kind) => {
    if (!row || row.ID === undefined || row.ID === null) { setPick(null); return; }
    setPick({ id: String(row.ID), kind });
  }, []);
  const clear = useCallback(() => setPick(null), []);

  return { selected, kind: selected ? pick.kind : null, select, clear };
}
