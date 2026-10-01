// node tgs-viz/control/test/restart.smoke.mjs 3101
// DESIGN.md 15.2 step 7. Starts its own Vite on the port (the port must be free), starts
// selftest.long, touches vite.config.js (mtime only), checks the job survives the restart,
// then stops the Vite process itself, checks again, starts Vite again and checks again.

import fs from 'node:fs'
import path from 'node:path'
import {
  TGS_VIZ, REPO, reporter, sleep, waitFor, connectWs, tgsToken, api, openSse, waitStatus,
  testEnv, startVite, stopVite, fileMtime, stripAnsi,
} from './smokeLib.mjs'

const port = Number(process.argv[2] || 3101)
const R = reporter('restart.smoke')
const env = testEnv()
const controlDir = path.resolve(env.TGS_CONTROL_DIR)
const configFile = path.join(TGS_VIZ, 'vite.config.js')

async function portFree() {
  try { await fetch(`http://localhost:${port}/`); return false } catch { return true }
}

async function connect() {
  const conn = await connectWs(port)
  const tok = await tgsToken(conn)
  return { conn, tok, A: api(port, tok.token) }
}

async function heartbeatMoves(id, timeoutMs = 13000) {
  const hb = path.join(controlDir, 'jobs', id, 'heartbeat')
  const t0 = fileMtime(hb)
  const moved = await waitFor(() => {
    const t = fileMtime(hb)
    return t !== null && t0 !== null && t > t0
  }, timeoutMs, 250)
  return !!moved
}

function stateOnDisk(id) {
  try { return JSON.parse(fs.readFileSync(path.join(controlDir, 'jobs', id, 'state.json'), 'utf8')) } catch { return null }
}

async function main() {
  if (!(await portFree())) throw new Error(`port ${port} is in use; stop that server first`)
  let v = await startVite(port, env)
  let { conn, tok, A } = await connect()
  let jobId = null
  let v2 = null
  try {
    let r = await A.post('/jobs', { task: 'selftest.long' })
    R.ok('selftest.long starts', r.status === 201, r.json)
    jobId = r.json.job.id

    // Follow the stream until the first step started, and keep its cursor.
    let sse = openSse(port, tok.token, jobId)
    await waitFor(() => sse.find('step', (e) => e.json.type === 'step_start'), 10000)
    await sleep(800)
    sse.close()
    const lastId = sse.state.lastId
    const lastSeq = Number(/^e(\d+)-/.exec(lastId)[1])
    R.ok('stream gave a cursor', /^e\d+-l\d+$/.test(lastId || ''), lastId)

    // ---- 1. restart through a config touch ----
    const mark = v.out.text.length
    const now = new Date()
    fs.utimesSync(configFile, now, now)
    const restarted = await waitFor(() => stripAnsi(v.out.text.slice(mark)).includes('server restarted'), 30000, 200)
    R.ok('Vite restarted after the vite.config.js touch', !!restarted, stripAnsi(v.out.text.slice(mark)))
    conn.close()
    ;({ conn, tok, A } = await connect())
    r = await A.get('/ping')
    R.ok('one live instance after the restart', r.json && r.json.debug && r.json.debug.instances_alive === 1, r.json && r.json.debug)
    r = await A.get('/jobs/active')
    R.ok('jobs/active returns the job after the restart', r.json && r.json.jobs.some((j) => j.id === jobId && j.status === 'running'), r.json)
    R.ok('heartbeat moves after the restart', await heartbeatMoves(jobId))
    sse = openSse(port, tok.token, jobId, { lastEventId: lastId })
    const next = await waitFor(() => sse.find('step', (e) => e.json.type === 'step_start' && e.json.seq > lastSeq), 25000)
    R.ok('SSE resumes from the last cursor with new events only', !!next && !sse.events.some((e) => e.event === 'step' && e.json.seq <= lastSeq), sse.events.map((e) => `${e.event}:${e.id}`))
    R.ok('SSE hello repeats the cursor', sse.events[0] && sse.events[0].event === 'hello' && sse.events[0].json.cursor === lastId, sse.events[0])
    sse.close()

    // ---- 2. the Vite process itself stops ----
    conn.close()
    await stopVite(v)
    R.ok('Vite process stopped', v.exited.code !== undefined)
    R.ok('job still runs without Vite (heartbeat moves)', await heartbeatMoves(jobId))
    const st = stateOnDisk(jobId)
    R.ok('job state still running', st && st.status === 'running', st && st.status)

    // ---- 3. Vite starts again and re-adopts the job ----
    v2 = await startVite(port, env)
    ;({ conn, tok, A } = await connect())
    r = await A.get('/ping')
    R.ok('one live instance after the new start', r.json && r.json.debug && r.json.debug.instances_alive === 1, r.json && r.json.debug)
    r = await A.get('/jobs/active')
    R.ok('jobs/active returns the job after the new start', r.json && r.json.jobs.some((j) => j.id === jobId && j.status === 'running'), r.json)
    R.ok('heartbeat moves after the new start', await heartbeatMoves(jobId))
    const since = Date.now()
    sse = openSse(port, tok.token, jobId)
    const st2 = await waitFor(() => sse.find('state'), 5000)
    R.ok('SSE works after the new start', !!st2 && st2.json.status === 'running', st2 && st2.json.status)
    sse.close()
    r = await A.post(`/jobs/${jobId}/stop`, { mode: 'kill' })
    R.ok('stop kill after the new start', r.status === 202, r.json)
    const end = await waitStatus(A, jobId, ['killed', 'stopped', 'failed', 'done'], 20000)
    R.ok('job ends killed', end && end.status === 'killed', end && end.status)
    const jobMsgs = await waitFor(() => conn.custom('tgs:job', since).find((m) => m.data.id === jobId && m.data.status === 'killed'), 5000)
    R.ok('tgs:job reports the final state', !!jobMsgs)
    jobId = null
    const out = stripAnsi(v.out.text + (v2 ? v2.out.text : ''))
    const errLines = out.split('\n').filter((l) => l.includes('[tgs-control]'))
    R.ok('no [tgs-control] error lines', errLines.length === 0, errLines)
    R.ok('no page reload lines', !/page reload/.test(out), out.split('\n').filter((l) => /page reload/.test(l)))
  } finally {
    if (jobId) {
      try { await A.post(`/jobs/${jobId}/stop`, { mode: 'kill' }); await sleep(2000) } catch { /* ignore */ }
    }
    try { conn.close() } catch { /* ignore */ }
    await stopVite(v)
    await stopVite(v2)
  }
}

main().then(() => process.exit(R.done() ? 1 : 0)).catch((err) => {
  console.log(`FAIL restart.smoke crashed: ${err && err.stack}`)
  R.done()
  process.exit(1)
})
