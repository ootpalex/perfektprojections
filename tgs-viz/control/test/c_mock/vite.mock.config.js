// Implementer C's test server: the app with the mock Control API.
// Run from tgs-viz (C test port 3102 only, never 3000):
//   TGS_SELFTEST=1 TGS_CONTROL_DIR=<wt>\.control-c TGS_VITE_CACHE_DIR=<wt>\.vite-cache-c \
//   npx vite --config control/test/c_mock/vite.mock.config.js --port 3102 --strictPort
import { fileURLToPath } from 'node:url';
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/vite';
import mockControl from './mockControl.js';

const root = fileURLToPath(new URL('../../..', import.meta.url));

// Same rule as vite.config.js (DESIGN 8.1): a data write never reloads the page.
const noPublicDataHmr = {
  name: 'tgs-public-data-no-hmr',
  apply: 'serve',
  hotUpdate: {
    order: 'post',
    handler({ file }) {
      if (/[\\/]public[\\/]data[\\/]/.test(file)) return [];
      return undefined;
    },
  },
};

export default defineConfig({
  root,
  plugins: [react(), tailwindcss(), noPublicDataHmr, mockControl()],
  cacheDir: process.env.TGS_VITE_CACHE_DIR || undefined,
  server: {
    port: 3102,
    strictPort: true,
    open: false,
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
});
