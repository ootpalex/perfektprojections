// The /__tgs/ router (DESIGN.md 8.3, 8.5). Every request passes the guards first.

import fs from 'node:fs'
import path from 'node:path'
import crypto from 'node:crypto'
import { checkRequest, checkPostHeaders, jobDirFor, MAX_BODY } from './guards.js'
import { runProcess, readJsonOrNull, statOrNull, lastLines } from './jobs.js'
import { commandsView, readTextOrNull } from './paths.js'
import { logError } from './safe.js'

const STOP_MODES = new Set(['after_step', 'after_cycle', 'kill'])
const LEAGUE_TYPES = new Set(['statsplus', 'local_export', 'dev', 'clone'])
const SECRET_FIELD_NAMES = new Set(['token', 'sessionid', 'csrftoken'])
const MAX_INPUT_BYTES = 4096
const MAX_SECRET_BYTES = 4096

// ---- small response helpers ----

export function sendJson(res, status, body) {
  if (res.headersSent) { try { res.end() } catch { /* ignore */ } return }
  const text = JSON.stringify(body)
  res.writeHead(status, {
    'Content-Type': 'application/json; charset=utf-8',
    'Cache-Control': 'no-store',
    'Content-Length': Buffer.byteLength(text),
  })
  res.end(text)
}

export function sendError(res, status, code, message, extra) {
  sendJson(res, status, { error: { code, message: message || code, ...(extra || {}) } })
}

function readBody(req) {
  return new Promise((resolve) => {
    const chunks = []
    let size = 0
    let tooLarge = false
    req.on('data', (d) => {
      if (tooLarge) return
      size += d.length
      if (size > MAX_BODY) { tooLarge = true; return }
      chunks.push(d)
    })
    req.on('end', () => resolve(tooLarge ? { tooLarge: true } : { text: Buffer.concat(chunks).toString('utf8') }))
    req.on('error', () => resolve({ error: true }))
  })
}

function isPlainObject(v) {
  return v !== null && typeof v === 'object' && !Array.isArray(v)
}

// ---- settings whitelist (8.5) ----

const ALLOWED_KEYS = [
  /^python\.main$/, /^python\.ml$/, /^node$/,
  /^ootp\.installs\.[0-9]{2}\.saved_games$/,
  /^leagues\.[A-Z0-9]{2,8}\.(enabled|name|my_team|my_org|ootp_save|ootp_version)$/,
  /^leagues\.TGS\.dispersal_orgs$/,
]

// Leaf keys of a patch, dotted. A list is a leaf.
export function patchKeys(patch, prefix = '') {
  const out = []
  for (const [k, v] of Object.entries(patch)) {
    const key = prefix ? `${prefix}.${k}` : k
    if (isPlainObject(v) && Object.keys(v).length) out.push(...patchKeys(v, key))
    else out.push(key)
  }
  return out
}

export function keyAllowed(key) {
  return ALLOWED_KEYS.some((re) => re.test(key))
}

function getPath(obj, dotted) {
  let cur = obj
  for (const part of dotted.split('.')) {
    if (!isPlainObject(cur) || !(part in cur)) return undefined
    cur = cur[part]
  }
  return cur
}

function isArgv(v) {
  return Array.isArray(v) && v.length > 0 && v.every((s) => typeof s === 'string' && s.length > 0)
}

// Run a new interpreter argv once (no shell, 15 s) and check its version.
export async function probeInterpreter(kind, argv, cwd) {
  if (!isArgv(argv)) return { ok: false, output: 'The command must be a list of words, for example ["python"].' }
  const isNode = kind === 'node'
  const args = isNode ? ['--version'] : ['-c', 'import sys; print(sys.version_info[0], sys.version_info[1])']
  const res = await runProcess([...argv, ...args], { cwd, timeoutMs: 15000 })
  const output = lastLines(`${res.stdout}\n${res.stderr}`, 10).join('\n') || res.errorMessage || ''
  if (res.error) return { ok: false, output: res.error === 'ENOENT' ? `The command "${argv.join(' ')}" was not found.` : output }
  if (res.code !== 0) return { ok: false, output: output || `Exit code ${res.code}.` }
  if (isNode) {
    const m = /v(\d+)\.(\d+)/.exec(res.stdout)
    if (!m) return { ok: false, output }
    const major = Number(m[1])
    const minor = Number(m[2])
    const good = (major === 20 && minor >= 19) || (major === 22 && minor >= 12) || major >= 23
    return good ? { ok: true, output } : { ok: false, output: `Node.js ${m[1]}.${m[2]} is too old. The app needs 20.19 or newer, or 22.12 or newer.` }
  }
  const m = /^\s*(\d+)\s+(\d+)\s*$/m.exec(res.stdout)
  if (!m) return { ok: false, output }
  if (Number(m[1]) !== 3 || Number(m[2]) < 11) {
    return { ok: false, output: `Python ${m[1]}.${m[2]} is too old. The tasks need Python 3.11 or newer.` }
  }
  return { ok: true, output }
}

function stampNow() {
  const d = new Date()
  const p = (n) => String(n).padStart(2, '0')
  return `${d.getFullYear()}${p(d.getMonth() + 1)}${p(d.getDate())}-${p(d.getHours())}${p(d.getMinutes())}${p(d.getSeconds())}`
}

function tmpFile(paths, label) {
  fs.mkdirSync(paths.tmpDir, { recursive: true })
  return path.join(paths.tmpDir, `${label}-${crypto.randomBytes(6).toString('hex')}.json`)
}

function rmQuiet(file) {
  try { fs.unlinkSync(file) } catch { /* ignore */ }
}

// ---------------------------------------------------------------------------

export function createRouter(ctx) {
  const { paths, jobs } = ctx

  // ---- secrets and inputs checks (8.5 steps 2 and 3) ----

  function checkInputs(task, inputs) {
    const declared = new Map((task.inputs || []).map((i) => [i.name, i]))
    const errors = {}
    for (const [name, value] of Object.entries(inputs)) {
      const decl = declared.get(name)
      if (decl && decl.type === 'secret') {
        return { status: 400, code: 'secret_in_inputs', message: 'Send secret values in "secrets", never in "inputs".', extra: { field: name } }
      }
      const t = typeof value
      if (t !== 'string' && t !== 'number' && t !== 'boolean') errors[name] = 'Must be text, a number or yes/no.'
      else if (Buffer.byteLength(String(value)) >= MAX_INPUT_BYTES) errors[name] = 'Too long.'
    }
    if (Object.keys(errors).length) {
      return { status: 400, code: 'invalid_input', message: 'Some inputs are not valid.', extra: { errors, fix_task: null } }
    }
    return null
  }

  function checkSecrets(task, secrets) {
    const declared = new Map()
    for (const i of task.inputs || []) if (i && i.type === 'secret') declared.set(String(i.name).toLowerCase(), i.name)
    const pairs = []
    for (const [key, value] of Object.entries(secrets)) {
      const name = declared.get(String(key).toLowerCase())
      const bad = (message) => ({ status: 400, code: 'bad_secret', message, extra: { field: key } })
      if (!name) return bad(`This task has no secret named ${key}.`)
      if (typeof value !== 'string') return bad('A secret value must be text.')
      if (Buffer.byteLength(value) > MAX_SECRET_BYTES) return bad('The secret value is too long.')
      if (/[\0\r\n]/.test(value)) return bad('The secret value must be one line.')
      const trimmed = value.trim()
      if (trimmed && (trimmed.length < 8 || trimmed.length > MAX_SECRET_BYTES)) return bad('The secret value must have at least 8 characters, or be blank.')
      pairs.push([name, value])
    }
    return { pairs }
  }

  // ---- route handlers ----

  async function ping(req, res, query) {
    // ?probe=1 (token needed): run the Python probe again, for the Setup page's Check again.
    if (query && query.probe === '1' && ctx.reprobe) await ctx.reprobe()
    const body = {
      ok: true, api: 1, control: { on: true },
      python: jobs.getPython(),
      live_refresh: ctx.liveRefresh(),
    }
    if (ctx.selftest) body.debug = ctx.debug()
    sendJson(res, 200, body)
  }

  async function catalogRoute(req, res, query) {
    const r = await jobs.getCatalog({ refresh: query.refresh === '1' })
    if (r.error) return sendError(res, r.error.status || 503, r.error.code || 'python_failed', r.error.message, r.error.stderr_tail ? { stderr_tail: r.error.stderr_tail } : undefined)
    sendJson(res, 200, r.data)
  }

  async function configRoute(req, res) {
    const r = await jobs.getCatalog()
    if (r.error) return sendError(res, r.error.status || 503, r.error.code || 'python_failed', r.error.message)
    sendJson(res, 200, r.data.app_config || {})
  }

  async function postJob(req, res, body) {
    if (!isPlainObject(body) || typeof body.task !== 'string' || !body.task) {
      return sendError(res, 404, 'unknown_task', 'No task was named.')
    }
    const inputs = body.inputs === undefined || body.inputs === null ? {} : body.inputs
    const secrets = body.secrets === undefined || body.secrets === null ? {} : body.secrets
    if (!isPlainObject(inputs)) return sendError(res, 400, 'invalid_input', 'The inputs must be an object.', { errors: {}, fix_task: null })
    if (!isPlainObject(secrets)) return sendError(res, 400, 'bad_secret', 'The secrets must be an object.', { field: null })

    const cat = await jobs.getCatalog()
    if (cat.error) return sendError(res, 500, 'python_failed', cat.error.message)
    const task = jobs.findTask(body.task)
    if (!task || (body.task.startsWith('selftest.') && !ctx.selftest)) {
      return sendError(res, 404, 'unknown_task', `There is no task named ${body.task}.`)
    }
    const badInputs = checkInputs(task, inputs)
    if (badInputs) return sendError(res, badInputs.status, badInputs.code, badInputs.message, badInputs.extra)
    const sec = checkSecrets(task, secrets)
    if (sec.status) return sendError(res, sec.status, sec.code, sec.message, sec.extra)

    const out = await jobs.startJob(task, inputs, sec.pairs)
    sendJson(res, out.status, out.body)
  }

  function jobExists(id) {
    const dir = jobDirFor(paths.jobsDir, id)
    return dir && statOrNull(dir) ? dir : null
  }

  async function getJob(req, res, id) {
    const view = jobs.jobView(id)
    if (!view) return sendError(res, 404, 'no_job', 'There is no such job.')
    sendJson(res, 200, { job: view })
  }

  async function events(req, res, id, query) {
    jobs.openStream(id, req, res, query)
  }

  async function log(req, res, id, query) {
    const dir = jobExists(id)
    const state = readJsonOrNull(path.join(dir, 'state.json'))
    if (state && state.mode === 'console') return sendError(res, 404, 'no_log', 'A console job has no log file. Its output is in its window.')
    const from = Math.max(0, Math.floor(Number(query.from) || 0))
    let max = Math.floor(Number(query.max) || 262144)
    if (max < 1) max = 262144
    max = Math.min(max, 4 * 1024 * 1024)
    const r = jobs.readLog(id, from, max)
    const text = r ? r.text : ''
    const next = r ? r.next : from
    res.writeHead(200, {
      'Content-Type': 'text/plain; charset=utf-8',
      'Cache-Control': 'no-store',
      'X-TGS-Next-Offset': String(next),
    })
    res.end(text)
  }

  async function answer(req, res, id, body) {
    if (!isPlainObject(body)) return sendError(res, 400, 'bad_value', 'Send {prompt_id, value}.')
    const prompt = jobs.readPrompt(id)
    // A prompt file left by a job that already ended is not a question any more.
    if (!prompt || !jobs.isRunning(id).running) return sendError(res, 409, 'no_prompt', 'This job is not waiting for an answer.')
    if (prompt.prompt_id !== body.prompt_id) return sendError(res, 409, 'prompt_mismatch', 'This question was already answered or replaced.')
    const choices = Array.isArray(prompt.choices) ? prompt.choices.map((c) => c && c.id) : []
    if (typeof body.value !== 'string' || !choices.includes(body.value)) {
      return sendError(res, 400, 'bad_value', 'That answer is not one of the choices.')
    }
    jobs.writeAnswer(id, body.prompt_id, body.value)
    sendJson(res, 200, { ok: true })
  }

  async function stop(req, res, id, body) {
    const mode = isPlainObject(body) ? body.mode : undefined
    if (typeof mode !== 'string' || !STOP_MODES.has(mode)) return sendError(res, 400, 'bad_mode', 'Unknown stop mode.')
    const { running, state } = jobs.isRunning(id)
    if (!running) return sendError(res, 409, 'not_running', 'This job is not running.')
    const dir = jobDirFor(paths.jobsDir, id)
    const reqJson = readJsonOrNull(path.join(dir, 'request.json')) || {}
    const taskId = (state && state.task) || reqJson.task
    const task = taskId ? jobs.findTask(taskId) : null
    const modes = task && Array.isArray(task.stop_modes) ? task.stop_modes : ['after_step', 'kill']
    if (!modes.includes(mode)) return sendError(res, 400, 'bad_mode', 'This task cannot stop that way.')
    jobs.requestStop(id, mode)
    sendJson(res, 202, { ok: true })
  }

  async function doctor(req, res) {
    const r = await jobs.callPythonJson([paths.doctorPy, '--json'], { timeoutMs: 60000 })
    if (!r.ok) {
      if (r.res && r.res.problem && r.res.problem.code === 'TIMEOUT') return sendError(res, 504, 'timeout', 'The setup check took longer than 60 seconds.')
      return sendError(res, 503, 'python_failed', r.error.message, r.error.stderr_tail ? { stderr_tail: r.error.stderr_tail } : undefined)
    }
    sendJson(res, 200, r.data)
  }

  async function getSettings(req, res) {
    const r = await jobs.callPythonJson([paths.settingsPy, '--json'], { timeoutMs: 60000 })
    const localPath = paths.localSettingsPath()
    if (!r.ok && r.res && r.res.problem) {
      // Python does not start: show the commands from the files, so the page can fix Python (10.5).
      return sendJson(res, 200, {
        merged: commandsView(readTextOrNull(paths.defaultsPath), readTextOrNull(localPath)),
        local: null,
        python_failed: r.error.message,
        paths: { defaults: paths.defaultsPath, local: localPath },
      })
    }
    if (!r.ok) {
      const tail = r.res ? lastLines(r.res.stderr, 5) : []
      return sendError(res, 503, 'python_failed', tail.length ? tail[tail.length - 1] : r.error.message, { stderr_tail: tail })
    }
    let local = null
    let localError = null
    let text = null
    try { text = fs.readFileSync(localPath, 'utf8') } catch { text = null }
    if (text !== null) {
      try { local = JSON.parse(text.replace(/^﻿/, '')) } catch (err) { localError = String(err.message) }
    }
    sendJson(res, 200, {
      merged: r.data.merged || r.data,
      local,
      ...(localError ? { local_error: localError } : {}),
      paths: { defaults: paths.defaultsPath, local: localPath },
    })
  }

  async function postSettings(req, res, body) {
    const patch = isPlainObject(body) ? body.patch : undefined
    if (!isPlainObject(patch) || !Object.keys(patch).length) return sendError(res, 400, 'invalid', 'Send {patch: {...}}.', { errors: ['The patch is empty.'] })
    for (const key of patchKeys(patch)) {
      if (!keyAllowed(key)) return sendError(res, 403, 'key_not_allowed', `The Setup page cannot change ${key}.`, { key })
    }
    if (jobs.activeCount() > 0) return sendError(res, 409, 'busy', 'A task is running. Change settings after it ends.')

    for (const [key, kind] of [['python.main', 'python'], ['python.ml', 'python'], ['node', 'node']]) {
      const argv = getPath(patch, key)
      if (argv === undefined) continue
      const probe = await probeInterpreter(kind, argv, paths.repo)
      if (!probe.ok) return sendError(res, 400, 'bad_interpreter', `This command does not work: ${Array.isArray(argv) ? argv.join(' ') : String(argv)}`, { argv, output: probe.output })
    }

    const newMain = getPath(patch, 'python.main')
    const file = tmpFile(paths, 'settings-patch')
    let r
    try {
      fs.writeFileSync(file, JSON.stringify(patch, null, 2), 'utf8')
      r = await jobs.callPythonJson([paths.settingsPy, 'set', '--patch-file', file], {
        timeoutMs: 60000, argv: isArgv(newMain) ? newMain : undefined,
      })
    } finally {
      rmQuiet(file)
    }
    if (!r.ok) return sendError(res, 503, 'python_failed', r.error.message, r.error.stderr_tail ? { stderr_tail: r.error.stderr_tail } : undefined)
    if (!r.data || r.data.ok !== true) {
      return sendError(res, 400, 'invalid', 'The settings were not saved.', { errors: (r.data && r.data.errors) || [] })
    }
    await ctx.afterSettingsChange()
    sendJson(res, 200, { ok: true, merged: r.data.merged })
  }

  async function resetLocal(req, res) {
    if (jobs.activeCount() > 0) return sendError(res, 409, 'busy', 'A task is running. Reset the settings after it ends.')
    const local = paths.localSettingsPath()
    if (!statOrNull(local)) return sendError(res, 404, 'no_local_file', 'There is no local settings file.')
    const target = path.join(path.dirname(local), `settings.local.bad-${stampNow()}.json`)
    fs.renameSync(local, target)
    await ctx.afterSettingsChange()
    sendJson(res, 200, { ok: true, renamed_to: target })
  }

  async function nlOptions(req, res, query) {
    const type = query.type
    const version = query.version
    if (typeof type !== 'string' || !LEAGUE_TYPES.has(type)) return sendError(res, 400, 'bad_query', 'Unknown league type.')
    if (version !== undefined && (typeof version !== 'string' || !/^\d{2}$/.test(version))) {
      return sendError(res, 400, 'bad_query', 'The OOTP version must be two digits.')
    }
    const args = [paths.newLeaguePy, 'options', '--type', type]
    if (version !== undefined) args.push('--version', version)
    args.push('--json')
    const r = await jobs.callPythonJson(args, { timeoutMs: 60000 })
    if (!r.ok) return sendError(res, 503, 'python_failed', r.error.message, r.error.stderr_tail ? { stderr_tail: r.error.stderr_tail } : undefined)
    sendJson(res, 200, r.data)
  }

  async function nlValidate(req, res, body) {
    if (!isPlainObject(body) || typeof body.type !== 'string' || !LEAGUE_TYPES.has(body.type)) {
      return sendError(res, 400, 'bad_query', 'Unknown league type.')
    }
    const fields = body.fields === undefined ? {} : body.fields
    if (!isPlainObject(fields)) return sendError(res, 400, 'bad_query', 'The fields must be an object.')
    for (const key of Object.keys(fields)) {
      if (SECRET_FIELD_NAMES.has(key.toLowerCase())) {
        return sendError(res, 400, 'secret_in_inputs', 'Never send the token to the check.', { field: key })
      }
    }
    const file = tmpFile(paths, 'new-league-spec')
    let r
    try {
      fs.writeFileSync(file, JSON.stringify({ ...fields, type: body.type }, null, 2), 'utf8')
      r = await jobs.callPythonJson([paths.newLeaguePy, 'check', '--spec', file, '--json'], { timeoutMs: 60000 })
    } finally {
      rmQuiet(file)
    }
    if (!r.ok) return sendError(res, 503, 'python_failed', r.error.message, r.error.stderr_tail ? { stderr_tail: r.error.stderr_tail } : undefined)
    sendJson(res, 200, r.data)
  }

  // ---- dispatch ----

  async function dispatch(req, res) {
    let url
    try { url = new URL(req.url || '/', 'http://localhost') } catch { return sendError(res, 404, 'not_found', 'Unknown address.') }
    const pathname = url.pathname.replace(/\/+$/, '') || '/'
    const query = Object.fromEntries(url.searchParams.entries())
    const method = req.method || 'GET'
    const parts = pathname.split('/').slice(1)
    let id = null
    if (parts[0] === 'jobs' && parts.length >= 2 && parts[1] !== 'active') {
      try { id = decodeURIComponent(parts[1]) } catch { id = '\u0000' }
    }
    const isEvents = id !== null && parts.length === 3 && parts[2] === 'events'

    const g = checkRequest({
      remoteAddress: req.socket && req.socket.remoteAddress,
      localPort: req.socket && req.socket.localPort,
      headers: req.headers,
      query,
    }, { token: ctx.token(), needToken: pathname !== '/ping' || query.probe !== undefined, tokenInQuery: isEvents })
    if (g) return sendError(res, g.status, g.code, g.message)

    let body
    if (method === 'POST') {
      const h = checkPostHeaders(req.headers)
      if (h) return sendError(res, h.status, h.code, h.message)
      const raw = await readBody(req)
      if (raw.tooLarge) return sendError(res, 413, 'too_large', 'The request is too large.')
      if (raw.error) return sendError(res, 400, 'bad_json', 'The request body could not be read.')
      try { body = raw.text ? JSON.parse(raw.text) : {} } catch { return sendError(res, 400, 'bad_json', 'The request body is not valid JSON.') }
    } else if (method !== 'GET' && method !== 'HEAD') {
      return sendError(res, 405, 'bad_method', 'This method is not allowed.')
    }

    const is = (m, p) => method === m && pathname === p
    if (is('GET', '/ping')) return ping(req, res, query)
    if (is('GET', '/catalog')) return catalogRoute(req, res, query)
    if (is('GET', '/config')) return configRoute(req, res)
    if (is('GET', '/jobs/active')) return sendJson(res, 200, { jobs: jobs.listActive() })
    if (is('GET', '/jobs')) {
      let limit = Math.floor(Number(query.limit) || 20)
      limit = Math.min(100, Math.max(1, limit))
      return sendJson(res, 200, { jobs: jobs.listJobs(limit) })
    }
    if (is('POST', '/jobs')) return postJob(req, res, body)
    if (is('GET', '/doctor')) return doctor(req, res)
    if (is('GET', '/settings')) return getSettings(req, res)
    if (is('POST', '/settings')) return postSettings(req, res, body)
    if (is('POST', '/settings/reset-local')) return resetLocal(req, res)
    if (is('GET', '/new-league/options')) return nlOptions(req, res, query)
    if (is('POST', '/new-league/validate')) return nlValidate(req, res, body)

    if (id !== null) {
      if (!jobExists(id)) return sendError(res, 404, 'no_job', 'There is no such job.')
      const sub = parts.length === 3 ? parts[2] : null
      if (parts.length === 2 && method === 'GET') return getJob(req, res, id)
      if (sub === 'events' && method === 'GET') return events(req, res, id, query)
      if (sub === 'log' && method === 'GET') return log(req, res, id, query)
      if (sub === 'answer' && method === 'POST') return answer(req, res, id, body)
      if (sub === 'stop' && method === 'POST') return stop(req, res, id, body)
    }
    return sendError(res, 404, 'not_found', 'Unknown address.')
  }

  // Connect middleware. A failing request answers 500; Control stays on (8.10).
  return function handle(req, res) {
    Promise.resolve()
      .then(() => dispatch(req, res))
      .catch((err) => {
        logError('request', err)
        try {
          if (!res.headersSent) sendJson(res, 500, { error: { code: 'internal', message: 'The Control panel hit an error. See the app window.' } })
          else res.end()
        } catch { /* ignore */ }
      })
  }
}

