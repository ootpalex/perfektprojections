// node tgs-viz/tests/client/leagueCalibSync.test.mjs
// The app cannot read engine/calib at runtime, so src/lib/leagueCalib.js mirrors the fitted
// values. This fails when a refit (currency_fit.py) or a replacement re-measurement changes
// the engine's files and the mirror was not updated.

import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { leagueCalib, replacementOffset, LEAGUE_REPLACEMENT_MARKET } from '../../src/lib/leagueCalib.js'

const here = path.dirname(fileURLToPath(import.meta.url))
const calib = path.resolve(here, '..', '..', 'engine', 'calib')
const read = (p) => JSON.parse(fs.readFileSync(p, 'utf8'))

let passed = 0
let failed = 0
function check(name, fn) {
  try { fn(); passed++ } catch (err) { failed++; console.log(`FAIL ${name}: ${err.message}`) }
}

const repl = read(path.join(calib, 'replacement.json'))
for (const lg of ['TGS', 'BLM']) {
  const cur = read(path.join(calib, lg, 'currency.json'))
  const app = leagueCalib(lg)
  check(`${lg} rpw`, () => assert.equal(app.rpw, cur.rpw))
  check(`${lg} luckSD`, () => assert.equal(app.luckSD, cur.luck_sd_wins))
  check(`${lg} spWorkload`, () => assert.equal(app.spWorkload, cur.sp_workload))
  check(`${lg} rpWorkload`, () => assert.equal(app.rpWorkload, cur.rp_workload))
  for (const [role, key] of [['hitter', 'hitter'], ['sp', 'sp'], ['rp', 'rp']]) {
    check(`${lg} replacementMarket.${role}`, () => assert.equal(app.replacementMarket[role], repl[lg][key]))
  }
}

// Leagues with their own measured replacement level (no calibration of their own).
for (const lg of Object.keys(LEAGUE_REPLACEMENT_MARKET)) {
  for (const role of ['hitter', 'sp', 'rp']) {
    check(`${lg} replacementOffset.${role}`, () => assert.equal(replacementOffset(lg, role), repl[lg][role]))
  }
}
check('SSB has its own replacement entry', () => assert.ok(LEAGUE_REPLACEMENT_MARKET.SSB && !repl.SSB.use))

console.log(`leagueCalibSync: ${passed} passed, ${failed} failed`)
process.exit(failed ? 1 : 0)
