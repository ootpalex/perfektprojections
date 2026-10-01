/**
 * dataVersion.js: the live-refresh store (DESIGN 9.4).
 *
 * The dev server sends `tgs:data` {league, keys, files, at, reason} when data
 * files under public/data change (control/watch.js). This store turns those
 * events into version numbers that hooks add to their effect deps, keeps a
 * short log of which files changed, and clears the module caches that would
 * otherwise serve the old file.
 *
 * import.meta.hot does not exist in a build or preview: every version stays
 * at 0 and nothing refreshes.
 */
import { useSyncExternalStore } from 'react';
import { invalidateRatingTrends } from './ratingTrends';
import { invalidateAgeCurves } from './ageCurve';

const versions = {};          // league -> key -> count
const globalV = {};           // key -> count (league null events)
const anyV = {};              // key -> count over every league and null
let tick = 0;                 // one step per applied event; the file log counts in it
const logs = new Map();       // `${league}|${key}` -> { entries: [{tick, files}], dropped }
const LOG_MAX = 50;
const COALESCE_MS = 250;
const invalidators = new Map(); // key -> Set(fn(league))
const listeners = new Set();
const pending = new Map();    // league ('' = null) -> { keys: Map(key -> Set(files)), timer }

function emit() {
  for (const fn of [...listeners]) {
    try { fn(); } catch (e) { console.warn('[tgs-data] listener failed:', e); }
  }
}

function subscribe(fn) {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

/**
 * Run fn(league) before the version for `key` moves, so the next load reads
 * the new file. Returns a function that removes it.
 */
export function registerInvalidator(key, fn) {
  if (!invalidators.has(key)) invalidators.set(key, new Set());
  invalidators.get(key).add(fn);
  return () => invalidators.get(key)?.delete(fn);
}

/** versions[league][key] + global[key]. League null: global[key] only. */
export function getDataVersion(league, key) {
  const own = league ? (versions[league]?.[key] || 0) : 0;
  return own + (globalV[key] || 0);
}

/** React hook form of getDataVersion. */
export function useDataVersion(league, key) {
  return useSyncExternalStore(subscribe, () => getDataVersion(league, key), () => 0);
}

/** Changes for `key` in any league (the league list follows every trends file). */
export function useAnyDataVersion(key) {
  return useSyncExternalStore(subscribe, () => anyV[key] || 0, () => 0);
}

/** The store's current step. A loader records it and later asks what changed since. */
export function currentTick() {
  return tick;
}

/**
 * File names changed for (league, key) after `sinceTick`, league-null changes
 * included. null when the log no longer reaches back that far: the caller then
 * refetches everything.
 */
export function changedFilesSince(league, key, sinceTick) {
  const out = new Set();
  for (const lg of [league || '', '']) {
    const log = logs.get(`${lg}|${key}`);
    if (!log) continue;
    if (log.dropped > sinceTick) return null;
    for (const e of log.entries) {
      if (e.tick > sinceTick) for (const f of e.files) out.add(f);
    }
    if (!league) break;
  }
  return out;
}

function addLog(league, key, files) {
  const id = `${league || ''}|${key}`;
  let log = logs.get(id);
  if (!log) { log = { entries: [], dropped: 0 }; logs.set(id, log); }
  log.entries.push({ tick, files: [...files] });
  while (log.entries.length > LOG_MAX) log.dropped = log.entries.shift().tick;
}

function invalidate(league, key) {
  try {
    if (key === 'trends') invalidateRatingTrends(league || undefined);
    if (key === 'age_curve') invalidateAgeCurves();
  } catch (e) {
    console.warn('[tgs-data] cache reset failed:', e);
  }
  for (const fn of invalidators.get(key) || []) {
    try { fn(league); } catch (e) { console.warn(`[tgs-data] ${key} reset failed:`, e); }
  }
}

function flush(lgKey) {
  const p = pending.get(lgKey);
  if (!p) return;
  pending.delete(lgKey);
  const league = lgKey || null;
  for (const [key, files] of p.keys) {
    invalidate(league, key);
    tick += 1;
    if (league) {
      versions[league] = versions[league] || {};
      versions[league][key] = (versions[league][key] || 0) + 1;
    } else {
      globalV[key] = (globalV[key] || 0) + 1;
    }
    anyV[key] = (anyV[key] || 0) + 1;
    addLog(league, key, files);
  }
  emit();
}

/**
 * Take one tgs:data payload. Events for the same league within 250 ms are
 * merged into one version step per key.
 */
export function queueDataEvent(evt) {
  if (!evt || typeof evt !== 'object') return;
  const keys = Array.isArray(evt.keys) ? evt.keys.filter(k => typeof k === 'string') : [];
  if (!keys.length) return;
  const files = Array.isArray(evt.files) ? evt.files.map(String) : [];
  const lgKey = evt.league ? String(evt.league) : '';
  let p = pending.get(lgKey);
  if (!p) {
    p = { keys: new Map(), timer: null };
    pending.set(lgKey, p);
    p.timer = setTimeout(() => flush(lgKey), COALESCE_MS);
  }
  for (const k of keys) {
    if (!p.keys.has(k)) p.keys.set(k, new Set());
    for (const f of files) p.keys.get(k).add(f);
  }
}

if (import.meta.hot) {
  import.meta.hot.on('tgs:data', (data) => {
    try { queueDataEvent(data); } catch (e) { console.warn('[tgs-data] bad event:', e); }
  });
}

// Read-only view for checks in the browser console.
if (typeof window !== 'undefined' && import.meta.env?.DEV) {
  window.__tgsData = {
    snapshot: () => ({ tick, versions: JSON.parse(JSON.stringify(versions)), global: { ...globalV } }),
  };
}
