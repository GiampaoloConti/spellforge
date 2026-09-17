import { defineConfig } from "vitest/config";

// In development, Vite serves the frontend on :5173 and forwards the websocket and API
// to the Python server on :8000, so the browser only ever talks to one origin.
export default defineConfig({
  server: {
    proxy: {
      "/ws": { target: "ws://127.0.0.1:8000", ws: true },
      "/api": { target: "http://127.0.0.1:8000" },
    },
  },
  test: {
    environment: "node",
  },
});
