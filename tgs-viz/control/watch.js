// Live refresh, server side (DESIGN.md 9.3): watch public/data, hold events while a job
// still writes that league, then send one tgs:data per league.

import fs from 'node:fs'
import path from 'node:path'
import { mapPath, claimKey } from './fileMap.js'
import { logError } from './safe.js'

const QUIET_MS = 2000          // rule 3: quiet time before the stability check
const RECHECK_MS = 500         // gap between the two stats
const MAX_CHANGE_MS = 60000    // rule 3: send anyway after this much continuous change
const SETTLE_MAX_MS = 5000     // rules 1 and 2: wait at most this long for files to settle
const GRACE_MS = 1000          // rules 1 and 2: a flush stays open this long for late watcher events
const ERROR_LIMIT = 10         // unhook after this many errors in one minute

function statSig(publicData, files) {
  const parts = []
  for (const rel of [...files].sort()) {
    try {
      const st = fs.statSync(path.join(publicData, rel))
      parts.push(`${rel}=${st.size}:${st.mtimeMs}`)
    } catch {
      parts.push(`${rel}=missing`)
    }
  }
  return parts.join('|')
}

export function createDataWatcher({ server, publicData, jobs, clock, broadcast, onOff }) {
  const holdPlayers = new Map()   // claim key -> {league, files: Map(rel -> key), jobs: Set}
  const holdOther = new Map()     // claim key -> same shape
  const batches = new Map()       // claim key -> open flush (rules 1 and 2)
  const quiet = new Map()         // claim key -> rule 3 debounce
  const errors = []
  let on = true
  const listeners = []

  function countError(where, err) {
    logError(where, err)
    const now = Date.now()
    errors.push(now)
    while (errors.length && now - errors[0] > 60000) errors.shift()
    if (errors.length >= ERROR_LIMIT && on) turnOff()
  }

  function guard(where, fn) {
    return (...args) => {
      if (!on) return undefined
      try { return fn(...args) } catch (err) { countError(where, err); return undefined }
    }
  }

  function send(league, files, reason) {
    if (!files.size) return
    const keys = [...new Set(files.values())].sort()
    broadcast('tgs:data', { league, keys, files: [...files.keys()].sort(), at: Date.now(), reason })
  }

  // ---- rules 1 and 2: a flush that waits for the files to settle ----

  function openBatch(ck, league, files, reason) {
    const existing = batches.get(ck)
    if (existing) {
      for (const [rel, key] of files) existing.files.set(rel, key)
      return
    }
    const b = { ck, league, files: new Map(files), reason, start: Date.now(), sig: null, timer: null }
    batches.set(ck, b)
    b.timer = clock.setTimeout(guard('flush check', () => checkBatch(b)), RECHECK_MS)
  }

  function checkBatch(b) {
    b.timer = null
    const now = Date.now()
    const sig = statSig(publicData, b.files.keys())
    const settled = b.sig !== null && sig === b.sig
    if ((settled && now - b.start >= GRACE_MS) || now - b.start >= SETTLE_MAX_MS) {
      batches.delete(b.ck)
      send(b.league, b.files, b.reason)
      return
    }
    b.sig = sig
    b.timer = clock.setTimeout(guard('flush check', () => checkBatch(b)), RECHECK_MS)
  }

  // A write that reached the watcher before the poller saw the job's claim sits in the rule 3 wait.
  // When that league is released, it belongs to the same update: take it in.
  function absorbQuiet(ck, files) {
    const q = quiet.get(ck)
    if (!q) return
    if (q.timer) clock.clearTimeout(q.timer)
    quiet.delete(ck)
    for (const [rel, key] of q.files) files.set(rel, key)
  }

  function release(ck, reason) {
    const files = new Map()
    let league = ck === '*' ? null : ck
    for (const holds of [holdPlayers, holdOther]) {
      const h = holds.get(ck)
      if (!h) continue
      holds.delete(ck)
      league = h.league
      for (const [rel, key] of h.files) files.set(rel, key)
    }
    absorbQuiet(ck, files)
    // Open the flush even with no files yet: a watcher event for the last write may still be on its way.
    openBatch(ck, league, files, reason)
  }

  function flushOther(ck, reason) {
    const h = holdOther.get(ck)
    if (!h) return
    holdOther.delete(ck)
    openBatch(ck, h.league, h.files, reason)
  }

  // ---- rule 3: nobody claims the league ----

  function quietAdd(ck, m) {
    let q = quiet.get(ck)
    if (!q) {
      q = { ck, league: m.league, files: new Map(), firstAt: Date.now(), timer: null }
      quiet.set(ck, q)
    }
    q.files.set(m.file, m.key)
    if (q.timer) clock.clearTimeout(q.timer)
    q.timer = null
    if (Date.now() - q.firstAt >= MAX_CHANGE_MS) {
      quiet.delete(ck)
      send(q.league, q.files, 'watch')
      return
    }
    q.timer = clock.setTimeout(guard('quiet check', () => quietCheck(q)), QUIET_MS)
  }

  function quietCheck(q) {
    const first = statSig(publicData, q.files.keys())
    q.timer = clock.setTimeout(guard('quiet check', () => {
      q.timer = null
      const second = statSig(publicData, q.files.keys())
      if (second === first || Date.now() - q.firstAt >= MAX_CHANGE_MS) {
        quiet.delete(q.ck)
        send(q.league, q.files, 'watch')
      } else {
        q.timer = clock.setTimeout(guard('quiet check', () => quietCheck(q)), QUIET_MS)
      }
    }), RECHECK_MS)
  }

  // ---- watcher events ----

  function handle(type, file) {
    const m = mapPath(String(file), publicData)
    if (!m) return
    jobs.syncNow()
    const ck = claimKey(m.league)
    const open = batches.get(ck)
    if (open) {
      open.files.set(m.file, m.key)
      return
    }
    const claim = jobs.claimers(ck)
    if (claim.length) {
      const holds = m.key === 'players' ? holdPlayers : holdOther
      let h = holds.get(ck)
      if (!h) {
        h = { league: m.league, files: new Map(), jobs: new Set() }
        holds.set(ck, h)
      }
      h.files.set(m.file, m.key)
      for (const id of claim) h.jobs.add(id)
      return
    }
    quietAdd(ck, m)
  }

  // ---- job signals from the poller (jobs.js) ----

  const onStepEnd = guard('step end', (jobId) => {
    for (const [ck, h] of [...holdOther]) if (h.jobs.has(jobId)) flushOther(ck, 'step_end')
  })

  const onLeagueDone = guard('league done', (jobId, ck) => {
    if (jobs.claimers(ck).length) return
    release(ck, 'league_done')
  })

  const onJobFinal = guard('job end', (jobId) => {
    for (const holds of [holdPlayers, holdOther]) {
      for (const [ck, h] of [...holds]) {
        if (!h.jobs.has(jobId)) continue
        h.jobs.delete(jobId)
        if (!jobs.claimers(ck).length) release(ck, 'job_end')
      }
    }
  })

  // Every tick: any hold whose league nobody claims any more goes out.
  const reconcile = guard('reconcile', () => {
    for (const [ck, h] of [...holdPlayers]) {
      if (jobs.claimers(ck).length) continue
      const ended = [...h.jobs].every((id) => jobs.isFinal(id))
      release(ck, ended ? 'job_end' : 'league_done')
    }
    for (const [ck, h] of [...holdOther]) {
      if (jobs.claimers(ck).length) continue
      const ended = [...h.jobs].every((id) => jobs.isFinal(id))
      flushOther(ck, ended ? 'job_end' : 'step_end')
    }
  })

  // ---- hook up and tear down ----

  for (const type of ['add', 'change', 'unlink']) {
    const fn = guard('data watcher', (file) => handle(type, file))
    server.watcher.on(type, fn)
    listeners.push([type, fn])
  }

  function unhook() {
    for (const [type, fn] of listeners) {
      try { server.watcher.off(type, fn) } catch { /* ignore */ }
    }
    listeners.length = 0
    for (const b of batches.values()) if (b.timer) clock.clearTimeout(b.timer)
    for (const q of quiet.values()) if (q.timer) clock.clearTimeout(q.timer)
    batches.clear()
    quiet.clear()
    holdPlayers.clear()
    holdOther.clear()
  }

  function turnOff() {
    on = false
    unhook()
    console.warn('[tgs-control] Live refresh is off after repeated errors. Press F5 after an update.')
    try { if (onOff) onOff() } catch (err) { logError('live refresh off', err) }
  }

  return {
    onStepEnd, onLeagueDone, onJobFinal, reconcile,
    isOn: () => on,
    dispose: unhook,
    // for tests and the debug ping
    _state: () => ({ holdPlayers: holdPlayers.size, holdOther: holdOther.size, batches: batches.size, quiet: quiet.size }),
  }
}
