#!/usr/bin/env node
/**
 * `npm run electron:dev` (and `npm start`): the full app in development.
 *
 *   1. regenerate the wire mirrors (what `predev` does for `npm run dev`)
 *   2. compile `electron/` to `dist-electron/`
 *   3. start Vite on 1420 and wait for it
 *   4. launch Electron at the repo root, pointed at Vite
 *
 * Closing the app stops Vite; Ctrl+C stops both. The main process is compiled
 * once: after editing `electron/`, quit and run this again. Webview edits
 * reload through Vite as usual.
 *
 * Every tool runs through Node against its package's own entry point, never
 * `npx`: on Windows that is a `.cmd`, which `spawn` refuses without a shell.
 */

import { spawn, spawnSync } from "node:child_process";
import { createRequire } from "node:module";
import { dirname, join } from "node:path";
import process from "node:process";
import { fileURLToPath } from "node:url";

const repoRoot = dirname(dirname(fileURLToPath(import.meta.url)));
const require = createRequire(import.meta.url);
const DEV_URL = "http://localhost:1420/";

function runOrExit(label, args) {
  console.log(`[electron:dev] ${label}`);
  const result = spawnSync(process.execPath, args, { stdio: "inherit", cwd: repoRoot });
  if (result.status !== 0) process.exit(result.status ?? 1);
}

async function waitFor(url, timeoutMs) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    try {
      await fetch(url);
      return;
    } catch {
      await new Promise((resolve) => setTimeout(resolve, 250));
    }
  }
  throw new Error(`nothing answered at ${url} within ${timeoutMs / 1000} s`);
}

runOrExit("generating the protocol", [join(repoRoot, "scripts", "gen-protocol.mjs")]);
runOrExit("compiling electron/", [
  join(repoRoot, "node_modules", "typescript", "bin", "tsc"),
  "-p",
  join(repoRoot, "electron", "tsconfig.build.json"),
]);

console.log("[electron:dev] starting Vite");
const vite = spawn(process.execPath, [join(repoRoot, "node_modules", "vite", "bin", "vite.js")], {
  stdio: "inherit",
  cwd: repoRoot,
});

let electron = null;
function stopAll(code) {
  // By child process, never by image name: other Node and Electron processes
  // on this machine are not ours to end.
  if (electron && electron.exitCode === null) electron.kill();
  if (vite.exitCode === null) vite.kill();
  process.exit(code);
}
process.on("SIGINT", () => stopAll(130));
process.on("SIGTERM", () => stopAll(143));
vite.on("exit", (code) => {
  if (electron === null || electron.exitCode === null) {
    console.error(`[electron:dev] Vite exited (${code}); stopping`);
    stopAll(code ?? 1);
  }
});

try {
  await waitFor(DEV_URL, 60_000);
} catch (err) {
  console.error(`[electron:dev] ${err.message}`);
  stopAll(1);
}

// The `electron` package's main export is the path to the binary.
const electronBinary = require("electron");
const env = { ...process.env, EPHYMERIS_DEV_URL: DEV_URL };
delete env.ELECTRON_RUN_AS_NODE;

console.log("[electron:dev] launching Electron");
// Anything after `--` goes to Electron, e.g. `npm run electron:dev -- --remote-debugging-port=9222`.
electron = spawn(electronBinary, [".", ...process.argv.slice(2)], { stdio: "inherit", cwd: repoRoot, env });
electron.on("exit", (code) => stopAll(code ?? 0));
