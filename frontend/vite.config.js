import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      // Proxy requests starting with '/api' to your backend server
      '/api': {
        target: 'http://localhost:8000', // The URL of your backend server
        changeOrigin: true, // Changes the origin header to the target host
        //rewrite: (path) => path.replace(/^\/api/, '') 
      }
    }
  }
})
