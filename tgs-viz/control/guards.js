// Request checks for every /__tgs/ request (DESIGN.md 8.3). Pure functions only.

import crypto from 'node:crypto'
import path from 'node:path'

const LOOPBACK = new Set(['127.0.0.1', '::1', '::ffff:127.0.0.1'])

export const JOB_ID_RE = /^\d{8}-\d{6}-[A-Za-z0-9_.-]+-[0-9a-f]{4}$/
export const MAX_BODY = 64 * 1024

export function isLoopback(remoteAddress) {
  return LOOPBACK.has(String(remoteAddress || ''))
}

export function allowedHosts(port) {
  const p = String(port)
  return [`localhost:${p}`, `127.0.0.1:${p}`, `[::1]:${p}`]
}

// Host must name this server on the port the request came in on.
export function hostOk(host, port) {
  if (!host || port === undefined || port === null || port === '') return false
  return allowedHosts(port).includes(String(host).toLowerCase())
}

// Origin, when present, must be exactly http://<one of the hosts>.
// With no Origin, Sec-Fetch-Site (when present) must be same-origin.
export function originOk(origin, secFetchSite, port) {
  if (origin !== undefined && origin !== null && origin !== '') {
    return allowedHosts(port).some((h) => origin === `http://${h}`)
  }
  if (secFetchSite !== undefined && secFetchSite !== null && secFetchSite !== '') {
    return secFetchSite === 'same-origin'
  }
  return true
}

export function tokenOk(given, token) {
  if (typeof given !== 'string' || typeof token !== 'string' || !token) return false
  const a = Buffer.from(given)
  const b = Buffer.from(token)
  if (a.length !== b.length) return false
  try { return crypto.timingSafeEqual(a, b) } catch { return false }
}

export function contentTypeOk(contentType) {
  return typeof contentType === 'string' && contentType.toLowerCase().startsWith('application/json')
}

// A job id must match the pattern and stay inside the jobs folder.
export function jobDirFor(jobsDir, id) {
  if (typeof id !== 'string' || !JOB_ID_RE.test(id)) return null
  const dir = path.resolve(jobsDir, id)
  if (path.dirname(dir) !== path.resolve(jobsDir)) return null
  return dir
}

export function isJobId(id) {
  return typeof id === 'string' && JOB_ID_RE.test(id)
}

// Guards 1 to 4 for one request. Returns null when the request may go on,
// else {status, code, message}.
//   req: {remoteAddress, localPort, headers, method, pathname, query}
//   opts: {token, needToken, tokenInQuery}
export function checkRequest(req, opts) {
  const headers = req.headers || {}
  if (!isLoopback(req.remoteAddress)) {
    return { status: 403, code: 'forbidden', message: 'Only this computer can use the Control panel.' }
  }
  if (!hostOk(headers.host, req.localPort)) {
    return { status: 403, code: 'forbidden', message: 'The Host header does not name this app.' }
  }
  if (!originOk(headers.origin, headers['sec-fetch-site'], req.localPort)) {
    return { status: 403, code: 'forbidden', message: 'This request did not come from the app page.' }
  }
  if (opts && opts.needToken) {
    let given = headers['x-tgs-token']
    if ((given === undefined || given === '') && opts.tokenInQuery && req.query) given = req.query.t
    if (!tokenOk(given, opts.token)) {
      return { status: 401, code: 'unauthorized', message: 'The page has no valid Control token. Reload the page.' }
    }
  }
  return null
}

// Guard 5 for a POST: content type and size. The body itself is parsed by the router.
export function checkPostHeaders(headers) {
  if (!contentTypeOk(headers['content-type'])) {
    return { status: 415, code: 'bad_content_type', message: 'Send the request as application/json.' }
  }
  const len = Number(headers['content-length'])
  if (Number.isFinite(len) && len > MAX_BODY) {
    return { status: 413, code: 'too_large', message: 'The request is too large.' }
  }
  return null
}
