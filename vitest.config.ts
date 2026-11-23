import { defineConfig } from "vitest/config";
import { fileURLToPath, URL } from "node:url";

/**
 * Unit tests for `src/lib/**` and `src/features/**`: the pure layer, and the stores driven through
 * `FakeSidecar` (`lib/ws/fakeSidecar.ts`). Also `electron/**`.
 *
 * Deliberately no jsdom and no component rendering. What is worth pinning in
 * this frontend is the arithmetic and the decoding: the places where a mistake
 * produces a drawing or a readout that looks deliberate and is wrong, rather
 * than an error. Those all live in pure modules (`topology.ts`,
 * `graphLayout.ts`), which is why they are pure. A component test would need a
 * DOM and a settings context to assert something the screenshot already shows
 * better.
 */
export default defineConfig({
  resolve: {
    alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) },
  },
  test: {
    environment: "node",
    // `electron/`: the Electron shell's pure parts (handshake, launch order,
    // window size, which URLs are the app's) and its settings file.
    include: ["src/lib/**/*.test.ts", "src/features/**/*.test.ts", "electron/**/*.test.ts"],
  },
});
