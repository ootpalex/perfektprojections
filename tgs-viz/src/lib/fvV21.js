// fvV21.js — ported subset of ootp-dashboard app/src/utils/futureValue.js (v21 power-law
// creditAge FV) for lib/accessors.js (pickFielderPos / pickPitcherRole). The function
// bodies are copied verbatim; only the DEV_CURVE_DEFAULTS import is inlined (ours'
// app/src/utils/constants.js). The rest of ours' futureValue.js (smart rank, demand,
// coverage floor) is not ported here — wave 2 adds it with the boards that need it.
//
// NOT his lib/futureValue.js: that is his FV model (measured / ML path), a different
// formula on a different scale. Nothing here touches it.

// ours' app/src/utils/constants.js DEV_CURVE_DEFAULTS (🟡 ours' tuned defaults)
export const DEV_CURVE_DEFAULTS = {
  gapMax: 0.80,
  gapExp: 3,
  maxCurrentAge: 27,
  bandwidth: 0.5,
};

function clamp(v, lo, hi) { return Math.max(lo, Math.min(hi, v)); }


// Linear-interp p50 lookup from the cohort devCurve at any age.
// Used by FVIAT diagnostic display only — not by the FV path.
export function typicalAtAge(devCurve, age) {
  if (!Array.isArray(devCurve) || devCurve.length === 0 || age == null) return null;
  if (age <= devCurve[0].age) return devCurve[0].p50;
  if (age >= devCurve[devCurve.length - 1].age) return devCurve[devCurve.length - 1].p50;
  for (let i = 0; i < devCurve.length - 1; i++) {
    const a0 = devCurve[i].age, a1 = devCurve[i + 1].age;
    if (age >= a0 && age <= a1) {
      const t = a1 === a0 ? 0 : (age - a0) / (a1 - a0);
      return devCurve[i].p50 * (1 - t) + devCurve[i + 1].p50 * t;
    }
  }
  return devCurve[devCurve.length - 1].p50;
}

// Age-cohort percentile rank for a player's dev signal value. v21: dev signal
// is cur-WAR across all cohorts (hitter `maxWar.wtd`, SP `sp.wtd.war`, RP
// scaled `rp.wtd.war`). Used purely for the Dev% display column — not in the
// FV formula. Interpolates through the embedded percentile distribution at
// the player's exact age. Returns 0..1.
//
// Tail handling: below p10 saturates to (devValue / p10) × 0.10; above p95
// saturates toward 1.0 over the (p10 → p95) headroom.
export function devPercentileRank(devCurve, age, devValue) {
  if (!Array.isArray(devCurve) || devCurve.length === 0) return null;
  if (age == null || devValue == null) return null;

  const PCT_KEYS = ['p10', 'p25', 'p50', 'p75', 'p90', 'p95', 'p99'];
  const ageRow = {};
  if (age <= devCurve[0].age) {
    PCT_KEYS.forEach(k => { ageRow[k] = devCurve[0][k]; });
  } else if (age >= devCurve[devCurve.length - 1].age) {
    PCT_KEYS.forEach(k => { ageRow[k] = devCurve[devCurve.length - 1][k]; });
  } else {
    for (let i = 0; i < devCurve.length - 1; i++) {
      const lo = devCurve[i], hi = devCurve[i + 1];
      if (age >= lo.age && age <= hi.age) {
        const t = hi.age === lo.age ? 0 : (age - lo.age) / (hi.age - lo.age);
        PCT_KEYS.forEach(k => { ageRow[k] = lo[k] * (1 - t) + hi[k] * t; });
        break;
      }
    }
  }

  // v21: p99 included for fuller resolution at the high tail (matches pipeline _PERCENTILE_KEYS).
  const anchors = [
    [0.10, ageRow.p10], [0.25, ageRow.p25], [0.50, ageRow.p50],
    [0.75, ageRow.p75], [0.90, ageRow.p90], [0.95, ageRow.p95], [0.99, ageRow.p99],
  ].filter(([, v]) => v != null);

  if (devValue <= anchors[0][1]) {
    if (!isFinite(anchors[0][1]) || anchors[0][1] === 0) return 0.05;
    return Math.max(0, Math.min(0.10, anchors[0][0] * (devValue / anchors[0][1])));
  }
  const lastVal = anchors[anchors.length - 1][1];
  if (devValue >= lastVal) {
    const headroom = lastVal - anchors[0][1];
    if (headroom <= 0) return 0.95;
    const excess = devValue - lastVal;
    return Math.min(1, 0.95 + 0.05 * (excess / headroom));
  }
  for (let i = 0; i < anchors.length - 1; i++) {
    const [pctLo, valLo] = anchors[i];
    const [pctHi, valHi] = anchors[i + 1];
    if (devValue >= valLo && devValue <= valHi) {
      if (valHi === valLo) return pctLo;
      const t = (devValue - valLo) / (valHi - valLo);
      return pctLo + t * (pctHi - pctLo);
    }
  }
  return null;
}


// Compute v21 FV for a player. Pure (cur, pot, age) inputs — no devPct.
// Inputs are WAR (post-v0.2.0). The math is metric-agnostic — gap and credit
// shape don't care whether the values are WAA or WAR — but the curveSettings
// `gapMax` ceiling is calibrated to the WAR distribution.
export function calcFutureValue(currentWAR, potentialWAR, age, cs = {}) {
  const {
    gapMax = DEV_CURVE_DEFAULTS.gapMax,
    gapExp = DEV_CURVE_DEFAULTS.gapExp,
    maxCurrentAge = DEV_CURVE_DEFAULTS.maxCurrentAge,
  } = cs;
  if (potentialWAR == null) return currentWAR ?? 0;
  if (currentWAR == null) return potentialWAR;
  if (age == null) return potentialWAR;
  if (age >= maxCurrentAge) return currentWAR;
  if (currentWAR > potentialWAR) return currentWAR;        // over-achievers preserved

  const t = clamp((age - 14) / (maxCurrentAge - 14), 0, 1);
  const creditAge = Math.max(0, gapMax * (1 - Math.pow(t, gapExp)));
  const gap = Math.max(0, potentialWAR - currentWAR);
  return currentWAR + gap * creditAge;
}

// Computes the v21 power-law creditAge at a given age. Used by CurveTuningPanel
// chart preview to render the parametric curve.
export function calcCreditAge(age, cs = {}) {
  const {
    gapMax = DEV_CURVE_DEFAULTS.gapMax,
    gapExp = DEV_CURVE_DEFAULTS.gapExp,
    maxCurrentAge = DEV_CURVE_DEFAULTS.maxCurrentAge,
  } = cs;
  if (age == null) return null;
  if (age >= maxCurrentAge) return 0;
  const t = clamp((age - 14) / (maxCurrentAge - 14), 0, 1);
  return Math.max(0, gapMax * (1 - Math.pow(t, gapExp)));
}
