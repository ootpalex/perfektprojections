// node tgs-viz/tests/client/leagueCalib.test.mjs
// A league without its own calibration block uses its manifest basis, not TGS.

import assert from 'node:assert/strict'
import { leagueCalib, setLeagueBases, replacementOffset } from '../../src/lib/leagueCalib.js'

let passed = 0
let failed = 0
function check(name, fn) {
  try { fn(); passed++ } catch (err) { failed++; console.log(`FAIL ${name}: ${err.message}`) }
}

const TGS = leagueCalib('TGS')
const BLM = leagueCalib('BLM')
check('TGS and BLM differ', () => assert.notDeepEqual(TGS, BLM))
check('unknown league, nothing registered: TGS', () => assert.equal(leagueCalib('SSB'), TGS))
setLeagueBases([{ id: 'SSB', basis: 'BLM' }, { id: 'RG', basis: 'BLM' }, { id: 'DEV' }, { id: 'ZZZ', basis: 'NOPE' }])
check('SSB on BLM basis', () => assert.equal(leagueCalib('SSB'), BLM))
check('RG on BLM basis', () => assert.equal(leagueCalib('RG'), BLM))
check('no basis: TGS', () => assert.equal(leagueCalib('DEV'), TGS))
check('unknown basis: TGS', () => assert.equal(leagueCalib('ZZZ'), TGS))
check('own block wins over basis', () => assert.equal(leagueCalib('BLM'), BLM))
check('market offset follows basis', () => assert.equal(replacementOffset('RG', 'hitter'), replacementOffset('BLM', 'hitter')))
check("a league's own replacement level wins over its basis", () => assert.equal(replacementOffset('SSB', 'sp'), 2.63))
setLeagueBases([{ id: 'RG', basis: 'BLM' }])
check('a reload forgets dropped leagues', () => assert.equal(leagueCalib('SSB'), TGS))

console.log(`leagueCalib: ${passed} passed, ${failed} failed`)
process.exit(failed ? 1 : 0)
