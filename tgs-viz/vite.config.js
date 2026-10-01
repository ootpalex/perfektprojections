import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// Data files under public/data are fetched, never imported: a write there must never reload the page.
const noPublicDataHmr = {
  name: 'tgs-public-data-no-hmr',
  apply: 'serve',
  hotUpdate: {
    order: 'post',
    handler({ file }) {
      if (/[\\/]public[\\/]data[\\/]/.test(file)) return []
    },
  },
}

// The Control panel. A dynamic import that esbuild cannot follow, so Vite does not bundle it into
// this config: a broken control file can never stop the app or the league data from loading.
async function loadControl() {
  try {
    const url = new URL('./control/plugin.js', import.meta.url).href
    const mod = await import(/* @vite-ignore */ url)
    return [mod.default()]
  } catch (e) {
    const reason = String((e && e.message) || e)
    console.warn(`[tgs-control] The Control panel is off: ${reason}`)
    return [{
      name: 'tgs-control-off',
      apply: 'serve',
      configureServer(server) {
        server.middlewares.use('/__tgs/ping', (req, res) => {
          res.setHeader('Content-Type', 'application/json')
          res.end(JSON.stringify({ ok: false, api: 1, control: { on: false, reason } }))
        })
      },
    }]
  }
}

export default defineConfig(async () => ({
  plugins: [react(), tailwindcss(), noPublicDataHmr, ...(await loadControl())],
  cacheDir: process.env.TGS_VITE_CACHE_DIR || undefined,
  server: {
    port: 3000,
    open: true,
    watch: {
      ignored: [
        '**/backtest/**', '**/engine/**', '**/ingest/**', '**/tools/**', '**/tests/**',
        '**/__pycache__/**', '**/*.tmp',
        '**/public/data/**/*.bak-*', '**/public/data/**/*_engine.json',
        '**/public/data/**/*_scurve_preview.json', '**/public/data/**/*_export.json',
        '**/public/data/* - Copy/**',
      ],
    },
  },
}))
