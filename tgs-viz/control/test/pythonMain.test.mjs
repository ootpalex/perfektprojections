// node tgs-viz/control/test/pythonMain.test.mjs
// The python.main rule (DESIGN.md 3.2) against the shared cases in fixtures/python_main_cases.json.
// "defaults": null means the committed tgs-viz/tools/settings.defaults.json (or its 3.2 content
// while that file does not exist yet). "local": null means no local file.

import assert from 'node:assert/strict'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { resolvePythonMain, createPaths, pythonMain } from '../paths.js'

const here = path.dirname(fileURLToPath(import.meta.url))
const cases = JSON.parse(fs.readFileSync(path.join(here, 'fixtures', 'python_main_cases.json'), 'utf8'))
const defaultsFile = path.resolve(here, '..', '..', 'tools', 'settings.defaults.json')
const SPEC_DEFAULTS = JSON.stringify({ schema: 1, python: { main: ['python'], ml: ['py', '-3.14'] }, node: ['node'] })
const committedDefaults = fs.existsSync(defaultsFile) ? fs.readFileSync(defaultsFile, 'utf8') : SPEC_DEFAULTS

let passed = 0
let failed = 0
function check(name, fn) {
  try { fn(); passed++ } catch (err) { failed++; console.log(`FAIL ${name}: ${err.message}`) }
}

for (const c of cases) {
  const defaultsText = c.defaults === null ? committedDefaults : JSON.stringify(c.defaults)
  check(`shared: ${c.name}`, () => assert.deepEqual(resolvePythonMain(defaultsText, c.local), c.expect))
}

// Node-only cases (not in the shared file: Python never runs without its defaults file).
check('defaults value used', () => assert.deepEqual(resolvePythonMain(JSON.stringify({ python: { main: ['py', '-3'] } }), null), ['py', '-3']))
check('no files at all', () => assert.deepEqual(resolvePythonMain(null, null), ['python']))
check('broken defaults', () => assert.deepEqual(resolvePythonMain('{bad', null), ['python']))
check('defaults main empty', () => assert.deepEqual(resolvePythonMain(JSON.stringify({ python: { main: [] } }), null), ['python']))
check('local main with an empty word', () => assert.deepEqual(resolvePythonMain(SPEC_DEFAULTS, JSON.stringify({ python: { main: ['py', ''] } })), ['python']))
check('local main with a number', () => assert.deepEqual(resolvePythonMain(SPEC_DEFAULTS, JSON.stringify({ python: { main: ['py', 3] } })), ['python']))
check('local python a list', () => assert.deepEqual(resolvePythonMain(SPEC_DEFAULTS, JSON.stringify({ python: ['x'] })), ['python']))
check('local file is a list', () => assert.deepEqual(resolvePythonMain(SPEC_DEFAULTS, '[1,2]'), ['python']))
check('local with BOM', () => assert.deepEqual(resolvePythonMain(SPEC_DEFAULTS, '\uFEFF{"python": {"main": ["py"]}}'), ['py']))
check('tilde not expanded', () => assert.deepEqual(resolvePythonMain(SPEC_DEFAULTS, JSON.stringify({ python: { main: ['~/py/python'] } })), ['~/py/python']))

// pythonMain() reads TGS_SETTINGS_LOCAL per call.
const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'tgs-pymain-'))
const local = path.join(tmp, 'settings.local.json')
const saved = process.env.TGS_SETTINGS_LOCAL
process.env.TGS_SETTINGS_LOCAL = local
try {
  const paths = createPaths(path.resolve(here, '..', '..'))
  const base = resolvePythonMain(fs.existsSync(defaultsFile) ? fs.readFileSync(defaultsFile, 'utf8') : null, null)
  check('file: missing local', () => assert.deepEqual(pythonMain(paths), base))
  fs.writeFileSync(local, JSON.stringify({ python: { main: ['C:\\nope\\python.exe'] } }))
  check('file: local read', () => assert.deepEqual(pythonMain(paths), ['C:\\nope\\python.exe']))
  fs.writeFileSync(local, '{bad')
  check('file: broken local', () => assert.deepEqual(pythonMain(paths), base))
} finally {
  if (saved === undefined) delete process.env.TGS_SETTINGS_LOCAL
  else process.env.TGS_SETTINGS_LOCAL = saved
  fs.rmSync(tmp, { recursive: true, force: true })
}

console.log(`pythonMain: ${passed} passed, ${failed} failed (${cases.length} shared cases)`)
process.exit(failed ? 1 : 0)
