// Paths for the Control plugin and the python.main read (DESIGN.md 3.1, 3.2).
// Nothing here reads a file at import time: settings are read per call.

import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const HERE = path.dirname(fileURLToPath(import.meta.url))

// Repo root = the folder that holds Launch TGS.bat = the parent of the Vite root (tgs-viz).
export function createPaths(viteRoot) {
  const tgsViz = path.resolve(viteRoot || path.resolve(HERE, '..'))
  const repo = path.resolve(tgsViz, '..')
  const controlDir = process.env.TGS_CONTROL_DIR
    ? path.resolve(process.env.TGS_CONTROL_DIR)
    : path.join(repo, '.control')
  // Test only: TGS_CONTROL_TOOLS_DIR points the plugin at a mock of the Python tools.
  const toolsDir = process.env.TGS_CONTROL_TOOLS_DIR
    ? path.resolve(process.env.TGS_CONTROL_TOOLS_DIR)
    : path.join(tgsViz, 'tools')
  return {
    repo,
    tgsViz,
    publicData: path.join(tgsViz, 'public', 'data'),
    controlDir,
    jobsDir: path.join(controlDir, 'jobs'),
    activeDir: path.join(controlDir, 'active'),
    locksDir: path.join(controlDir, 'locks'),
    tmpDir: path.join(controlDir, 'tmp'),
    toolsDir,
    runTask: path.join(toolsDir, 'run_task.py'),
    settingsPy: path.join(toolsDir, 'settings.py'),
    doctorPy: path.join(toolsDir, 'doctor.py'),
    newLeaguePy: path.join(toolsDir, 'new_league.py'),
    defaultsPath: path.join(tgsViz, 'tools', 'settings.defaults.json'),
    localSettingsPath: () => localSettingsPath(repo),
  }
}

export function localSettingsPath(repo) {
  return process.env.TGS_SETTINGS_LOCAL
    ? path.resolve(process.env.TGS_SETTINGS_LOCAL)
    : path.join(repo, 'settings.local.json')
}

function isArgv(v) {
  return Array.isArray(v) && v.length > 0 && v.every((s) => typeof s === 'string' && s.length > 0)
}

function mainOf(obj) {
  if (!obj || typeof obj !== 'object' || Array.isArray(obj)) return null
  const py = obj.python
  if (!py || typeof py !== 'object' || Array.isArray(py)) return null
  return isArgv(py.main) ? py.main.slice() : null
}

function parseOrNull(text) {
  if (typeof text !== 'string') return null
  try { return JSON.parse(text.replace(/^﻿/, '')) } catch { return null }
}

// The python.main rule (3.2): the local value when the local file parses and holds a
// non-empty list of strings, else the defaults value, else ["python"]. No expansion.
// defaultsText and localText are file contents, or null when the file is missing.
export function resolvePythonMain(defaultsText, localText) {
  const local = mainOf(parseOrNull(localText))
  if (local) return local
  const defaults = mainOf(parseOrNull(defaultsText))
  if (defaults) return defaults
  return ['python']
}

function argvAt(obj, keys) {
  let cur = obj
  for (const k of keys) {
    if (!cur || typeof cur !== 'object' || Array.isArray(cur)) return null
    cur = cur[k]
  }
  return isArgv(cur) ? cur.slice() : null
}

// The three commands the Setup page needs when Python does not start (settings.py cannot
// run then): local wins when it holds a non-empty list of strings, else the defaults.
export function commandsView(defaultsText, localText) {
  const d = parseOrNull(defaultsText)
  const l = parseOrNull(localText)
  const pick = (keys, fallback) => argvAt(l, keys) || argvAt(d, keys) || fallback
  return {
    python: { main: pick(['python', 'main'], ['python']), ml: pick(['python', 'ml'], ['py', '-3.14']) },
    node: pick(['node'], ['node']),
  }
}

function readTextOrNull(file) {
  try { return fs.readFileSync(file, 'utf8') } catch { return null }
}

// Read both files now and apply the rule.
export function pythonMain(paths) {
  return resolvePythonMain(readTextOrNull(paths.defaultsPath), readTextOrNull(paths.localSettingsPath()))
}

export { readTextOrNull }
