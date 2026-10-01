// Jobs: catalog cache, spawn, following active jobs, SSE tails, stop and answer writes
// (DESIGN.md 3.4, 7, 8.5 to 8.9). B only writes request.json, answer.json, stop.json and tmp files.
// B never kills a process itself: it calls run_task.py --reap and --kill.

import fs from 'node:fs'
import path from 'node:path'
import crypto from 'node:crypto'
import { spawn } from 'node:child_process'
import { safe, settle } from './safe.js'
import { jobDirFor } from './guards.js'
import { claimKey } from './fileMap.js'
import { pythonMain } from './paths.js'

export const ACTIVE_STATUSES = new Set(['starting', 'queued', 'running', 'waiting'])
export const FINAL_STATUSES = new Set(['done', 'partial', 'failed', 'stopped', 'killed', 'invalid', 'refused', 'lost'])

const STEP_EVENTS = new Set(['step_start', 'step_end', 'cycle_start', 'league_done', 'lock'])
const TICK_MS = 500
const SCAN_MS = 1000
const STALE_HEARTBEAT_MS = 60 * 1000
const REAP_GAP_MS = 5000
const KILL_FALLBACK_MS = 15 * 1000
const PARTIAL_IDLE_MS = 500
const SSE_PING_MS = 15 * 1000
const MAX_READ = 1024 * 1024
const DEFAULT_TAIL = 262144

// ---------------------------------------------------------------------------
// Small file helpers (sync: the files are small, and one tick never interleaves).

function statOrNull(file) {
  try { return fs.statSync(file) } catch { return null }
}

// Windows can refuse a read or rename for a moment while run_task swaps the same file.
const TRANSIENT = new Set(['EPERM', 'EBUSY', 'EACCES'])
const pauseBuf = new Int32Array(new SharedArrayBuffer(4))
function pause(ms) {
  try { Atomics.wait(pauseBuf, 0, 0, ms) } catch { /* ignore */ }
}

function withRetry(fn, tries = 5, ms = 20) {
  for (let i = 0; ; i++) {
    try {
      return fn()
    } catch (err) {
      if (i >= tries - 1 || !err || !TRANSIENT.has(err.code)) throw err
      pause(ms)
    }
  }
}

function readTextOrNull(file) {
  try { return withRetry(() => fs.readFileSync(file, 'utf8')) } catch { return null }
}

function readJsonOrNull(file) {
  const text = readTextOrNull(file)
  if (text === null) return null
  try { return JSON.parse(text.replace(/^﻿/, '')) } catch { return null }
}

// Bytes [from, min(size, from + max)) of a file.
function readRange(file, from, max = MAX_READ) {
  let fd
  try {
    fd = fs.openSync(file, 'r')
    const size = fs.fstatSync(fd).size
    if (from >= size) return { buf: Buffer.alloc(0), size }
    const len = Math.min(size - from, max)
    const buf = Buffer.alloc(len)
    const n = fs.readSync(fd, buf, 0, len, from)
    return { buf: n === len ? buf : buf.subarray(0, n), size }
  } catch {
    return { buf: Buffer.alloc(0), size: -1 }
  } finally {
    if (fd !== undefined) { try { fs.closeSync(fd) } catch { /* ignore */ } }
  }
}

// Write a small JSON file: tmp in the same folder, then rename (7.1).
export function writeJsonAtomic(file, obj) {
  const tmp = `${file}.${process.pid}.${crypto.randomBytes(3).toString('hex')}.tmp`
  fs.writeFileSync(tmp, JSON.stringify(obj, null, 2), 'utf8')
  try {
    withRetry(() => fs.renameSync(tmp, file), 10, 50)
  } catch (err) {
    try { fs.unlinkSync(tmp) } catch { /* ignore */ }
    throw err
  }
}

function lastLines(text, n) {
  if (!text) return []
  const lines = text.replace(/\r\n?/g, '\n').split('\n')
  while (lines.length && lines[lines.length - 1] === '') lines.pop()
  return lines.slice(-n)
}

function tailOfFile(file, n = 20) {
  const st = statOrNull(file)
  if (!st) return []
  const from = Math.max(0, st.size - 64 * 1024)
  const { buf } = readRange(file, from, 64 * 1024)
  return lastLines(buf.toString('utf8'), n)
}

// Event name: the contract lists names without fixing the key, so accept the usual ones.
export function eventType(ev) {
  if (!ev || typeof ev !== 'object') return ''
  return String(ev.type || ev.event || ev.kind || '')
}

// Split new bytes of a JSON-lines file into parsed objects. reader = {offset, carry}.
function readNewJsonLines(file, reader) {
  const out = []
  const { buf, size } = readRange(file, reader.offset)
  if (size >= 0 && size < reader.offset) {
    // The file shrank (should never happen); start over.
    reader.offset = 0
    reader.carry = Buffer.alloc(0)
    return out
  }
  if (!buf.length) return out
  reader.offset += buf.length
  const all = reader.carry.length ? Buffer.concat([reader.carry, buf]) : buf
  let start = 0
  for (let i = 0; i < all.length; i++) {
    if (all[i] !== 0x0a) continue
    const line = all.subarray(start, i).toString('utf8').trim()
    start = i + 1
    if (!line) continue
    try { out.push(JSON.parse(line)) } catch { /* skip a broken line */ }
  }
  reader.carry = Buffer.from(all.subarray(start))
  return out
}

// End index that does not cut a UTF-8 sequence in half.
function utf8SafeEnd(buf) {
  let end = buf.length
  let i = end - 1
  let back = 0
  while (i >= 0 && back < 4 && (buf[i] & 0xc0) === 0x80) { i--; back++ }
  if (i < 0) return end
  const b = buf[i]
  let need = 1
  if (b >= 0xf0) need = 4
  else if (b >= 0xe0) need = 3
  else if (b >= 0xc0) need = 2
  if (end - i < need) end = i
  return end
}

// Index just past the last line end in buf. A CR as the very last byte waits (it may be CR LF).
function completeEnd(buf) {
  for (let i = buf.length - 1; i >= 0; i--) {
    const c = buf[i]
    if (c === 0x0a) return i + 1
    if (c === 0x0d) {
      if (i === buf.length - 1) continue
      return i + 1
    }
  }
  return 0
}

function normalizeText(s) {
  return s.replace(/\r\n/g, '\n').replace(/\r/g, '\n')
}

function parseCursor(text) {
  const m = /^e(\d+)-l(\d+)$/.exec(String(text || ''))
  return m ? { seq: Number(m[1]), off: Number(m[2]) } : null
}

function stamp(d = new Date()) {
  const p = (n) => String(n).padStart(2, '0')
  return `${d.getFullYear()}${p(d.getMonth() + 1)}${p(d.getDate())}-${p(d.getHours())}${p(d.getMinutes())}${p(d.getSeconds())}`
}

export function newJobId(taskId) {
  return `${stamp()}-${taskId}-${crypto.randomBytes(2).toString('hex')}`
}

function pidAlive(pid) {
  const n = Number(pid)
  if (!Number.isInteger(n) || n <= 0) return false
  try {
    process.kill(n, 0)
    return true
  } catch (err) {
    return err && err.code === 'EPERM'
  }
}

// ---------------------------------------------------------------------------
// Child processes (short-lived): no shell, hidden window, error listener, timeout.

export function runProcess(argv, { cwd, env, timeoutMs = 60000, maxBytes = 64 * 1024 * 1024 } = {}) {
  return new Promise((resolve) => {
    let done = false
    let timer = null
    const out = []
    const err = []
    let outLen = 0
    let errLen = 0
    const result = (extra) => ({
      stdout: Buffer.concat(out).toString('utf8'),
      stderr: Buffer.concat(err).toString('utf8'),
      ...extra,
    })
    const finish = (res) => {
      if (done) return
      done = true
      if (timer) clearTimeout(timer)
      resolve(res)
    }
    let child
    try {
      child = spawn(argv[0], argv.slice(1), {
        cwd, env: env || process.env, windowsHide: true, stdio: ['ignore', 'pipe', 'pipe'],
      })
    } catch (e) {
      finish({ stdout: '', stderr: '', code: null, error: (e && e.code) || 'SPAWN', errorMessage: String(e && e.message) })
      return
    }
    timer = setTimeout(() => {
      try { child.kill() } catch { /* ignore */ }
      finish(result({ code: null, error: 'TIMEOUT', errorMessage: 'timed out' }))
    }, timeoutMs)
    child.on('error', (e) => finish(result({ code: null, error: (e && e.code) || 'SPAWN', errorMessage: String(e && e.message) })))
    child.stdout.on('data', (d) => { if (outLen < maxBytes) { out.push(d); outLen += d.length } })
    child.stderr.on('data', (d) => { if (errLen < 1024 * 1024) { err.push(d); errLen += d.length } })
    child.stdout.on('error', () => {})
    child.stderr.on('error', () => {})
    child.on('close', (code) => finish(result({ code, error: null })))
  })
}

const INSTALL_HINT = 'Install Python 3.13 from python.org and tick Add python.exe to PATH.'

// Plain words for a Python start problem. Returns null when Python ran.
export function pythonProblem(res, argv) {
  const cmd = argv.join(' ')
  if (res.error === 'ENOENT') {
    return { code: 'ENOENT', message: `Python did not start: the command "${cmd}" was not found. ${INSTALL_HINT}` }
  }
  if (res.code === 9009) {
    return { code: 9009, message: `Python did not start: "${cmd}" reached only the Microsoft Store shortcut. ${INSTALL_HINT}` }
  }
  if (res.error === 'TIMEOUT') {
    return { code: 'TIMEOUT', message: `Python did not answer in time ("${cmd}").` }
  }
  if (res.error) {
    return { code: res.error, message: `Python did not start ("${cmd}"): ${res.errorMessage || res.error}.` }
  }
  return null
}

// ---------------------------------------------------------------------------

export function createJobs({ paths, clock, broadcast, selftest }) {
  const tracked = new Map()       // job id -> track (active jobs, and jobs this server started)
  const subs = new Set()          // SSE streams
  const pyEnv = () => ({ ...process.env, PYTHONUNBUFFERED: '1', PYTHONIOENCODING: 'utf-8' })
  let watch = null
  let lastScan = 0
  let lastReap = 0
  let ticking = false
  let disposed = false

  let catalog = { data: null, error: null, builtAt: 0, sig: '' }
  let catalogBuild = null
  let python = { ok: null, argv: pythonMain(paths), version: null }

  const py = () => pythonMain(paths)

  function setWatch(w) { watch = w }

  // ---- short-lived Python calls --------------------------------------------

  async function callPython(args, { timeoutMs = 60000, argv } = {}) {
    const base = argv || py()
    const res = await runProcess([...base, ...args], { cwd: paths.repo, env: pyEnv(), timeoutMs })
    const problem = pythonProblem(res, base)
    return { ...res, problem, argv: base }
  }

  async function callPythonJson(args, opts) {
    const res = await callPython(args, opts)
    if (res.problem) return { ok: false, res, error: { status: 503, code: 'python_failed', message: res.problem.message } }
    let data = null
    try {
      const text = res.stdout.trim()
      const start = text.indexOf('{')
      data = JSON.parse(start > 0 ? text.slice(start) : text)
    } catch {
      return {
        ok: false, res,
        error: {
          status: 503, code: 'python_failed',
          message: `The Python tool stopped without an answer (exit code ${res.code}).`,
          stderr_tail: lastLines(res.stderr, 20),
        },
      }
    }
    return { ok: true, res, data }
  }

  async function probePython() {
    const argv = py()
    const res = await runProcess([...argv, '-c', 'import sys; print(sys.version)'], {
      cwd: paths.repo, env: pyEnv(), timeoutMs: 15000,
    })
    const problem = pythonProblem(res, argv)
    let next
    if (problem) next = { ok: false, argv, code: problem.code, message: problem.message }
    else if (res.code !== 0) {
      next = { ok: false, argv, code: res.code, message: `Python stopped with exit code ${res.code}. ${lastLines(res.stderr, 1).join('')}`.trim() }
    } else next = { ok: true, argv, version: res.stdout.trim().split(/\s+/)[0] || res.stdout.trim() }
    const changed = JSON.stringify(next) !== JSON.stringify(python)
    python = next
    return { python, changed }
  }

  // ---- catalog --------------------------------------------------------------

  function watchSig(files) {
    if (!Array.isArray(files)) return ''
    return files.map((f) => {
      const st = statOrNull(String(f))
      return st ? `${st.size}:${st.mtimeMs}` : 'missing'
    }).join('|')
  }

  function buildCatalog(reason) {
    if (catalogBuild) return catalogBuild
    const args = [paths.runTask, '--list-json']
    if (selftest) args.push('--selftest')
    catalogBuild = (async () => {
      try {
        const r = await callPythonJson(args, { timeoutMs: 60000 })
        if (!r.ok) {
          catalog = { ...catalog, error: r.error, builtAt: Date.now() }
          return catalog
        }
        const data = r.data
        catalog = { data, error: null, builtAt: Date.now(), sig: watchSig(data && data.state && data.state.watch_files) }
        if (!disposed) broadcast('tgs:catalog', { at: Date.now(), reason: reason || 'refresh' })
        return catalog
      } finally {
        catalogBuild = null
      }
    })()
    return catalogBuild
  }

  // Returns {data} or {error}. Rebuilds when asked, when nothing is cached, or a watched file changed.
  async function getCatalog({ refresh = false } = {}) {
    if (refresh || !catalog.data || catalog.error) {
      await buildCatalog(refresh ? 'refresh' : 'load')
    } else {
      const sig = watchSig(catalog.data.state && catalog.data.state.watch_files)
      if (sig !== catalog.sig) await buildCatalog('watch_files')
    }
    if (catalog.data && !catalog.error) return { data: catalog.data }
    return { error: catalog.error || { status: 503, code: 'python_failed', message: 'The task list is not available.' } }
  }

  function checkWatchFiles() {
    if (!catalog.data || catalogBuild) return
    const sig = watchSig(catalog.data.state && catalog.data.state.watch_files)
    if (sig !== catalog.sig) settle('catalog rebuild', buildCatalog('watch_files'))
  }

  function findTask(id) {
    const tasks = (catalog.data && catalog.data.tasks) || []
    return tasks.find((t) => t && t.id === id) || null
  }

  // ---- following jobs (8.8) ---------------------------------------------------

  function makeTrack(id, { adopt }) {
    const dir = path.join(paths.jobsDir, id)
    const t = {
      id, dir,
      entry: null, inActive: false, seenActive: false, missingSince: 0,
      state: null, stateKey: '',
      ev: { offset: 0, carry: Buffer.alloc(0) },
      pending: new Set(),
      final: false, finalHandled: false, jobEndSeen: false, finalAt: 0,
      lastJobMsg: '', stale: false, lastAliveCheck: 0,
      launcher: null, killTimer: null, createdAt: Date.now(),
    }
    if (adopt) {
      // Re-adopted after a restart: follow from the current file sizes.
      const st = statOrNull(path.join(dir, 'events.jsonl'))
      if (st) t.ev.offset = st.size
    }
    tracked.set(id, t)
    return t
  }

  function scanActive({ adopt = false } = {}) {
    lastScan = Date.now()
    let names = []
    try { names = fs.readdirSync(paths.activeDir) } catch { names = [] }
    const ids = new Set()
    for (const name of names) {
      if (!name.endsWith('.json')) continue
      const id = name.slice(0, -5)
      if (!jobDirFor(paths.jobsDir, id)) continue
      ids.add(id)
      let t = tracked.get(id)
      if (!t) t = makeTrack(id, { adopt })
      const entry = readJsonOrNull(path.join(paths.activeDir, name))
      if (entry) t.entry = entry
      t.inActive = true
      t.seenActive = true
      t.missingSince = 0
    }
    for (const t of tracked.values()) {
      if (!ids.has(t.id) && t.inActive) {
        t.inActive = false
        t.missingSince = Date.now()
      }
    }
  }

  function readTrackState(t) {
    const file = path.join(t.dir, 'state.json')
    const st = statOrNull(file)
    if (!st) return false
    const key = `${st.size}:${st.mtimeMs}`
    if (key === t.stateKey) return false
    const obj = readJsonOrNull(file)
    if (!obj) return false
    t.stateKey = key
    t.state = obj
    t.pending = new Set(Array.isArray(obj.pending_leagues) ? obj.pending_leagues.map((l) => claimKey(l === '*' ? null : l)) : [])
    if (FINAL_STATUSES.has(obj.status)) t.final = true
    return true
  }

  function processTrackEvent(t, ev) {
    const type = eventType(ev)
    if (type === 'step_end') {
      if (watch) watch.onStepEnd(t.id)
    } else if (type === 'league_done') {
      const ck = claimKey(ev.league === '*' ? null : ev.league)
      t.pending.delete(ck)
      if (watch) watch.onLeagueDone(t.id, ck)
    } else if (type === 'job_end') {
      t.jobEndSeen = true
      t.final = true
    }
  }

  function jobMessage(t) {
    const s = t.state || {}
    const e = t.entry || {}
    const steps = Array.isArray(s.steps) ? s.steps : []
    const cur = Number.isInteger(s.current) ? s.current : null
    const step = cur !== null && cur >= 0 && cur < steps.length
      ? { index: cur, total: steps.length, title: (steps[cur] && steps[cur].title) || '' }
      : null
    let stop = null
    if (s.stop) stop = typeof s.stop === 'string' ? s.stop : (s.stop.mode || null)
    return {
      id: t.id,
      task: s.task || e.task || null,
      title: s.title || e.title || null,
      mode: s.mode || e.mode || null,
      status: s.status || (t.final ? 'lost' : 'starting'),
      step,
      prompt: !!s.prompt || s.status === 'waiting',
      stop,
      stale: !!t.stale,
      waiting_for: s.waiting_for || null,
    }
  }

  function sendJob(t, extra) {
    const msg = { ...jobMessage(t), ...(extra || {}) }
    const sig = JSON.stringify(msg)
    if (sig === t.lastJobMsg) return
    t.lastJobMsg = sig
    broadcast('tgs:job', { ...msg, at: Date.now() })
  }

  function requestReap() {
    const now = Date.now()
    if (now - lastReap < REAP_GAP_MS) return
    lastReap = now
    settle('reap', callPython([paths.runTask, '--reap'], { timeoutMs: 60000 }))
  }

  function tailTrack(t) {
    const stateChanged = readTrackState(t)
    const events = readNewJsonLines(path.join(t.dir, 'events.jsonl'), t.ev)
    for (const ev of events) safe('job event', () => processTrackEvent(t, ev))

    const now = Date.now()
    // Liveness: cheap first check only; run_task applies the exact rule (7.6).
    // An active entry cut short by a crash has no pid; state.json names the same runner.
    const pid = (t.entry && t.entry.pid) || (t.inActive && t.state && t.state.pid) || null
    if (!t.final && pid && now - t.lastAliveCheck >= SCAN_MS) {
      t.lastAliveCheck = now
      const alive = pidAlive(pid)
      if (!alive) {
        requestReap()
        t.stale = false
      } else {
        const hb = statOrNull(path.join(t.dir, 'heartbeat'))
        t.stale = !!(hb && now - hb.mtimeMs > STALE_HEARTBEAT_MS)
      }
    }
    if (stateChanged || t.state) sendJob(t)

    if (t.final && !t.finalHandled) {
      t.finalHandled = true
      t.finalAt = now
      if (t.killTimer) { clock.clearTimeout(t.killTimer); t.killTimer = null }
      if (watch) watch.onJobFinal(t.id)
      settle('catalog rebuild', buildCatalog('job_end'))
    }
  }

  function sweepTracks() {
    const now = Date.now()
    for (const t of tracked.values()) {
      if (t.final && t.finalHandled && !t.inActive && now - t.finalAt > 2000) {
        tracked.delete(t.id)
        continue
      }
      // Gone from active/ without a final state, and not one we are still starting.
      if (!t.inActive && t.seenActive && !t.final && t.missingSince && now - t.missingSince > 10000) {
        tracked.delete(t.id)
        continue
      }
      // Started here, never became active, launcher long gone.
      if (!t.seenActive && !t.state && t.launcher && t.launcher.exited && now - t.createdAt > 60000) {
        tracked.delete(t.id)
      }
    }
  }

  // Jobs that claim league ck (9.3): running or waiting, and ck still in pending_leagues.
  // Only a job that holds the data lock (or runs without it) can write app data now. A Grind that
  // sims in OOTP does not hold it, so a pull that runs meanwhile is not held for the whole cycle.
  function claimers(ck) {
    const out = []
    for (const t of tracked.values()) {
      if (t.final || !t.state) continue
      const st = t.state.status
      const dl = t.state.data_lock
      if (dl !== 'held' && dl !== 'skipped') continue
      if ((st === 'running' || st === 'waiting') && t.pending.has(ck)) out.push(t.id)
    }
    return out
  }

  function isFinal(id) {
    const t = tracked.get(id)
    return !t || !!t.final
  }

  function tick() {
    if (ticking || disposed) return
    ticking = true
    try {
      if (Date.now() - lastScan >= SCAN_MS) safe('scan active', () => scanActive())
      for (const t of tracked.values()) safe('follow job', () => tailTrack(t))
      if (watch) safe('reconcile', () => watch.reconcile())
      safe('sweep', () => sweepTracks())
      for (const s of subs) safe('job stream', () => pumpSub(s))
    } finally {
      ticking = false
    }
  }

  // Fresh claims for a watcher event. Cheap: a few small files per active job.
  function syncNow() {
    lastScan = 0
    tick()
  }

  function adoptActive() {
    scanActive({ adopt: true })
    for (const t of tracked.values()) {
      safe('adopt job', () => {
        readTrackState(t)
        // A kill asked for before the restart still gets its fallback.
        const stop = readJsonOrNull(path.join(t.dir, 'stop.json'))
        if (stop && stop.mode === 'kill' && !t.final) {
          const asked = Date.parse(stop.requested_at) || Date.now()
          armKillFallback(t, Math.max(0, asked + KILL_FALLBACK_MS - Date.now()))
        }
      })
    }
  }

  // ---- reading jobs for the API ------------------------------------------------

  function activeIds() {
    let names = []
    try { names = fs.readdirSync(paths.activeDir) } catch { names = [] }
    return new Set(names.filter((n) => n.endsWith('.json')).map((n) => n.slice(0, -5)))
  }

  // state.json, or a derived record when there is none (8.5).
  function jobView(id, active) {
    const dir = jobDirFor(paths.jobsDir, id)
    if (!dir) return null
    const state = readJsonOrNull(path.join(dir, 'state.json'))
    if (state) {
      const t = tracked.get(id)
      if (t && t.stale && !FINAL_STATUSES.has(state.status)) return { ...state, stale: true }
      return state
    }
    if (!statOrNull(dir)) return null
    const req = readJsonOrNull(path.join(dir, 'request.json')) || {}
    const isActive = active ? active.has(id) : activeIds().has(id)
    const entry = isActive ? readJsonOrNull(path.join(paths.activeDir, `${id}.json`)) : null
    if (entry) {
      return { id, task: entry.task || req.task || null, title: entry.title || null, mode: entry.mode || req.mode || null, status: 'starting' }
    }
    const t = tracked.get(id)
    const st = statOrNull(path.join(dir, 'request.json')) || statOrNull(dir)
    const age = st ? Date.now() - st.mtimeMs : Infinity
    const launcherGone = !!(t && t.launcher && t.launcher.exited)
    if (launcherGone || age > 60000) {
      const tail = tailOfFile(path.join(dir, 'runner.log'), 1)
      return {
        id, task: req.task || null, status: 'did_not_start',
        message: tail.length ? `The task did not start: ${tail[0]}` : 'The task did not start.',
      }
    }
    return { id, task: req.task || null, mode: req.mode || null, status: 'starting' }
  }

  // Oldest first: by request time (ms), else start time, else the id (which starts with the time).
  function startKey(id, view) {
    const req = readJsonOrNull(path.join(paths.jobsDir, id, 'request.json'))
    return Date.parse(req && req.requested_at) || Date.parse(view && view.started) || 0
  }

  function listActive() {
    const active = activeIds()
    const rows = []
    for (const id of active) {
      const v = jobView(id, active)
      if (v) rows.push({ id, v, key: startKey(id, v) })
    }
    rows.sort((a, b) => (a.key && b.key && a.key !== b.key ? a.key - b.key : a.id.localeCompare(b.id)))
    return rows.map((r) => r.v)
  }

  function listJobs(limit) {
    let names = []
    try { names = fs.readdirSync(paths.jobsDir) } catch { names = [] }
    const ids = names.filter((n) => jobDirFor(paths.jobsDir, n)).sort().reverse().slice(0, limit)
    const active = activeIds()
    return ids.map((id) => jobView(id, active)).filter(Boolean)
  }

  // ---- start a job (8.5 POST /jobs, 8.7) ------------------------------------------

  function needsData(task) {
    const flags = task.flags || {}
    if (flags.read_only) return false
    const steps = Array.isArray(task.steps) ? task.steps : []
    if (steps.some((s) => s && s.data === true)) return true
    return !steps.some((s) => s && Object.prototype.hasOwnProperty.call(s, 'data'))
  }

  function lockHolder(name) {
    const holder = readJsonOrNull(path.join(paths.locksDir, `${name}.json`))
    if (!holder) return null
    if (!pidAlive(holder.pid)) return null
    return holder
  }

  function holderJob(holder) {
    return { id: holder.job_id || null, task: holder.task || null, title: holder.title || null, mode: holder.mode || null }
  }

  function precheck(task) {
    const locks = Array.isArray(task.locks) ? task.locks.slice() : []
    const flags = task.flags || {}
    if (!flags.read_only && !locks.includes(`task.${task.id}`)) locks.push(`task.${task.id}`)
    for (const name of locks) {
      const holder = lockHolder(name)
      if (holder) {
        return {
          status: 409,
          body: { error: { code: 'conflict', message: `${holder.title || holder.task || 'Another task'} is running and holds ${name}.`, job: holderJob(holder), lock: name } },
        }
      }
    }
    if (needsData(task)) {
      for (const j of listActive()) {
        if (j.status === 'queued') {
          return {
            status: 409,
            body: { error: { code: 'queue_full', message: 'Another task is already waiting. Start this one after it.', job: { id: j.id, task: j.task, title: j.title } } },
          }
        }
      }
    }
    return null
  }

  function spawnLauncher(t, jobDir, secretEnv) {
    const argv = py()
    t.launcher = { exited: false, code: null, error: null, answered: false }
    fs.mkdirSync(jobDir, { recursive: true })
    const out = fs.openSync(path.join(jobDir, 'runner.log'), 'a')
    let child
    try {
      child = spawn(argv[0], [...argv.slice(1), paths.runTask, '--launch', jobDir], {
        cwd: paths.repo, detached: true, windowsHide: true, stdio: ['ignore', out, out],
        env: { ...process.env, PYTHONUNBUFFERED: '1', PYTHONIOENCODING: 'utf-8', ...secretEnv },
      })
    } catch (err) {
      t.launcher.exited = true
      t.launcher.error = err
      return
    } finally {
      fs.closeSync(out)
    }
    child.on('error', (err) => safe('launcher error', () => onLaunchFailed(t, err)))
    child.on('exit', (code) => safe('launcher exit', () => onLauncherExit(t, code)))
    child.unref()
  }

  function launchFailedMessage(t) {
    const err = t.launcher && t.launcher.error
    if (err && err.code === 'ENOENT') {
      return `Python did not start: the command "${py().join(' ')}" was not found. ${INSTALL_HINT}`
    }
    if (t.launcher && t.launcher.code === 9009) {
      return `Python did not start: only the Microsoft Store shortcut answered. ${INSTALL_HINT}`
    }
    return 'The task runner did not start.'
  }

  function onLaunchFailed(t, err) {
    t.launcher.exited = true
    t.launcher.error = err
    afterLaunchProblem(t)
  }

  function onLauncherExit(t, code) {
    t.launcher.exited = true
    t.launcher.code = code
    if (code !== 0) afterLaunchProblem(t)
  }

  // After the POST has answered: tell the page the job failed (8.7).
  function afterLaunchProblem(t) {
    if (!t.launcher.answered) return
    if (readJsonOrNull(path.join(t.dir, 'state.json'))) return
    broadcast('tgs:job', {
      id: t.id, task: t.taskId || null, title: t.title || null, mode: 'job', status: 'failed',
      step: null, prompt: false, stop: null, stale: false, waiting_for: null,
      message: launchFailedMessage(t), log_tail: tailOfFile(path.join(t.dir, 'runner.log'), 20), at: Date.now(),
    })
  }

  // Resolves even after dispose(), so a request in flight during a restart never hangs.
  const wait = (ms) => new Promise((resolve) => {
    if (!clock.setTimeout(resolve, ms)) setTimeout(resolve, ms)
  })

  async function startJob(task, inputs, secretPairs) {
    const pre = precheck(task)
    if (pre) return pre

    fs.mkdirSync(paths.jobsDir, { recursive: true })
    let id = null
    let jobDir = null
    for (let i = 0; i < 5 && !jobDir; i++) {
      const candidate = newJobId(task.id)
      const dir = jobDirFor(paths.jobsDir, candidate)
      if (!dir) break
      try {
        fs.mkdirSync(dir)
        id = candidate
        jobDir = dir
      } catch (err) {
        if (!err || err.code !== 'EEXIST') throw err
      }
    }
    if (!jobDir) {
      return { status: 500, body: { error: { code: 'runner_failed', message: 'Could not make a job folder.' } } }
    }

    const secretEnv = {}
    const secretNames = []
    for (const [name, value] of secretPairs) {
      const v = String(value).trim()
      if (!v) continue
      const upper = name.toUpperCase()
      secretEnv[`TGS_SECRET_${upper}`] = v
      secretNames.push(upper)
    }
    writeJsonAtomic(path.join(jobDir, 'request.json'), {
      schema: 1, task: task.id, inputs, secret_names: secretNames, mode: 'job',
      requested_at: new Date().toISOString(), by: 'control-page',
    })

    const t = tracked.get(id) || makeTrack(id, { adopt: false })
    t.taskId = task.id
    t.title = task.title
    spawnLauncher(t, jobDir, secretEnv)

    const statePath = path.join(jobDir, 'state.json')
    const deadline = Date.now() + 10000
    let reaped = false
    while (Date.now() < deadline && !disposed) {
      const state = readJsonOrNull(statePath)
      if (state) {
        const st = state.status
        if (st === 'running' || st === 'waiting' || st === 'queued') {
          t.launcher.answered = true
          return { status: 201, body: { job: state } }
        }
        if (st === 'invalid') {
          t.launcher.answered = true
          return {
            status: 400,
            body: { error: { code: 'invalid_input', message: state.message || 'The inputs are not valid.', errors: state.errors || {}, fix_task: state.fix_task || null }, job: state },
          }
        }
        if (st === 'refused') {
          t.launcher.answered = true
          let job = null
          let lock = null
          for (const name of (task.locks || [])) {
            const holder = lockHolder(name)
            if (holder) { job = holderJob(holder); lock = name; break }
          }
          return { status: 409, body: { error: { code: 'conflict', message: state.message || 'Another task holds a lock this task needs.', job, lock } } }
        }
        const ran = Array.isArray(state.steps) && state.steps.some((s) => s && s.status && s.status !== 'pending')
        if (st === 'failed' && !ran) {
          t.launcher.answered = true
          return {
            status: 500,
            body: { error: { code: 'runner_failed', message: state.message || 'The task runner stopped before it started the task.', log_tail: tailOfFile(path.join(jobDir, 'runner.log'), 20) } },
          }
        }
        if (FINAL_STATUSES.has(st)) {
          t.launcher.answered = true
          return { status: 201, body: { job: state } }
        }
      } else if (t.launcher.exited && (t.launcher.error || (t.launcher.code !== 0 && t.launcher.code !== null))) {
        const notFound = t.launcher.error && t.launcher.error.code === 'ENOENT'
        if (!notFound && !reaped) {
          reaped = true
          await callPython([paths.runTask, '--reap'], { timeoutMs: 30000 })
          const again = readJsonOrNull(statePath)
          if (again) continue
        }
        t.launcher.answered = true
        return {
          status: 500,
          body: { error: { code: 'runner_failed', message: launchFailedMessage(t), log_tail: tailOfFile(path.join(jobDir, 'runner.log'), 20) } },
        }
      }
      await wait(100)
    }
    t.launcher.answered = true
    return { status: 202, body: { job: { id, status: 'starting' } } }
  }

  // ---- stop and answer ------------------------------------------------------------------

  function isRunning(id) {
    const state = readJsonOrNull(path.join(paths.jobsDir, id, 'state.json'))
    if (state && FINAL_STATUSES.has(state.status)) return { running: false, state }
    const active = activeIds().has(id)
    return { running: active, state }
  }

  // If a kill is not in state.json within 15 s, run_task --kill checks the runner and ends it (8.8).
  function armKillFallback(t, ms) {
    if (t.killTimer) clock.clearTimeout(t.killTimer)
    t.killTimer = clock.setTimeout(() => {
      t.killTimer = null
      const state = readJsonOrNull(path.join(t.dir, 'state.json'))
      if (state && FINAL_STATUSES.has(state.status)) return
      settle('kill fallback', callPython([paths.runTask, '--kill', t.id], { timeoutMs: 60000 }))
    }, ms)
  }

  function requestStop(id, mode) {
    const dir = jobDirFor(paths.jobsDir, id)
    writeJsonAtomic(path.join(dir, 'stop.json'), { mode, requested_at: new Date().toISOString() })
    if (mode === 'kill') {
      let t = tracked.get(id)
      if (!t) t = makeTrack(id, { adopt: true })
      armKillFallback(t, KILL_FALLBACK_MS)
    }
  }

  function writeAnswer(id, promptId, value) {
    const dir = jobDirFor(paths.jobsDir, id)
    writeJsonAtomic(path.join(dir, 'answer.json'), { prompt_id: promptId, value })
  }

  function readPrompt(id) {
    const dir = jobDirFor(paths.jobsDir, id)
    return dir ? readJsonOrNull(path.join(dir, 'prompt.json')) : null
  }

  // ---- log reads (GET /jobs/:id/log) ---------------------------------------------------

  function readLog(id, from, max) {
    const dir = jobDirFor(paths.jobsDir, id)
    const file = path.join(dir, 'log.txt')
    const { buf, size } = readRange(file, from, max)
    if (size < 0) return null
    const end = utf8SafeEnd(buf)
    return { text: buf.subarray(0, end).toString('utf8'), next: from + end, size }
  }

  // ---- SSE (8.6) --------------------------------------------------------------------------

  function sseWrite(s, event, data) {
    if (s.closed) return
    const id = `e${s.seq}-l${s.logOffset}`
    s.res.write(`id: ${id}\nevent: ${event}\ndata: ${JSON.stringify(data)}\n\n`)
  }

  function closeSub(s) {
    if (s.closed) return
    s.closed = true
    subs.delete(s)
    if (s.partialTimer) { clock.clearTimeout(s.partialTimer); s.partialTimer = null }
    try { s.res.end() } catch { /* ignore */ }
  }

  function tailStart(file, tail) {
    const st = statOrNull(file)
    if (!st) return 0
    const start = Math.max(0, st.size - tail)
    if (start === 0) return 0
    const { buf } = readRange(file, start - 1, 64 * 1024)
    const nl = buf.indexOf(0x0a)
    return nl < 0 ? st.size : start - 1 + nl + 1
  }

  function openStream(id, req, res, query) {
    const dir = jobDirFor(paths.jobsDir, id)
    const cursor = parseCursor(req.headers['last-event-id']) || parseCursor(query.from)
    const state = readJsonOrNull(path.join(dir, 'state.json'))
    const logFile = path.join(dir, 'log.txt')
    let logStart
    if (cursor) logStart = cursor.off
    else {
      let tail = Number(query.tail)
      if (!Number.isFinite(tail) || tail < 0) tail = DEFAULT_TAIL
      logStart = tailStart(logFile, tail)
    }
    const s = {
      id, dir, req, res, closed: false,
      seq: cursor ? cursor.seq : 0,
      logOffset: logStart, readPos: logStart, pend: Buffer.alloc(0), pendSince: 0,
      ev: { offset: 0, carry: Buffer.alloc(0) },
      stateText: null, jobEnd: null, finalSince: 0,
      console: !!(state && state.mode === 'console'),
      first: true, openedAt: Date.now(), lastDerived: 0, partialTimer: null,
    }
    res.writeHead(200, {
      'Content-Type': 'text/event-stream; charset=utf-8',
      'Cache-Control': 'no-cache',
      Connection: 'keep-alive',
      'X-Accel-Buffering': 'no',
    })
    res.write('retry: 2000\n\n')
    sseWrite(s, 'hello', { job_id: id, cursor: `e${s.seq}-l${s.logOffset}` })
    subs.add(s)
    req.on('close', () => closeSub(s))
    res.on('error', () => closeSub(s))
    pumpSub(s)
  }

  function pumpLog(s, { all = false } = {}) {
    if (s.console) return
    const file = path.join(s.dir, 'log.txt')
    for (let round = 0; round < 64; round++) {
      const { buf } = readRange(file, s.readPos)
      if (!buf.length) break
      s.readPos += buf.length
      s.pend = s.pend.length ? Buffer.concat([s.pend, buf]) : buf
      // Idle time counts from the last write to the file, not from this read.
      const st = statOrNull(file)
      s.pendSince = st ? Math.min(Date.now(), st.mtimeMs) : Date.now()
      if (!all) break
    }
    const cut = completeEnd(s.pend)
    if (cut > 0) {
      const text = normalizeText(s.pend.subarray(0, cut).toString('utf8'))
      const offset = s.logOffset
      s.logOffset += cut
      s.pend = Buffer.from(s.pend.subarray(cut))
      sseWrite(s, 'log', { text, offset, partial: false })
    }
    if (s.pend.length && (all || Date.now() - s.pendSince >= PARTIAL_IDLE_MS)) {
      const end = all ? s.pend.length : utf8SafeEnd(s.pend)
      if (end > 0) {
        const text = normalizeText(s.pend.subarray(0, end).toString('utf8'))
        const offset = s.logOffset
        s.logOffset += end
        s.pend = Buffer.from(s.pend.subarray(end))
        sseWrite(s, 'log', { text, offset, partial: true })
      }
    }
    // A held partial line goes out 500 ms after the last write, not at the next 500 ms tick.
    if (s.pend.length && !all && !s.partialTimer && !s.closed) {
      const delay = Math.max(20, PARTIAL_IDLE_MS - (Date.now() - s.pendSince))
      s.partialTimer = clock.setTimeout(() => {
        s.partialTimer = null
        safe('job stream', () => pumpSub(s))
      }, delay)
    }
  }

  function pumpState(s) {
    const text = readTextOrNull(path.join(s.dir, 'state.json'))
    if (!text || text === s.stateText) return null
    let obj
    try { obj = JSON.parse(text) } catch { return null }
    s.stateText = text
    if (obj.mode === 'console') s.console = true
    sseWrite(s, 'state', obj)
    return obj
  }

  function pumpSub(s) {
    if (s.closed) return
    pumpLog(s)
    const events = readNewJsonLines(path.join(s.dir, 'events.jsonl'), s.ev)
    // On the first read, a prompt that already has an answer is old news.
    const answered = new Set()
    if (s.first) {
      for (const ev of events) if (eventType(ev) === 'answer' && ev.prompt_id) answered.add(ev.prompt_id)
    }
    s.first = false
    for (const ev of events) {
      const seq = Number(ev.seq)
      if (Number.isFinite(seq) && seq <= s.seq) continue
      if (Number.isFinite(seq)) s.seq = seq
      const type = eventType(ev)
      if (STEP_EVENTS.has(type)) sseWrite(s, 'step', ev)
      else if (type === 'message') sseWrite(s, 'message', ev)
      else if (type === 'prompt') {
        if (ev.prompt_id && answered.has(ev.prompt_id)) continue
        const prompt = readJsonOrNull(path.join(s.dir, 'prompt.json'))
        sseWrite(s, 'prompt', prompt && (!ev.prompt_id || prompt.prompt_id === ev.prompt_id) ? prompt : ev)
      } else if (type === 'job_end') s.jobEnd = ev
    }
    const state = pumpState(s)
    if (s.jobEnd) {
      pumpLog(s, { all: true })
      pumpState(s)
      sseWrite(s, 'done', s.jobEnd)
      closeSub(s)
      return
    }
    // No state.json for a while: the job may never have started.
    if (!s.stateText && Date.now() - s.openedAt > 15000 && Date.now() - s.lastDerived > 2000) {
      s.lastDerived = Date.now()
      const view = jobView(s.id)
      if (view && view.status === 'did_not_start') {
        sseWrite(s, 'done', { type: 'job_end', status: 'did_not_start', message: view.message, exit_code: null, fails: [], summary: [] })
        closeSub(s)
        return
      }
    }
    let current = state
    if (!current && s.stateText) { try { current = JSON.parse(s.stateText) } catch { current = null } }
    if (current && FINAL_STATUSES.has(current.status)) {
      // A final state with no job_end (a reaped or killed runner): close after a short wait.
      if (!s.finalSince) s.finalSince = Date.now()
      else if (Date.now() - s.finalSince > 2000) {
        pumpLog(s, { all: true })
        sseWrite(s, 'done', {
          type: 'job_end', status: current.status, exit_code: current.exit_code ?? null,
          fails: current.fails || [], summary: current.summary || [],
        })
        closeSub(s)
      }
    }
  }

  function pingSubs() {
    for (const s of subs) {
      if (s.closed) continue
      try { s.res.write(': ping\n\n') } catch { closeSub(s) }
    }
  }

  // ---- timers and lifetime -----------------------------------------------------------------

  function start() {
    adoptActive()
    clock.setInterval(() => tick(), TICK_MS)
    clock.setInterval(() => checkWatchFiles(), 5000)
    clock.setInterval(() => pingSubs(), SSE_PING_MS)
  }

  function dispose() {
    disposed = true
    for (const s of [...subs]) closeSub(s)
    for (const t of tracked.values()) {
      if (t.killTimer) { clock.clearTimeout(t.killTimer); t.killTimer = null }
    }
  }

  return {
    setWatch, start, dispose, tick, syncNow,
    claimers, isFinal,
    probePython, getPython: () => python,
    getCatalog, buildCatalog, findTask, getCachedCatalog: () => catalog,
    callPython, callPythonJson,
    startJob, requestStop, writeAnswer, readPrompt, isRunning,
    listActive, listJobs, jobView, readLog, openStream,
    activeCount: () => activeIds().size,
    tracked,
  }
}

export { readJsonOrNull, statOrNull, lastLines, tailOfFile }
