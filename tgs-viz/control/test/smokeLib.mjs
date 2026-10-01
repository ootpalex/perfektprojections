// Shared helpers for the Control smoke tests (api, restart, failsafe). Node built-ins only.

import fs from 'node:fs'
import path from 'node:path'
import { spawn, spawnSync } from 'node:child_process'
import { fileURLToPath } from 'node:url'

export const HERE = path.dirname(fileURLToPath(import.meta.url))
export const TGS_VIZ = path.resolve(HERE, '..', '..')
export const REPO = path.resolve(TGS_VIZ, '..')
export const VITE_BIN = path.join(TGS_VIZ, 'node_modules', 'vite', 'bin', 'vite.js')

export const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

// ---- reporting ----

export function reporter(name) {
  let passed = 0
  let failed = 0
  const lines = []
  return {
    ok(label, cond, detail) {
      if (cond) { passed++; lines.push(`ok   ${label}`); console.log(`ok   ${label}`) }
      else { failed++; const l = `FAIL ${label}${detail !== undefined ? `: ${typeof detail === 'string' ? detail : JSON.stringify(detail)}` : ''}`; lines.push(l); console.log(l) }
      return !!cond
    },
    info(text) { console.log(`     ${text}`) },
    done() {
      console.log(`${name}: ${passed} passed, ${failed} failed`)
      return failed
    },
  }
}

export async function waitFor(fn, timeoutMs, stepMs = 100) {
  const end = Date.now() + timeoutMs
  for (;;) {
    const v = await fn()
    if (v) return v
    if (Date.now() >= end) return null
    await sleep(stepMs)
  }
}

// ---- Vite websocket and the tgs token ----

export async function viteWsToken(base) {
  const res = await fetch(`${base}/@vite/client`)
  const text = await res.text()
  const m = /const wsToken = "([^"]+)"/.exec(text)
  if (!m) throw new Error('no ws token in /@vite/client')
  return m[1]
}

export async function connectWs(port) {
  const base = `http://localhost:${port}`
  const wsToken = await viteWsToken(base)
  const ws = new WebSocket(`ws://localhost:${port}/?token=${encodeURIComponent(wsToken)}`, 'vite-hmr')
  const messages = []
  ws.addEventListener('message', (ev) => {
    try { messages.push({ at: Date.now(), msg: JSON.parse(String(ev.data)) }) } catch { /* ignore */ }
  })
  await new Promise((resolve, reject) => {
    ws.addEventListener('open', resolve, { once: true })
    ws.addEventListener('error', (e) => reject(new Error('ws error')), { once: true })
  })
  return {
    ws, messages,
    send(event, data) { ws.send(JSON.stringify({ type: 'custom', event, data })) },
    custom(event, since = 0) {
      return messages.filter((m) => m.at >= since && m.msg.type === 'custom' && m.msg.event === event).map((m) => ({ at: m.at, data: m.msg.data }))
    },
    close() { try { ws.close() } catch { /* ignore */ } },
  }
}

export async function tgsToken(conn) {
  const since = Date.now()
  conn.send('tgs:hello', {})
  const got = await waitFor(() => conn.custom('tgs:token', since)[0], 5000)
  if (!got) throw new Error('no tgs:token reply')
  return got.data
}

// ---- HTTP ----

export function api(port, token) {
  const base = `http://localhost:${port}/__tgs`
  async function call(method, p, body, headers = {}) {
    const h = { ...headers }
    if (token && !('X-TGS-Token' in h)) h['X-TGS-Token'] = token
    let payload
    if (body !== undefined) {
      h['Content-Type'] = h['Content-Type'] || 'application/json'
      payload = typeof body === 'string' ? body : JSON.stringify(body)
    }
    const res = await fetch(base + p, { method, headers: h, body: payload })
    const text = await res.text()
    let json = null
    try { json = JSON.parse(text) } catch { /* not json */ }
    return { status: res.status, json, text, headers: res.headers }
  }
  return {
    get: (p, headers) => call('GET', p, undefined, headers),
    post: (p, body, headers) => call('POST', p, body, headers),
  }
}

// ---- SSE ----

export function openSse(port, token, jobId, { from, lastEventId } = {}) {
  const url = new URL(`http://localhost:${port}/__tgs/jobs/${jobId}/events`)
  url.searchParams.set('t', token)
  if (from) url.searchParams.set('from', from)
  const ctrl = new AbortController()
  const events = []
  const state = { closed: false, status: null, lastId: null }
  const headers = {}
  if (lastEventId) headers['Last-Event-ID'] = lastEventId
  const done = (async () => {
    try {
      const res = await fetch(url, { headers, signal: ctrl.signal })
      state.status = res.status
      if (res.status !== 200) { state.closed = true; return }
      const reader = res.body.getReader()
      const dec = new TextDecoder()
      let buf = ''
      for (;;) {
        const { value, done: end } = await reader.read()
        if (end) break
        buf += dec.decode(value, { stream: true })
        let idx
        while ((idx = buf.indexOf('\n\n')) >= 0) {
          const block = buf.slice(0, idx)
          buf = buf.slice(idx + 2)
          const ev = { id: null, event: 'message', data: '' }
          let hasData = false
          for (const line of block.split('\n')) {
            if (line.startsWith(':')) continue
            const c = line.indexOf(':')
            const field = c < 0 ? line : line.slice(0, c)
            const val = c < 0 ? '' : line.slice(c + 1).replace(/^ /, '')
            if (field === 'id') ev.id = val
            else if (field === 'event') ev.event = val
            else if (field === 'data') { ev.data += (hasData ? '\n' : '') + val; hasData = true }
          }
          if (!hasData) continue
          try { ev.json = JSON.parse(ev.data) } catch { ev.json = null }
          if (ev.id) state.lastId = ev.id
          events.push(ev)
        }
      }
    } catch { /* aborted or closed */ }
    state.closed = true
  })()
  return {
    events, state, done,
    close() { ctrl.abort() },
    find(event, pred = () => true) { return events.find((e) => e.event === event && pred(e)) },
    logText() { return events.filter((e) => e.event === 'log').map((e) => e.json.text).join('') },
  }
}

// ---- job helpers ----

export async function jobState(a, id) {
  const r = await a.get(`/jobs/${id}`)
  return r.json && r.json.job
}

export async function waitStatus(a, id, statuses, timeoutMs) {
  const want = new Set([].concat(statuses))
  return waitFor(async () => {
    const s = await jobState(a, id)
    return s && want.has(s.status) ? s : null
  }, timeoutMs, 250)
}

// ---- starting and stopping Vite ----

export function testEnv(extra = {}) {
  const env = { ...process.env }
  env.BROWSER = 'none'
  env.TGS_SELFTEST = '1'
  if (!env.TGS_CONTROL_DIR) env.TGS_CONTROL_DIR = path.join(REPO, '.control-b')
  if (!env.TGS_VITE_CACHE_DIR) env.TGS_VITE_CACHE_DIR = path.join(REPO, '.vite-cache-b')
  for (const [k, v] of Object.entries(extra)) {
    if (v === null) delete env[k]
    else env[k] = v
  }
  return env
}

export async function startVite(port, env, { args = [] } = {}) {
  const child = spawn(process.execPath, [VITE_BIN, '--port', String(port), '--strictPort', ...args], {
    cwd: TGS_VIZ, env, windowsHide: true, stdio: ['ignore', 'pipe', 'pipe'],
  })
  const out = { text: '' }
  child.stdout.on('data', (d) => { out.text += d.toString('utf8') })
  child.stderr.on('data', (d) => { out.text += d.toString('utf8') })
  child.on('error', () => {})
  const exited = { code: undefined }
  child.on('exit', (code) => { exited.code = code })
  const up = await waitFor(async () => {
    if (exited.code !== undefined) return 'exited'
    try {
      const r = await fetch(`http://localhost:${port}/__tgs/ping`)
      return r.status ? 'up' : null
    } catch { return null }
  }, 60000, 250)
  if (up !== 'up') throw new Error(`Vite did not start on ${port} (${up}). Output:\n${out.text}`)
  return { child, out, exited }
}

export async function stopVite(v) {
  if (!v || v.exited.code !== undefined) return
  try { v.child.kill() } catch { /* ignore */ }
  await waitFor(() => v.exited.code !== undefined, 10000)
  if (v.exited.code === undefined) {
    spawnSync('taskkill', ['/PID', String(v.child.pid), '/T', '/F'], { windowsHide: true })
  }
}

export function stripAnsi(s) {
  return String(s).replace(/\x1b\[[0-9;]*m/g, '')
}

export function fileMtime(file) {
  try { return fs.statSync(file).mtimeMs } catch { return null }
}
