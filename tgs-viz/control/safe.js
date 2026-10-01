// Error isolation for the Control plugin (DESIGN.md 8.10).
// Every entry point runs through safe(): an error logs one short line and never reaches Vite.

const PREFIX = '[tgs-control]'
const lastLogged = new Map()   // where -> time of the last line
const ONE_MINUTE = 60 * 1000

function messageOf(err) {
  if (err && typeof err === 'object' && err.message) return String(err.message).split('\n')[0]
  return String(err)
}

// One line per `where`, at most once a minute.
export function logError(where, err) {
  try {
    const now = Date.now()
    const last = lastLogged.get(where)
    if (last !== undefined && now - last < ONE_MINUTE) return
    lastLogged.set(where, now)
    console.warn(`${PREFIX} ${where}: ${messageOf(err)}`)
  } catch {
    // Logging must never throw.
  }
}

// Plain info line (not rate limited). Used for a few one-time notices.
export function logInfo(text) {
  try { console.log(`${PREFIX} ${text}`) } catch { /* ignore */ }
}

// Run fn; on an error log one line, call onError, return undefined.
export function safe(where, fn, onError) {
  try {
    const out = fn()
    if (out && typeof out.then === 'function') {
      return out.catch((err) => {
        logError(where, err)
        if (onError) { try { onError(err) } catch (e2) { logError(where + ' (handler)', e2) } }
        return undefined
      })
    }
    return out
  } catch (err) {
    logError(where, err)
    if (onError) { try { onError(err) } catch (e2) { logError(where + ' (handler)', e2) } }
    return undefined
  }
}

// Attach the shared log to a promise that nobody awaits.
export function settle(where, promise) {
  if (promise && typeof promise.catch === 'function') promise.catch((err) => logError(where, err))
  return promise
}

export { messageOf }
