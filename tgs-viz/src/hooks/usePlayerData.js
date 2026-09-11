import { useState, useEffect, useMemo, useCallback } from 'react';
import { calculateFutureValue } from '../lib/futureValue';
import { controlWindow } from '../lib/serviceTime';
import { buildAgeGroups, calculateDraftFV } from '../lib/draftFV';
import { replacementOffset } from '../lib/leagueCalib.js';
import { buildDevPercentileData, calculateG5FV } from '../lib/g5FV';
import { calculateHybridFV } from '../lib/hybridFV';
import { getBestWAA, getPlayerWAR, calculatePlayerValue, calculatePitcherValue, fitFAMarket, resolveRate } from '../lib/marketValue';

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
    // NOTE: hitters_fa/pitchers_fa.json are no longer fetched — they were a
    // retired Excel extract that shadowed live data; the FA pages now derive
    // free agents from the live hitters/pitchers rows (no org = FA) in App.jsx.
    // Membership + signing terms for the international amateur class. Absent for a
    // league with no international phase, which the loader already treats as empty.
    iafa: `${prefix}/iafa.json`,
    // Rule 5 pool membership (ingest/r5.py). Absent file -> empty pool.
    r5: `${prefix}/r5.json`,
  };
}

/**
 * Per-league feature flags. Anything not declared in the manifest defaults to
 * true so legacy manifests keep today's behavior (everything shown).
 */
export const DEFAULT_FEATURES = { draft: true, fa: true, contracts: true };

// Hardcoded fallback when /data/leagues.json is missing or unreadable —
// the two leagues the app originally shipped with. Guarantees the app
// always boots even if the manifest was never generated.
const FALLBACK_LEAGUES = [
  { id: 'TGS', name: 'TGS', features: { draft: true, fa: true, contracts: true } },
  { id: 'BLM', name: 'BLM', features: { draft: true, fa: false, contracts: true } },
];

/**
 * Accept both manifest schemas:
 *   new:    { "leagues": [{ id, name, features: {draft, fa, contracts}, ... }] }
 *   legacy: [{ id, name, folder, datasets }]
 * Legacy entries derive features from their dataset list (contracts unknowable
 * from the old schema, so assumed present — columns are null-safe anyway).
 */
function normalizeLeagues(raw) {
  const list = Array.isArray(raw) ? raw : (raw && Array.isArray(raw.leagues) ? raw.leagues : []);
  return list
    .filter(lg => lg && lg.id)
    .map(lg => {
      let features = lg.features;
      if (!features && Array.isArray(lg.datasets)) {
        features = {
          draft: lg.datasets.some(d => String(d).endsWith('_draft')),
          fa: lg.datasets.some(d => String(d).endsWith('_fa')),
          contracts: true,
        };
      }
      return {
        ...lg,
        name: lg.name || lg.id,
        features: { ...DEFAULT_FEATURES, ...(features || {}) },
      };
    });
}

/**
 * Hook to load the leagues manifest (/data/leagues.json).
 * Returns { leagues, loading }. Never fails: if the manifest is missing,
 * unreadable, or empty, it falls back to the built-in TGS/BLM list.
 */
export function useLeagues() {
  const [leagues, setLeagues] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetch('/data/leagues.json')
      .then(res => {
        // Non-JSON = dev-server SPA fallback for a missing file — same as 404.
        const ctype = res.headers.get('content-type') || '';
        if (!res.ok || !ctype.includes('json')) {
          throw new Error(`leagues.json fetch failed (${res.status})`);
        }
        return res.json();
      })
      .then(data => {
        const normalized = normalizeLeagues(data);
        setLeagues(normalized.length ? normalized : FALLBACK_LEAGUES);
        setLoading(false);
      })
      .catch(e => {
        console.warn('leagues.json unavailable — using built-in TGS/BLM fallback:', e);
        setLeagues(FALLBACK_LEAGUES);
        setLoading(false);
      });
  }, []);

  return { leagues, loading };
}

/**
 * Main data loading hook.
 * Loads all player data for the given league.
 * Re-fetches when league changes.
 */
export function usePlayerData(league, parkMode = 'neutral') {
  const [data, setData] = useState({
    hitters: [],
    pitchers: [],
    hitters_draft: [],
    pitchers_draft: [],
    hitters_draft_all: [],
    pitchers_draft_all: [],
    hitters_fa: [], iafa: [], r5: [],
    pitchers_fa: [],
    metadata: null,
    marketBank: null,
  });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [loadProgress, setLoadProgress] = useState({});

  useEffect(() => {
    let cancelled = false;

    // Reset state when league changes
    setLoading(true);
    setError(null);
    setLoadProgress({});
    setData({
      hitters: [], pitchers: [],
      hitters_draft: [], pitchers_draft: [],
      hitters_draft_all: [], pitchers_draft_all: [],
      hitters_fa: [], pitchers_fa: [], iafa: [], r5: [],
      metadata: null,
      marketBank: null,
    });

    const dataFiles = getDataFiles(league, parkMode);

    async function loadAll() {
      const results = {};

      for (const [key, url] of Object.entries(dataFiles)) {
        try {
          setLoadProgress(prev => ({ ...prev, [key]: 'loading' }));
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
          if (!res.ok || !ctype.includes('json')) {
            setLoadProgress(prev => ({ ...prev, [key]: 'missing' }));
            results[key] = [];
            continue;
          }
          const json = await res.json();
          // Filter out blank/empty rows (no Name) that come from empty sheet rows.
          // Stamp the app's league id (M5): the raw 'League' field is StatsPlus's
          // NUMERIC OOTP id (e.g. 112), useless for keying leagueCalib — the
          // per-league replacement offsets in futureValue/draftFV read _appLeague.
          results[key] = json
            .filter(p => p.Name && String(p.Name).trim() !== '' && String(p.Name).trim() !== '-')
            .map(p => ({ ...p, _appLeague: league || 'TGS' }));
          setLoadProgress(prev => ({ ...prev, [key]: 'loaded' }));
        } catch (e) {
          console.warn(`Failed to load ${key}:`, e);
          setLoadProgress(prev => ({ ...prev, [key]: 'error' }));
          results[key] = [];
        }
      }

      const base = league ? `/data/${league}` : '/data';

      // Per-league metadata (matchup shares etc.) — an object, not a player array.
      try {
        const mres = await fetch(`${base}/metadata.json`);
        const mtype = mres.headers.get('content-type') || '';
        results.metadata = (mres.ok && mtype.includes('json')) ? await mres.json() : null;
      } catch {
        results.metadata = null;
      }

      // Banked FA market fit (scripts/bank_market_fit.mjs). Optional: a league
      // that has never been banked just prices off its live fit.
      try {
        const bres = await fetch(`${base}/market_fit.json`);
        const btype = bres.headers.get('content-type') || '';
        results.marketBank = (bres.ok && btype.includes('json')) ? await bres.json() : null;
      } catch {
        results.marketBank = null;
      }

      if (!cancelled) {
        setData(results);
        setLoading(false);
      }
    }

    loadAll().catch(e => {
      if (!cancelled) {
        setError(e.message);
        setLoading(false);
      }
    });

    return () => { cancelled = true; };
  }, [league, parkMode]);

  return { data, loading, error, loadProgress };
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
// League minimum salary. Measured, not guessed: 437 of 489 (89%) pre-arb one-year
// MLB deals in the TGS market sample sit exactly here (market_fit.json minSalaryInfo).
const LEAGUE_MIN_SALARY = 750000;

export function usePlayersWithFV(players) {
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
      const fv = calculateFutureValue(p, cw.valueYears);
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
        // ceiling minus current, in display WAA — one meaning for every player
        // (the old % mixed three formulas; see futureValue.pctToPeak history)
        _toPeakWAA: fv.displayWAA
          ? Math.round((fv.displayWAA.potential - fv.displayWAA.current) * 10) / 10
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
        // "Proj Peak" = the REALISTIC age-adjusted peak (what we project he'll actually reach),
        // i.e. the raw ceiling AFTER the gap-factor and risk haircut. So a 26+ player past
        // development shows his current WAA — no credit for potential he'll never fill.
        // The un-haircut scouting ceiling is the board's "Ceiling (WAA)" column.
        _potentialWAA: toWAA(d.expectedPeak),
        _rawPotentialWAA: toWAA(d.potential),
        _controlYears: cw.controlYears,
        _controlSource: cw.source,
        _svcYears: cw.serviceYears,
        _controlWindow: cw,
        _fvBreakdown: fv,
      };
    });
  }, [players]);
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
        _draftCeiling: dfv.draftCeiling,          // WAR — what Draft FV is scored on
        _draftCeilingWAA: dfv.draftCeilingWAA,    // WAA — what the board displays
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
  return useMemo(() => {
    if (!players || players.length === 0 || !marketFit || !marketFit.pooled) return players;
    const rate = resolveRate(marketFit, 'hitter');
    if (!(rate.slope > 0)) return players;
    return players.map(p => {
      const val = calculatePlayerValue(p, rate);
      return withMarketValue(p, val, getPlayerWAR(p) ?? 0);
    });
  }, [players, marketFit]);
}

/**
 * Hook that adds market value calculations to PITCHER data.
 * Same fitted line resolution; shows SP/RP role for reference.
 */
export function usePitchersWithMarketValue(players, marketFit) {
  return useMemo(() => {
    if (!players || players.length === 0 || !marketFit || !marketFit.pooled) return players;
    const rate = resolveRate(marketFit, 'pitcher');
    if (!(rate.slope > 0)) return players;
    return players.map(p => {
      const val = calculatePitcherValue(p, rate);
      return { ...withMarketValue(p, val, getPlayerWAR(p) ?? 0), _marketRole: val.role };
    });
  }, [players, marketFit]);
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
