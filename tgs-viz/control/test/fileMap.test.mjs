// node tgs-viz/control/test/fileMap.test.mjs
// Every row of DESIGN.md 9.2, both separators, ignored files.

import assert from 'node:assert/strict'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { mapDataFile, mapPath, relDataPath, claimKey } from '../fileMap.js'

let passed = 0
let failed = 0
function check(name, fn) {
  try { fn(); passed++ } catch (err) { failed++; console.log(`FAIL ${name}: ${err.message}`) }
}

const PLAYER = [
  'hitters', 'pitchers', 'hitters_park', 'pitchers_park', 'hitters_draft', 'pitchers_draft',
  'hitters_draft_park', 'pitchers_draft_park', 'hitters_draft_all', 'pitchers_draft_all',
  'hitters_draft_all_park', 'pitchers_draft_all_park', 'draft_picks', 'iafa', 'r5', 'parks',
  'park_list', 'metadata', 'market_fit', 'dev_signals', 'dev_ml',
]

// Root files
check('leagues.json', () => assert.deepEqual(mapDataFile('leagues.json'), { league: null, key: 'leagues', file: 'leagues.json' }))
check('dev_rating_odds.json', () => assert.deepEqual(mapDataFile('dev_rating_odds.json'), { league: null, key: 'odds', file: 'dev_rating_odds.json' }))

// League files
for (const lg of ['TGS', 'BLM', 'RG', 'XY_1', 'a-b']) {
  check(`${lg} age_curve`, () => assert.deepEqual(mapDataFile(`${lg}/age_curve.json`), { league: lg, key: 'age_curve', file: `${lg}/age_curve.json` }))
  check(`${lg} trends`, () => assert.deepEqual(mapDataFile(`${lg}/rating_trends.json`), { league: lg, key: 'trends', file: `${lg}/rating_trends.json` }))
  check(`${lg} calibration`, () => assert.deepEqual(mapDataFile(`${lg}/calibration.json`), { league: lg, key: 'calibration', file: `${lg}/calibration.json` }))
  check(`${lg} series`, () => assert.deepEqual(mapDataFile(`${lg}/park_lineup_values.json`), { league: lg, key: 'series', file: `${lg}/park_lineup_values.json` }))
  for (const name of PLAYER) {
    check(`${lg} ${name}`, () => assert.deepEqual(mapDataFile(`${lg}/${name}.json`), { league: lg, key: 'players', file: `${lg}/${name}.json` }))
  }
}

// DEV age curve counts for every league
check('DEV age_curve is league null', () => assert.deepEqual(mapDataFile('DEV/age_curve.json'), { league: null, key: 'age_curve', file: 'DEV/age_curve.json' }))
check('DEV rating_trends is DEV', () => assert.deepEqual(mapDataFile('DEV/rating_trends.json'), { league: 'DEV', key: 'trends', file: 'DEV/rating_trends.json' }))

// Ignored
const IGNORED = [
  'BLM - Copy/hitters.json', 'TGS - Copy/rating_trends.json',
  'TGS/hitters.json.bak-20260101-1200', 'TGS/hitters.bak-20260101.json', 'TGS/hitters.json.tmp', 'TGS/hitters.json.1234.tmp',
  'TGS/hitters_engine.json', 'TGS/hitters_export.json', 'TGS/hitters_scurve_preview.json',
  'TGS/hitters_fa.json', 'TGS/pitchers_fa.json', 'dev_odds.json', 'hitters.json', 'pitchers.json',
  'hitters_draft.json', 'metadata.json', 'nul', 'TGS/nul', 'TGS/sub/hitters.json',
  'ABCDEFGHIJKLMNOPQ/hitters.json', 'TGS/notes.txt', 'TGS/hitters.JSON', '', 'TGS',
]
for (const rel of IGNORED) check(`ignored ${rel}`, () => assert.equal(mapDataFile(rel), null))

// Separators and absolute paths
const WIN_ROOT = 'C:\\Users\\x\\TGS-control-wt\\tgs-viz\\public\\data'
check('windows absolute', () => assert.deepEqual(mapPath(`${WIN_ROOT}\\TGS\\r5.json`), { league: 'TGS', key: 'players', file: 'TGS/r5.json' }))
check('windows relative', () => assert.deepEqual(mapDataFile('TGS\\hitters.json'), { league: 'TGS', key: 'players', file: 'TGS/hitters.json' }))
check('posix absolute', () => assert.deepEqual(mapPath('/home/x/tgs-viz/public/data/BLM/calibration.json'), { league: 'BLM', key: 'calibration', file: 'BLM/calibration.json' }))
check('mixed separators', () => assert.deepEqual(mapPath('C:/x/tgs-viz/public\\data/RG\\iafa.json'), { league: 'RG', key: 'players', file: 'RG/iafa.json' }))
check('windows root file', () => assert.deepEqual(mapPath(`${WIN_ROOT}\\leagues.json`), { league: null, key: 'leagues', file: 'leagues.json' }))
check('copy folder absolute', () => assert.equal(mapPath(`${WIN_ROOT}\\BLM - Copy\\hitters.json`), null))
check('outside public/data', () => assert.equal(mapPath('C:\\x\\tgs-viz\\src\\App.jsx'), null))

// With a real public/data folder (path.relative based)
const here = path.dirname(fileURLToPath(import.meta.url))
const publicData = path.resolve(here, '..', '..', 'public', 'data')
check('relDataPath native', () => assert.equal(relDataPath(path.join(publicData, 'TGS', 'r5.json'), publicData), 'TGS/r5.json'))
check('relDataPath outside', () => assert.equal(relDataPath(path.join(publicData, '..', 'index.html'), publicData), null))
check('mapPath with folder', () => assert.deepEqual(mapPath(path.join(publicData, 'DEV', 'age_curve.json'), publicData), { league: null, key: 'age_curve', file: 'DEV/age_curve.json' }))
if (process.platform === 'win32') {
  check('relDataPath forward slashes on Windows', () => assert.equal(relDataPath(publicData.replace(/\\/g, '/') + '/BLM/hitters.json', publicData), 'BLM/hitters.json'))
}

// claim keys
check('claimKey null', () => assert.equal(claimKey(null), '*'))
check('claimKey league', () => assert.equal(claimKey('TGS'), 'TGS'))

console.log(`fileMap: ${passed} passed, ${failed} failed`)
process.exit(failed ? 1 : 0)
