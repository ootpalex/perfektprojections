// node tgs-viz/control/test/failsafe.smoke.mjs [port]
// DESIGN.md 15.2 step 9 (and 16 step 9). Starts Vite five times on the port (default 3101), once per
// broken case, and checks that the app and all four leagues' data still serve.

import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import {
  reporter, testEnv, startVite, stopVite, connectWs, tgsToken, api, stripAnsi,
} from './smokeLib.mjs'

const port = Number(process.argv[2] || 3101)
const R = reporter('failsafe.smoke')
const base = `http://localhost:${port}`
const DATA = ['/data/leagues.json', '/data/TGS/hitters.json', '/data/BLM/pitchers.json', '/data/RG/hitters.json', '/data/DEV/rating_trends.json']

const scratch = fs.mkdtempSync(path.join(os.tmpdir(), 'tgs-failsafe-'))
const badJson = path.join(scratch, 'bad.json')
fs.writeFileSync(badJson, '{bad')
const nopePython = path.join(scratch, 'nope-python.json')
fs.writeFileSync(nopePython, JSON.stringify({ python: { main: ['C:\\nope\\python.exe'] } }))
const missingControl = path.join(scratch, 'no-such-control-dir')

const CASES = [
  { name: 'broken settings.local.json', env: { TGS_SETTINGS_LOCAL: badJson }, controlOn: true },
  { name: 'no control folder', env: { TGS_CONTROL_DIR: missingControl }, controlOn: true, noControlDir: true },
  { name: 'python.main is a missing exe', env: { TGS_SETTINGS_LOCAL: nopePython }, controlOn: true, pythonMissing: true },
  { name: 'plugin.js throws while it loads', env: { TGS_CONTROL_TEST_THROW: 'import' }, controlOn: false, oneLine: true },
  { name: 'throw inside configureServer', env: { TGS_CONTROL_TEST_THROW: 'configure' }, controlOn: false, oneLine: true },
]

async function checkServes(label) {
  for (const p of DATA) {
    try {
      const res = await fetch(base + p)
      const ct = res.headers.get('content-type') || ''
      const text = await res.text()
      let parsed = false
      try { JSON.parse(text); parsed = true } catch { parsed = false }
      R.ok(`${label}: ${p} 200 JSON`, res.status === 200 && ct.includes('json') && parsed, { status: res.status, ct, bytes: text.length })
    } catch (err) {
      R.ok(`${label}: ${p} 200 JSON`, false, String(err))
    }
  }
  const res = await fetch(base + '/')
  const html = await res.text()
  R.ok(`${label}: / serves the app`, res.status === 200 && html.includes('<div id="root">') && html.includes('/src/main.jsx'), res.status)
  const main = await fetch(base + '/src/main.jsx')
  R.ok(`${label}: /src/main.jsx compiles`, main.status === 200, main.status)
}

async function runCase(c) {
  const env = testEnv({ TGS_CONTROL_TEST_THROW: null, ...c.env })
  let v = null
  try {
    v = await startVite(port, env)
    await checkServes(c.name)
    const ping = await (await fetch(`${base}/__tgs/ping`)).json()
    R.ok(`${c.name}: ping control.on is ${c.controlOn}`, ping.control && ping.control.on === c.controlOn, ping)
    if (!c.controlOn) R.ok(`${c.name}: ping gives the reason`, typeof ping.control.reason === 'string' && ping.control.reason.length > 0, ping)
    if (c.controlOn) {
      const conn = await connectWs(port)
      const tok = await tgsToken(conn)
      const A = api(port, tok.token)
      const active = await A.get('/jobs/active')
      R.ok(`${c.name}: jobs/active answers`, active.status === 200 && Array.isArray(active.json.jobs), active.json)
      if (c.pythonMissing) {
        R.ok(`${c.name}: ping says Python is missing`, ping.python && ping.python.ok === false && ping.python.code === 'ENOENT', ping.python)
        const r = await A.post('/jobs', { task: 'selftest.ok' })
        R.ok(`${c.name}: POST a selftest job: 500 python_failed`, r.status === 500 && r.json.error.code === 'python_failed', r.json)
        const st = await A.get('/settings')
        R.ok(`${c.name}: GET settings still gives the commands, from the files`,
          st.status === 200 && !!st.json.python_failed && st.json.merged.python.main[0] === 'C:\\nope\\python.exe', st.json)
        const re = await A.get('/ping?probe=1')
        R.ok(`${c.name}: ping?probe=1 probes again`, re.status === 200 && re.json.python && re.json.python.ok === false, re.json)
        const noTok = await fetch(`${base}/__tgs/ping?probe=1`)
        R.ok(`${c.name}: ping?probe=1 needs the token`, noTok.status === 401, noTok.status)
        await checkServes(`${c.name} (after the POST)`)
      } else {
        const cat = await A.get('/catalog')
        R.ok(`${c.name}: catalog answers`, cat.status === 200, cat.status)
        if (c.env.TGS_SETTINGS_LOCAL === badJson) {
          R.ok(`${c.name}: catalog reports the settings error`, cat.json && cat.json.state && !!cat.json.state.settings_error, cat.json && cat.json.state)
        }
      }
      conn.close()
    }
    const out = stripAnsi(v.out.text)
    const lines = out.split('\n').filter((l) => l.includes('[tgs-control]'))
    R.ok(`${c.name}: at most one [tgs-control] line`, lines.length <= 1 && (!c.oneLine || lines.length === 1), lines)
    if (lines.length) R.info(lines[0].trim())
  } catch (err) {
    R.ok(`${c.name}: server ran`, false, String(err && err.message))
  } finally {
    await stopVite(v)
  }
  if (c.noControlDir) R.ok(`${c.name}: Control made no folder`, !fs.existsSync(missingControl))
}

async function main() {
  for (const c of CASES) await runCase(c)
}

main().then(() => {
  fs.rmSync(scratch, { recursive: true, force: true })
  process.exit(R.done() ? 1 : 0)
}).catch((err) => {
  console.log(`FAIL failsafe.smoke crashed: ${err && err.stack}`)
  R.done()
  process.exit(1)
})
