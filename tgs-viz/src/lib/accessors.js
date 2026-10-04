// ============================================================================
// accessors.js — ADAPTER: ootp-dashboard's ("ours") accessor API over this app's
// ("his") flat player records.
//
// Ported from ootp-dashboard app/src/utils/accessors.js (main, 474 lines). Every
// export there exists here with the same name, arguments and return shape, so a
// ported view can keep its accessor calls unchanged. What differs is the record
// underneath: ours reads a nested JSON shape (`maxWar.wtd`, `positions['1b']`,
// `meta.price`, `ratings.stm` …); his rows are flat, keyed by sheet column names
// ('Max WAR wtd', '1B WAR wtd', '1B Eligible', 'Price', 'STM' …). Nothing nested
// leaks out of this file — a ported view must call these functions and never
// read a column name itself.
//
// Rules this adapter follows (Phase 4 brief, docs/phase4/bridge.md):
//   1. WAR comes from his engine WAR columns ('Max WAR wtd', '{pos} WAR wtd',
//      'WAR wtd', 'WARP' …). A row without them (BLM/TGS/RG until their next pull)
//      returns null. WAA + an offset is NEVER substituted.
//   2. No OOTP rule is re-derived. Where ours computed one (Rule 5, options,
//      service thresholds, injury), the accessor reads the data field or returns
//      null (= "unknown"). bridge.md lists each case.
//   3. Absent key → null (or false for a boolean flag that ours also defaults to
//      false, documented per function). Never a fabricated number.
//
// The extra accessors below the ported block (getName, getOrg, getLevel …) are
// new: ours' views read those fields straight off `p.meta.*`, which cannot work
// on his rows. Wave-2 ports replace each `p.meta.x` with the matching accessor.
// ============================================================================
import { calcFutureValue, devPercentileRank } from "./fvV21.js";

// ── local helpers (ours: app/src/utils/helpers.js num / parseCSVBoolean) ──────
export const num = (v) => {
  if (v == null || v === "" || v === "-") return null;
  if (typeof v === "number") return Number.isFinite(v) ? v : null;
  const n = parseFloat(v);
  return Number.isFinite(n) ? n : null;
};
// His StatsPlus keys are real booleans; sheet-extracted ones arrive as 'True'/'Yes'
// strings (same tolerance as his lib/waivers.js isFlag).
const flag = (v) => v === true || v === "true" || v === "True" || v === "TRUE" || v === "Yes";
// Tri-state: true / false when the key is present, null when absent (unknown).
const flagOrNull = (v) => (v === undefined || v === null || v === "" ? null : flag(v));
const has = (p, k) => p != null && p[k] !== undefined && p[k] !== null && p[k] !== "";

// ours' constants.js — model calibration constants (🟡 borrowed, see bridge.md).
const IP_SP = 185.47;
const IP_RP = 69.55;
const RP_SCALE_THRESHOLD = -0.50;

// Pitcher-vs-hitter. Ours stamps `_type` in processData; his rows come from two
// files. A pitcher row always carries the RP projection keys (same test as his
// lib/waivers.js isPitcherRow) or the Starter flag.
export const isPitcher = (p) => {
  if (!p) return false;
  if (p._type) return p._type === "pitcher";
  if (p._poolType) return p._poolType === "pitcher";
  return p["WAA wtd RP"] !== undefined || p["WAA wtd"] !== undefined || p.Starter !== undefined;
};
export const getPlayerType = (p) => (isPitcher(p) ? "pitcher" : "hitter");

// ── position values ─────────────────────────────────────────────────────────
export const getWaa = (p, pos, split = "wtd") => num(p?.[`${pos} WAA ${split}`]);
export const getWaaP = (p, pos) => num(p?.[`${pos} WAA P`]);
// WAR — his engine column; null on rows that predate Phase 1 (BLM today).
export const getWar = (p, pos, split = "wtd") => num(p?.[`${pos} WAR ${split}`]);
export const getWarP = (p, pos) => num(p?.[`${pos} WAR P`]);
export const getRunsP = (p, pos) => num(p?.[`${pos} RunsP`]);

// Eligibility. His '{pos} Eligible' is a real boolean. DH: ours' pipeline makes
// every hitter DH-eligible (model/src/hitters.py "DH Elig": True); his rows carry
// no 'DH Eligible' key but do carry DH WAA/WAR for every hitter, so the same
// convention is kept. SP/RP: ours has no positions entry for them (→ false).
export const isEligible = (p, pos) => {
  if (!p || !pos) return false;
  const P = pos.toUpperCase();
  if (P === "DH") return !isPitcher(p);
  return flag(p[`${P} Eligible`]);
};

export const INF_POSITIONS = ["1B", "2B", "3B", "SS"];
export const OF_POSITIONS = ["LF", "CF", "RF"];

const _expandFieldPositions = (posHint) => {
  const arr = Array.isArray(posHint) ? posHint : [posHint];
  const out = new Set();
  for (const ph of arr) {
    if (ph === "INF") INF_POSITIONS.forEach((x) => out.add(x));
    else if (ph === "OF") OF_POSITIONS.forEach((x) => out.add(x));
    else if (ph && !["Hitters", "Pitchers", "SP", "RP"].includes(ph)) out.add(ph);
  }
  return [...out];
};

// Same contract as ours: { war, warP, fv } at the best eligible matching position,
// null when not eligible anywhere. On a row without WAR columns war/warP are null.
export const pickFielderPos = (p, posHint, hitDevCurve = null, curveSettings = null) => {
  if (!posHint) return null;
  const positions = _expandFieldPositions(posHint);
  if (!positions.length) return null;
  const eligible = positions.filter((pos) => isEligible(p, pos));
  if (!eligible.length) return null;
  let bestWar = null, bestWarP = null;
  for (const pos of eligible) {
    const w = getWar(p, pos);
    const wp = getWarP(p, pos);
    if (w != null && (bestWar == null || w > bestWar)) bestWar = w;
    if (wp != null && (bestWarP == null || wp > bestWarP)) bestWarP = wp;
  }
  let fv = bestWar;
  if (bestWar != null && curveSettings != null) {
    fv = calcFutureValue(bestWar, bestWarP, getAge(p), curveSettings);
  }
  return { war: bestWar, warP: bestWarP, fv };
};

const _matchesSinglePosFilter = (p, posFilter) => {
  const pit = isPitcher(p);
  if (posFilter === "Pitchers") return pit;
  if (posFilter === "Hitters") return !pit;
  if (posFilter === "SP") return pit && isStarter(p);
  if (posFilter === "RP") return pit && !isStarter(p);
  if (posFilter === "INF") return !pit && INF_POSITIONS.some((pos) => isEligible(p, pos));
  if (posFilter === "OF") return !pit && OF_POSITIONS.some((pos) => isEligible(p, pos));
  return !pit && isEligible(p, posFilter);
};

// ── levels ──────────────────────────────────────────────────────────────────
// Ours' categories: MLB, AAA, AA, A+, A, A-, Rookie, INT. His Lev strings: MLB,
// AAA, AA, A+, A-, R+, R-, WL (winter), INT (TGS only), plus FA (free agent) and
// AMA (amateur draft pool), which are not levels at all → null here.
export const STANDARD_LEVELS = ["MLB", "AAA", "AA", "A+", "A", "A-"];
export const LEVEL_CATEGORY_ORDER = ["MLB", "AAA", "AA", "A+", "A", "A-", "Rookie", "INT"];
const NOT_A_LEVEL = new Set(["FA", "AMA", "-", "0"]);

export const categorizeLevel = (lev) => {
  if (lev == null || lev === "" || NOT_A_LEVEL.has(lev)) return null;
  if (STANDARD_LEVELS.includes(lev)) return lev;
  if (lev === "INT") return "INT";
  return "Rookie";
};

// Level string as ours' `meta.lev`. The international complex: ours reads OOTP's
// "INT" level from the export; his SSB rows carry the export's IC flag as
// `IntlComplex` (collinear with INT, docs/phase3/roster_fields.md), so a row with
// IntlComplex === true reports "INT". Absent flag → his Lev as shipped.
export const getLevel = (p) => {
  if (!p) return null;
  if (p.IntlComplex === true) return "INT";
  return has(p, "Lev") ? String(p.Lev) : null;
};

// Same filter values as ours: category strings, "team:<id>", "tm:<abbr>".
// "team:" matches his `Team` (the team id); "tm:" has no per-row source (his rows
// carry no team abbreviation) and never matches.
export const passesLevelFilter = (p, levelFilter) => {
  if (!levelFilter) return true;
  if (Array.isArray(levelFilter)) {
    if (levelFilter.length === 0) return true;
    const cat = categorizeLevel(getLevel(p));
    const tid = getTeamId(p);
    return levelFilter.some((entry) => {
      if (typeof entry !== "string") return false;
      if (entry.startsWith("team:")) return tid != null && String(tid) === entry.slice(5);
      if (entry.startsWith("tm:")) return false;
      return cat === entry;
    });
  }
  if (levelFilter === "ALL") return true;
  return categorizeLevel(getLevel(p)) === levelFilter;
};

export const passesPositionFilter = (p, posFilter) => {
  if (!posFilter) return true;
  if (Array.isArray(posFilter)) {
    if (posFilter.length === 0) return true;
    return posFilter.some((f) => _matchesSinglePosFilter(p, f));
  }
  if (posFilter === "ALL") return true;
  return _matchesSinglePosFilter(p, posFilter);
};

// ── position ratings (20-80) ────────────────────────────────────────────────
// His current position rating is the bare column ('C', '1B' … 'RF'); potential
// is 'Pot{pos}'. A 0 there means no rating (0 is off the 20-80 scale; on SSB the
// current and potential are 0 together on every row), mapped to null the way
// ours' pipeline leaves a missing rating null.
export const POS_RATING_MIN = 50;
export const POS_RATING_PCT = 0.75;
const FIELD_POSITIONS = new Set(["C", "1B", "2B", "3B", "SS", "LF", "CF", "RF"]);
const _rating = (v) => { const n = num(v); return n == null || n <= 0 ? null : n; };

export const getPosRating = (p, pos) => {
  const P = String(pos).toUpperCase();
  return FIELD_POSITIONS.has(P) ? _rating(p?.[P]) : null;
};
export const getPosPotential = (p, pos) => {
  const P = String(pos).toUpperCase();
  return FIELD_POSITIONS.has(P) ? _rating(p?.[`Pot${P}`]) : null;
};

// Ours' display heuristic (50 or 75% of potential), not an OOTP rule: kept as is.
export const isCurrentlyEligible = (p, pos) => {
  if (!isEligible(p, pos)) return false;
  const cur = getPosRating(p, pos);
  const pot = getPosPotential(p, pos);
  if (cur == null || pot == null) return !FIELD_POSITIONS.has(pos.toUpperCase());
  if (cur >= POS_RATING_MIN) return true;
  return cur >= POS_RATING_PCT * pot;
};

export const eligibilityStatus = (p, pos) => {
  if (!isEligible(p, pos)) return "none";
  return isCurrentlyEligible(p, pos) ? "current" : "potential";
};

// ── max / batting / baserunning ─────────────────────────────────────────────
export const getMaxWaa = (p, split = "wtd") => num(p?.[`Max WAA ${split}`]);
export const getMaxWaaP = (p) => num(p?.["MAX WAA P"]);
export const getMaxWar = (p, split = "wtd") => num(p?.[`Max WAR ${split}`]);
export const getMaxWarP = (p) => num(p?.["MAX WAR P"]);
export const getBatR = (p, split = "wtd") => num(p?.[`BatR ${split}`]);
export const getBsr = (p, split = "wtd") => num(p?.[`BSR ${split}`]);

// ── pitchers ────────────────────────────────────────────────────────────────
// Ours gates SP values on `starter || starterP` (two flags from ours' pitch-count
// + stamina gate). His rows carry ONE flag, `Starter`, and SP projection columns
// exist only on rows where it is true (SSB: 0 of 1,777 non-starters carry
// 'WAA wtd'). His flag agrees with ours' gate on POTENTIAL pitch grades on 93% of
// SSB rows and with the current-grade gate on 73%, so it stands in for both.
export const isStarter = (p) => flag(p?.Starter);
export const isStarterP = (p) => flag(p?.Starter);

export const getSpWaa = (p, split = "wtd") => (isStarter(p) ? num(p[`WAA ${split}`]) : null);
export const getRpWaa = (p, split = "wtd") => num(p?.[`WAA ${split} RP`]);
export const getSpWaaP = (p) => (isStarter(p) ? num(p.WAP) : null);
export const getRpWaaP = (p) => num(p?.["WAP RP"]);
export const getSpWar = (p, split = "wtd") => (isStarter(p) ? num(p[`WAR ${split}`]) : null);
export const getRpWar = (p, split = "wtd") => num(p?.[`WAR ${split} RP`]);
export const getSpWarP = (p) => (isStarter(p) ? num(p.WARP) : null);
export const getRpWarP = (p) => num(p?.["WARP RP"]);

// Floor (ours' developable-ratings-at-cohort-minimum pipeline). His data has no
// floor projection at all → always null.
export const getFloorWaa = () => null;
export const getSpFloor = () => null;
export const getRpFloor = () => null;
export const getFloorWar = () => null;
export const getSpFloorWar = () => null;
export const getRpFloorWar = () => null;

// Injury. Ours: StatsPlus injury_is_injured === "1" OR is_on_dl. His rows carry
// only the DL flags (OnDL / OnDL60; same reading as his rosterOptimizer.isInjured).
// The "injured but not on the IL" set ours catches is not in his data.
export const isInjured = (p) => flag(p?.OnDL) || flag(p?.OnDL60);

// ── resolveKey: ours' column keys → values ──────────────────────────────────
// Ours' column definitions use the sheet's own names as keys, so most of them
// are his column names verbatim. The cases below are the ones where ours
// re-routed through a nested path or a computed field.
export const resolveKey = (p, key) => {
  if (!p) return undefined;
  switch (key) {
    case "Max WAA wtd": return getMaxWaa(p, "wtd");
    case "Max WAA vR": return getMaxWaa(p, "vR");
    case "Max WAA vL": return getMaxWaa(p, "vL");
    case "MAX WAA P": return getMaxWaaP(p);
    case "WAA wtd": return getSpWaa(p);
    case "WAA wtd RP": return getRpWaa(p);
    case "WAP": return getSpWaaP(p);
    case "WAP RP": return getRpWaaP(p);
    case "Max WAR wtd": return getMaxWar(p, "wtd");
    case "Max WAR vR": return getMaxWar(p, "vR");
    case "Max WAR vL": return getMaxWar(p, "vL");
    case "MAX WAR P": return getMaxWarP(p);
    case "WAR wtd": return getSpWar(p);
    case "WAR wtd RP": return getRpWar(p);
    case "WARP": return getSpWarP(p);
    case "WARP RP": return getRpWarP(p);
    case "OBP vR": case "OBP vL": case "wOBA vR": case "wOBA vL":
      // ours reads batting.* (hitter lines only); his pitcher rows reuse the
      // same names for wOBA AGAINST, so pitchers get null here as in ours.
      return isPitcher(p) ? null : num(p[key]);
    case "Name": return getName(p);
    case "POS": return getPos(p);
    case "ORG": return getOrg(p);
    case "Lev": return getLevel(p);
    case "Prone": return getProne(p);
    case "Price": return getPrice(p);
    case "PROY": return getProServiceYears(p);
    case "B": return getBats(p);
    case "Age": return getAge(p);
    case "INT": return getIntangible(p, "int");
    case "WE": return getIntangible(p, "we");
    case "LEA": return getIntangible(p, "lea");
    case "AD": return getIntangible(p, "ad");
    case "_intangibles": return p._intangibles ?? null;
    case "STM": return getRating(p, "stm");
    case "VELO": return getVelo(p);
    case "Starter": return isPitcher(p) ? isStarter(p) : null;
    case "Starter P": return isPitcher(p) ? isStarterP(p) : null;
    case "MLD": return getMlbServiceDays(p);
    case "OY": return getOptionYearUsed(p);
    case "OVR": return getOvr(p);
    case "POT": return getPot(p);
    default: return p[key];
  }
};

const POS_SORT_ORDER = { C: 0, "1B": 1, "2B": 2, "3B": 3, SS: 4, LF: 5, CF: 6, RF: 7, DH: 8, SP: 9, RP: 10 };
export { POS_SORT_ORDER };

// Verbatim from ours (sorting is shape-independent once resolveKey is adapted).
export const genericSort = (arr, col, dir, specialCols = {}) => {
  const isPosSortCol = col === "POS" || col === "_bestPos";
  const sortOverride = SORT_KEY_OVERRIDE[col];
  arr.sort((a, b) => {
    let va, vb;
    if (specialCols[col]) { va = specialCols[col](a); vb = specialCols[col](b); }
    else if (sortOverride && (a[sortOverride] != null || b[sortOverride] != null)) {
      va = a[sortOverride] != null ? a[sortOverride] : num(resolveKey(a, col));
      vb = b[sortOverride] != null ? b[sortOverride] : num(resolveKey(b, col));
    }
    else {
      const ra = col === "_bestPos" ? getBestPos(a) : resolveKey(a, col);
      const rb = col === "_bestPos" ? getBestPos(b) : resolveKey(b, col);
      if (isPosSortCol) {
        const pa = POS_SORT_ORDER[typeof ra === "string" ? ra.replace("*", "") : ra];
        const pb = POS_SORT_ORDER[typeof rb === "string" ? rb.replace("*", "") : rb];
        va = pa ?? 99; vb = pb ?? 99;
      } else {
        const na = num(ra), nb = num(rb);
        if (na != null || nb != null) { va = na; vb = nb; }
        else { va = (ra === "" || ra == null) ? null : ra; vb = (rb === "" || rb == null) ? null : rb; }
      }
    }
    if (va == null && vb == null) return 0;
    if (va == null) return 1; if (vb == null) return -1;
    if (typeof va === "string") return dir === "asc" ? va.localeCompare(vb) : vb.localeCompare(va);
    return dir === "asc" ? va - vb : vb - va;
  });
};

// WAA-era RP scaler, kept for API parity. Its constants are ours' calibration
// (🟡 not re-checked against his WAA scale); no WAR path uses it.
export const scaleRpWaaP = (v, threshold = RP_SCALE_THRESHOLD) => {
  if (v == null) return null;
  if (v >= 0) return v;
  const ratio = IP_SP / IP_RP;
  if (v <= threshold) return v * ratio;
  const t = v / threshold;
  return v * (1 + (ratio - 1) * t);
};
export const scaleRpWarP = (v) => v;

// Same contract as ours. devCurves are ours' pipeline `meta.devCurve`; his data
// ships none, so callers pass null and devPct is null. floorSort is always null
// (no floor projection in his data). On a row without WAR columns every WAR
// field is null and role falls to 'rp' (ours' rule: no SP WAR P → RP).
export const pickPitcherRole = (p, devCurves = null, curveSettings = null, roleHint = "best") => {
  const spWar = getSpWar(p);
  const spWarP = getSpWarP(p);
  const rpWar = getRpWar(p);
  const rpWarP = getRpWarP(p);
  const rpWarScaled = scaleRpWarP(rpWar);
  const rpWarPScaled = scaleRpWarP(rpWarP);
  const spFloor = getSpFloorWar(p);
  const rpFloorScaled = scaleRpWarP(getRpFloorWar(p));

  let useRp;
  if (roleHint === "rp") useRp = true;
  else if (roleHint === "sp") useRp = (spWar == null && spWarP == null);
  else useRp = (spWarP == null) || (rpWarPScaled != null && rpWarPScaled > spWarP);

  const role = useRp ? "rp" : "sp";
  const cur = useRp ? rpWarScaled : spWar;
  const pot = useRp ? rpWarPScaled : spWarP;
  const floor = useRp ? rpFloorScaled : spFloor;
  const age = getAge(p);

  const devCurve = devCurves ? (useRp ? devCurves.rp : devCurves.sp) : null;
  const devPct = (cur != null && devCurve != null) ? devPercentileRank(devCurve, age, cur) : null;
  let fv = cur;
  if (cur != null && curveSettings) fv = calcFutureValue(cur, pot, age, curveSettings);

  return {
    role,
    war: useRp ? rpWar : spWar,
    warP: useRp ? rpWarP : spWarP,
    warSort: cur,
    warPSort: pot,
    floorSort: floor,
    devPct,
    devCurve,
    fv,
  };
};

export const getBestPitcherWar = (p) => pickPitcherRole(p).war;
export const getBestPitcherWarP = (p) => pickPitcherRole(p).warP;
export const getBestPitcherFv = (p, progressCurves, cs) => pickPitcherRole(p, progressCurves, cs).fv;

export const SORT_KEY_OVERRIDE = {
  war: "_warSort",
  warP: "_warPSort",
  _war: "_warSort",
  _warP: "_warPSort",
};

// Platoon blend (pure arithmetic). `splits` is ours' pipeline `meta.platoonSplits`;
// without it ours falls back to 62/38 (🟡 ours' default, kept).
export const blendPlatoon = (vR, vL, hand, splits, type) => {
  const r = num(vR), l = num(vL);
  if (r == null && l == null) return null;
  if (r == null) return l;
  if (l == null) return r;
  const baseKey = (hand === "L" || hand === "R" || hand === "S") ? hand : "OVR";
  const w = splits?.[type]?.[baseKey] ?? splits?.[type]?.["OVR"] ?? { vR: 0.62, vL: 0.38 };
  return r * w.vR + l * w.vL;
};

// ============================================================================
// NEW ACCESSORS — fields ours' views read straight off the nested record
// (`p.meta.*`, `p.ratings.*`, `p._age` …). Each maps to his column(s); a field
// his data does not carry returns null. bridge.md has the full table.
// ============================================================================

// ── identity ────────────────────────────────────────────────────────────────
export const getId = (p) => (has(p, "ID") ? String(p.ID) : null);
export const getName = (p) => (has(p, "Name") ? p.Name : null);
// Listed position (ours meta.pos). His POS uses OOTP's strings incl. 'CL'.
export const getPos = (p) => (has(p, "POS") ? p.POS : null);
// Organisation name (ours meta.org). Ours writes "-" for no organisation; his
// rows carry ORG '0'. Normalised to ours' "-" so ported FA checks keep working.
export const getOrg = (p) => {
  const o = p?.ORG;
  if (o == null || o === "" || o === "0" || o === 0) return "-";
  return String(o);
};
export const getOrgId = (p) => (has(p, "Org") && String(p.Org) !== "0" ? String(p.Org) : null);
// Team id (ours meta.team_id) — his `Team`, '0' = none.
export const getTeamId = (p) => (has(p, "Team") && String(p.Team) !== "0" ? String(p.Team) : null);
// Ours' "tm" (team abbreviation) has no per-row source in his data.
export const getTeamAbbr = () => null;
// Free agent / amateur. His pull stamps FA (true FA) and Lev 'AMA' (draft pool).
export const isFreeAgent = (p) => (p?.FA !== undefined ? flag(p.FA) : getOrg(p) === "-" && getLevel(p) !== "AMA");
export const isAmateur = (p) => getLevel(p) === "AMA";

// ── bio ─────────────────────────────────────────────────────────────────────
// Age. Ours uses `_age` (fractional, recomputed from DOB + game date). His rows
// carry an integer `Age` string and no DOB, so ported views get whole years
// unless a caller stamps `_age` itself.
export const getAge = (p) => (p?._age != null ? p._age : num(p?.Age));
export const getDob = () => null;          // no DOB in his data
export const getBats = (p) => (has(p, "B") ? p.B : null);
export const getThrows = (p) => (has(p, "T") ? p.T : null);
export const getHeightCm = (p) => num(p?.["HT Sort"] ?? p?.HT);
export const getWeight = () => null;       // no weight in his data
export const getProne = (p) => (has(p, "Prone") ? p.Prone : null);
// Personality (ours meta.int/we/lea/ad/loy/fin, OOTP H/N/L). His columns:
// Int, WrkEthic, Lead, Loy, Greed. No adaptability ('ad') and no 'fin'.
const INTANGIBLE_COL = { int: "Int", we: "WrkEthic", lea: "Lead", loy: "Loy", greed: "Greed", ad: null, fin: null };
export const getIntangible = (p, key) => {
  const col = INTANGIBLE_COL[String(key).toLowerCase()];
  return col && has(p, col) ? p[col] : null;
};
export const getOvr = (p) => num(p?.Ovr);
export const getPot = (p) => num(p?.Pot);
// Scouting accuracy — his `Acc` (VH/H/A/L); ours has no equivalent column.
export const getScoutAccuracy = (p) => (has(p, "Acc") ? p.Acc : null);

// ── ratings (20-80) ─────────────────────────────────────────────────────────
// Ours: ratings.{vR,vL,potential}.<key> and bare ratings.<key>. split = 'vR' |
// 'vL' | 'potential' | null (overall / unsplit). The table is his column names;
// note his 'CON*' columns are PITCHER control — hitter contact is 'Cntct*'.
const RATING_COLS = {
  // hitters
  con:    { vR: "Cntct_R",   vL: "Cntct_L",   potential: "PotCntct", overall: "Cntct" },
  gap:    { vR: "GAP vR",    vL: "GAP vL",    potential: "GAP P",    overall: "Gap" },
  pow:    { vR: "POW vR",    vL: "POW vL",    potential: "POW P",    overall: "Pow" },
  eye:    { vR: "EYE vR",    vL: "EYE vL",    potential: "EYE P",    overall: "Eye" },
  k:      { vR: "K vR",      vL: "K vL",      potential: "K P",      overall: "Ks" },
  ba:     { vR: "BA vR",     vL: "BA vL",     potential: "HT P",     overall: "BABIP" },
  ht:     { potential: "HT P" },
  // pitchers
  stu:    { vR: "STU vR",    vL: "STU vL",    potential: "STU P",    overall: "STU" },
  mov:    { vR: "Mov_R",     vL: "Mov_L",     potential: "PotMov",   overall: "Mov" },
  pcon:   { vR: "CON vR",    vL: "CON vL",    potential: "CON P",    overall: "CON" },
  hrr:    { vR: "HRR vR",    vL: "HRR vL",    potential: "HRR P",    overall: "HRR" },
  pbabip: { vR: "PBABIP vR", vL: "PBABIP vL", potential: "PBABIP P", overall: "PBABIP" },
  // unsplit
  stm: { overall: "STM" }, hld: { overall: "HLD" },
  spe: { overall: "SPE" }, ste: { overall: "STE" }, run: { overall: "RUN" },
  sr: { overall: "SR" }, bun: { overall: "SacBunt" }, bfh: { overall: "BuntHit" },
  // fielding components (ours fieldingRatings.*)
  cAbi: { overall: "C ABI" }, cFrm: { overall: "C FRM" }, cArm: { overall: "C ARM" },
  ifRng: { overall: "IF RNG" }, ifErr: { overall: "IF ERR" }, ifArm: { overall: "IF ARM" },
  tdp: { overall: "TDP" },
  ofRng: { overall: "OF RNG" }, ofErr: { overall: "OF ERR" }, ofArm: { overall: "OF ARM" },
};
export const getRating = (p, key, split = null) => {
  const cols = RATING_COLS[key];
  if (!cols) return null;
  const col = cols[split || "overall"];
  return col ? num(p?.[col]) : null;
};

// Pitch grades (ours pitchGrades.current/potential.<fb…kn>). 0 = pitch not
// thrown → null, as ours' CSV leaves it blank.
const PITCHES = ["fb", "ch", "cb", "sl", "si", "sp", "ct", "fo", "cc", "sc", "kc", "kn"];
export const PITCH_KEYS = PITCHES;
export const getPitchGrade = (p, pitch, potential = false) => {
  const k = String(pitch).toLowerCase();
  if (!PITCHES.includes(k)) return null;
  return _rating(p?.[k.toUpperCase() + (potential ? "P" : "")]);
};
export const getPitchCount = (p) => num(p?.Pitches);
// Velocity — his `Vel` is OOTP's display range ("95-97"); ours had a numeric
// `velo` plus display `vt`. num() reads the range's lower bound for sorting.
export const getVelo = (p) => (has(p, "Vel") ? p.Vel : null);
export const getVeloPotential = (p) => (has(p, "PotVel") ? p.PotVel : null);

// ── best position ───────────────────────────────────────────────────────────
// Ours computes `_bestPos` in processData (dataProcessing.js calcBestPos). A
// stamped `_bestPos` wins. Hitters: ours' rule (RunsP + ours' per-league
// DEF_SPECTRUM, LF/RF arm split) is ours' model with per-league constants that
// do not exist for his leagues; his engine ships its own answer, 'Best Pos WAR'
// (falling back to 'Best Pos' on rows that predate Phase 1).
// Pitchers: his data ships none, so ours' pitcher branch is ported verbatim,
// including ours' model thresholds (🟡 constants.js SP_REPLACEMENT_WAP = -0.5,
// RP_ADVANTAGE_THRESHOLD = 1.0, WAR-calibrated on ours' scale). `matured`
// switches potential → current WAR, as in ours. On a row without WAR columns
// this returns his listed POS (ours' own fallback).
const SP_REPLACEMENT_WAP = -0.5;
const RP_ADVANTAGE_THRESHOLD = 1.0;
export const getBestPos = (p, matured = false) => {
  if (!p) return null;
  if (p._bestPos != null) return p._bestPos;
  if (isPitcher(p)) {
    if (!(isStarter(p) || isStarterP(p))) return "RP";
    const spVal = matured ? getSpWar(p) : getSpWarP(p);
    const rpVal = matured ? getRpWar(p) : getRpWarP(p);
    if (spVal != null || rpVal != null) {
      const sp = spVal ?? -Infinity;
      const rp = rpVal ?? -Infinity;
      if (sp >= SP_REPLACEMENT_WAP) return rp - sp > RP_ADVANTAGE_THRESHOLD ? "RP*" : "SP";
      return sp >= rp ? "SP" : "RP*";
    }
    return getPos(p) || "RP";
  }
  if (has(p, "Best Pos WAR")) return p["Best Pos WAR"];
  return has(p, "Best Pos") ? p["Best Pos"] : null;
};

// ── injuries ────────────────────────────────────────────────────────────────
// Ours' planner `_ilShort`/`_ilLong` are frontend move overlays, not data.
export const isOnIL = (p) => flag(p?.OnDL);         // ours meta.is_on_dl
export const isOnIL60 = (p) => flag(p?.OnDL60);     // ours meta.is_on_dl60
export const getInjuryDaysLeft = (p) => num(p?.DLDays);

// ── roster status (all tri-state: true / false / null = unknown) ────────────
// 40-man (ours meta.on40). StatsPlus `IsOnSecondary` first: it comes with every
// pull, while the OOTP export (`On40Man`, Phase 3 roster_export merge) is made by
// hand and can be months old. The two agree on 99.5% of rows when the export is
// fresh (docs/phase3/waivers_service.md §1). The export is the fallback for rows
// StatsPlus did not send. User decision 2026-10-04.
export const isOn40Man = (p) => flagOrNull(p?.IsOnSecondary) ?? flagOrNull(p?.On40Man);
// Active (26-man) roster (ours meta.act): StatsPlus `IsActive`, else export `ActiveRoster`.
export const isActiveRoster = (p) => flagOrNull(p?.IsActive) ?? flagOrNull(p?.ActiveRoster);
// Rule 5 (ours meta.r5): the export's own flag. No fallback — ours' signing-age
// rule (eligibility.js calcR5Projection) is an OOTP rule and is NOT ported.
export const isRule5Eligible = (p) => flagOrNull(p?.Rule5Eligible);
// StatsPlus's per-player protection length (4 / 5; 0 = none on file).
export const getYearsProtectedFromRule5 = (p) => num(p?.YearsProtectedFromRule5);
// Options: used so far (ours meta.opt) and the option year in use (ours meta.oy).
// Options REMAINING is ours' `3 - used` (an OOTP rule) — not computed: null.
export const getOptionsUsed = (p) => num(p?.OptionsUsed);
export const getOptionYearUsed = (p) => num(p?.OptionYearUsed);
export const getOptionsRemaining = () => null;
export const isRookie = (p) => flagOrNull(p?.RookieStatus);              // ours meta.rook
export const isIntlComplex = (p) => flagOrNull(p?.IntlComplex);          // ours meta.ic
// OOTP's "years left" string, e.g. "1 (auto.)", "2 (arbitr.)" (ours meta.yl).
export const getYearsLeftStatus = (p) => (has(p, "ContractStatus") ? String(p.ContractStatus) : null);
// Date the roster-export fields above were taken, and its age vs the pull.
export const getRosterExportDate = (p) => (has(p, "RosterExportDate") ? p.RosterExportDate : null);
export const getRosterExportGapDays = (p) => num(p?.RosterExportGapDays);

// ── waivers ─────────────────────────────────────────────────────────────────
export const isOnWaivers = (p) => flag(p?.OnWaivers);        // ours meta.is_on_waivers
export const isDFA = (p) => flag(p?.DFA);                     // ours meta.dfa / designated_for_assignment
// 0 = cleared waivers (ours' reading); null = no clock on the row.
export const getWaiverDaysLeft = (p) => num(p?.WaiverDaysLeft);
export const getWaiverDays = (p) => num(p?.WaiverDays);

// ── service time (league-calendar days; ours' MLD = years × 172 + days) ─────
export const getMlbServiceDays = (p) => num(p?.MLBSvcDays);          // ours meta.mld
export const getMlbServiceYears = (p) => num(p?.MLBSvcYrs);          // ours meta.mly
export const getMlbServiceDaysThisYear = (p) => num(p?.MLBSvcDaysTY); // ours meta.mlb_service_days_this_year
export const getProServiceYears = (p) => num(p?.ProSvcYrs);          // ours meta.proy
export const getProServiceDays = (p) => num(p?.ProSvcDays);
export const getSecServiceYears = (p) => num(p?.SecSvcYrs);          // ours meta.secy
export const getSecServiceDays = (p) => num(p?.SecSvcDays);          // ours meta.secd
// Draft year (ours meta.draft) — not in his rows.
export const getDraftYear = () => null;

// ── money / contract ────────────────────────────────────────────────────────
// Current-season salary. His `Price` is set only on contracted rows (SSB: 2,087
// of 14,003). Ours' meta.price was max(salary, league minimum), or the demand
// for an unsigned free agent — that floor and that substitution are NOT applied
// here: no salary on the row → null.
export const getPrice = (p) => num(p?.Price);
export const getSalary = getPrice;
// Ours meta.cv (contract value, used as the current-year salary). Same column.
export const getContractValue = getPrice;
// Contract demand (ours meta.dem, display string like "$5.0m") and its dollar
// value (ours meta.demSort). Parsing the printed amount is not a rule.
export const getDemand = (p) => (has(p, "ContractDemand") ? String(p.ContractDemand) : null);
export const getDemandValue = (p) => {
  const s = getDemand(p);
  if (!s) return null;
  const m = /^\$?\s*([\d.,]+)\s*([mk]?)$/i.exec(s.trim());
  if (!m) return null;
  const v = parseFloat(m[1].replace(/,/g, ""));
  if (!Number.isFinite(v)) return null;
  const unit = m[2].toLowerCase();
  return unit === "m" ? v * 1e6 : unit === "k" ? v * 1e3 : v;
};
export const getSignDifficulty = (p) => (has(p, "SignDifficulty") ? p.SignDifficulty : null); // ours meta.sign
export const getFaType = (p) => (has(p, "FAType") ? p.FAType : null);
export const hasNoTrade = (p) => flagOrNull(p?.NoTrade);

// Remaining salary schedule: { startYear, salaries } — `SalarySchedule` is the
// REMAINING seasons starting at `SalaryStartYr` (his serviceTime.js measured the
// schedule length = years remaining). startYear is null on rows that predate the
// Phase 3 contract keys (BLM today).
export const getSalarySchedule = (p) => {
  const s = Array.isArray(p?.SalarySchedule) ? p.SalarySchedule.filter(Number.isFinite) : [];
  if (!s.length) return null;
  return { startYear: num(p.SalaryStartYr), salaries: s };
};
export const getContractYearsRemaining = (p) => {
  const s = getSalarySchedule(p);
  return s ? s.salaries.length : null;
};

// Ours' option-type vocabulary: 'club' | 'player' | 'vesting'.
const OPTION_TYPE = { team: "club", club: "club", player: "player", vesting: "vesting" };
const _ext = (p) => {
  const e = p?.ContractExt;
  if (!e || typeof e !== "object") return null;
  const sal = Array.isArray(e.salaries) ? e.salaries : [];
  if (!num(e.yr) || !sal.some((v) => num(v) > 0)) return null;  // empty / placeholder rows
  return e;
};
export const getExtension = (p) => {
  const e = _ext(p);
  return e ? { startYear: num(e.yr), years: num(e.years), salaries: e.salaries.map(num) } : null;
};

// Equivalent of ours' resolveContractYear(contract, calendarYear): the salary,
// option type and buyout for one calendar year, from the base deal or the
// extension; null when neither covers the year or the row has no start year.
export const getContractYear = (p, calendarYear) => {
  const yr = num(calendarYear);
  if (yr == null) return null;
  const sched = getSalarySchedule(p);
  if (sched && sched.startYear != null) {
    const i = yr - sched.startYear;
    if (i >= 0 && i < sched.salaries.length) {
      const o = (Array.isArray(p.ContractOptions) ? p.ContractOptions : []).find((x) => num(x?.yr) === yr);
      return { salary: sched.salaries[i], optionType: o ? (OPTION_TYPE[o.type] ?? null) : null, buyout: o ? (num(o.buyout) ?? 0) : 0 };
    }
  }
  const e = _ext(p);
  if (e) {
    const i = yr - num(e.yr);
    if (i >= 0 && i < e.salaries.length) {
      const o = (Array.isArray(e.options) ? e.options : []).find((x) => num(x?.yr) === yr);
      return { salary: num(e.salaries[i]) ?? 0, optionType: o ? (OPTION_TYPE[o.type] ?? null) : null, buyout: o ? (num(o.buyout) ?? 0) : 0 };
    }
  }
  return null;
};

// OOTP salary report (team page): one cell per shown year, arbitration
// projection, opt-out years. Ours scraped the same page (utils/salaryReport.js).
export const getSalaryReportCell = (p, year) => {
  const r = p?.SalaryReport;
  return r && typeof r === "object" ? (r[String(year)] ?? null) : null;
};
export const getSalaryReportSpan = (p) => (Array.isArray(p?.SalaryReportSpan) ? p.SalaryReportSpan : null);
export const getArbProjection = (p) => (p?.ArbProjection && typeof p.ArbProjection === "object" ? p.ArbProjection : null);
export const getOptOutYears = (p) => (Array.isArray(p?.OptOutYrs) ? p.OptOutYrs : null);

// ── things ours reads that his data does not carry (always null) ────────────
// Kept as named accessors so a ported view compiles and shows "unknown".
export const getSourceTag = () => null;    // ours meta.source/manual ("IAFA", "2042 Draft"); use isAmateur()
export const isTwoWay = () => null;        // ours meta.isTwoWay
export const isInjuredNotOnIL = () => null; // ours meta.injury_is_injured without is_on_dl

// ── projected stat lines (ours batting / baserunning / sp / rp / prospect) ──
// Ours nests one object per split; his columns are '<stat> <split>' for hitters
// and '<stat> <split>[ RP]' for pitchers, P = potential. `split` = 'vR' | 'vL' |
// 'wtd' | 'P'. Keys use ours' names; a stat his engine does not ship → null.
const HIT_STAT_COL = {
  obp: "OBP", woba: "wOBA", batR: "BatR", hr: "HR", hMinusHr: "H-HR", xbhMinusHr: "XBH-HR",
  ubb: "uBB", hbp: "HBP", so: "SO",
};
export const getBattingStat = (p, stat, split = "wtd") => {
  if (isPitcher(p)) return null;
  const col = HIT_STAT_COL[stat];
  return col ? num(p?.[`${col} ${split}`]) : null;
};
// Baserunning: bsr / wsb / ubr per split; sbPct unsplit ('SB%'). No potential
// baserunning columns in his data.
const BR_STAT_COL = { bsr: "BSR", wsb: "wSB", ubr: "UBR" };
export const getBaserunningStat = (p, stat, split = "wtd") => {
  if (isPitcher(p)) return null;
  if (stat === "sbPct") return split === "P" ? null : num(p?.["SB%"]);
  const col = BR_STAT_COL[stat];
  return col && split !== "P" ? num(p?.[`${col} ${split}`]) : null;
};
// Pitching lines per role. Ours: player[role][split].<stat>, prospect[role].<stat>.
const PIT_STAT_COL = {
  woba: "wOBA", ra9: "RA/9", so: "SO", ubb: "uBB", hr: "HR", hbp: "HBP",
  hMinusHr: "H-HR", xbhMinusHr: "XBH-HR", sbPct: "SB%", sb: "SB", cs: "CS", sbat: "SBAT",
  singles: "1B", doubles: "2B", triples: "3B",
};
export const getPitchingStat = (p, role, stat, split = "wtd") => {
  if (!isPitcher(p)) return null;
  const r = String(role).toLowerCase();
  if (r === "sp" && !isStarter(p)) return null;
  if (stat === "war") return r === "sp" ? (split === "P" ? getSpWarP(p) : getSpWar(p, split)) : (split === "P" ? getRpWarP(p) : getRpWar(p, split));
  if (stat === "waa") return r === "sp" ? (split === "P" ? getSpWaaP(p) : getSpWaa(p, split)) : (split === "P" ? getRpWaaP(p) : getRpWaa(p, split));
  const col = PIT_STAT_COL[stat];
  if (!col) return null;
  // His pitcher rows ship counting stats for vR / vL / P only; the wtd split
  // exists for wOBA, RA/9, WAA and WAR alone, so e.g. SO wtd → null.
  return num(p?.[`${col} ${split}${r === "rp" ? " RP" : ""}`]);
};
