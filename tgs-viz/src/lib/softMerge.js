/**
 * softMerge.js: the pure rules of a live refresh in usePlayerData (DESIGN 9.4).
 * No React, no fetch, so a node test can load it as it is.
 *
 * A live refresh refetches only the files that changed and that the current
 * view uses, and keeps the previous value of any file that fails to load, so
 * a refresh can never empty the app.
 */

// The object files of a league load, by file name, and the raw input each one fills.
export const OBJECT_FILES = {
  'metadata.json': 'metadata',
  'market_fit.json': 'marketBank',
  'dev_signals.json': 'devSignals',
  'dev_ml.json': 'devMl',
};
export const OBJECT_KEYS = Object.values(OBJECT_FILES);

/** Last path part, for "TGS/hitters.json", "TGS\\hitters.json" or "/data/TGS/hitters.json". */
export function baseName(p) {
  const s = String(p || '');
  const i = Math.max(s.lastIndexOf('/'), s.lastIndexOf('\\'));
  return i >= 0 ? s.slice(i + 1) : s;
}

/**
 * Raw inputs to refetch.
 * changedFiles: a Set (or array) of changed file names, or null = everything changed.
 * dataFiles: { listKey: url } for the current league and park mode (getDataFiles).
 * Returns list keys and object keys in a stable order.
 */
export function keysToFetch(changedFiles, dataFiles, parkMode = 'neutral') {
  const listKeys = Object.keys(dataFiles || {});
  if (changedFiles === null || changedFiles === undefined) return [...listKeys, ...OBJECT_KEYS];
  const changed = new Set([...changedFiles].map(baseName));
  const out = [];
  for (const key of listKeys) {
    const name = baseName(dataFiles[key]);
    let hit = changed.has(name);
    // A missing *_park draft file falls back to the neutral one (usePlayerData),
    // so on My Park a changed neutral draft file can be the one on screen.
    if (!hit && parkMode === 'park' && name.includes('_draft') && name.includes('_park')) {
      hit = changed.has(name.replace('_park', ''));
    }
    if (hit) out.push(key);
  }
  for (const [file, key] of Object.entries(OBJECT_FILES)) {
    if (changed.has(file)) out.push(key);
  }
  return out;
}

/**
 * New raw inputs: the previous ones with the fetched values laid over them.
 * A key in failedKeys keeps its previous value, whatever `fetched` holds for it.
 */
export function mergeRaw(prevRaw, fetched, failedKeys = []) {
  const failed = new Set(failedKeys || []);
  const out = { ...(prevRaw || {}) };
  for (const [k, v] of Object.entries(fetched || {})) {
    if (failed.has(k)) continue;
    out[k] = v;
  }
  return out;
}
