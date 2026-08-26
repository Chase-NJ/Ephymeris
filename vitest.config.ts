import { defineConfig } from "vitest/config";
import { fileURLToPath, URL } from "node:url";

/**
 * Unit tests for the pure layer only — `src/lib/**`.
 *
 * Deliberately no jsdom and no component rendering. What is worth pinning in
 * this frontend is the arithmetic and the decoding: the places where a mistake
 * produces a drawing or a readout that looks deliberate and is wrong, rather
 * than an error. Those all live in pure modules (`topology.ts`,
 * `graphLayout.ts`), which is why they are pure. A component test would need a
 * DOM, a settings context and a WebSocket client to assert something the
 * screenshot already shows better.
 */
export default defineConfig({
  resolve: {
    alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) },
  },
  test: {
    environment: "node",
    include: ["src/lib/**/*.test.ts"],
  },
});
