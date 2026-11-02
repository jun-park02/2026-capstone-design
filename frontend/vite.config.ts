import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    watch: {
      // Windows에서 수정한 파일을 Docker에서도 감지한다.
      usePolling: true,
      interval: 300,
    },
  },
})
