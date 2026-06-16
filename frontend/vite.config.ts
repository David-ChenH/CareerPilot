import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/chat": "http://127.0.0.1:8000",
      "/assistant": "http://127.0.0.1:8000",
      "/profile": "http://127.0.0.1:8000",
      "/prep-plans": "http://127.0.0.1:8000",
      "/leetcode": "http://127.0.0.1:8000",
      "/resumes": "http://127.0.0.1:8000",
      "/jobs": "http://127.0.0.1:8000",
      "/health": "http://127.0.0.1:8000",
      "/docs": "http://127.0.0.1:8000",
      "/openapi.json": "http://127.0.0.1:8000"
    }
  }
});
