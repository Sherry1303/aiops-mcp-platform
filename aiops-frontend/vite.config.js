import { fileURLToPath, URL } from 'node:url'
import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import tailwindcss from '@tailwindcss/vite'

// Tailwind v4 通过 Vite 插件接入，无需 tailwind.config.js / postcss.config.js
export default defineConfig({
  plugins: [vue(), tailwindcss()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  server: {
    host: '127.0.0.1',
    port: 5173,
    // 如果需要绕过 CORS 调试，可把下面这段注释打开，并把 src/api/index.js 的 BASE_URL 改成 '/api-proxy'
    // proxy: {
    //   '/api-proxy': {
    //     target: 'http://localhost:8000',
    //     changeOrigin: true,
    //     rewrite: (path) => path.replace(/^\/api-proxy/, ''),
    //   },
    // },
  },
})
