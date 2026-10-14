import react from "@vitejs/plugin-react";
import path from "node:path";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react()],
  resolve: { alias: { "@": path.resolve(__dirname, "src") } },
  server: { port: Number(process.env.WEB_PORT ?? 5173), proxy: { "/api": process.env.API_PROXY ?? "http://127.0.0.1:8010" } },
  build: { chunkSizeWarningLimit: 1500 },
});
