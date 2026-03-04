import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      // This is the "nickname" Vite looks for
      '/api': {
        target: 'http://100.49.61.97:8000', // Your EC2 Backend
        changeOrigin: true,
        // Optional: If your FastAPI routes ALREADY start with /api, 
        // you don't need to rewrite anything. 
        // If they DON'T, use the rewrite line below:
        // rewrite: (path) => path.replace(/^\/api/, '')
      }
    }
  }
})
