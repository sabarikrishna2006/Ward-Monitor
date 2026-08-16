import { defineConfig } from 'vite';

export default defineConfig({
  server: {
    port: parseInt(process.env.VITE_PORT || '5184'),
    host: process.env.VITE_HOST || 'localhost',
    proxy: {
      '/api': {
        target: process.env.VITE_API_URL || 'http://localhost:6037',
        changeOrigin: true,
      }
    }
  },
  preview: {
    port: parseInt(process.env.VITE_PORT || '5184'),
    host: '0.0.0.0',
  }
});
