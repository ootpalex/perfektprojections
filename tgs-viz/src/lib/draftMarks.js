/**
 * draftMarks.js — the Draft Board's manual "I drafted" / "taken" marks, merged
 * with the live picks.
 *
 * Ported from ootp-dashboard app/src/components/DraftBoard.jsx (`myManualPicks`,
 * stored per league as `ssb_draft_my_picks::<league>`), with one addition:
 * a "taken" mark for a player another club took.
 *
 * Why the marks exist next to the live picks. The live picks come from the pull
 * (ingest/draft.py): a drafted player is stamped in *_draft_all.json and dropped
 * from the board files, and draft_picks.json carries the pick order. That is only
 * as fresh as the last pull. During a live draft the GM marks picks between pulls:
 *   - 'mine'  — I drafted him. He stays on the board, highlighted, and is listed
 *               under My picks.
 *   - 'taken' — another club took him. The board can hide him.
 * A live pick always wins over a manual mark for the same player: once the pull
 * has the pick, the mark is redundant and is reported as such, not double-counted.
 *
 * Storage: one localStorage key per league, the pattern his Series Planner uses
 * (`tgs-series-<league>`). Values are { [playerId]: 'mine' | 'taken' }.
 * Pure functions; the storage object is passed in so node tests can fake it.
 */

export const MARK_MINE = 'mine';
export const MARK_TAKEN = 'taken';

export const marksKey = (league) => `tgs-draft-marks-${league || 'default'}`;

const VALID = new Set([MARK_MINE, MARK_TAKEN]);

/** Read one league's marks. Bad or blocked storage reads as no marks. */
export function loadMarks(storage, league) {
  try {
    const raw = JSON.parse(storage.getItem(marksKey(league)) || 'null');
    if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return {};
    const out = {};
    for (const [id, m] of Object.entries(raw)) if (VALID.has(m)) out[id] = m;
    return out;
  } catch {
    return {};
  }
}

/** Write one league's marks; an empty set removes the key. Blocked storage is ignored. */
export function saveMarks(storage, league, marks) {
  try {
    if (!marks || Object.keys(marks).length === 0) storage.removeItem(marksKey(league));
    else storage.setItem(marksKey(league), JSON.stringify(marks));
  } catch { /* storage blocked: the marks last for the session */ }
}

/** Set `kind` on a player; setting the kind he already has clears it. Returns a new object. */
export function toggleMark(marks, id, kind) {
  const key = String(id);
  const next = { ...marks };
  if (!VALID.has(kind) || next[key] === kind) delete next[key];
  else next[key] = kind;
  return next;
}

/** draft_picks.json rows → Map(playerId → { overall, round, pick, team, name }). Rows without an ID are skipped. */
export function livePickIndex(picks) {
  const map = new Map();
  for (const p of picks || []) {
    if (p == null || p.ID == null || p.ID === '') continue;
    map.set(String(p.ID), {
      overall: Number.parseInt(p.Overall, 10),
      round: Number.parseInt(p.Round, 10),
      pick: Number.parseInt(p.Pick, 10),
      team: p.Team || null,
      name: p.Name || null,
    });
  }
  return map;
}

/**
 * One player's merged draft status.
 *   source 'live'   — in the live picks (manual mark, if any, is `redundant`).
 *   source 'manual' — only a manual mark.
 *   null            — neither.
 * `mine` is true for my manual 'mine' mark, or a live pick by `myOrg`.
 */
export function draftStatus(id, marks, liveIndex, myOrg) {
  const key = id == null ? '' : String(id);
  const mark = marks?.[key] ?? null;
  const live = liveIndex?.get(key) ?? null;
  if (live) {
    return { source: 'live', mine: !!myOrg && live.team === myOrg, taken: true, pick: live, mark, redundant: mark != null };
  }
  if (mark) return { source: 'manual', mine: mark === MARK_MINE, taken: true, pick: null, mark, redundant: false };
  return null;
}

/** "1.04"-style label for a live pick, or null. */
export function pickLabel(pick) {
  if (!pick || !Number.isFinite(pick.round) || !Number.isFinite(pick.pick)) return null;
  return `${pick.round}.${String(pick.pick).padStart(2, '0')}`;
}

/** Whether the board hides this player when "hide taken" is on: taken by anyone but me. */
export function hiddenAsTaken(status) {
  return !!status && status.taken && !status.mine;
}

/**
 * Counts for the board's strip: my picks (manual + live by my org), taken by
 * others (manual + live), and manual marks the live picks have overtaken.
 */
export function summarizeMarks(marks, liveIndex, myOrg) {
  const ids = new Set([...Object.keys(marks || {}), ...(liveIndex ? liveIndex.keys() : [])]);
  let mine = 0, taken = 0, redundant = 0, live = 0, manual = 0;
  for (const id of ids) {
    const s = draftStatus(id, marks, liveIndex, myOrg);
    if (!s) continue;
    if (s.source === 'live') live += 1; else manual += 1;
    if (s.redundant) redundant += 1;
    if (s.mine) mine += 1; else taken += 1;
  }
  return { mine, taken, redundant, live, manual };
}
