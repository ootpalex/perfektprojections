/**
 * Measured league development curve (engine/agecurve_fit.py output).
 *
 * age_curve.json holds per-age dWAA/yr and gap-closure rates measured from the
 * league's own ratings archive (two engine passes over the earliest and latest
 * vintages). LEAGUE-WIDE numbers only — nothing player-specific feeds back into
 * any projection; the app uses it to draw a "measured" development trajectory
 * next to the model's assumed logistic. A league with no clean archive window
 * (e.g. one straddling a scout recalibration) simply has no file.
 */

const cache = new Map();

export async function loadAgeCurve(league) {
  if (cache.has(league)) return cache.get(league);
  let curve = null;
  try {
    const res = await fetch(`/data/${league}/age_curve.json`);
    const ct = res.headers.get('content-type') || '';
    if (res.ok && !ct.includes('text/html')) curve = await res.json();
  } catch { /* absent -> feature hidden */ }
  cache.set(league, curve);
  return curve;
}

/**
 * Project a player's WAA from his age to 25 using the MEASURED per-age rates.
 * Gap-closure form when he has a real ceiling gap (each year closes the
 * measured share of whatever gap remains); flat measured drift otherwise.
 * Returns [{age, waa}] starting at his current age, or null when unusable.
 */
export function measuredTrajectory(ageCurve, age, currentWAA, ceilingWAA) {
  if (!ageCurve || !ageCurve.curve) return null;
  const a0 = Math.floor(age);
  if (!isFinite(a0) || !isFinite(currentWAA) || a0 >= 25) return null;
  let waa = currentWAA;
  const out = [{ age: a0, waa: Math.round(waa * 100) / 100 }];
  for (let a = a0; a < 25; a++) {
    const c = ageCurve.curve[a] || ageCurve.curve[String(a)];
    if (!c) { out.push({ age: a + 1, waa: Math.round(waa * 100) / 100 }); continue; }
    const gap = isFinite(ceilingWAA) ? ceilingWAA - waa : null;
    if (c.closure !== null && c.closure !== undefined && gap !== null && gap > 0) {
      waa += c.closure * gap;
    } else {
      waa += c.trim ?? c.mean ?? 0;
    }
    if (isFinite(ceilingWAA) && waa > ceilingWAA) waa = ceilingWAA;
    out.push({ age: a + 1, waa: Math.round(waa * 100) / 100 });
  }
  return out;
}
