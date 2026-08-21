import os from 'node:os'
import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

function apiProxyTarget() {
  if (process.env.VITE_API_PROXY) return process.env.VITE_API_PROXY
  const ips = []
  for (const addrs of Object.values(os.networkInterfaces())) {
    for (const a of addrs || []) {
      const v4 = a.family === 'IPv4' || a.family === 4
      if (!v4 || a.internal) continue
      if (a.address.startsWith('169.254.')) continue
      ips.push(a.address)
    }
  }
  const lan =
    ips.find((ip) => ip.startsWith('192.168.')) ||
    ips.find((ip) => ip.startsWith('10.')) ||
    ips[0]
  // Prefer LAN so VS Code/Cursor port-forward on 127.0.0.1:8000 cannot swallow /api.
  return `http://${lan || '127.0.0.1'}:8000`
}

export default defineConfig({
  plugins: [vue()],
  server: {
    host: '0.0.0.0',
    port: 5174,
    strictPort: true,
    allowedHosts: true,
    proxy: {
      '/api': {
        target: apiProxyTarget(),
        changeOrigin: true,
        timeout: 0,
        proxyTimeout: 0,
      },
    },
  },
})

