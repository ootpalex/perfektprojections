// The Control panel plugin (DESIGN.md 8). Dev server only.
// vite.config.js loads this file with a dynamic import inside try/catch, so nothing here can stop
// Vite or the league data from loading. Node keeps this module across Vite restarts.

import crypto from 'node:crypto'
import { safe, settle, messageOf } from './safe.js'
import { createPaths } from './paths.js'
import { createJobs } from './jobs.js'
import { createDataWatcher } from './watch.js'
import { createRouter, sendJson } from './http.js'

// Test hook for the failsafe test (15.2 step 9).
if (process.env.TGS_CONTROL_TEST_THROW === 'import') {
  throw new Error('test: plugin.js threw while it loaded (TGS_CONTROL_TEST_THROW=import)')
}

let current = null        // the live instance; module level because Node keeps this module
let instancesAlive = 0

// Timers that the instance owns, so dispose() can clear every one.
function createClock() {
  const timeouts = new Set()
  const intervals = new Set()
  let stopped = false
  return {
    setTimeout(fn, ms) {
      if (stopped) return null
      const h = setTimeout(() => {
        timeouts.delete(h)
        safe('timer', fn)
      }, ms)
      timeouts.add(h)
      return h
    },
    clearTimeout(h) {
      if (!h) return
      clearTimeout(h)
      timeouts.delete(h)
    },
    setInterval(fn, ms) {
      if (stopped) return null
      const h = setInterval(() => safe('interval', fn), ms)
      intervals.add(h)
      return h
    },
    count: () => timeouts.size + intervals.size,
    stop() {
      stopped = true
      for (const h of timeouts) clearTimeout(h)
      for (const h of intervals) clearInterval(h)
      timeouts.clear()
      intervals.clear()
    },
  }
}

function createInstance(server) {
  if (process.env.TGS_CONTROL_TEST_THROW === 'configure') {
    throw new Error('test: configureServer threw (TGS_CONTROL_TEST_THROW=configure)')
  }
  const selftest = process.env.TGS_SELFTEST === '1'
  const paths = createPaths(server.config && server.config.root)
  const token = crypto.randomBytes(24).toString('hex')
  const clock = createClock()
  let disposed = false
  let liveRefreshOn = true

  const broadcast = (event, data) => {
    if (disposed) return
    safe('ws send', () => server.ws.send(event, data))
  }

  const jobs = createJobs({ paths, clock, broadcast, selftest })

  const controlMessage = () => ({ on: true, reason: null, python: jobs.getPython(), live_refresh: liveRefreshOn })
  const sendControl = () => broadcast('tgs:control', controlMessage())

  const watch = createDataWatcher({
    server, publicData: paths.publicData, jobs, clock, broadcast,
    onOff: () => {
      liveRefreshOn = false
      sendControl()
    },
  })
  jobs.setWatch(watch)

  // Token handshake (8.4): only pages Vite served can reach this socket.
  const onHello = (data, client) => safe('ws hello', () => {
    const addr = server.httpServer && server.httpServer.address()
    client.send('tgs:token', { token, port: addr && typeof addr === 'object' ? addr.port : null, api: 1 })
  })
  server.ws.on('tgs:hello', onHello)

  async function probeAndTell() {
    const { changed } = await jobs.probePython()
    if (changed) sendControl()
  }

  const handle = createRouter({
    paths, jobs, selftest,
    token: () => token,
    liveRefresh: () => liveRefreshOn && watch.isOn(),
    debug: () => ({ instances_alive: instancesAlive, timers: clock.count() }),
    afterSettingsChange: async () => {
      await jobs.probePython()
      await jobs.buildCatalog('settings')
      sendControl()
    },
    reprobe: async () => {
      const { changed } = await jobs.probePython()
      if (!changed) return
      await jobs.buildCatalog('python')
      sendControl()
    },
  })

  const inst = {
    handle: (req, res) => {
      if (disposed) {
        sendJson(res, 503, { error: { code: 'restarting', message: 'The app is restarting. Try again in a moment.' } })
        return
      }
      safe('request', () => handle(req, res), () => {
        try { if (!res.headersSent) sendJson(res, 500, { error: { code: 'internal' } }) } catch { /* ignore */ }
      })
    },
    dispose() {
      if (disposed) return
      disposed = true
      instancesAlive = Math.max(0, instancesAlive - 1)
      safe('dispose clock', () => clock.stop())
      safe('dispose watcher', () => watch.dispose())
      safe('dispose jobs', () => jobs.dispose())
      safe('dispose ws', () => server.ws.off('tgs:hello', onHello))
      if (current === inst) current = null
    },
  }
  instancesAlive += 1

  // Re-adopt every active job, start the pollers, probe Python, load the catalog.
  try {
    jobs.start()
  } catch (err) {
    inst.dispose()
    throw err
  }
  settle('python probe', probeAndTell())
  settle('catalog', jobs.buildCatalog('start'))
  return inst
}

// Control is off: answer ping only, touch nothing else. Logs one line.
function turnOff(server, err) {
  const reason = messageOf(err)
  try { console.warn(`[tgs-control] The Control panel is off: ${reason}`) } catch { /* ignore */ }
  safe('turn off', () => {
    server.middlewares.use('/__tgs/ping', (req, res) => {
      res.setHeader('Content-Type', 'application/json')
      res.end(JSON.stringify({ ok: false, api: 1, control: { on: false, reason } }))
    })
  })
}

export default function tgsControl() {
  return {
    name: 'tgs-control',
    apply: 'serve',
    configureServer(server) {
      // Same as safe(), but the one log line comes from turnOff().
      let inst = null
      try {
        if (current) current.dispose()        // the instance from before a restart
        inst = createInstance(server)
        current = inst
        server.middlewares.use('/__tgs', inst.handle)
        if (server.httpServer) server.httpServer.once('close', () => safe('server close', () => inst.dispose()))
      } catch (err) {
        if (inst) safe('dispose after error', () => inst.dispose())
        turnOff(server, err)
      }
    },
  }
}
