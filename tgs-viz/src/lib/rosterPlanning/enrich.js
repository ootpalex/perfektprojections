// ============================================================================
// enrich.js — the per-player values the planner sorts and shows (ours'
// processData enrich step, the part the Roster Planner reads).
//
//   _war  — current WAR: hitters 'Max WAR wtd'; pitchers the better role
//           (accessors pickPitcherRole, ours' rule).
//   _warP — potential WAR, same source ('MAX WAR P'; SP 'WARP' / RP 'WARP RP').
//   _fv   — ours' v21 FV, calcFutureValue(cur, pot, age) with DEV_CURVE_DEFAULTS
//           (🟡 ours' tuned defaults; his data ships no curve settings).
//   _sp / _rp — role-locked values, so a rotation slot shows SP numbers and a
//           bullpen slot RP numbers (ours' classifyPitchers).
// Leagues whose pull carries no WAR columns get null everywhere; they sort last.
// ============================================================================
import { getId, getAge, isPitcher, getMaxWar, getMaxWarP, getSpWar, getSpWarP, getRpWar, getRpWarP, pickPitcherRole } from "../accessors.js";
import { calcFutureValue, DEV_CURVE_DEFAULTS } from "../fvV21.js";

const fvOf = (war, warP, age) => (war == null && warP == null ? null : calcFutureValue(war, warP, age, DEV_CURVE_DEFAULTS));

export function enrichForPlanner(p) {
  const age = getAge(p);
  const base = { ...p, _uid: getId(p), _age: age };
  if (!isPitcher(p)) {
    const war = getMaxWar(p);
    const warP = getMaxWarP(p);
    return { ...base, _type: "hitter", _war: war, _warP: warP, _fv: fvOf(war, warP, age) };
  }
  const pick = pickPitcherRole(p, null, DEV_CURVE_DEFAULTS);
  const sp = { war: getSpWar(p), warP: getSpWarP(p) };
  const rp = { war: getRpWar(p), warP: getRpWarP(p) };
  return {
    ...base, _type: "pitcher", _role: pick.role,
    _war: pick.war, _warP: pick.warP, _fv: pick.war == null && pick.warP == null ? null : pick.fv,
    _sp: { ...sp, fv: fvOf(sp.war, sp.warP, age) },
    _rp: { ...rp, fv: fvOf(rp.war, rp.warP, age) },
  };
}
