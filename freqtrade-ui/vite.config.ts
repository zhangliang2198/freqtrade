import { fileURLToPath } from 'node:url'

import react from '@vitejs/plugin-react'
import { defineConfig, loadEnv } from 'vite'

// The app talks to the freqtrade REST API directly. `VITE_API_BASE` sets the
// default backend; individual bots can override it at login time.
//
// If you would rather not touch the backend's `CORS_origins`, set
// `VITE_USE_PROXY=true` and the dev server proxies /api to `VITE_PROXY_TARGET`
// so every request is same-origin.
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  const target = env.VITE_PROXY_TARGET || 'http://127.0.0.1:8081'

  return {
    plugins: [react()],
    resolve: {
      alias: {
        // semi-ui 2.103 ships its bundled stylesheet under `dist/css/` but
        // omits that path from its `exports` map, so a bare import fails to
        // resolve. Aliasing happens before `exports` is consulted.
        '@douyinfe/semi-ui/dist/css/semi.min.css': fileURLToPath(
          new URL('./node_modules/@douyinfe/semi-ui/dist/css/semi.min.css', import.meta.url),
        ),
      },
    },
    server: {
      port: 5273,
      strictPort: false,
      ...(env.VITE_USE_PROXY === 'true'
        ? {
            proxy: {
              '/api': {
                target,
                changeOrigin: true,
                ws: true,
              },
            },
          }
        : {}),
    },
    build: {
      outDir: 'dist',
      sourcemap: false,
      chunkSizeWarningLimit: 1500,
    },
  }
})
