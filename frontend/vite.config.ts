import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// バックエンドのポート。run.sh が API_PORT を渡してくる。
// 直接 npm run dev したときは既定の 8765 を見る。
const apiPort = process.env.API_PORT ?? '8765'

export default defineConfig({
  plugins: [react()],
  server: {
    // Tailscale 経由で他の端末から開けるように、外向きにも待ち受ける。
    // FastAPI 自体は 127.0.0.1 のままにして、外に出すのはこの dev server だけ。
    host: '0.0.0.0',
    proxy: {
      // フロントは相対パス /api/... で呼ぶ。ここで FastAPI に中継するので
      // CORS の設定はいらない。
      '/api': `http://127.0.0.1:${apiPort}`,
    },
  },
})
