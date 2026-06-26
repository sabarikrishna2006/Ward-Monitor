import { defineConfig } from 'vite';

export default defineConfig({
  server: {
    port: parseInt(process.env.VITE_PORT || '5174'),
    host: process.env.VITE_HOST || 'localhost',
    proxy: {
      '/api': {
        target: process.env.VITE_API_URL || 'http://localhost:8006',
        changeOrigin: true,
      }
    }
  },
  preview: {
    port: parseInt(process.env.VITE_PORT || '5174'),
    host: '0.0.0.0',
  }
});
