import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Dev server proxies /api to the backend (docker: http://localhost:8080 serves both).
export default defineConfig({
  plugins: [react()],
  build: {
    rollupOptions: {
      output: { manualChunks: { react: ["react", "react-dom", "react-router-dom"], mui: ["@mui/material", "@emotion/react", "@emotion/styled"], icons: ["@mui/icons-material"] } },
    },
    chunkSizeWarningLimit: 700,
  },
  server: {
    port: 5173,
    proxy: { "/api": { target: process.env.VITE_API_PROXY ?? "http://localhost:8080", changeOrigin: true } },
  },
});
