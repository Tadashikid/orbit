import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
// /api/* -> the Orbit FastAPI backend (backend/main.py). 127.0.0.1, not localhost: avoids a ~1 s IPv6 detour on
// Windows. ORBIT_API points the dev server at another backend (used for testing). The dev server listens on this
// machine only; pass --host to show it on your network.
const target = process.env.ORBIT_API || "http://127.0.0.1:8000";
const proxy = { "/api": { target, ws: true, rewrite: (p: string) => p.replace(/^\/api/, "") } }; // ws: the voice socket
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: { host: "127.0.0.1", port: 4173, proxy },
  preview: { host: "127.0.0.1", port: 4173, proxy },
});
