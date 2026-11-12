import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// In development the API runs separately (uvicorn on :8000); in production nginx
// serves the built files and proxies /api to the platform-api container.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: { "/api": process.env.API_URL ?? "http://localhost:8000" },
  },
  build: {
    rollupOptions: {
      output: {
        // Vendor chunks cache well across UI releases.
        manualChunks: { react: ["react", "react-dom", "react-router-dom"], charts: ["recharts"] },
      },
    },
  },
});
