// node tgs-viz/control/test/api.smoke.mjs 3101
// DESIGN.md 15.2 step 5, against a running test dev server (TGS_SELFTEST=1, own control dir,
// TGS_SETTINGS_LOCAL at a scratch file). Runs only selftest tasks.

import fs from 'node:fs'
import path from 'node:path'
import {
  REPO, TGS_VIZ, reporter, sleep, waitFor, connectWs, tgsToken, api, openSse, jobState, waitStatus,
} from './smokeLib.mjs'

const port = Number(process.argv[2] || 3101)
const R = reporter('api.smoke')
const controlDir = process.env.TGS_CONTROL_DIR ? path.resolve(process.env.TGS_CONTROL_DIR) : path.join(REPO, '.control-b')

async function main() {
  const conn = await connectWs(port)
  const tok = await tgsToken(conn)
  R.ok('ws hello gives tgs:token', typeof tok.token === 'string' && tok.token.length >= 32 && tok.api === 1 && tok.port === port, tok)
  const A = api(port, tok.token)
  const N = api(port, null)

  // ---- guards ----
  let r = await N.get('/catalog')
  R.ok('401 without the token', r.status === 401, r.status)
  r = await A.get('/catalog', { Origin: 'http://localhost:5173' })
  R.ok('403 with Origin http://localhost:5173', r.status === 403, r.status)
  r = await A.get('/catalog', { 'Sec-Fetch-Site': 'cross-site' })
  R.ok('403 with no Origin and Sec-Fetch-Site cross-site', r.status === 403, r.status)
  r = await A.get('/catalog', { Origin: `http://localhost:${port}` })
  R.ok('200 with the exact Origin', r.status === 200, r.status)
  r = await N.get('/ping')
  R.ok('ping needs no token', r.status === 200 && r.json.ok === true && r.json.control.on === true && r.json.api === 1, r.json)
  R.ok('ping reports python and live refresh', r.json && r.json.python && r.json.python.ok === true && r.json.live_refresh === true, r.json)
  R.ok('ping debug with TGS_SELFTEST', r.json && r.json.debug && r.json.debug.instances_alive === 1, r.json && r.json.debug)
  r = await A.post('/jobs', 'task=selftest.ok', { 'Content-Type': 'application/x-www-form-urlencoded' })
  R.ok('415 for a form POST', r.status === 415, r.status)
  r = await A.post('/jobs', '{bad', {})
  R.ok('400 for bad JSON', r.status === 400 && r.json.error.code === 'bad_json', r.json)
  r = await A.post('/jobs', JSON.stringify({ task: 'selftest.ok', pad: 'x'.repeat(70 * 1024) }))
  R.ok('413 for a body over 64 KB', r.status === 413, r.status)

  // ---- read routes ----
  r = await A.get('/catalog')
  const catalog = r.json
  R.ok('catalog', r.status === 200 && Array.isArray(catalog.tasks) && catalog.tasks.length > 0, r.status)
  R.ok('catalog keeps hidden tasks', catalog.tasks.some((t) => t.flags && t.flags.hidden === true))
  R.ok('catalog has selftests', catalog.tasks.some((t) => t.id === 'selftest.ok'))
  r = await A.get('/config')
  R.ok('config', r.status === 200 && r.json && typeof r.json === 'object' && r.json.leagues !== undefined, r.json)
  r = await A.get('/jobs/active')
  R.ok('jobs/active', r.status === 200 && Array.isArray(r.json.jobs), r.json)
  const activeBefore = r.json.jobs.length
  R.ok('no job active at the start', activeBefore === 0, r.json.jobs.map((j) => j.id))

  // ---- selftest.ok with its SSE stream ----
  r = await A.post('/jobs', { task: 'selftest.ok', inputs: {}, secrets: {} })
  R.ok('selftest.ok starts (201)', r.status === 201 && r.json.job && ['running', 'waiting', 'queued', 'done'].includes(r.json.job.status), r.json)
  const okId = r.json.job.id
  let sse = openSse(port, tok.token, okId)
  await waitFor(() => sse.state.closed, 20000)
  const done = sse.find('done')
  R.ok('SSE ends with done', !!done && done.json.status === 'done', done && done.json)
  R.ok('SSE hello first', sse.events[0] && sse.events[0].event === 'hello' && sse.events[0].json.job_id === okId, sse.events[0])
  const okLog = sse.logText()
  R.ok('SSE log keeps UTF-8', okLog.includes('caf\u00e9') && okLog.includes('\u2713') && !okLog.includes('\ufffd'), okLog.slice(0, 300))
  R.ok('SSE log ends the partial line', okLog.includes('partial line ... done'), okLog)
  R.ok('SSE sent the partial line first', sse.events.some((e) => e.event === 'log' && e.json.partial === true))
  R.ok('SSE step events', sse.events.some((e) => e.event === 'step' && e.json.type === 'step_start') && sse.events.some((e) => e.event === 'step' && e.json.type === 'step_end'))
  R.ok('SSE state events', sse.events.some((e) => e.event === 'state'))
  R.ok('SSE ids carry the cursor', sse.events.every((e) => /^e\d+-l\d+$/.test(e.id)), sse.events.map((e) => e.id))
  r = await A.get(`/jobs/${okId}/log?from=0`)
  R.ok('GET log', r.status === 200 && r.text.includes('line 1') && Number(r.headers.get('x-tgs-next-offset')) > 0, r.status)
  // resume: from the cursor of the first log event, only later text comes back
  const firstLog = sse.events.find((e) => e.event === 'log')
  const resumed = openSse(port, tok.token, okId, { lastEventId: firstLog.id })
  await waitFor(() => resumed.state.closed, 10000)
  R.ok('SSE resumes from Last-Event-ID', !resumed.logText().includes('line 1:') && resumed.logText().includes('done'), resumed.logText())

  // ---- selftest.confirm ----
  r = await A.post('/jobs', { task: 'selftest.confirm' })
  R.ok('selftest.confirm starts', r.status === 201, r.json)
  const cfId = r.json.job.id
  const waiting = await waitStatus(A, cfId, 'waiting', 15000)
  R.ok('confirm waits for an answer', !!waiting && waiting.prompt && waiting.prompt.prompt_id, waiting)
  const pid = waiting && waiting.prompt.prompt_id
  r = await A.post(`/jobs/${cfId}/answer`, { prompt_id: 'p999', value: 'yes' })
  R.ok('answer with a wrong prompt id: 409 prompt_mismatch', r.status === 409 && r.json.error.code === 'prompt_mismatch', r.json)
  r = await A.post(`/jobs/${cfId}/answer`, { prompt_id: pid, value: 'maybe' })
  R.ok('answer with a bad value: 400 bad_value', r.status === 400 && r.json.error.code === 'bad_value', r.json)
  r = await A.post(`/jobs/${cfId}/answer`, { prompt_id: pid, value: 'yes' })
  R.ok('answer yes', r.status === 200 && r.json.ok === true, r.json)
  const cfDone = await waitStatus(A, cfId, ['done', 'partial', 'failed'], 15000)
  R.ok('confirm ends done', cfDone && cfDone.status === 'done', cfDone && cfDone.status)
  r = await A.get(`/jobs/${cfId}/log`)
  R.ok('confirm applied', r.text.includes('applied'), r.text)
  r = await A.post(`/jobs/${cfId}/answer`, { prompt_id: pid, value: 'yes' })
  R.ok('answer after the end: 409 no_prompt', r.status === 409 && r.json.error.code === 'no_prompt', r.json)

  // ---- selftest.long, stop after_step ----
  r = await A.post('/jobs', { task: 'selftest.long' })
  R.ok('selftest.long starts', r.status === 201, r.json)
  const l1 = r.json.job.id
  r = await A.post(`/jobs/${l1}/stop`, { mode: 'after_cycle' })
  R.ok('after_cycle on a task without it: 400 bad_mode', r.status === 400 && r.json.error.code === 'bad_mode', r.json)
  r = await A.post(`/jobs/${l1}/stop`, { mode: 'after_step' })
  R.ok('stop after_step: 202', r.status === 202 && r.json.ok === true, r.json)
  const l1End = await waitStatus(A, l1, ['stopped', 'done', 'failed', 'killed'], 40000)
  R.ok('selftest.long stops after the step', l1End && l1End.status === 'stopped' && l1End.steps[0].status === 'ok' && l1End.steps.slice(1).every((s) => s.status === 'skipped'), l1End && { status: l1End.status, steps: l1End.steps.map((s) => s.status) })
  r = await A.post(`/jobs/${l1}/stop`, { mode: 'after_step' })
  R.ok('stop a finished job: 409 not_running', r.status === 409 && r.json.error.code === 'not_running', r.json)

  // ---- selftest.long, kill ----
  r = await A.post('/jobs', { task: 'selftest.long' })
  const l2 = r.json && r.json.job && r.json.job.id
  R.ok('selftest.long starts again', r.status === 201, r.json)
  r = await A.post(`/jobs/${l2}/stop`, { mode: 'kill' })
  R.ok('stop kill: 202', r.status === 202, r.json)
  const l2End = await waitStatus(A, l2, ['killed', 'stopped', 'failed', 'done'], 20000)
  R.ok('selftest.long killed', l2End && l2End.status === 'killed', l2End && l2End.status)

  // ---- locks ----
  r = await A.post('/jobs', { task: 'selftest.long' })
  const lockJob = r.json && r.json.job && r.json.job.id
  R.ok('lock holder starts', r.status === 201 && r.json.job.status === 'running', r.json)
  r = await A.post('/jobs', { task: 'selftest.long' })
  R.ok('second selftest.long: 409 conflict', r.status === 409 && r.json.error.code === 'conflict' && r.json.error.lock === 'task.selftest.long' && r.json.error.job.id === lockJob, r.json)
  r = await A.post('/jobs', { task: 'selftest.ok' })
  const queuedId = r.json && r.json.job && r.json.job.id
  R.ok('selftest.ok while long runs: 201 queued', r.status === 201 && r.json.job.status === 'queued', r.json)
  r = await A.post('/jobs', { task: 'selftest.confirm' })
  R.ok('third data task: 409 queue_full', r.status === 409 && r.json.error.code === 'queue_full', r.json)
  r = await A.post('/jobs', { task: 'doctor' })
  const docId = r.json && r.json.job && r.json.job.id
  R.ok('read-only doctor still starts: 201', r.status === 201, r.json)
  r = await A.get('/jobs/active')
  R.ok('jobs/active lists the running jobs, oldest first', r.json.jobs.length >= 2 && r.json.jobs[0].id === lockJob, r.json.jobs.map((j) => `${j.id} ${j.status}`))
  const tgsJobs = conn.custom('tgs:job')
  R.ok('tgs:job events arrive', tgsJobs.some((e) => e.data.id === lockJob && e.data.status === 'running'), tgsJobs.length)
  await waitStatus(A, docId, ['done', 'partial', 'failed'], 15000)
  await A.post(`/jobs/${lockJob}/stop`, { mode: 'kill' })
  const qDone = await waitStatus(A, queuedId, ['done', 'partial', 'failed', 'stopped'], 30000)
  R.ok('the queued job runs after the holder ends', qDone && qDone.status === 'done', qDone && qDone.status)

  // ---- validation ----
  r = await A.post('/jobs', { task: 'selftest.secret', secrets: { token: '12345' } })
  R.ok('5-character secret: 400 bad_secret', r.status === 400 && r.json.error.code === 'bad_secret' && r.json.error.field === 'token', r.json)
  R.ok('bad_secret never echoes the value', !r.text.includes('12345'), r.text)
  r = await A.post('/jobs', { task: 'selftest.secret', secrets: { other: 'abcdefghijk' } })
  R.ok('undeclared secret name: 400 bad_secret', r.status === 400 && r.json.error.code === 'bad_secret', r.json)
  r = await A.post('/jobs', { task: 'selftest.secret', secrets: { token: 'abcdefgh\nijk' } })
  R.ok('secret with a newline: 400 bad_secret', r.status === 400 && r.json.error.code === 'bad_secret', r.json)
  r = await A.post('/jobs', { task: 'selftest.secret', inputs: { token: 'abcdefghijk' } })
  R.ok('secret sent as an input: 400 secret_in_inputs', r.status === 400 && r.json.error.code === 'secret_in_inputs', r.json)
  r = await A.post('/jobs', { task: 'selftest.ok', inputs: { x: { y: 1 } } })
  R.ok('object input: 400 invalid_input', r.status === 400 && r.json.error.code === 'invalid_input', r.json)
  r = await A.post('/jobs', { task: 'no.such.task' })
  R.ok('unknown task: 404', r.status === 404 && r.json.error.code === 'unknown_task', r.json)
  const SECRET = 'Zq9-secret-value-77'
  r = await A.post('/jobs', { task: 'selftest.secret', secrets: { TOKEN: SECRET } })
  R.ok('secret given (name in other case): 201', r.status === 201, r.json)
  const secId = r.json && r.json.job && r.json.job.id
  await waitStatus(A, secId, ['done', 'partial', 'failed'], 15000)
  r = await A.get(`/jobs/${secId}/log`)
  R.ok('secret reached the step, masked in the log', r.text.includes(`length ${SECRET.length}`) && r.text.includes('****') && !r.text.includes(SECRET), r.text)
  const reqFile = path.join(controlDir, 'jobs', secId, 'request.json')
  if (fs.existsSync(reqFile)) {
    const reqText = fs.readFileSync(reqFile, 'utf8')
    const req = JSON.parse(reqText)
    R.ok('request.json holds no secret, names upper-cased', !reqText.includes(SECRET) && JSON.stringify(req.secret_names) === '["TOKEN"]' && req.by === 'control-page', req)
  } else {
    R.info(`(request.json not readable at ${reqFile}; set TGS_CONTROL_DIR to check it)`)
  }
  r = await A.get('/new-league/options?type=x')
  R.ok('options?type=x: 400 bad_query', r.status === 400 && r.json.error.code === 'bad_query', r.json)
  r = await A.get('/new-league/options?type=dev&version=2a')
  R.ok('options?version=2a: 400 bad_query', r.status === 400 && r.json.error.code === 'bad_query', r.json)
  r = await A.get('/new-league/options?type=dev&version=27')
  R.ok('options with a good query: 200', r.status === 200, r.json)
  r = await A.post('/new-league/validate', { type: 'dev', fields: { token: 'abcdefghijklmnopqrstuvwxyz' } })
  R.ok('validate refuses a token: 400', r.status === 400 && r.json.error.code === 'secret_in_inputs', r.json)
  r = await A.post('/new-league/validate', { type: 'dev', fields: {} })
  R.ok('validate answers the check JSON', r.status === 200 && r.json && 'ok' in r.json, r.json)
  for (const bad of ['..%2F..', '..%5C..', '20261001-x', '20261001-210000-x-zzzz', '20991231-235959-nojob-0000']) {
    r = await A.get(`/jobs/${bad}`)
    R.ok(`/jobs/${bad}: 404`, r.status === 404, r.status)
  }
  r = await A.get(`/jobs/${'..%2F..'}/events?t=${tok.token}`)
  R.ok('/jobs/..%2F../events: 404', r.status === 404, r.status)
  r = await A.get('/jobs?limit=3')
  R.ok('jobs list, newest first, limit', r.status === 200 && r.json.jobs.length === 3 && r.json.jobs[0].id >= r.json.jobs[1].id, r.json.jobs && r.json.jobs.map((j) => j.id))
  r = await A.get('/doctor')
  R.ok('doctor JSON', r.status === 200 && Array.isArray(r.json.checks), r.json)

  // ---- live refresh: selftest.touch gives exactly one tgs:data, league_done ----
  let since = Date.now()
  r = await A.post('/jobs', { task: 'selftest.touch', inputs: { file: 'TGS/r5.json' } })
  R.ok('selftest.touch starts', r.status === 201, r.json)
  const touchId = r.json && r.json.job && r.json.job.id
  await waitStatus(A, touchId, ['done', 'partial', 'failed'], 15000)
  await sleep(4000)
  let data = conn.custom('tgs:data', since)
  R.ok('selftest.touch: exactly one tgs:data {league TGS, keys [players], reason league_done}',
    data.length === 1 && data[0].data.league === 'TGS' && JSON.stringify(data[0].data.keys) === '["players"]' && data[0].data.reason === 'league_done' && data[0].data.files.includes('TGS/r5.json'),
    data.map((d) => d.data))

  // ---- live refresh rule 1 across steps: selftest.leagues claims TGS for steps 1-2 and BLM for 1-3 ----
  since = Date.now()
  r = await A.post('/jobs', { task: 'selftest.leagues' })
  R.ok('selftest.leagues starts', r.status === 201, r.json)
  const lgId = r.json && r.json.job && r.json.job.id
  const lgSse = openSse(port, tok.token, lgId)
  await waitFor(() => lgSse.find('step', (e) => e.json.type === 'step_start'), 5000)
  for (const rel of ['TGS/r5.json', 'BLM/draft_picks.json']) {
    const f = path.join(TGS_VIZ, 'public', 'data', rel)
    fs.writeFileSync(f, fs.readFileSync(f))
  }
  await waitFor(() => lgSse.state.closed, 20000)
  await sleep(3000)
  data = conn.custom('tgs:data', since)
  const tgsEv = data.filter((d) => d.data.league === 'TGS')
  const blmEv = data.filter((d) => d.data.league === 'BLM')
  const stepEnd = (i) => {
    const e = lgSse.find('step', (x) => x.json.type === 'step_end' && x.json.index === i)
    return e ? Date.parse(e.json.at) : null
  }
  R.ok('TGS players flush once, league_done', tgsEv.length === 1 && tgsEv[0].data.reason === 'league_done' && tgsEv[0].data.files.includes('TGS/r5.json'), tgsEv.map((d) => d.data))
  R.ok('BLM players flush once, league_done', blmEv.length === 1 && blmEv[0].data.reason === 'league_done' && blmEv[0].data.files.includes('BLM/draft_picks.json'), blmEv.map((d) => d.data))
  R.ok('BLM waits for its last step (after TGS)', tgsEv.length === 1 && blmEv.length === 1 && blmEv[0].at > tgsEv[0].at, { tgs: tgsEv[0] && tgsEv[0].at, blm: blmEv[0] && blmEv[0].at, stepEnds: [0, 1, 2].map(stepEnd) })

  // ---- live refresh: a write with no job running ----
  const r5 = path.join(TGS_VIZ, 'public', 'data', 'TGS', 'r5.json')
  since = Date.now()
  fs.writeFileSync(r5, fs.readFileSync(r5))
  const got = await waitFor(() => conn.custom('tgs:data', since).find((d) => d.data.league === 'TGS'), 6000)
  R.ok('a write with no job: tgs:data reason watch within 4 s', !!got && got.data.reason === 'watch' && got.at - since <= 4000, got && { ...got.data, ms: got.at - since })

  // ---- settings ----
  r = await A.get('/settings')
  R.ok('GET settings', r.status === 200 && r.json.merged && r.json.paths && r.json.paths.local, r.json)
  const localPath = r.json && r.json.paths && r.json.paths.local
  const before = localPath && fs.existsSync(localPath) ? fs.readFileSync(localPath, 'utf8') : null
  r = await A.post('/settings', { patch: { python: { main: ['C:\\nope\\python.exe'] } } })
  R.ok('python.main C:\\nope\\python.exe: 400 bad_interpreter', r.status === 400 && r.json.error.code === 'bad_interpreter' && Array.isArray(r.json.error.argv), r.json)
  const after = localPath && fs.existsSync(localPath) ? fs.readFileSync(localPath, 'utf8') : null
  R.ok('bad_interpreter saved nothing', before === after)
  r = await A.post('/settings', { patch: { app: { port: 4000 } } })
  R.ok('a key off the whitelist: 403 key_not_allowed', r.status === 403 && r.json.error.code === 'key_not_allowed', r.json)
  const repoLocal = path.join(REPO, 'settings.local.json')
  if (localPath && path.resolve(localPath).toLowerCase() !== repoLocal.toLowerCase()) {
    fs.writeFileSync(localPath, '{"schema": 1}\n')
    r = await A.post('/settings/reset-local', {})
    const renamed = r.json && r.json.renamed_to
    R.ok('reset-local renames the scratch local file', r.status === 200 && renamed && fs.existsSync(renamed) && !fs.existsSync(localPath) && /settings\.local\.bad-\d{8}-\d{6}\.json$/.test(renamed), r.json)
    if (renamed && fs.existsSync(renamed)) fs.unlinkSync(renamed)
    if (before !== null) fs.writeFileSync(localPath, before)
    r = await A.post('/settings/reset-local', {})
    R.ok('reset-local with no file: 404 no_local_file', before !== null || (r.status === 404 && r.json.error.code === 'no_local_file'), r.json)
  } else {
    R.info('reset-local skipped: start the server with TGS_SETTINGS_LOCAL at a scratch file')
  }

  r = await A.get('/jobs/active')
  R.ok('no job left active', r.json.jobs.length === 0, r.json.jobs.map((j) => `${j.id} ${j.status}`))
  conn.close()
}

main().then(() => process.exit(R.done() ? 1 : 0)).catch((err) => {
  console.log(`FAIL api.smoke crashed: ${err && err.stack}`)
  R.done()
  process.exit(1)
})
