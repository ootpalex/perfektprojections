import { useState, useEffect, useMemo, useCallback, useRef } from 'react';
import { calculateFutureValue } from '../lib/futureValue';
import { controlWindow } from '../lib/serviceTime';
import { buildAgeGroups, calculateDraftFV } from '../lib/draftFV';
import { replacementOffset, setLeagueBases } from '../lib/leagueCalib.js';
import { buildDevPercentileData, calculateG5FV } from '../lib/g5FV';
import { calculateHybridFV } from '../lib/hybridFV';
import { getBestWAA, getPlayerWAR, calculatePlayerValue, calculatePitcherValue, fitFAMarket, resolveRate } from '../lib/marketValue';
import { DEFAULT_FEATURES, FALLBACK_LEAGUES, normalizeLeagues, isTrendsOnly } from '../lib/leagues.js';
import { loadRatingTrends } from '../lib/ratingTrends';
import { applyDevSignals, fetchDevSignals } from '../lib/devSignals';
import { applyDevMl, fetchDevMl, devMlStaleReason } from '../lib/devMl';
import { loadAgeCurve, peekAgeCurve, MEASURED_CURVE_LEAGUE } from '../lib/ageCurve';
import { useDataVersion, useAnyDataVersion, registerInvalidator, changedFilesSince, currentTick } from '../lib/dataVersion';
import { keysToFetch, mergeRaw } from '../lib/softMerge';

export { DEFAULT_FEATURES };

// Player lists that get the Dev_* fields from dev_signals.json (keyed by ID).
const DEV_SIGNAL_LISTS = [
  'hitters', 'pitchers',
  'hitters_draft', 'pitchers_draft',
  'hitters_draft_all', 'pitchers_draft_all',
];

// The dev_ml.json stale-guard lines already written to the console. Several
// hooks load the same league on one page (the Org page loaded it 3 times),
// so each distinct line is logged once per page load, not once per load.
const devMlStaleLogged = new Set();

/**
 * Build data file paths for a given league.
 * With a league: /data/{league}/hitters.json
 * Without (fallback): /data/hitters.json
 */
function getDataFiles(league, parkMode = 'neutral') {
  const prefix = league ? `/data/${league}` : '/data';
  // Park basis (park spec 2026-08-14): the shipped default is NEUTRAL (all
  // parks equal — contracts normalized). 'park' swaps hitters/pitchers for the
  // *_park variants (50% home park / 50% avg of other MLB parks). The DRAFT
  // boards follow the basis too ("we have to draft for our park", 2026-09-04) —
  // draft.py builds both variants like refresh.py does. FA derives live from
  // hitters/pitchers (so it follows automatically); IAFA/R5 stay neutral-built.
  const suffix = parkMode === 'park' ? '_park' : '';
  return {
    hitters: `${prefix}/hitters${suffix}.json`,
    pitchers: `${prefix}/pitchers${suffix}.json`,
    hitters_draft: `${prefix}/hitters_draft${suffix}.json`,
    pitchers_draft: `${prefix}/pitchers_draft${suffix}.json`,
    // Full class incl. already-drafted (stamped with DraftedOverall/DraftedTeam) —
    // the Mock Draft page's from-the-beginning dataset. Absent file -> empty
    // (the loader falls back to the neutral draft files for a league whose last
    // board build predates the park variants).
    hitters_draft_all: `${prefix}/hitters_draft_all${suffix}.json`,
    pitchers_draft_all: `${prefix}/pitchers_draft_all${suffix}.json`,
    // The real draft's pick order (round / pick / overall / club, supplementals
    // included). The Mock Draft slots our board into these picks. Absent -> [].
    draft_picks: `${prefix}/draft_picks.json`,
    // NOTE: hitters_fa/pitchers_fa.json are no longer fetched — they were a
    // retired Excel extract that shadowed live data; the FA pages now derive
    // free agents from the live hitters/pitchers rows (no org = FA) in App.jsx.
    // Membership + signing terms for the international amateur class. Absent for a
    // league with no international phase, which the loader already treats as empty.
    iafa: `${prefix}/iafa.json`,
    // Rule 5 pool membership (ingest/r5.py). Absent file -> empty pool.
    r5: `${prefix}/r5.json`,
    // Stadiums + park factors + occupancy (ingest/parks.py). Absent -> [].
    parks: `${prefix}/parks.json`,
    park_list: `${prefix}/park_list.json`,
  };
}

function emptyData() {
  return {
    hitters: [], pitchers: [],
    hitters_draft: [], pitchers_draft: [],
    hitters_draft_all: [], pitchers_draft_all: [],
    draft_picks: [], parks: [], park_list: [],
    hitters_fa: [], pitchers_fa: [], iafa: [], r5: [],
    metadata: null,
    marketBank: null,
  };
}

// Per-league feature flags, manifest schemas and the built-in TGS/BLM fallback
// live in lib/leagues.js (a pure module, so a node check can load it).

/**
 * Hook to load the leagues manifest (/data/leagues.json).
 * Returns { leagues, loading }. Never fails: if the manifest is missing,
 * unreadable, or empty, it falls back to the built-in TGS/BLM list.
 * A trends-only league (features.players false) is listed only when its
 * rating_trends.json exists; the probe is the same cached fetch the Rating
 * Trends page reuses, so the file is downloaded once.
 * It loads again when leagues.json or any league's trends file changes (live
 * refresh). A reload that fails keeps the list it had.
 */
export function useLeagues() {
  const [leagues, setLeagues] = useState([]);
  const [loading, setLoading] = useState(true);
  const leaguesVersion = useDataVersion(null, 'leagues');
  const trendsVersion = useAnyDataVersion('trends');

  useEffect(() => {
    let on = true;
    const keepOrFallback = (prev) => (prev.length ? prev : FALLBACK_LEAGUES);
    fetch('/data/leagues.json')
      .then(res => {
        // Non-JSON = dev-server SPA fallback for a missing file — same as 404.
        const ctype = res.headers.get('content-type') || '';
        if (!res.ok || !ctype.includes('json')) {
          throw new Error(`leagues.json fetch failed (${res.status})`);
        }
        return res.json();
      })
      .then(async data => {
        const normalized = normalizeLeagues(data);
        setLeagueBases(normalized);
        const present = await Promise.all(normalized.map(lg => (
          isTrendsOnly(lg) ? loadRatingTrends(lg.id).then(t => t != null) : Promise.resolve(true)
        )));
        if (!on) return;
        setLeagues(prev => {
          // On a reload, a failed probe keeps a trends-only league that was listed
          // (a file read mid-write): only leagues.json takes a league away (9.4).
          const had = new Set(prev.map(lg => lg.id));
          const shown = normalized.filter((lg, i) => present[i] || had.has(lg.id));
          return shown.length ? shown : keepOrFallback(prev);
        });
        setLoading(false);
      })
      .catch(e => {
        if (!on) return;
        console.warn('leagues.json did not load; keeping the current list, or the built-in TGS/BLM list on the first load:', e);
        setLeagues(keepOrFallback);
        setLoading(false);
      });
    return () => { on = false; };
  }, [leaguesVersion, trendsVersion]);

  return { leagues, loading };
}

// One player list. A missing *_park draft file falls back to the neutral
// one; a 404 or a non-JSON answer (the dev server's SPA fallback) is
// 'missing'. Rows with no Name are dropped and every row is stamped with the
// app league. A body that does not parse throws.
async function fetchPlayerList(url, league) {
  let res = await fetch(url);
  // Dev server SPA-fallback returns index.html (200, text/html) for
  // missing files — treat non-JSON responses as missing, same as a 404.
  let ctype = res.headers.get('content-type') || '';
  // A missing *_park draft file (league's last board build predates the
  // park variants) falls back to the neutral draft file rather than an
  // empty board.
  if ((!res.ok || !ctype.includes('json')) && url.includes('_draft') && url.includes('_park')) {
    res = await fetch(url.replace('_park', ''));
    ctype = res.headers.get('content-type') || '';
  }
  if (!res.ok || !ctype.includes('json')) return { status: 'missing', rows: [] };
  const json = await res.json();
  // Filter out blank/empty rows (no Name) that come from empty sheet rows.
  // Stamp the app's league id (M5): the raw 'League' field is StatsPlus's
  // NUMERIC OOTP id (e.g. 112), useless for keying leagueCalib — the
  // per-league replacement offsets in futureValue/draftFV read _appLeague.
  // The parsed rows are this call's own objects, so the stamp goes on them
  // directly: copying ~7,000 rows of ~300 fields cost about 0.4 s per list.
  const stamp = league || 'TGS';
  const rows = json.filter(p => p.Name && String(p.Name).trim() !== '' && String(p.Name).trim() !== '-');
  for (const p of rows) p._appLeague = stamp;
  return { status: 'loaded', rows };
}

// An object file (metadata, market_fit). { ok, value }: value null when it is missing.
async function fetchObjectFile(url) {
  try {
    const res = await fetch(url);
    const ctype = res.headers.get('content-type') || '';
    if (!res.ok || !ctype.includes('json')) return { ok: false, value: null };
    return { ok: true, value: await res.json() };
  } catch {
    return { ok: false, value: null };
  }
}

/**
 * The app's lists from the raw inputs: dev signals onto the raw lists, then
 * the dev ML numbers with the same-pull guard. The raw lists are never
 * enriched in place, so a live refresh can build again from them.
 */
function buildFromRaw(raw, listKeys, league) {
  const results = {};
  for (const key of listKeys) results[key] = raw[key] || [];
  // Per-league metadata (matchup shares etc.) — an object, not a player array.
  results.metadata = raw.metadata ?? null;
  // Banked FA market fit (scripts/bank_market_fit.mjs). Optional: a league
  // that has never been banked just prices off its live fit.
  results.marketBank = raw.marketBank ?? null;

  // Dev signals (growth, Pot direction, the MLB / Starter / Star chances and
  // Exp peak) for players aged 16-26 at the latest pull. Absent file = no
  // Dev_* fields on any row. The park variants carry the same IDs, so one
  // file serves both bases.
  const devSignals = raw.devSignals || null;
  if (devSignals) {
    for (const key of DEV_SIGNAL_LISTS) {
      results[key] = applyDevSignals(results[key], devSignals);
    }
  }
  // ML numbers (backtest/ml/score.py; user, 2026-09-24: "is there any way
  // you can make a machine learning model to help with figuring out this
  // dev stuff") replace the cell method right after the signals, so Proj
  // Potential, the Org Builder, the columns, the card and the draft boards
  // all read them. Stale guard: only when dev_ml.json is on the same pull
  // as dev_signals.json; otherwise the cell method stays.
  const devMl = raw.devMl || null;
  if (devMl) {
    const stale = devMlStaleReason(devMl, devSignals);
    if (stale) {
      const line = `dev_ml.json not used for ${league || 'default'}: ${stale}; the cell method stays`;
      if (!devMlStaleLogged.has(line)) {
        devMlStaleLogged.add(line);
        console.info(line);
      }
    } else {
      for (const key of DEV_SIGNAL_LISTS) {
        results[key] = applyDevMl(results[key], devMl, devSignals);
      }
    }
  }
  return results;
}

/**
 * Every raw input of one view: the player lists and the object files, all
 * fetched at once (the object files used to wait for the lists, which put
 * the 10 MB dev_signals.json behind the 50 MB hitters.json). progress(key,
 * status) reports each list.
 */
async function loadRaw(listKeys, dataFiles, league, base, progress) {
  const raw = {};
  const objects = Promise.all([
    fetchObjectFile(`${base}/metadata.json`),
    fetchObjectFile(`${base}/market_fit.json`),
    fetchDevSignals(base),
    fetchDevMl(base),
  ]);

  // The files load in parallel; each keeps its own progress line.
  await Promise.all(listKeys.map(async (key) => {
    try {
      progress(key, 'loading');
      const res = await fetchPlayerList(dataFiles[key], league);
      raw[key] = res.rows;
      progress(key, res.status);
    } catch (e) {
      console.warn(`Failed to load ${key}:`, e);
      progress(key, 'error');
      raw[key] = [];
    }
  }));

  const [metadata, marketBank, devSignals, devMl] = await objects;
  raw.metadata = metadata.value;
  raw.marketBank = marketBank.value;
  raw.devSignals = devSignals;
  raw.devMl = devMl;
  return raw;
}

const REFRESH_IDLE = { refreshing: false, refreshedAt: null, refreshFailed: false };
const RETRY_MS = 5000;

/**
 * Main data loading hook.
 * Loads all player data for the given league.
 * Re-fetches when league changes.
 * wantPlayers false (a trends-only league) skips every fetch and resolves at
 * once with empty lists, so no "missing file" error can come from it.
 *
 * Live refresh (DESIGN 9.4): when the dev server says this league's player
 * files changed, only the changed files the current view uses are fetched
 * again, with no loading screen. A file that fails to load keeps its previous
 * rows (refreshFailed), and the failed files are tried once more after 5 s.
 */
export function usePlayerData(league, parkMode = 'neutral', wantPlayers = true) {
  const [data, setData] = useState(emptyData);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [loadProgress, setLoadProgress] = useState({});
  const [refresh, setRefresh] = useState(REFRESH_IDLE);
  const [retry, setRetry] = useState(0);
  const version = useDataVersion(league, 'players');
  // The last good load: which view it was for, its raw inputs, and the store
  // step it reflects. Failed keys wait for the next refresh or the retry.
  const ref = useRef({ ident: null, raw: null, tick: 0, failedKeys: [], retryTimer: null, retried: false, pending: null });

  useEffect(() => () => clearTimeout(ref.current.retryTimer), []);

  useEffect(() => {
    let cancelled = false;
    const r = ref.current;
    const ident = `${league}|${parkMode}|${wantPlayers}`;
    const dataFiles = getDataFiles(league, parkMode);
    const listKeys = Object.keys(dataFiles);
    const base = league ? `/data/${league}` : '/data';

    // ---- soft path: same view, the data version moved ------------------
    if (r.ident === ident) {
      if (!wantPlayers || !r.raw) return () => { cancelled = true; };
      const tickNow = currentTick();
      const changed = changedFilesSince(league, 'players', r.tick);
      const keys = [...new Set([...keysToFetch(changed, dataFiles, parkMode), ...r.failedKeys])];
      if (!keys.length) {
        r.tick = tickNow;
        setRefresh(prev => (prev.refreshing ? { ...prev, refreshing: false } : prev));
        return () => { cancelled = true; };
      }
      setRefresh(prev => ({ ...prev, refreshing: true }));

      (async () => {
        const fetched = {};
        const failed = [];
        await Promise.all(keys.map(async (key) => {
          try {
            if (dataFiles[key]) {
              const res = await fetchPlayerList(dataFiles[key], league);
              if (res.status === 'loaded') fetched[key] = res.rows;
              else failed.push(key);
            } else if (key === 'metadata' || key === 'marketBank') {
              const res = await fetchObjectFile(`${base}/${key === 'metadata' ? 'metadata' : 'market_fit'}.json`);
              if (res.ok) fetched[key] = res.value;
              else failed.push(key);
            } else if (key === 'devSignals' || key === 'devMl') {
              const v = key === 'devSignals' ? await fetchDevSignals(base) : await fetchDevMl(base);
              if (v) fetched[key] = v;
              else failed.push(key);
            }
          } catch (e) {
            console.warn(`Live refresh of ${key} failed; keeping the previous data:`, e);
            failed.push(key);
          }
        }));
        if (cancelled) return;
        const merged = mergeRaw(r.raw, fetched, failed);
        const results = buildFromRaw(merged, listKeys, league);
        r.raw = merged;
        r.tick = tickNow;
        r.failedKeys = failed;
        setData(results);
        setRefresh({ refreshing: false, refreshedAt: Date.now(), refreshFailed: failed.length > 0 });
        clearTimeout(r.retryTimer);
        if (failed.length && !r.retried) {
          r.retried = true;
          r.retryTimer = setTimeout(() => setRetry(n => n + 1), RETRY_MS);
        } else if (!failed.length) {
          r.retried = false;
        }
      })().catch(e => {
        if (cancelled) return;
        console.warn('Live refresh failed; keeping the previous data:', e);
        setRefresh(prev => ({ ...prev, refreshing: false, refreshFailed: true }));
      });
      return () => { cancelled = true; };
    }

    // ---- hard path: a new league, park basis or player switch -----------
    const tickAtStart = currentTick();
    const loadKey = `${ident}|${tickAtStart}`;
    // The same load already in flight (React's development double effect runs
    // this twice in a row): wait for it instead of fetching and parsing every
    // file a second time. Its state reset has already been applied.
    let pending = r.pending && r.pending.key === loadKey ? r.pending : null;

    if (!pending) {
      clearTimeout(r.retryTimer);
      r.ident = null;
      r.raw = null;
      r.failedKeys = [];
      r.retried = false;

      // Reset state when league changes
      setLoading(true);
      setError(null);
      setLoadProgress({});
      setRefresh(REFRESH_IDLE);
      setData(emptyData());

      if (!wantPlayers) {
        r.pending = null;
        r.ident = ident;
        setLoading(false);
        return () => { cancelled = true; };
      }

      pending = { key: loadKey, promise: null };
      r.pending = pending;
      const entry = pending;
      // Progress lines belong to the load on screen, not to one effect run.
      const progress = (key, status) => {
        if (r.pending === entry) setLoadProgress(prev => ({ ...prev, [key]: status }));
      };
      // Every player list uses the measured curve: start it now, so the lists
      // are enriched once with it rather than once without and again with it.
      loadAgeCurve(MEASURED_CURVE_LEAGUE);
      entry.promise = loadRaw(listKeys, dataFiles, league, base, progress);
    }

    const entry = pending;
    entry.promise.then((raw) => {
      if (!cancelled) {
        r.pending = null;
        const results = buildFromRaw(raw, listKeys, league);
        r.ident = ident;
        r.raw = raw;
        r.tick = tickAtStart;
        setData(results);
        setLoading(false);
      }
    }).catch(e => {
      if (!cancelled) {
        if (r.pending === entry) r.pending = null;
        setError(e.message);
        setLoading(false);
      }
    });

    return () => { cancelled = true; };
  }, [league, parkMode, wantPlayers, version, retry]);

  return { data, loading, error, loadProgress, ...refresh };
}

/**
 * Files the Series Planner reads on top of the app data. Data key
 * `park_lineup_values`: every MLB/AAA hitter in every club park
 * (ingest/park_values.py, rebuilt by each ratings pull). It is an object, not a
 * player list, and it is about 2 MB, so the page loads it when it opens
 * instead of adding it to every app start.
 */
export function getSeriesFiles(league) {
  const prefix = league ? `/data/${league}` : '/data';
  return {
    park_lineup_values: `${prefix}/park_lineup_values.json`,
    // The planner always works from the NEUTRAL hitters: the park values are
    // stored as park minus neutral. No park suffix here, whatever the toggle says.
    hitters_neutral: `${prefix}/hitters.json`,
  };
}

// JSON or null. A dev-server SPA fallback (200, text/html) counts as missing, same as a 404.
async function fetchJsonOrNull(url) {
  const res = await fetch(url);
  const ctype = res.headers.get('content-type') || '';
  if (!res.ok || !ctype.includes('json')) return null;
  return res.json();
}

// The park toggle remounts the page while the app reloads its data, so the
// planner asks for the same file twice within a second or two. hitters.json is
// about 38 MB: share one request for a short time. The window is short on
// purpose, so a new pull is never hidden behind an old copy.
const RECENT_MS = 30000;
const _recent = new Map();
function fetchJsonShared(url) {
  const hit = _recent.get(url);
  if (hit && Date.now() - hit.at < RECENT_MS) return hit.promise;
  const promise = fetchJsonOrNull(url);
  _recent.set(url, { at: Date.now(), promise });
  promise.catch(() => _recent.delete(url));
  return promise;
}

// A live refresh of player or series files must never answer from the shared copy.
function clearRecent() {
  _recent.clear();
}
registerInvalidator('players', clearRecent);
registerInvalidator('series', clearRecent);

/**
 * Series Planner data for one league.
 * `hitters` is the app's loaded list: it IS the neutral file when the park
 * toggle is on Neutral, so it is reused. On My Park the neutral file is fetched.
 * status: 'loading' | 'ready' | 'missing' (no park values file yet) | 'error'.
 * A reload after a data change keeps the ready state on screen: it swaps on
 * success and keeps the old state on failure.
 */
export function useSeriesPlannerData(league, parkMode, hitters) {
  const [state, setState] = useState({ status: 'loading', parkValues: null, neutralHitters: [], error: null });
  const version = useDataVersion(league, 'series');
  const last = useRef({ ident: null, status: 'loading' });
  last.current.status = state.status;

  useEffect(() => {
    let cancelled = false;
    const ident = `${league}|${parkMode}`;
    const soft = last.current.ident === ident && last.current.status === 'ready';
    last.current.ident = ident;
    if (!soft) setState({ status: 'loading', parkValues: null, neutralHitters: [], error: null });
    const files = getSeriesFiles(league);

    async function load() {
      const parkValues = await fetchJsonOrNull(files.park_lineup_values);
      if (!parkValues || !parkValues.hitters || !Array.isArray(parkValues.parks)) {
        return { status: 'missing', parkValues: null, neutralHitters: [], error: null };
      }
      let neutralHitters = hitters;
      if (parkMode !== 'neutral') {
        const rows = await fetchJsonShared(files.hitters_neutral);
        if (!Array.isArray(rows)) {
          return { status: 'error', parkValues: null, neutralHitters: [], error: 'The neutral hitters file did not load.' };
        }
        neutralHitters = rows
          .filter(p => p.Name && String(p.Name).trim() !== '' && String(p.Name).trim() !== '-')
          .map(p => ({ ...p, _appLeague: league || 'TGS' }));
      }
      return { status: 'ready', parkValues, neutralHitters, error: null };
    }

    load()
      .then(next => {
        if (cancelled) return;
        if (soft && next.status !== 'ready') return;   // keep the old state
        setState(next);
      })
      .catch(e => {
        if (cancelled || soft) return;
        setState({ status: 'error', parkValues: null, neutralHitters: [], error: e.message });
      });
    return () => { cancelled = true; };
  }, [league, parkMode, hitters, version]);

  return state;
}

/**
 * Hook for filtering and sorting player data.
 */
export function useFilteredPlayers(players, initialFilters = {}) {
  const [filters, setFilters] = useState({
    search: '',
    position: 'ALL',
    org: 'ALL',
    level: 'ALL',
    minAge: 0,
    maxAge: 50,
    minOVR: 0,
    minPOT: 0,
    ...initialFilters,
  });

  const [sortConfig, setSortConfig] = useState({
    key: null,
    direction: 'desc',
  });

  const organizations = useMemo(() => {
    const orgs = new Set(players.map(p => p.ORG).filter(Boolean));
    return ['ALL', ...Array.from(orgs).sort()];
  }, [players]);

  const levels = useMemo(() => {
    const lvls = new Set(players.map(p => p.Lev).filter(Boolean));
    return ['ALL', ...Array.from(lvls).sort()];
  }, [players]);

  const positions = useMemo(() => {
    const pos = new Set(players.map(p => p.POS).filter(Boolean));
    return ['ALL', ...Array.from(pos).sort()];
  }, [players]);

  const filtered = useMemo(() => {
    let result = players;

    if (filters.search) {
      const s = filters.search.toLowerCase();
      result = result.filter(p =>
        (p.Name || '').toLowerCase().includes(s) ||
        (p.ID || '').toString().includes(s)
      );
    }

    if (filters.position !== 'ALL') {
      result = result.filter(p => (p.POS || '') === filters.position);
    }

    if (filters.org !== 'ALL') {
      result = result.filter(p => (p.ORG || '') === filters.org);
    }

    if (filters.level !== 'ALL') {
      result = result.filter(p => (p.Lev || '') === filters.level);
    }

    if (filters.minAge > 0) {
      result = result.filter(p => parseFloat(p.Age) >= filters.minAge);
    }
    if (filters.maxAge < 50) {
      result = result.filter(p => parseFloat(p.Age) <= filters.maxAge);
    }
    if (filters.minOVR > 0) {
      result = result.filter(p => parseFloat(p.OVR) >= filters.minOVR);
    }
    if (filters.minPOT > 0) {
      result = result.filter(p => parseFloat(p.POT) >= filters.minPOT);
    }

    // Sort
    if (sortConfig.key) {
      result = [...result].sort((a, b) => {
        let aVal = a[sortConfig.key];
        let bVal = b[sortConfig.key];

        // Try numeric sort
        const aNum = parseFloat(aVal);
        const bNum = parseFloat(bVal);

        if (!isNaN(aNum) && !isNaN(bNum)) {
          return sortConfig.direction === 'asc' ? aNum - bNum : bNum - aNum;
        }

        // String sort
        aVal = String(aVal || '');
        bVal = String(bVal || '');
        return sortConfig.direction === 'asc'
          ? aVal.localeCompare(bVal)
          : bVal.localeCompare(aVal);
      });
    }

    return result;
  }, [players, filters, sortConfig]);

  const handleSort = useCallback((key) => {
    setSortConfig(prev => ({
      key,
      direction: prev.key === key && prev.direction === 'desc' ? 'asc' : 'desc',
    }));
  }, []);

  const updateFilter = useCallback((key, value) => {
    setFilters(prev => ({ ...prev, [key]: value }));
  }, []);

  const resetFilters = useCallback(() => {
    setFilters({
      search: '',
      position: 'ALL',
      org: 'ALL',
      level: 'ALL',
      minAge: 0,
      maxAge: 50,
      minOVR: 0,
      minPOT: 0,
    });
  }, []);

  return {
    filtered,
    filters,
    updateFilter,
    resetFilters,
    sortConfig,
    handleSort,
    organizations,
    levels,
    positions,
  };
}

/**
 * Hook that adds Future Value calculations to player data.
 */
// First age after the peak where the display path has fallen 0.1 WAA or
// more below it; null when it never does inside the path.
function declineStartAge(path, peakAge) {
  if (!Array.isArray(path) || !path.length) return null;
  const peak = path.find(x => x.age === peakAge) || path[0];
  for (const x of path) {
    if (x.age > peak.age && peak.waa - x.waa >= 0.1) return x.age;
  }
  return null;
}

// League minimum salary. Measured, not guessed: 437 of 489 (89%) pre-arb one-year
// MLB deals in the TGS market sample sit exactly here (market_fit.json minSalaryInfo).
const LEAGUE_MIN_SALARY = 750000;

// The measured DEV curve, loaded once. With it, calculateFutureValue runs
// the measured year-by-year path for every player (futureValue.js); until
// it arrives (or when the file is missing) the assumed model runs.
// It loads again when DEV's curve or the league's own curve changes (live
// refresh); a reload that finds no file keeps the curve it had.
function useMeasuredCurve(league) {
  const [curve, setCurve] = useState(() => peekAgeCurve(MEASURED_CURVE_LEAGUE) ?? null);
  const version = useDataVersion(league || null, 'age_curve');
  useEffect(() => {
    let on = true;
    loadAgeCurve(MEASURED_CURVE_LEAGUE).then(c => { if (on) setCurve(prev => c ?? prev); });
    return () => { on = false; };
  }, [version]);
  return curve;
}

// The app league of a row list (every row carries the same stamp).
const listLeague = (rows) => (Array.isArray(rows) && rows.length ? rows[0]._appLeague || null : null);

export function usePlayersWithFV(players) {
  const curve = useMeasuredCurve(listLeague(players));
  return useMemo(() => {
    // League minimum salary, measured from THIS league's own rows: the modal
    // single-year salary among org-attached players (TGS 750k, BLM 700k — the
    // leagues are separate and their minimums differ; the old shared 750k
    // constant misread BLM salaries between ~805k and ~862k as Pre-arb).
    // Falls back to the TGS-measured 750k when no mode is computable.
    const salCount = new Map();
    for (const p of players) {
      const org = String(p.ORG ?? '').trim();
      if (!org || org === '0') continue;
      const sched = Array.isArray(p.SalarySchedule) ? p.SalarySchedule.filter(Number.isFinite) : [];
      if (sched.length > 1) continue;
      const sal = parseFloat(p.Price);
      if (!Number.isFinite(sal) || sal <= 0 || sal > 2_000_000) continue;
      salCount.set(sal, (salCount.get(sal) || 0) + 1);
    }
    let minSalary = LEAGUE_MIN_SALARY, bestN = 0;
    for (const [s, c] of salCount) if (c > bestN || (c === bestN && s < minSalary)) { minSalary = s; bestN = c; }
    return players.map(p => {
      // Value only the seasons this club actually holds. Every board used to
      // count six for everyone, which is right for a prospect (his clock hasn't
      // started) and badly wrong for a veteran with one year to free agency.
      const cw = controlWindow(p);
      // valueYears, not controlYears: a free agent controls zero seasons but the value
      // left in him is the term you would sign him for (serviceTime.controlWindow).
      // The measured DEV curve and the row's DEV cell gain make this the
      // year-by-year path model (futureValue.js); the card in PlayerDetail
      // passes the same two, so its numbers match the lists.
      const fv = calculateFutureValue(p, cw.valueYears, { ageCurve: curve, devGain: p.Dev_PeakGainP50 });
      const path = fv.fullPath || null;
      const pathAt = (k) => (path && path[k] && Number.isFinite(path[k].waa) ? path[k].waa : null);
      // Value Gap = our projection-based FV minus OOTP's POT (what other GMs eyeball).
      // Positive → we rate him higher than his potential shows → undervalued / a buy.
      const pot = parseFloat(p.Pot);
      // DISPLAY BASIS = WAA (vs average), per user preference: in a league this deep,
      // "better than an average starter" is the decision-relevant question — replacement
      // is only the right zero for PRICING. The FV engine computes internally on the WAR
      // basis (its scale anchors are calibrated there, and $ math needs a replacement
      // zero) and hands back a matching WAA track in fv.displayWAA.
      // marketValue.js keeps its own WAR basis untouched.
      //
      // Do NOT go back to "subtract fv.offsetUsed" here. That offset belongs to the
      // player's best CURRENT role; expectedPeak/potential are anchored on his best
      // PEAK role, and for ~1/3 of pitchers those are different roles (RP now, SP at
      // peak). Subtracting the RP offset from an SP-anchored peak inflated "Pot WAA"
      // by ~2.2 wins and inverted the board against its own Ceiling column.
      const d = fv.displayWAA || {};
      const toWAA = (v) => (Number.isFinite(v) ? v : null);
      return {
        ...p,
        _futureValue: fv.futureValue,
        _fvScale: fv.fvScale,
        _fvGap: (Number.isFinite(fv.fvScale) && Number.isFinite(pot)) ? fv.fvScale - pot : null,
        _peakWAA: toWAA(d.peakProjected),
        // Proj Potential minus current, in display WAA: what he still gains
        // to the top of his projected path. One meaning for every player
        // (the old % mixed three formulas; see futureValue.pctToPeak history).
        _toPeakWAA: (Number.isFinite(d.expectedPeak) && Number.isFinite(d.current))
          ? Math.round((d.expectedPeak - d.current) * 10) / 10
          : null,
        _yearsTilPeak: fv.yearsTilPeak,
        // --- contract, summarized for trade work -------------------------------
        // The pull already carries Price / ContractYr / ContractYrs / SalarySchedule
        // / NoTrade / service time; reading a raw per-year array to work out "what
        // would I be taking on" is the part that sent the user to another source.
        // controlWindow() already measured that the schedule IS the remaining years.
        _ctrLeft: cw.controlYears ?? null,
        _owed: Array.isArray(p.SalarySchedule) && p.SalarySchedule.length
          ? p.SalarySchedule.filter(Number.isFinite).reduce((a, b) => a + b, 0)
          : (Number.isFinite(parseFloat(p.Price)) ? parseFloat(p.Price) : null),
        _ctrStatus: (() => {
          const yrs = Number.isFinite(cw.serviceYears) ? cw.serviceYears : null;
          const sched = Array.isArray(p.SalarySchedule)
            ? p.SalarySchedule.filter(Number.isFinite) : [];
          const org = String(p.ORG ?? '').trim();
          const sal = parseFloat(p.Price);
          if (!org || org === '0') return p.FA === false ? 'AMA' : 'FA';
          if (sched.length > 1) return sched.length + "Y";
          // SALARY leads, service time only breaks ties. Service years are missing or
          // stale on ~20% of MLB rows, and OOTP's Super-Two arb pays 2-service-year
          // players well above the minimum — reading those as "Pre-arb" was wrong on
          // 33 TGS players (Montero, $6.6M at 2 svc yrs). Nobody paid meaningfully
          // above the league minimum is pre-arbitration.
          if (Number.isFinite(sal) && sal > minSalary * 1.15) {
            return (yrs !== null && yrs >= 6) ? 'FA after' : 'Arb';
          }
          if (Number.isFinite(sal)) return 'Pre-arb';        // at/near the minimum
          if (yrs !== null && yrs >= 6) return 'FA after';   // no salary on the row
          if (yrs !== null && yrs >= 3) return 'Arb';
          if (yrs !== null) return 'Pre-arb';
          return null;
        })(),
        _projYears: fv.projectionYears,
        _currentWAA: toWAA(d.current),
        // Proj Potential = the top of his projected path (user, 2026-09-24:
        // "what we project them to end up at by the time they are at their
        // peak"). On the measured path that is current + the DEV cell gain
        // for a player with a cell, or current + the closable share of his
        // listed gap; never below his current. Without the curve it is the
        // assumed model's haircut ceiling. The un-haircut ceiling is "Peak
        // Potential".
        _potentialWAA: toWAA(d.expectedPeak),
        _potentialSource: !fv.measured ? 'model'
          : fv.targetSource === 'ml' ? 'ML'
          : fv.targetSource === 'cell' ? 'DEV cell'
          : 'measured curve',
        _rawPotentialWAA: toWAA(d.potential),
        // Year by year: display WAA at age+1, +2, +3, +5 on the measured path,
        // the age of the projected peak, and the first age the path has
        // fallen 0.1 or more below it. All null on the assumed model.
        _yr1WAA: pathAt(1),
        _yr2WAA: pathAt(2),
        _yr3WAA: pathAt(3),
        _yr5WAA: pathAt(5),
        _peakAge: fv.peakAge ?? null,
        _declineStart: declineStartAge(path, fv.peakAge),
        _controlYears: cw.controlYears,
        _controlSource: cw.source,
        _svcYears: cw.serviceYears,
        _controlWindow: cw,
        _fvBreakdown: fv,
      };
    });
  }, [players, curve]);
}

/**
 * Hook that adds Draft FV calculations to player data.
 * Requires the full league population for age-relative percentile calculation.
 *
 * @param {Array} draftPlayers - Players to compute Draft FV for (already enriched with FV)
 * @param {Array} allPlayers - Full league population for percentile calculation
 * @param {'hitter'|'pitcher'} playerType
 */
export function usePlayersWithDraftFV(draftPlayers, allPlayers, playerType) {
  // Pitchers: best of SP or RP WAR for age comparison (audit M5 — same
  // role-offset currency calculateDraftFV uses, so a swingman's percentile is
  // taken on the same value that scores him; league read off the data itself).
  // Hitters: 0.7·Off Runs + 0.3·Def Runs — bat AND the delivered glove, NOT bare
  // wOBA (Otoo 2026-09-04: 71.5th pctile bat-only; bat-only buried young catchers
  // by 17-22 raw FV). The 70/30 bat-glove lean is a USER PREFERENCE (2026-09-04):
  // full-run-value glove (Max WAA wtd) overweighted defense for his taste — glove
  // counts at 3/7 of its run value in this CURRENT leg only; the ceiling leg
  // stays full-value. Must match calculateDraftFV's hitter currentPerf.
  const metricKeyOrFn = useMemo(() => {
    if (playerType === 'hitter') {
      return (player) => {
        const o = parseFloat(player['Off Runs']);
        const d = parseFloat(player['Def Runs']);
        return (Number.isFinite(o) && Number.isFinite(d)) ? 0.7 * o + 0.3 * d : NaN;
      };
    }
    const lg = (allPlayers && allPlayers[0] && allPlayers[0]._appLeague) || undefined;
    const spOff = replacementOffset(lg, 'sp');
    const rpOff = replacementOffset(lg, 'rp');
    return (player) => {
      const sp = parseFloat(player['WAA wtd']);
      const rp = parseFloat(player['WAA wtd RP']);
      const best = Math.max(isNaN(sp) ? -Infinity : sp + spOff, isNaN(rp) ? -Infinity : rp + rpOff);
      return isFinite(best) ? best : NaN;
    };
  }, [playerType, allPlayers]);

  const ageGroups = useMemo(() => {
    if (!allPlayers || allPlayers.length === 0) return {};
    return buildAgeGroups(allPlayers, metricKeyOrFn);
  }, [allPlayers, metricKeyOrFn]);

  return useMemo(() => {
    if (!draftPlayers || draftPlayers.length === 0) return [];
    return draftPlayers.map(p => {
      const dfv = calculateDraftFV(p, ageGroups, playerType);
      return {
        ...p,
        _draftFV: dfv.draftFV,
        _draftRawFV: dfv.draftRawFV,
        _agePercentile: dfv.agePercentile,
        _ceilingScore: dfv.ceilingScore,
        _draftCeiling: dfv.draftCeiling,          // WAA, the same number (ceilingOffset 0); the board's sort tier reads it
        _draftCeilingWAA: dfv.draftCeilingWAA,    // WAA, what the board displays and Draft FV scores
        _ceilingRole: dfv.ceilingRole,
        _durability: dfv.proneValue,
        _toolPenalty: dfv.toolPenalty,
        _highINT: dfv.highINT,
        _wrecked: dfv.wrecked,
        _weBoost: dfv.weBoost,
      };
    });
  }, [draftPlayers, ageGroups, playerType]);
}

/**
 * Hook that adds G5 FV calculations to player data.
 * G5 uses Gaussian kernel-weighted devPercentile among age-peers.
 * Requires the full league population for comparison.
 *
 * @param {Array} players - Players to compute G5 FV for (already enriched with FV)
 * @param {Array} allPlayers - Full league population for devPercentile
 * @param {'hitter'|'pitcher'} playerType
 */
export function usePlayersWithG5FV(players, allPlayers, playerType) {
  // G5 uses BatR wtd for hitters, WAA wtd for pitchers (per FINDINGS.md)
  const devMetricKey = playerType === 'hitter' ? 'BatR wtd' : 'WAA wtd';

  const devPercentileData = useMemo(() => {
    if (!allPlayers || allPlayers.length === 0) return {};
    return buildDevPercentileData(allPlayers, devMetricKey);
  }, [allPlayers, devMetricKey]);

  return useMemo(() => {
    if (!players || players.length === 0) return [];
    return players.map(p => {
      const g5 = calculateG5FV(p, devPercentileData);
      return {
        ...p,
        _g5FV: g5.g5FV,
        _g5Raw: g5.g5Raw,
        _g5DevPct: g5.g5DevPct,
        _g5GapFactor: g5.g5GapFactor,
        _g5RiskFactor: g5.g5RiskFactor,
      };
    });
  }, [players, devPercentileData]);
}

/**
 * Hook that adds Hybrid FV calculations to player data.
 * Requires players to already have _fvScale, _g5FV, and _draftFV.
 *
 * @param {Array} players - Players enriched with FV, G5, and Draft FV
 */
export function usePlayersWithHybridFV(players) {
  return useMemo(() => {
    if (!players || players.length === 0) return [];
    return players.map(p => {
      const hfv = calculateHybridFV(p);
      return {
        ...p,
        _hybridFV: hfv.hybridFV,
        _hybridRaw: hfv.hybridRaw,
        _hybridWFV: hfv.hybridWeightFV,
        _hybridWG5: hfv.hybridWeightG5,
        _hybridWDraft: hfv.hybridWeightDraft,
      };
    });
  }, [players]);
}

/**
 * Hook that fits the FA salary market for the loaded league (marketValue.js
 * fitFAMarket: salary ~ slope * WAR + floor over fresh FA signings only).
 * Re-fits automatically whenever the league data refreshes.
 * Call once in App and pass down to pages. Name kept for App.jsx compat.
 * `banked` is the league's market_fit.json, used when FA opening has left the
 * live sample smaller than the banked one (see fitFAMarket).
 */
export function useMarketRate(hitters, pitchers, banked) {
  return useMemo(() => {
    if (!hitters.length && !pitchers.length) return null;
    return fitFAMarket(hitters, pitchers, { banked });
  }, [hitters, pitchers, banked]);
}

/** Shared enrichment for both market-value hooks. */
function withMarketValue(p, val, war) {
  return {
    ...p,
    _bestWAA: getBestWAA(p),
    _war: war,
    _marketValue: val.adjustedValue,
    _annualValue: val.annualValue,          // line value (replaceable tier)
    _mktPrice: val.marketPrice,             // tier-local market price
    _mktSurplus: val.marketSurplus,         // tier-local surplus
    _mktTier: val.tier,                     // 'replaceable' | 'scarcity'
    _offerFloor: val.offerFloor,
    _offerMid: val.offerMid,
    _offerCeiling: val.offerCeiling,
    _surplus: val.surplus,
    _ctrSurplus: val.contract ? val.contract.surplus : null,
    _ctrYears: val.contract ? val.contract.yearsRemaining : null,
    _futureAAV: val.futureAnnualValue,
    _futureOfferLow: val.futureOfferFloor,
    _futureOfferMid: val.futureOfferMid,
    _futureOfferHigh: val.futureOfferCeiling,
    _perWAA: p.Price > 0 && war > 0 ? Math.round(p.Price / war) : null,
  };
}

/**
 * Hook that adds market value calculations to HITTER data.
 * v2: prices with the hitter's OWN fitted line (market-WAR basis — see
 * marketValue.js resolveRate); offers are tier-local (LOESS over
 * comparable-WAR signings).
 */
export function useHittersWithMarketValue(players, marketFit) {
  // The measured DEV curve: contract and offer paths run on the row's
  // measured path (marketValue.agedWARPath) and the curve extends it past
  // its last age.
  const curve = useMeasuredCurve(listLeague(players));
  return useMemo(() => {
    if (!players || players.length === 0 || !marketFit || !marketFit.pooled) return players;
    const rate = resolveRate(marketFit, 'hitter');
    if (!(rate.slope > 0)) return players;
    return players.map(p => {
      const val = calculatePlayerValue(p, rate, { ageCurve: curve });
      return withMarketValue(p, val, getPlayerWAR(p) ?? 0);
    });
  }, [players, marketFit, curve]);
}

/**
 * Hook that adds market value calculations to PITCHER data.
 * Same fitted line resolution; shows SP/RP role for reference.
 */
export function usePitchersWithMarketValue(players, marketFit) {
  const curve = useMeasuredCurve(listLeague(players));
  return useMemo(() => {
    if (!players || players.length === 0 || !marketFit || !marketFit.pooled) return players;
    const rate = resolveRate(marketFit, 'pitcher');
    if (!(rate.slope > 0)) return players;
    return players.map(p => {
      const val = calculatePitcherValue(p, rate, { ageCurve: curve });
      return { ...withMarketValue(p, val, getPlayerWAR(p) ?? 0), _marketRole: val.role };
    });
  }, [players, marketFit, curve]);
}

/**
 * Detect WAA-like columns from player data.
 */
export function detectWAAColumns(players) {
  if (!players.length) return { hitter: [], pitcher: [] };

  const allCols = Object.keys(players[0]);
  const waaCols = allCols.filter(c => {
    const cl = c.toLowerCase();
    return cl.includes('waa') || cl.includes('war') ||
           (cl.includes('wtd') && !cl.includes('pot'));
  });

  return waaCols;
}
