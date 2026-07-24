import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import { fileURLToPath, URL } from "node:url";

// Tauri drives the dev server, so the port is fixed and failures must be loud
// rather than silently falling back to another port the shell isn't pointed at.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      "@": fileURLToPath(new URL("./src", import.meta.url)),
    },
  },
  clearScreen: false,
  server: {
    port: 1420,
    strictPort: true,
    watch: {
      // The sidecar and the Rust shell have their own toolchains; watching them
      // from Vite only produces spurious frontend reloads.
      ignored: ["**/src-tauri/**", "**/sidecar/**", "**/docs/**"],
    },
  },
  build: {
    target: "es2022",
    sourcemap: true,
  },
});
